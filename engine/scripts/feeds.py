# -*- coding: utf-8 -*-
"""AI 资讯信源：RSS/Atom 拉取与解析（纯标准库，零额外依赖）。

设计：
- 信源声明在 data/sources/feeds.json（参考 KKKKhazix/AIHOT 的 industry/sources.json）。
- 单源容错：任一信源超时/解析失败只记 error，不影响其他源。
- 缓存：每个源的原始 XML 缓存 data/cache/feeds/<id>.xml，离线/失败时回退缓存。
- 解析用 xml.etree（结构化、抗 HTML 嵌套），不拼脆弱正则。
- 仅支持零 key 的 rss/atom；AIHOT 的 web_list/x_search/mp_account 需付费 key，不纳入。
"""
import gzip
import json
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
FEEDS_CONF = ROOT / "data" / "sources" / "feeds.json"
CACHE_DIR = ROOT / "data" / "cache" / "feeds"
CACHE_MAX_ITEMS = 30                    # 写缓存前只保留最新 N 条，防止单 feed 缓存膨胀到 MB 级
SUMMARY_MAX_CHARS = 800                 # strip_html 前先粗截断 HTML 到此长度（前端最多显示几百字）
HEALTH_FILE = ROOT / "data" / "source-health.json"
AUTO_DISABLE_FAILS = 3              # 连续失败次数达到该值自动停用信源

UA = "Mozilla/5.0 (compatible; ai-git-radar/0.5; +https://github.com/)"
TIMEOUT = 20
CACHE_TTL_SECONDS = 3 * 3600          # 资讯缓存 3 小时
PROGRESS_FILE = ROOT / "data" / "news-progress.json"  # 采集进度（插件轮询用）

