"""免费机器翻译通道：把英文资讯标题/摘要自动翻成中文。

设计要点
--------
- **无 API key、无付费**：主通道走 Bing 翻译网页端（cn.bing.com/ttranslatev3），
  国内直连可用、单请求翻一条、可并发；失败降级腾讯交互翻译，再降级 MyMemory。
  谷歌系（translate.googleapis.com / clients5.google.com）实测国内整段超时，不可用。
- **并发**：Bing 单请求只吃一条文本（多 text 只回第一条），串行约 1 条/秒，
  并发 8 实测约 7 条/秒且稳定；上千条待译只需数分钟。
- **容错**：任何一条失败不影响其余；返回与输入等长的列表，失败位置为 None。
- **不做本地词典兜底**：机翻质量不够时宁可不入库，交由人工择机补译。

用法
----
    from mt import translate_batch
    out = translate_batch(["Hello world", "..."], log=print)
"""

import concurrent.futures
import json
import re
import threading
import time
import urllib.error
import netcfg
import urllib.parse
import urllib.request

# 假名 / 谚文：与 i18n.detect_lang 同判据，供 MyMemory 显式指定源语言
_KANA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff\uff66-\uff9f]")
_HANGUL_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# ---- Bing 网页翻译 ----
# 网页端要三个参数：页面里的 IG、params_AbusePreventionHelper（[key, token, 有效期ms]）。
# token 有效期 1 小时，过期或被拒就重抓页面刷新。
BING_HOME = "https://cn.bing.com/translator"
BING_API = "https://cn.bing.com/ttranslatev3"
BING_TIMEOUT = 15
# 并发数：实测 14 稳定（40 条 4.6s、8.6 条/秒，无限流），取 12 留余量
BING_WORKERS = 12
BING_IID_BASE = 5023

_bing_lock = threading.Lock()
_bing_auth = {"ig": "", "key": "", "token": "", "expires_at": 0.0}

# transmart 单批上限：条数 + 总字符数（实测 6000 字符通过、12000 报 outOfLimit，
# 取 4000 留余量；条数上限实测 80 通过，取 40 保守）
TRANSMART_BATCH = 40
TRANSMART_CHAR_BUDGET = 4000
# 超时别给太长：该域名在国内经常整段不可达（TCP 443 直接连不上），
# 30s×2 次重试意味着每个批次白等 60s，上千条待译就会"看起来卡死"（v0.18.15，坑 57）
TRANSMART_TIMEOUT = 10
TRANSMART_RETRIES = 1

MYMEMORY_TIMEOUT = 12
MYMEMORY_RETRIES = 1
# MyMemory 匿名额度约 1000 词/天，带 email 可到 10000 词/天；留空即匿名
MYMEMORY_EMAIL = ""

# 进程级熔断：某通道出现「网络不可达 / 配额耗尽」这类硬失败后，本次运行不再尝试它。
# 只对硬失败熔断（连不上、配额耗尽）；单条失败、限流退避不熔断。
_DEAD = set()


def dead_providers():
    """本次运行已熔断的通道名集合（供日志/进度展示）。"""
    return set(_DEAD)


def reset_breaker():
    """清空熔断状态（测试用）。"""
    _DEAD.clear()


class MTError(Exception):
    """机器翻译失败。"""


class _BingRejected(MTError):
    """Bing 明确拒绝了请求（token 过期 / IG 不匹配 / 限流）——重抓页面通常能恢复。"""


# ---------------------------------------------------------------- Bing 网页翻译

_BING_IG_RE = re.compile(r'IG:"([A-F0-9]{16,})"')
_BING_ABUSE_RE = re.compile(r"params_AbusePreventionHelper\s*=\s*\[(\d+),\s*\"([^\"]+)\",\s*(\d+)\]")


