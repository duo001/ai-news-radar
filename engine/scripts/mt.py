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
import pathlib
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

# ---- 通道健康度：按「上次有没有翻成功」决定先后 ----------------------------
# 免费通道的可用性经常整段变化（腾讯整月连不上、Bing 偶尔被限流），
# 每次都按写死的顺序先撞一遍坏通道，等于每批都白等一次超时（v0.18.17）。
# 这里把「哪个通道上次成功/失败」记在 data/translate-health.json，
# 下次跑时把近期成功的排前面、近期失败的排最后。冷却期过后自动重新尝试，
# 不会因为一次失败就永久拉黑（免费通道恢复后要能重新用上）。
HEALTH_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "translate-health.json"
HEALTH_COOLDOWN = 6 * 3600      # 失败后 6 小时内排到最后，过了自动给机会
_health_lock = threading.Lock()


def dead_providers():
    """本次运行已熔断的通道名集合（供日志/进度展示）。"""
    return set(_DEAD)


def reset_breaker():
    """清空熔断状态（测试用）。"""
    _DEAD.clear()


# ---------------------------------------------------------------- 通道健康度

def read_health():
    """读通道健康记录：{通道名: {"ok_at": 时间戳, "fail_at": 时间戳, "fails": 连续失败数}}。"""
    try:
        doc = json.loads(HEALTH_PATH.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def _write_health(doc):
    try:
        HEALTH_PATH.parent.mkdir(parents=True, exist_ok=True)
        HEALTH_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass  # 健康记录写失败不影响翻译本身


def mark_health(name, ok):
    """记一次通道结果。成功清掉失败记录；失败记时间戳并累加 fails。"""
    now = time.time()
    with _health_lock:
        doc = read_health()
        rec = doc.get(name) if isinstance(doc.get(name), dict) else {}
        if ok:
            rec["ok_at"] = now
            rec["fails"] = 0
            rec.pop("fail_at", None)
        else:
            rec["fail_at"] = now
            rec["fails"] = int(rec.get("fails") or 0) + 1
        doc[name] = rec
        _write_health(doc)


def rank_providers(chain=None, now=None):
    """按历史健康把通道排序：近期成功过的最前，近期失败过的垫底（冷却期内）。

    排序键（升序）：
      0 = 近期成功过（按成功时间，越近越前）
      1 = 没试过（保持原始顺序）
      2 = 失败过且仍在冷却期（按失败时间，越久越前，便于尽快重试）
    不在冷却期的失败不再垫底 —— 重新给机会。
    """
    chain = list(PROVIDERS if chain is None else chain)
    now = time.time() if now is None else now
    health = read_health()
    ranked = []
    for i, (name, fn) in enumerate(chain):
        rec = health.get(name) if isinstance(health.get(name), dict) else {}
        ok_at = rec.get("ok_at") or 0
        fail_at = rec.get("fail_at") or 0
        # 失败时间晚于成功时间，才算「当前处于失败态」
        if fail_at and fail_at > ok_at:
            fresh = (now - fail_at) < HEALTH_COOLDOWN
            key = (2, fail_at if not fresh else -fail_at, i)
            if not fresh:
                key = (1, 0, i)          # 冷却期已过：当作没试过，正常顺序
        elif ok_at:
            key = (0, -ok_at, i)         # 越近成功越靠前
        else:
            key = (1, 0, i)
        ranked.append((key, name, fn))
    ranked.sort(key=lambda x: x[0])
    return [(name, fn) for _, name, fn in ranked]


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
    # 按上次成功/失败情况排先后：近期成功过的排前面，近期失败的垫底，
    # 免得每批都先撞一遍坏通道、白等一次超时（v0.18.17）
    health_now = read_health()
    chain = rank_providers(chain, now=None)
    if log and len(chain) > 1:
        log("  通道顺序（按上次成败）：" + " → ".join(n for n, _ in chain))
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
            rec = health_now.get(name) or {}
            suffix = ""
            if rec.get("fails") and (rec.get("fail_at") or 0) > (rec.get("ok_at") or 0):
                suffix = "（上次失败，排后面）"
            elif rec.get("ok_at"):
                suffix = "（上次成功，优先）"
            log(f"  通道 {name}：{len(batch)} 条{suffix}")
        got = fn(batch, log=log)
        residual = []
        got_any = False
        for idx, value in zip(pending, got):
            if value:
                out[idx] = value
                used = name
                got_any = True
            else:
                residual.append(idx)
        # 记录通道这次到底有没有翻成：有就排前面，一条没成就算坏通道（v0.18.17）
        if got is not None and len(got):
            mark_health(name, got_any)
        pending = residual

    if pending and log:
        log(f"  {len(pending)} 条所有通道均失败，跳过")
    return out, used