# Atom 命名空间
NS = {"atom": "http://www.w3.org/2005/Atom"}
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# 整块移除 <style>/<script>（含内部 CSS/JS 文本，DOTALL 跨行）
_BLOCK_RE = re.compile(r"<(style|script)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
# 去标签后残留的 CSS/JS 块注释与行注释，以及 { ... } 样式规则残片
_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_CSS_RULE_RE = re.compile(r"[^{}]*\{[^{}]*\}")
# HTML 注释 <!-- ... -->
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


class FeedError(Exception):
    """单个信源失败（网络/解析/格式），不应中断整轮采集。"""


# --------------------------------------------------------------- 配置

def load_feeds(only=None, include_disabled=False):
    """返回启用的信源 dict 列表。only: 逗号分隔的 id/group 过滤。"""
    conf = json.loads(FEEDS_CONF.read_text(encoding="utf-8"))
    sources = conf["sources"]
    if not include_disabled:
        sources = [s for s in sources if s.get("enabled", True)]
    if only:
        wanted = {x.strip() for x in only.split(",") if x.strip()}
        sources = [s for s in sources
                   if s["id"] in wanted or s.get("group") in wanted]
    return sources


def load_conf():
    """读取完整信源配置（含停用源），供写回/采纳新源使用。"""
    return json.loads(FEEDS_CONF.read_text(encoding="utf-8"))


def save_conf(conf):
    """写回信源表（2 空格缩进 + 尾换行），与插件面板的写入口径一致。"""
    FEEDS_CONF.parent.mkdir(parents=True, exist_ok=True)
    FEEDS_CONF.write_text(
        json.dumps(conf, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# --------------------------------------------------------------- 健康检查（自动停用）

def load_health():
    """读健康记录 {id: {consecutive_failures, last_error, last_ok, last_fail}}。"""
    if not HEALTH_FILE.exists():
        return {}
    try:
        return json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_health(health):
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_FILE.write_text(
        json.dumps(health, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def record_health(ok_map, failure_map, log=None):
    """按一轮采集结果更新健康记录；连续失败达 AUTO_DISABLE_FAILS 自动停用。

    ok_map: 成功 id 集合；failure_map: {id: error 文本}。离线模式调用方不应调用。
    自动停用会改写 feeds.json 并写 disabled_reason，成功一次即重置计数。
    """
    health = load_health()
    if not hasattr(failure_map, "items"):      # 容忍空集/迭代器等非 mapping 入参
        failure_map = {sid: "" for sid in (failure_map or ())}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for sid in ok_map:
        rec = health.setdefault(sid, {})
        if rec.get("consecutive_failures"):
            rec["consecutive_failures"] = 0
            rec.pop("last_error", None)
        rec["last_ok"] = now
    changed = False
    for sid, err in failure_map.items():
        rec = health.setdefault(sid, {})
        rec["consecutive_failures"] = int(rec.get("consecutive_failures", 0)) + 1
        rec["last_error"] = str(err)[:200]
        rec["last_fail"] = now
        if rec["consecutive_failures"] >= AUTO_DISABLE_FAILS:
            conf = load_conf()
            for src in conf["sources"]:
                if (src["id"] == sid and src.get("enabled", True)
                        and not src.get("manual_disabled")):
                    src["enabled"] = False
                    src["disabled_reason"] = (
                        f"健康检查自动停用：连续 {rec['consecutive_failures']} 次失败"
                        f"（最近错误：{str(err)[:80]}）")
                    rec["auto_disabled"] = True
                    changed = True
                    if log:
                        log(f"  ⏸ 自动停用 {sid}（连续 {rec['consecutive_failures']} 次失败）")
    if changed:
        save_conf(conf)
    save_health(health)
    return health


# --------------------------------------------------------------- 工具

def _strip_html(text):
    """去 HTML 标签、压缩空白，返回纯文本摘要。

    先整块移除 <style>/<script>（否则内部 CSS/JS 在去标签后会变成文本噪声，
    实测 GitHub Blog 的字体版权、MS Research 的 .yt-consent 样式都这样混入），
    再清 HTML 注释、残留 CSS 注释与 {规则} 残片，最后去普通标签。
    """
    if not text:
        return ""
    # 快速路径：纯文本（无 HTML 标签）跳过全部正则，只做空白压缩
    if "<" not in text:
        return _WS_RE.sub(" ", text).strip()
    # 粗截断：原始 HTML 可能是几十 KB 全文，避免超大字符串跑正则
    if len(text) > SUMMARY_MAX_CHARS * 2:
        cut = text.rfind(">", 0, SUMMARY_MAX_CHARS * 2)
        if cut > 0:
            text = text[:cut + 1]
    text = _BLOCK_RE.sub(" ", text)
    text = _HTML_COMMENT_RE.sub(" ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = _TAG_RE.sub("", text)
    text = _CSS_COMMENT_RE.sub(" ", text)
    # 只清理「明显是样式规则」的残片（选择器{声明}），避免误伤正常花括号内容
    if "{" in text and (";" in text or ":" in text):
        text = _CSS_RULE_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def _parse_date(value):
    """解析 RSS 的 RFC822（pubDate）或 Atom 的 ISO8601（published/updated）。

    失败返回 None（调用方按无日期处理，不抛异常）。
    """
    if not value:
        return None
    value = value.strip()
    # Atom / ISO8601：把结尾 Z 归一化为 +00:00
    try:
        if value.endswith("Z"):
            return datetime.fromisoformat(value[:-1] + "+00:00")
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    # RSS RFC822：Thu, 12 Nov 2026 00:00:00 GMT
    try:
        dt = parsedate_to_datetime(value)
        if dt is None:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _atom_text(entry, path):
    el = entry.find(path, NS)
    return el.text if el is not None and el.text else ""


# --------------------------------------------------------------- 解析

def parse_feed(xml_text, source):
    """把一段 RSS 2.0 或 Atom XML 解析成统一的条目 list。

    每条：{title, link, summary, published(datetime|None), source_id, source_name, group}
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise FeedError(f"XML 解析失败: {e}")

    meta = {"source_id": source["id"], "source_name": source["name"],
            "group": source.get("group", "其他")}
    items = []

    # RSS 2.0：rss/channel/item
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = item.findtext("description") or ""
        # content:encoded 常含全文，优先取它再截断由渲染层负责
        full = item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded")
        summary = _strip_html(full or desc)
        pub = _parse_date(item.findtext("pubDate"))
        if title and link:
            items.append({**meta, "title": _strip_html(title), "link": link,
                          "summary": summary, "published": pub})

    # Atom：feed/entry
    for entry in root.iter(f"{{{NS['atom']}}}entry"):
        title = _atom_text(entry, "atom:title")
        link = ""
        for le in entry.findall("atom:link", NS):
            if le.get("rel") in (None, "alternate") and le.get("href"):
                link = le.get("href")
                break
        summary = _atom_text(entry, "atom:summary") or _atom_text(entry, "atom:content")
        pub = (_parse_date(_atom_text(entry, "atom:published"))
               or _parse_date(_atom_text(entry, "atom:updated")))
        if title and link:
            items.append({**meta, "title": _strip_html(title), "link": link,
                          "summary": _strip_html(summary), "published": pub})

    if not items:
        # 区分「合法的空 feed」与「根本不是 feed」：arXiv 在周末不发布公告，
        # rss.arxiv.org 会返回含 <channel><skip><day>Saturday</day>… 但零 item 的
        # 合法 RSS。这类不能算采集失败，否则连续 3 天会被健康检查自动停用（见坑 34）。
        root_tag = root.tag.split("}")[-1] if isinstance(root.tag, str) else ""
        if root_tag in ("rss", "feed", "RDF"):
            return []
        raise FeedError("未解析到任何 item/entry（页面结构变化或非 feed）")
    return items


# --------------------------------------------------------------- 拉取

def _rebuild_xml(items, source):
    """把 items 重打包成 RSS 2.0 XML 写入缓存。只保留前 N 条（已按时间倒序），
    每条只留 title/link/summary/published 四字段，能从 MB 级砍到 KB 级。
    """
    items = items[:CACHE_MAX_ITEMS]
    esc = (lambda s: (s or "").replace("&", "&amp;").replace("<", "&lt;")
           .replace(">", "&gt;").replace('"', "&quot;"))
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<rss version="2.0"><channel>',
           f"<title>{esc(source['name'])}</title>",
           f"<link>{esc(source.get('url', ''))}</link>"]
    for it in items:
        pub = it.get("published")
        pub_str = pub.strftime("%a, %d %b %Y %H:%M:%S GMT") if pub else ""
        out.append("<item>"
                   f"<title>{esc(it.get('title', ''))}</title>"
                   f"<link>{esc(it.get('link', ''))}</link>"
                   f"<description>{esc(it.get('summary', ''))}</description>"
                   f"<pubDate>{pub_str}</pubDate>"
                   "</item>")
    out.append("</channel></rss>")
    return "\n".join(out)


def _cache_path(source_id):
    return CACHE_DIR / f"{source_id}.xml"


def _read_cache(source_id):
    p = _cache_path(source_id)
    if not p.exists():
        return None
    age = datetime.now().timestamp() - p.stat().st_mtime
    if age > CACHE_TTL_SECONDS:
        return None
    return p.read_text(encoding="utf-8", errors="replace")


def _decode_body(raw, encoding):
    """按响应头或魔数解压 gzip，再按 UTF-8 解码。

    部分站点（如 deepmind.google）无视请求头强制返回 gzip，urllib 不自动解压，
    直接 decode 会得到一堆替换符并导致 XML 解析失败。
    """
    if encoding == "gzip" or raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    elif encoding == "deflate":
        import zlib
        raw = zlib.decompress(raw)
    return raw.decode("utf-8", errors="replace")


def fetch_one(source, offline=False):
    """拉取并解析单个信源，返回条目 list。

    网络失败时回退缓存（即使过期也用，保证离线可出报告）；都没有才抛 FeedError。
    缓存统一存解压后的 XML 文本，离线路径不再需要处理压缩。
    """
    cache = _cache_path(source["id"])
    xml_text = None
    if not offline:
        req = urllib.request.Request(source["url"], headers={
            "User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read()
                xml_text = _decode_body(raw, resp.headers.get("Content-Encoding", ""))
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            # 解析后重打包瘦身写回（只留最新 N 条，防止缓存膨胀）
            try:
                parsed = parse_feed(xml_text, source)
                # 空 feed（如 arXiv 周末无公告）不要覆盖缓存，否则离线时
                # 会丢掉上一批真实的论文条目（见坑 34）
                if parsed:
                    cache.write_text(_rebuild_xml(parsed, source), encoding="utf-8")
            except FeedError:
                # 解析失败保留原始缓存（下次离线还能用）
                cache.write_text(xml_text, encoding="utf-8")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            # 回退缓存：新鲜缓存优先，过期也接受
            if cache.exists():
                xml_text = cache.read_text(encoding="utf-8", errors="replace")
            else:
                raise FeedError(f"拉取失败且无缓存: {e}")
    else:
        xml_text = _read_cache(source_id=source["id"])
        if xml_text is None and cache.exists():
            xml_text = cache.read_text(encoding="utf-8", errors="replace")
        if xml_text is None:
            raise FeedError("离线模式且无缓存")
    return parse_feed(xml_text, source)


# ------------------------------------------------------------- 进度追踪

def _write_progress(stage, done, total, current_name, started_ms):
    """写进度文件，供插件 GET /news/progress 轮询；失败静默忽略。"""
    try:
        PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        PROGRESS_FILE.write_text(json.dumps({
            "stage": stage,           # idle | fetching | done
            "done": done,
            "total": total,
            "current": current_name,
            "started_at": started_ms,
        }, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def clear_progress():
    """采集结束后删除进度文件（next 轮询返回 idle）。"""
    try:
        PROGRESS_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# ------------------------------------------------------------- 跨源去重

DEDUP_SIM_THRESHOLD = 0.82       # 标题相似度阈值；≥此值视为同一篇


def _normalize_title(t):
    """标题归一：小写、去标点空白、全角转半角。"""
    if not t:
        return ""
    import unicodedata
    t = unicodedata.normalize("NFKC", t).lower()
    out = []
    for ch in t:
        cat = unicodedata.category(ch)
        if cat.startswith("P") or cat.startswith("Z") or cat in ("S",):
            continue
        out.append(ch)
    return "".join(out)


def _ngrams(s, n=3):
    if len(s) < n:
        return {s} if s else set()
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def _title_sim(a, b):
    """基于字符 3-gram 的 Dice 系数，0~1。"""
    ga, gb = _ngrams(a), _ngrams(b)
    if not ga or not gb:
        return 0.0
    return 2 * len(ga & gb) / (len(ga) + len(gb))


def _dedup_entries(entries, threshold=DEDUP_SIM_THRESHOLD):
    """按归一化标题去重；保留最先出现的一条（feeds 已按时间倒序，等价于最新）。"""
    keep, dup_count = [], 0
    kept_norm = []
    for e in entries:
        norm = _normalize_title(e.get("title", ""))
        if norm:
            dup = False
            for kn in kept_norm:
                if _title_sim(norm, kn) >= threshold:
                    dup = True
                    break
            if dup:
                dup_count += 1
                continue
            kept_norm.append(norm)
        keep.append(e)
    return keep, dup_count



def _safe_dt_sort_key(x):
    """排序 key：None → epoch；naive → 补 UTC；aware 直接用。"""
    dt = x.get("published")
    if dt is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fetch_all(only=None, offline=False, per_source_limit=8, log=print, workers=8):
    """并发采集全部启用信源。

    返回 (entries, failures)：
      entries  全部条目（已按时间倒序、每源截断 per_source_limit）
      failures [{id,name,error}]  失败信源，供报告标注

    用线程池并发（纯网络 I/O），各源写各自的缓存文件、无共享可变状态；
    日志在全部返回后按 feeds.json 的源顺序统一打印，避免多线程输出交错。
    workers=1 时退化为串行（selftest/调试用）。
    """
    sources = load_feeds(only=only)
    results = [None] * len(sources)     # 按下标占位，保证日志与源顺序一致
    workers = max(1, min(workers, len(sources) or 1))

    def _job(i, src):
        try:
            return i, src, fetch_one(src, offline=offline), None
        except FeedError as e:
            return i, src, None, str(e)

    import time
    import threading
    started_ms = int(time.time() * 1000)
    _write_progress("init", 0, len(sources), "", started_ms)

    done_counter = [0]
    _lock = threading.Lock()

    def _job_tracked(i, src):
        try:
            items = fetch_one(src, offline=offline)
            result = (i, src, items, None)
        except FeedError as e:
            result = (i, src, None, str(e))
        with _lock:
            done_counter[0] += 1
            _write_progress("fetching", done_counter[0], len(sources),
                            src["name"], started_ms)
        return result

    if workers == 1:
        for i, src in enumerate(sources):
            results[i] = _job_tracked(i, src)
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_job_tracked, i, src): i
                       for i, src in enumerate(sources)}
            for future in as_completed(futures):
                i, src, items, err = future.result()
                results[i] = (i, src, items, err)

    _write_progress("done", len(sources), len(sources), "", started_ms)
    entries, failures = [], []
    ok_ids, fail_map = set(), {}
    for i, src, items, err in results:
        if err is not None:
            failures.append({"id": src["id"], "name": src["name"], "error": err})
            fail_map[src["id"]] = err
            if log:
                log(f"  ✗ {src['name']}: {err}")
            continue
        ok_ids.add(src["id"])
        items.sort(key=_safe_dt_sort_key, reverse=True)
        entries.extend(items[:per_source_limit])
        if log:
            log(f"  ✓ {src['name']}: {len(items)} 条（取前 {min(len(items), per_source_limit)}）")
    # 在线模式才记录健康并可能自动停用；离线失败只是无缓存，不代表源失效
    if not offline and (ok_ids or fail_map):
        record_health(ok_ids, fail_map, log=log)
    entries.sort(key=_safe_dt_sort_key, reverse=True)
    entries, dup_count = _dedup_entries(entries)
    clear_progress()
    return entries, failures, dup_count
