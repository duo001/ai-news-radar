# -*- coding: utf-8 -*-
"""信源自动发现与待审队列（纯标准库，零额外依赖）。

四条发现通道（用户在 v0.8 选定全部启用）：
1. 网页自动发现：抓种子站点 HTML，解析 <link rel="alternate" type="rss/atom">，
   没找到再探测 /feed、/rss 等常见路径；每个候选必须通过 feeds.parse_feed 验证。
2. OPML 批量导入：解析阅读器订阅导出的 <outline xmlUrl=...>，逐条验证。
3. 远程清单同步：拉 AIHOT 等开源项目的 sources.json，与本地 feeds.json 做 diff。
4. 健康检查自动停用：在 feeds.fetch_all 内按连续失败计数实现（见 feeds.py）。

发现结果不直接进信源表，统一写入 data/source-suggestions.json 的待审队列
（status: pending/accepted/ignored），由 CLI 或插件面板人工采纳，避免低质量源
污染资讯流。采纳时才写回 data/sources/feeds.json。
"""
import gzip
import json
import re
import time
import urllib.request
import netcfg
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import feeds

ROOT = Path(__file__).resolve().parent.parent
SEED_FILE = ROOT / "data" / "sources" / "discover-seeds.json"
OPML_CATALOG = ROOT / "data" / "sources" / "opml-catalog.json"
SUGGESTIONS_FILE = ROOT / "data" / "source-suggestions.json"

DISCOVER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
DISCOVER_TIMEOUT = 15       # 单个候选 feed 的验证超时
LIST_TIMEOUT = 45           # OPML / 远程清单下载超时（raw.githubusercontent 较慢）
LIST_RETRIES = 2            # 清单下载失败重试次数
# link 标签没找到时的常见 feed 路径（WordPress/Hugo/Ghost/Jekyll 惯例）
COMMON_PATHS = ("/feed", "/feed.xml", "/rss", "/rss.xml", "/index.xml", "/atom.xml")
# 远程清单默认值（AIHOT 开源信源表）
DEFAULT_REMOTE = ("https://raw.githubusercontent.com/KKKKhazix/AIHOT"
                  "/main/industry/sources.json")
_LINK_RE = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_TYPE_RE = re.compile(r"""type\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_REL_RE = re.compile(r"""rel\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_FEED_TYPES = {"application/rss+xml", "application/atom+xml", "application/rdf+xml"}
# 评论/回复类 feed 不是资讯源（WordPress 站点常同时暴露 /comments/feed），发现时跳过
_COMMENT_FEED_RE = re.compile(r"/(comments?|replies?|comment-page)/|comments?\.|/feed/comments",
                              re.IGNORECASE)


def _is_comment_feed(url):
    return bool(_COMMENT_FEED_RE.search(urllib.parse.urlsplit(url).path))


class DiscoverError(Exception):
    """发现过程中的非致命错误（单站/单源失败不中断整轮）。"""


# --------------------------------------------------------------- 存储

def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_suggestions():
    if not SUGGESTIONS_FILE.exists():
        return {"generated_at": None, "suggestions": []}
    return json.loads(SUGGESTIONS_FILE.read_text(encoding="utf-8"))


def save_suggestions(data):
    SUGGESTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data["generated_at"] = _now_iso()
    SUGGESTIONS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _norm_url(url):
    """归一化用于去重：小写 host、去末尾斜杆、去常见跟踪参数。"""
    p = urllib.parse.urlsplit(url.strip())
    path = p.path.rstrip("/")
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(),
                                    path, p.query, ""))


def _slug(url):
    p = urllib.parse.urlsplit(url)
    raw = (p.netloc + p.path).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    return slug[:60] or "feed"


def _existing_urls():
    return {_norm_url(s["url"])
            for s in feeds.load_feeds(include_disabled=True)}


def _existing_ids():
    return {s["id"] for s in feeds.load_feeds(include_disabled=True)}


# --------------------------------------------------------------- 网络与验证

def _http_get(url, accept="*/*", timeout=None):
    req = urllib.request.Request(url, headers={
        "User-Agent": DISCOVER_UA,
        "Accept": accept,
        "Accept-Encoding": "gzip, deflate"})
    with netcfg.open_url(req, timeout=timeout or DISCOVER_TIMEOUT) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding", "") == "gzip" or raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", errors="replace"), resp.geturl()


def _get_list(url, log=print):
    """下载 OPML / 远程清单：长超时 + 重试（网络抖动常见）。"""
    last = None
    for attempt in range(LIST_RETRIES + 1):
        try:
            text, _ = _http_get(url, accept="application/xml, text/xml, */*",
                                timeout=LIST_TIMEOUT)
            return text
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            if attempt < LIST_RETRIES:
                log(f"    清单下载失败（第 {attempt + 1} 次），重试：{e}")
                time.sleep(2)
    raise DiscoverError(str(last))


