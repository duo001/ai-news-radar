"""非 RSS 的结构化 API 采集器（零 key、纯标准库）。

借鉴 ZiChuanLan/freebie-radar 的「多类型采集器」思路：RSS 之外，直接打
返回 JSON 的公开 API，把结果转成与 feeds.parse_feed 完全相同的 entry 结构，
从而无缝进入既有的 去重 → SQLite → 翻译 → 渲染 链路。

当前网络（国内、无代理）实测可达的零 key 端点：
  - OpenRouter  /api/v1/models            → 免费模型上新（免费 token 情报）
  - Hacker News /hn.algolia.com/api       → AI 相关故事（项目/技术资讯金矿）

需要特殊网络、当前不可达的采集器（Bluesky / v2ex / linux.do / reddit）
在 data/sources/collectors.json 里保留配置位但默认 enabled:false，
网络条件具备时改 true 即可，无需改代码。

每条 entry 与 feeds 对齐：
  {title, link, summary, published(datetime|None),
   source_id, source_name, group, kind}
其中 kind 用采集器类型（openrouter / hackernews），落 DB 的 kind 列。
"""

import gzip
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COLLECTORS_CONF = ROOT / "data" / "sources" / "collectors.json"
CACHE_DIR = ROOT / "data" / "cache" / "collectors"
CACHE_TTL_SECONDS = 3 * 60 * 60          # 与 feeds 缓存一致：3 小时
TIMEOUT = 25
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 news-radar/1.0")


class CollectorError(RuntimeError):
    """采集器失败（网络/解析/配置）。"""


# --------------------------------------------------------------- 配置与缓存

def load_collectors(only=None):
    """读 collectors.json，返回启用的采集器配置 list。

    only: None 全部启用项；或传入 id/type/group 做过滤（与 feeds.load_feeds 对齐）。
    """
    if not COLLECTORS_CONF.exists():
        return []
    data = json.loads(COLLECTORS_CONF.read_text(encoding="utf-8"))
    out = []
    for c in data.get("collectors", []):
        if not c.get("enabled", False):
            continue
        if only and not (c.get("id") == only or c.get("type") == only
                         or c.get("group") == only):
            continue
        out.append(c)
    return out


def _cache_path(cid):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", cid)
    return CACHE_DIR / f"{safe}.json"


def _read_cache(cid):
    p = _cache_path(cid)
    if not p.exists():
        return None
    age = time.time() - p.stat().st_mtime
    if age > CACHE_TTL_SECONDS:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_cache(cid, payload):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _cache_path(cid).with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_cache_path(cid))