def _bing_fetch_auth(force=False):
    """抓翻译页，取 IG / key / token；有效期未过半就复用。

    并发下多个线程会同时发现 token 过期，用锁串行化，避免抓 6 次页面。
    """
    now = time.time()
    with _bing_lock:
        if not force and _bing_auth["token"] and now < _bing_auth["expires_at"]:
            return dict(_bing_auth)

        req = urllib.request.Request(BING_HOME, headers={
            "User-Agent": UA,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        with netcfg.open_url(req, timeout=BING_TIMEOUT) as resp:
            html = resp.read().decode("utf-8", "replace")

        m_ig = _BING_IG_RE.search(html)
        m_ab = _BING_ABUSE_RE.search(html)
        if not m_ig or not m_ab:
            raise MTError("Bing 翻译页结构变化（没找到 IG / params_AbusePreventionHelper）")

        key, token, ttl_ms = m_ab.group(1), m_ab.group(2), int(m_ab.group(3))
        # 有效期留 5 分钟余量；网页给的 ttl 是 1 小时
        _bing_auth.update(ig=m_ig.group(1), key=key, token=token,
                          expires_at=time.time() + max(ttl_ms / 1000 - 300, 60))
        return dict(_bing_auth)


def _bing_one(text, auth, iid):
    """翻一条。返回译文字符串；失败抛异常由调用方记 None。"""
    data = urllib.parse.urlencode({
        "fromLang": "auto-detect",
        "to": "zh-Hans",
        "text": text,
        "token": auth["token"],
        "key": auth["key"],
    }).encode("utf-8")
    url = (f"{BING_API}?isVertical=1&IG={auth['ig']}"
           f"&IID=translator.{BING_IID_BASE}.{iid}")
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": BING_HOME,
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    with netcfg.open_url(req, timeout=BING_TIMEOUT) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    # 成功：[{"translations":[{"text": "..."}], "detectedLanguage": {...}}]
    # 被拒：{"statusCode": 205/400, "errorMessage": "..."}
    # 205 = 缺 token / token 过期 / IG 不匹配，刷新 token 可恢复（坑 58）
    if isinstance(payload, dict):
        raise _BingRejected(f"Bing 拒绝：statusCode={payload.get('statusCode')} "
                            f"errorMessage={payload.get('errorMessage') or ''}")
    if not payload or not payload[0].get("translations"):
        raise MTError("Bing 返回空译文")
    return payload[0]["translations"][0]["text"]


def _bing(texts, log=None):
    """并发翻译，返回与 texts 等长的列表（失败为 None）。"""
    if "bing" in _DEAD:
        return [None] * len(texts)
    try:
        auth = _bing_fetch_auth()
    except Exception as err:  # 抓不到 token 就算硬失败，本轮不再试
        _DEAD.add("bing")
        if log:
            log(f"  Bing 通道不可用：{err}")
        return [None] * len(texts)

    out = [None] * len(texts)
    auth_expired = {"hit": False}

    def work(idx):
        text = texts[idx]
        try:
            return idx, _bing_one(text, auth, idx), None
        except _BingRejected as err:
            # token 过期 / IG 不匹配：标记后由主线程统一刷新，本条重试一次
            auth_expired["hit"] = True
            return idx, None, err
        except Exception as err:
            return idx, None, err

    with concurrent.futures.ThreadPoolExecutor(max_workers=BING_WORKERS) as ex:
        results = list(ex.map(work, range(len(texts))))

    failed = [r for r in results if r[1] is None]
    if failed and auth_expired["hit"]:
        # 刷新 token 后重试失败的那些（仍并发）
        try:
            auth = _bing_fetch_auth(force=True)
        except Exception as err:
            _DEAD.add("bing")
            if log:
                log(f"  Bing token 刷新失败：{err}")
            return out
        retry_idx = [r[0] for r in failed]

        def work2(idx):
            try:
                return idx, _bing_one(texts[idx], auth, idx), None
            except Exception as err:
                return idx, None, err

        with concurrent.futures.ThreadPoolExecutor(max_workers=BING_WORKERS) as ex:
            for idx, val, err in ex.map(work2, retry_idx):
                if val:
                    out[idx] = val

    for idx, val, err in results:
        if val:
            out[idx] = val

    ok = sum(1 for v in out if v)
    if log:
        log(f"  Bing：成功 {ok}/{len(texts)}")
        if ok == 0 and not auth_expired["hit"]:
            # 一条都没成且不是 token 问题 → 很可能被限流/封，本轮别再用
            _DEAD.add("bing")
            if log:
                log("  Bing 整批失败，本次运行停用该通道")
    return out


# ---------------------------------------------------------------- 腾讯交互翻译

def _transmart_one_batch(texts):
    """一次 transmart 请求，返回译文列表（长度 == len(texts)）。"""
    body = {
        "header": {
            "fn": "auto_translation",
            "client_key": ("browser-chrome-131.0.0.0-abcdefgh-1234-5678-9012-"
                           "abcdef123456-1763000000000"),
        },
        "type": "plain",
        "model_category": "normal",
        # 源语言必须 auto：写死 "en" 时日文会被当成英文强行翻译，实测把
        # 「OpenAIが新しいモデルを発表」译成「OpenAI新一代智能手表」这种臆造内容。
        # auto 能同时正确处理英文/日文/韩文混排（v0.18.13，坑 56）。
        "source": {"lang": "auto", "text_list": list(texts)},
        "target": {"lang": "zh"},
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "https://transmart.qq.com/api/imt", data=data,
        headers={
            "User-Agent": UA,
            "Content-Type": "application/json;charset=UTF-8",
            "Referer": "https://transmart.qq.com/zh-CN/index",
            "Origin": "https://transmart.qq.com",
        })
    with netcfg.open_url(req, timeout=TRANSMART_TIMEOUT) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    ret = (payload.get("header") or {}).get("ret_code")
    if ret != "succ":
        raise MTError(f"transmart ret_code={ret}")
    out = payload.get("auto_translation") or []
    if len(out) != len(texts):
        raise MTError(f"transmart 返回条数不符：{len(out)} != {len(texts)}")
    return out


def _chunk_texts(texts, max_items, max_chars):
    """按条数与总字符数双预算切片，返回 [[...], [...]]。"""
    chunks, cur, cur_chars = [], [], 0
    for t in texts:
        n = len(t)
        if cur and (len(cur) >= max_items or cur_chars + n > max_chars):
            chunks.append(cur)
            cur, cur_chars = [], 0
        cur.append(t)
        cur_chars += n
    if cur:
        chunks.append(cur)
    return chunks


def _is_network_failure(err):
    """网络级硬失败（连不上 / 超时 / DNS），区别于「服务器回了但内容不对」。"""
    return isinstance(err, (urllib.error.URLError, TimeoutError, ConnectionError, OSError))


def _transmart(texts, log=None):
    """按条数+字符双预算切片翻译，返回与 texts 等长的列表。"""
    if "transmart" in _DEAD:
        return [None] * len(texts)
    results = []
    chunks = _chunk_texts(texts, TRANSMART_BATCH, TRANSMART_CHAR_BUDGET)
    for idx, chunk in enumerate(chunks):
        got = None
        last_err = None
        for attempt in range(1, TRANSMART_RETRIES + 1):
            try:
                got = _transmart_one_batch(chunk)
                break
            except Exception as e:                      # noqa: BLE001 - 兜底降级
                last_err = e
                if log:
                    log(f"  transmart 第 {attempt} 次失败：{type(e).__name__}: {e}")
                if attempt < TRANSMART_RETRIES:
                    # outOfLimit 是限流，退避久一点；其他错误快速重试
                    backoff = 8.0 if "outOfLimit" in str(e) else 1.5 * attempt
                    time.sleep(backoff)
        if got is None:
            # 第一批就网络级失败 → 该域名整段不可达，熔断后剩余批次不再白等
            if idx == 0 and last_err is not None and _is_network_failure(last_err):
                _DEAD.add("transmart")
                if log:
                    log("  transmart 不可达，本次运行熔断该通道（剩余批次不再尝试）")
                results.extend([None] * (len(texts) - len(results)))
                return results
            results.extend([None] * len(chunk))
        else:
            results.extend(got)
        time.sleep(1.0)                                 # 节流，避免触发限流
    return results


# ---------------------------------------------------------------- MyMemory 兜底

def _src_lang(text):
    """给 MyMemory 用的源语言码（它不支持 auto，必须显式给）。

    与 i18n.detect_lang 同判据：假名→ja、谚文→ko、其余按 en。
    这里刻意不 import i18n，避免 mt ↔ i18n 的导入顺序耦合。
    """
    if _KANA_RE.search(text):
        return "ja"
    if _HANGUL_RE.search(text):
        return "ko"
    return "en"


def _mymemory_one(text):
    params = {"q": text, "langpair": f"{_src_lang(text)}|zh-CN"}
    if MYMEMORY_EMAIL:
        params["de"] = MYMEMORY_EMAIL
    url = "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with netcfg.open_url(req, timeout=MYMEMORY_TIMEOUT) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    status = payload.get("responseStatus")
    if status != 200:
        raise MTError(f"mymemory responseStatus={status}")
    text_out = ((payload.get("responseData") or {}).get("translatedText") or "").strip()
    if not text_out or "MYMEMORY WARNING" in text_out.upper():
        raise MTError("mymemory 配额用尽或空译文")
    return text_out


def _mymemory(texts, log=None):
    if "mymemory" in _DEAD:
        return [None] * len(texts)
    results = []
    for pos, t in enumerate(texts):
        got = None
        last_err = None
        for attempt in range(1, MYMEMORY_RETRIES + 1):
            try:
                got = _mymemory_one(t)
                break
            except Exception as e:                      # noqa: BLE001
                last_err = e
                if log:
                    log(f"  mymemory 第 {attempt} 次失败：{type(e).__name__}: {e}")
                if attempt < MYMEMORY_RETRIES:
                    time.sleep(1.0)
        if got is None and last_err is not None:
            # 配额用尽是当天硬上限，熔断后不再逐条空转
            if "配额" in str(last_err):
                _DEAD.add("mymemory")
                if log:
                    log("  mymemory 今日额度已用尽，本次运行熔断该通道")
                results.extend([None] * (len(texts) - pos))
                return results
            if pos == 0 and _is_network_failure(last_err):
                _DEAD.add("mymemory")
                if log:
                    log("  mymemory 不可达，本次运行熔断该通道")
                results.extend([None] * (len(texts) - pos))
                return results
        results.append(got)
        time.sleep(0.25)                                # 匿名额度下必须慢
    return results


# ---------------------------------------------------------------- 对外接口

PROVIDERS = (
    ("bing", _bing),
    ("transmart", _transmart),
    ("mymemory", _mymemory),
)


def translate_batch(texts, log=None, provider=None):
    """批量英译中。

    返回 (译文列表, 提供方名)。译文列表与 texts 等长，失败位置为 None。
    provider 为 None 时按 PROVIDERS 顺序自动降级；显式指定则只用该通道。
    全部文本都为空时直接返回空列表。
    """
    texts = list(texts)
    if not texts:
        return [], "none"

    chain = [p for p in PROVIDERS if provider is None or p[0] == provider]
    if not chain:
        raise MTError(f"未知翻译通道：{provider}")
    # 已熔断的通道直接跳过：provider 显式指定时也遵守（宁可返回空也不白等）
    live = [p for p in chain if p[0] not in _DEAD]
    if not live:
        raise MTError("所有翻译通道本次运行均已熔断（" + "、".join(p[0] for p in chain) + "）")

    pending = list(range(len(texts)))
    out = [None] * len(texts)
    used = "none"

    for name, fn in live:
        if not pending:
            break
        batch = [texts[i] for i in pending]
        if log:
            log(f"  通道 {name}：{len(batch)} 条")
        got = fn(batch, log=log)
        residual = []
        for idx, value in zip(pending, got):
            if value:
                out[idx] = value
                used = name
            else:
                residual.append(idx)
        pending = residual

    if pending and log:
        log(f"  {len(pending)} 条所有通道均失败，跳过")
    return out, used