def validate_feed(url):
    """验证 URL 确实是可解析的 RSS/Atom。

    返回 (item_count, latest_iso, feed_title)；失败抛 DiscoverError。
    """
    try:
        xml_text, final_url = _http_get(url, accept="application/rss+xml, application/atom+xml, */*")
        items = feeds.parse_feed(xml_text, {"id": "_probe", "name": "_probe"})
    except (urllib.error.URLError, TimeoutError, OSError, feeds.FeedError) as e:
        raise DiscoverError(str(e))
    latest = None
    for it in items:
        if it.get("published") and (latest is None or it["published"] > latest):
            latest = it["published"]
    title = _feed_title(xml_text)
    return len(items), (latest.isoformat() if latest else None), title, final_url


def _feed_title(xml_text):
    m = re.search(r"<channel[^>]*>\s*<title[^>]*>(.*?)</title>", xml_text,
                  re.IGNORECASE | re.DOTALL)
    if not m:
        m = re.search(r"<feed[^>]*>.*?<title[^>]*>(.*?)</title>", xml_text,
                      re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    return feeds._strip_html(m.group(1))[:80]


# --------------------------------------------------------------- 通道 1：网页发现

def _link_alternates(html, base_url):
    """从 HTML 提取 rel=alternate 且类型为 RSS/Atom 的绝对 URL（保序去重）。"""
    out, seen = [], set()
    for tag in _LINK_RE.findall(html):
        rel_m, type_m, href_m = _REL_RE.search(tag), _TYPE_RE.search(tag), _HREF_RE.search(tag)
        if not (rel_m and type_m and href_m):
            continue
        if "alternate" not in rel_m.group(1).lower():
            continue
        if type_m.group(1).lower().split(";")[0].strip() not in _FEED_TYPES:
            continue
        abs_url = urllib.parse.urljoin(base_url, href_m.group(1).strip())
        if _is_comment_feed(abs_url):
            continue
        key = _norm_url(abs_url)
        if key not in seen:
            seen.add(key)
            out.append(abs_url)
    return out


def discover_from_page(seed):
    """对一个种子站点：先找 link 标签，找不到再并发探测常见路径。返回候选 URL 列表。"""
    url = seed["url"]
    try:
        html, final_url = _http_get(url, accept="text/html, */*")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise DiscoverError(f"首页抓取失败: {e}")
    candidates = _link_alternates(html, final_url)
    if not candidates:
        base = f"{urllib.parse.urlsplit(final_url).scheme}://{urllib.parse.urlsplit(final_url).netloc}"
        candidates = _probe_common_paths(base)
    return candidates


def _probe_common_paths(base):
    """并发探测常见 feed 路径，返回第一个能解析出条目的 URL（全失败返回空）。

    串行探测 6 个路径 × 15s 超时最坏会让单站卡 90s，30 个种子站就是几十分钟；
    并发 + 短超时后整轮网页发现通常 1~3 分钟。
    """
    from concurrent.futures import ThreadPoolExecutor

    def _try(path):
        try:
            xml_text, final = _http_get(base + path,
                                        accept="application/rss+xml, application/atom+xml, */*")
            items = feeds.parse_feed(xml_text, {"id": "_probe", "name": "_probe"})
            return base + path if items else None
        except (urllib.error.URLError, TimeoutError, OSError, feeds.FeedError):
            return None

    with ThreadPoolExecutor(max_workers=len(COMMON_PATHS)) as ex:
        for hit in ex.map(_try, COMMON_PATHS):
            if hit:
                return [hit]
    return []


def load_seeds(path=None):
    p = Path(path) if path else SEED_FILE
    if not p.exists():
        raise DiscoverError(f"种子文件不存在: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    return data["seeds"]


def load_opml_catalog():
    """读外部 OPML 目录（data/sources/opml-catalog.json），返回 alias→条目映射。"""
    if not OPML_CATALOG.exists():
        return {}
    data = json.loads(OPML_CATALOG.read_text(encoding="utf-8"))
    return {c["alias"]: c for c in data.get("catalogs", [])}


# --------------------------------------------------------------- 通道 2：OPML

def parse_opml(text):
    """从 OPML 文本提取订阅条目 [{name, url}]，容错属性顺序与嵌套。"""
    out, seen = [], set()
    for m in re.finditer(r"<outline\b[^>]*>", text, re.IGNORECASE):
        tag = m.group(0)
        url_m = re.search(r"""xmlurl\s*=\s*["']([^"']+)["']""", tag, re.IGNORECASE)
        if not url_m:
            continue
        url = url_m.group(1).strip()
        key = _norm_url(url)
        if key in seen:
            continue
        seen.add(key)
        title_m = re.search(r"""(?:title|text)\s*=\s*["']([^"']+)["']""", tag, re.IGNORECASE)
        out.append({"name": title_m.group(1) if title_m else "", "url": url})
    return out


# --------------------------------------------------------------- 通道 3：远程清单

def discover_remote(remote_url=None):
    """拉取远程开源信源表（AIHOT 格式），返回其中 rss/atom 条目。"""
    url = remote_url or DEFAULT_REMOTE
    try:
        text = _get_list(url, log=print)
        data = json.loads(text)
    except (DiscoverError, json.JSONDecodeError) as e:
        raise DiscoverError(f"远程清单获取失败: {e}")
    out = []
    for src in data.get("sources", []):
        kind = (src.get("kind") or "").lower()
        feed_url = (src.get("config") or {}).get("feedUrl") or src.get("url")
        if kind in ("rss", "atom") and feed_url:
            out.append({"name": src.get("name", ""), "url": feed_url,
                        "group": src.get("group", "其他"), "kind": kind})
    return out


# --------------------------------------------------------------- 待审队列写入

def _verify_one(url):
    """并发验证单元：返回 (url, ("ok", (count, latest, title, final_url)) | ("err", msg))。

    捕获网络异常（IncompleteRead/ConnectionError/Timeout 等），失败计 errors 而非崩溃。
    """
    try:
        return url, ("ok", validate_feed(url))
    except DiscoverError as e:
        return url, ("err", str(e))
    except Exception as e:
        # 网络层异常（http.client.IncompleteRead、urllib.error.URLError、socket.timeout 等）
        return url, ("err", f"{type(e).__name__}: {e}")


def verify_many(urls, workers=8, log=None):
    """并发验证一批 URL，返回 {归一化 URL: 验证结果}。

    validate_feed 每条约 1~15s，串行验证几十上百条会拖到几十分钟；这里并发后
    入队仍是串行（见 add_suggestion），保证 data 结构不被多线程破坏。
    """
    from concurrent.futures import ThreadPoolExecutor

    uniq = []
    seen = set()
    for u in urls:
        k = _norm_url(u)
        if k not in seen:
            seen.add(k)
            uniq.append(u)
    if not uniq:
        return {}
    out = {}
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(uniq)))) as ex:
        for url, res in ex.map(_verify_one, uniq):
            out[_norm_url(url)] = res
            if log:
                status = "✓" if res[0] == "ok" else "✗"
                log(f"  {status} {url}")
    return out