def _http_json(url):
    """GET 一个 JSON 端点，自动解 gzip，返回解析后的对象。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding", "").lower() == "gzip" \
                    or raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise CollectorError(f"请求失败: {e}") from e
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        raise CollectorError(f"JSON 解析失败: {e}") from e


def _dt(epoch_seconds):
    if not epoch_seconds:
        return None
    try:
        return datetime.fromtimestamp(int(epoch_seconds), tz=timezone.utc)
    except (ValueError, OSError, TypeError):
        return None


# --------------------------------------------------------------- OpenRouter

def collect_openrouter(conf):
    """OpenRouter 免费模型上新：只取近 max_age_days 天且 prompt/补全都免费的。"""
    cid = conf["id"]
    max_age = int(conf.get("max_age_days", 14))
    limit = int(conf.get("limit", 20))
    group = conf.get("group", "模型优惠与福利")
    cutoff = time.time() - max_age * 86400

    data = _http_json("https://openrouter.ai/api/v1/models")
    models = data.get("data", []) if isinstance(data, dict) else []
    entries = []
    for m in models:
        mid = m.get("id")
        if not mid:
            continue
        pricing = m.get("pricing") or {}
        try:
            is_free = mid.endswith(":free") or (
                float(pricing.get("prompt", "1") or "1") == 0
                and float(pricing.get("completion", "1") or "1") == 0)
        except (ValueError, TypeError):
            is_free = mid.endswith(":free")
        if not is_free:
            continue
        created = m.get("created")
        if created and created < cutoff:
            continue
        ctx = m.get("context_length")
        ctx_txt = f"{round(ctx / 1024)}K 上下文" if ctx else ""
        desc = re.sub(r"\s+", " ", m.get("description") or "").strip()[:260]
        summary = " · ".join(x for x in (ctx_txt, desc) if x) \
            or "OpenRouter 免费 API 模型，prompt 与补全定价均为 0"
        entries.append({
            "title": f"OpenRouter 新免费模型：{m.get('name') or mid}",
            "link": f"https://openrouter.ai/{mid}",
            "summary": summary,
            "published": _dt(created),
            "source_id": cid,
            "source_name": conf.get("name", "OpenRouter 免费模型"),
            "group": group,
            "kind": "openrouter",
        })
    entries.sort(key=lambda e: e["published"] or datetime.min.replace(tzinfo=timezone.utc),
                 reverse=True)
    payload = {"fetched_at": int(time.time()),
               "entries": [{**e, "published": e["published"].isoformat() if e["published"] else None}
                           for e in entries[:limit]]}
    _write_cache(cid, payload)
    return entries[:limit]


# --------------------------------------------------------------- Hacker News

# 本地再卡一道 AI 相关性，避免 Algolia 全文检索召回的泛科技噪音
_HN_AI_RE = re.compile(
    r"\b(ai|llm|gpt|agent|agents|claude|gemini|openai|anthropic|rag|mcp|"
    r"diffusion|transformer|neural|machine learning|deep learning|inference|"
    r"fine[- ]?tun|embedding|chatbot|copilot|aigc)\b|大模型|智能体|人工智能",
    re.I)
_HN_QUERIES = ("AI", "LLM", "GPT", "agent", "Claude", "OpenAI")


def collect_hackernews(conf):
    """Hacker News 上的 AI 故事：Algolia 单次搜索 API，多关键词合并去重。"""
    cid = conf["id"]
    limit = int(conf.get("limit", 30))
    group = conf.get("group", "开发者社区")
    queries = conf.get("queries") or _HN_QUERIES
    hits_per = max(10, min(int(conf.get("hits_per_query", 20)), 50))

    seen, entries = set(), []
    for q in queries:
        url = ("https://hn.algolia.com/api/v1/search?tags=story"
               f"&query={urllib.parse.quote(q)}&hitsPerPage={hits_per}")
        try:
            data = _http_json(url)
        except CollectorError:
            continue                       # 单个关键词失败不拖垮整组
        for h in data.get("hits", []):
            oid = h.get("objectID")
            title = (h.get("title") or "").strip()
            if not oid or not title or oid in seen:
                continue
            if not _HN_AI_RE.search(title):
                continue                   # 标题不含 AI 信号则丢弃
            seen.add(oid)
            link = h.get("url") or f"https://news.ycombinator.com/item?id={oid}"
            points = h.get("points") or 0
            comments = h.get("num_comments") or 0
            story = re.sub(r"\s+", " ", h.get("story_text") or "").strip()
            story = re.sub(r"<[^>]+>", "", story)[:200]
            meta = f"HN {points} 分 / {comments} 评论"
            summary = (meta + (" · " + story if story else ""))
            entries.append({
                "title": title,
                "link": link,
                "summary": summary,
                "published": _dt(h.get("created_at_i")),
                "source_id": cid,
                "source_name": conf.get("name", "Hacker News · AI"),
                "group": group,
                "kind": "hackernews",
            })
    entries.sort(key=lambda e: e["published"] or datetime.min.replace(tzinfo=timezone.utc),
                 reverse=True)
    payload = {"fetched_at": int(time.time()),
               "entries": [{**e, "published": e["published"].isoformat() if e["published"] else None}
                           for e in entries[:limit]]}
    _write_cache(cid, payload)
    return entries[:limit]


_COLLECTOR_FUNCS = {
    "openrouter": collect_openrouter,
    "hackernews": collect_hackernews,
}


# --------------------------------------------------------------- 统一入口

def _from_cache(cid):
    payload = _read_cache(cid)
    if not payload:
        return None
    out = []
    for e in payload.get("entries", []):
        pub = e.get("published")
        out.append({**e, "published": datetime.fromisoformat(pub) if pub else None})
    return out


def fetch_one(conf, offline=False):
    """采集单个采集器。失败/离线时回退缓存，无缓存抛 CollectorError。"""
    ctype = conf.get("type")
    func = _COLLECTOR_FUNCS.get(ctype)
    if func is None:
        raise CollectorError(f"未知采集器类型: {ctype}")
    if offline:
        cached = _from_cache(conf["id"])
        if cached is None:
            raise CollectorError("离线模式且无本地缓存")
        return cached
    try:
        return func(conf)
    except CollectorError:
        cached = _from_cache(conf["id"])
        if cached is not None:
            return cached
        raise


def fetch_all(only=None, offline=False, log=print):
    """采集全部启用采集器，返回 (entries, failures)。单源容错。"""
    confs = load_collectors(only=only)
    entries, failures = [], []
    for conf in confs:
        cid, name = conf["id"], conf.get("name", conf["id"])
        try:
            items = fetch_one(conf, offline=offline)
            entries.extend(items)
            if log:
                log(f"  ✓ [{conf.get('type')}] {name}: {len(items)} 条")
        except CollectorError as e:
            failures.append({"id": cid, "name": name, "error": str(e)})
            if log:
                log(f"  ✗ [{conf.get('type')}] {name}: {e}")
    return entries, failures
