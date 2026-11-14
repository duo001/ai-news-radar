"""免费机器翻译通道：把英文资讯标题/摘要自动翻成中文。

设计要点
--------
- **无 API key、无付费**：优先用腾讯交互翻译（transmart.qq.com）的 web 端点，
  国内直连、支持批量、质量可接受；失败自动降级到 MyMemory（公共免费额度）。
- **批量**：transmart 单次最多约 50 条（实测 100 条报 outOfLimit），这里保守取 40。
- **容错**：任何一条失败不影响其余；返回与输入等长的列表，失败位置为 None。
- **不做本地词典兜底**：机翻质量不够时宁可不入库，交由人工择机补译。

用法
----
    from mt import translate_batch
    out = translate_batch(["Hello world", "..."], log=print)
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# transmart 单批上限：条数 + 总字符数（实测 6000 字符通过、12000 报 outOfLimit，
# 取 4000 留余量；条数上限实测 80 通过，取 40 保守）
TRANSMART_BATCH = 40
TRANSMART_CHAR_BUDGET = 4000
TRANSMART_TIMEOUT = 30
TRANSMART_RETRIES = 2

MYMEMORY_TIMEOUT = 20
MYMEMORY_RETRIES = 1
# MyMemory 匿名额度约 1000 词/天，带 email 可到 10000 词/天；留空即匿名
MYMEMORY_EMAIL = ""


class MTError(Exception):
    """机器翻译失败。"""


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
        "source": {"lang": "en", "text_list": list(texts)},
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
    with urllib.request.urlopen(req, timeout=TRANSMART_TIMEOUT) as resp:
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


def _transmart(texts, log=None):
    """按条数+字符双预算切片翻译，返回与 texts 等长的列表。"""
    results = []
    for chunk in _chunk_texts(texts, TRANSMART_BATCH, TRANSMART_CHAR_BUDGET):
        got = None
        for attempt in range(1, TRANSMART_RETRIES + 1):
            try:
                got = _transmart_one_batch(chunk)
                break
            except Exception as e:                      # noqa: BLE001 - 兜底降级
                if log:
                    log(f"  transmart 第 {attempt} 次失败：{type(e).__name__}: {e}")
                if attempt < TRANSMART_RETRIES:
                    # outOfLimit 是限流，退避久一点；其他错误快速重试
                    backoff = 8.0 if "outOfLimit" in str(e) else 1.5 * attempt
                    time.sleep(backoff)
        if got is None:
            results.extend([None] * len(chunk))
        else:
            results.extend(got)
        time.sleep(1.0)                                 # 节流，避免触发限流
    return results


# ---------------------------------------------------------------- MyMemory 兜底

def _mymemory_one(text):
    params = {"q": text, "langpair": "en|zh-CN"}
    if MYMEMORY_EMAIL:
        params["de"] = MYMEMORY_EMAIL
    url = "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=MYMEMORY_TIMEOUT) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    status = payload.get("responseStatus")
    if status != 200:
        raise MTError(f"mymemory responseStatus={status}")
    text_out = ((payload.get("responseData") or {}).get("translatedText") or "").strip()
    if not text_out or "MYMEMORY WARNING" in text_out.upper():
        raise MTError("mymemory 配额用尽或空译文")
    return text_out


def _mymemory(texts, log=None):
    results = []
    for t in texts:
        got = None
        for attempt in range(1, MYMEMORY_RETRIES + 1):
            try:
                got = _mymemory_one(t)
                break
            except Exception as e:                      # noqa: BLE001
                if log:
                    log(f"  mymemory 第 {attempt} 次失败：{type(e).__name__}: {e}")
                if attempt < MYMEMORY_RETRIES:
                    time.sleep(1.0)
        results.append(got)
        time.sleep(0.25)                                # 匿名额度下必须慢
    return results


# ---------------------------------------------------------------- 对外接口

PROVIDERS = (
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

    pending = list(range(len(texts)))
    out = [None] * len(texts)
    used = "none"

    for name, fn in chain:
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