def add_suggestion(data, url, *, found_via, group, name="", kind="rss", tags=None,
                   verified=None):
    """验证并加入待审队列；已在信源表或队列中的跳过。返回 (status, detail)。

    verified 可传入 verify_many 的预验证结果，避免重复发网络请求。
    """
    norm = _norm_url(url)
    if norm in _existing_urls():
        return "exists", "已在信源表"
    for s in data["suggestions"]:
        if _norm_url(s["url"]) == norm and s["status"] == "pending":
            return "duplicate", "已在待审队列"
    if verified is not None:
        kind_res, payload = verified
        if kind_res == "err":
            return "invalid", payload
        count, latest, feed_title, final_url = payload
    else:
        try:
            count, latest, feed_title, final_url = validate_feed(url)
        except DiscoverError as e:
            return "invalid", str(e)
    suggestion_id = _slug(final_url)
    base = suggestion_id
    n = 2
    while suggestion_id in {s["id"] for s in data["suggestions"]}:
        suggestion_id = f"{base}-{n}"
        n += 1
    data["suggestions"].append({
        "id": suggestion_id,
        "name": (name or feed_title or suggestion_id).strip()[:80],
        "url": final_url,
        "kind": kind,
        "group": group or "其他",
        "tags": tags or [],
        "found_via": found_via,
        "discovered_at": _now_iso(),
        "status": "pending",
        "item_count": count,
        "latest_item_at": latest,
        "note": "",
    })
    return "added", f"{count} 条条目"


def run_web_discovery(seed_path=None, log=print, workers=6):
    """通道1：并发抓种子站首页拿候选 feed，再并发验证，串行入队。"""
    from concurrent.futures import ThreadPoolExecutor

    seeds = load_seeds(seed_path)
    data = load_suggestions()
    stats = {"seeds": len(seeds), "added": 0, "exists": 0,
             "duplicate": 0, "invalid": 0, "errors": 0}

    def _page(seed):
        try:
            return seed, discover_from_page(seed)
        except DiscoverError as e:
            return seed, e

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(seeds)))) as ex:
        pages = list(ex.map(_page, seeds))

    pairs = []
    for seed, res in pages:
        if isinstance(res, Exception):
            stats["errors"] += 1
            log(f"  \u2717 {seed['name']}: {res}")
            continue
        for url in res:
            if not _is_comment_feed(url):
                pairs.append((url, seed))
    log(f"  种子站 {len(seeds)} 个\uff0c候选 feed {len(pairs)} 个\uff0c开始并发验证\u2026")
    verified = verify_many([u for u, _ in pairs], workers=max(8, workers * 2))
    for url, seed in pairs:
        status, detail = add_suggestion(
            data, url, found_via=f"\u7f51\u9875\u53d1\u73b0:{seed['name']}",
            group=seed.get("group", "\u5176\u4ed6"), name=seed.get("name", ""),
            verified=verified.get(_norm_url(url)))
        stats[status] = stats.get(status, 0) + 1
        if status == "added":
            log(f"  + {url}\uff08{detail}\uff09")
    save_suggestions(data)
    return stats


def run_opml_import(opml_path_or_url, log=print, workers=12):
    if opml_path_or_url.startswith(("http://", "https://")):
        try:
            text = _get_list(opml_path_or_url, log=log)
        except DiscoverError as e:
            raise DiscoverError(f"OPML 下载失败: {e}")
    else:
        text = Path(opml_path_or_url).read_text(encoding="utf-8", errors="replace")
    entries = parse_opml(text)
    data = load_suggestions()
    stats = {"entries": len(entries), "added": 0, "exists": 0,
             "duplicate": 0, "invalid": 0}
    todo = [e for e in entries if not _is_comment_feed(e["url"])]
    verified = verify_many([e["url"] for e in todo], workers=workers)
    if todo:
        log(f"  OPML \u6761\u76ee {len(todo)} \u4e2a\uff0c\u5df2\u5e76\u53d1\u9a8c\u8bc1\uff0c\u9010\u6761\u5165\u961f\u2026")
    for ent in todo:
        status, detail = add_suggestion(
            data, ent["url"], found_via="OPML 导入",
            group="其他", name=ent["name"],
            verified=verified.get(_norm_url(ent["url"])))
        stats[status] = stats.get(status, 0) + 1
        if status == "added":
            log(f"  + {ent['url']}（{detail}）")
    save_suggestions(data)
    return stats


def run_remote_sync(remote_url=None, log=print, workers=12):
    entries = discover_remote(remote_url)
    data = load_suggestions()
    stats = {"remote_sources": len(entries), "added": 0, "exists": 0,
             "duplicate": 0, "invalid": 0}
    todo = [e for e in entries if not _is_comment_feed(e["url"])]
    verified = verify_many([e["url"] for e in todo], workers=workers)
    if todo:
        log(f"  远程清单 {len(todo)} 条\uff0c\u5df2\u5e76\u53d1\u9a8c\u8bc1\uff0c\u9010\u6761\u5165\u961f\u2026")
    for ent in todo:
        status, detail = add_suggestion(
            data, ent["url"], found_via="远程清单同步",
            group=ent.get("group", "其他"), name=ent["name"],
            kind=ent.get("kind", "rss"),
            verified=verified.get(_norm_url(ent["url"])))
        stats[status] = stats.get(status, 0) + 1
        if status == "added":
            log(f"  + {ent['url']}（{detail}）")
    save_suggestions(data)
    return stats


# --------------------------------------------------------------- 采纳/忽略

def set_status(ids, status):
    """把待审条目标记为 accepted/ignored；accepted 同时写回 feeds.json。"""
    data = load_suggestions()
    wanted = set(ids)
    changed = []
    for s in data["suggestions"]:
        if s["id"] in wanted and s["status"] == "pending":
            s["status"] = status
            s["decided_at"] = _now_iso()
            changed.append(s)
    if not changed:
        save_suggestions(data)
        return []
    if status == "accepted":
        conf = feeds.load_conf()
        existing = _existing_ids()
        for s in changed:
            new_id = s["id"]
            base, n = new_id, 2
            while new_id in existing:
                new_id = f"{base}-{n}"
                n += 1
            conf["sources"].append({
                "id": new_id, "name": s["name"], "url": s["url"],
                "kind": s.get("kind", "rss"), "group": s.get("group", "其他"),
                "tags": s.get("tags", []), "enabled": True})
            existing.add(new_id)
        feeds.save_conf(conf)
    save_suggestions(data)
    return changed
