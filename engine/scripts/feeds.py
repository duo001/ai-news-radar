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

UA = "Mozilla/5.0 (compatible; ai-git-radar/0.5; +https://github.com/)"
TIMEOUT = 20
CACHE_TTL_SECONDS = 3 * 3600          # 资讯缓存 3 小时

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


# --------------------------------------------------------------- 工具

def _strip_html(text):
    """去 HTML 标签、压缩空白，返回纯文本摘要。

    先整块移除 <style>/<script>（否则内部 CSS/JS 在去标签后会变成文本噪声，
    实测 GitHub Blog 的字体版权、MS Research 的 .yt-consent 样式都这样混入），
    再清 HTML 注释、残留 CSS 注释与 {规则} 残片，最后去普通标签。
    """
    if not text:
        return ""
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
        return parsedate_to_datetime(value)
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
        raise FeedError("未解析到任何 item/entry（页面结构变化或非 feed）")
    return items


# --------------------------------------------------------------- 拉取

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

    if workers == 1:
        for i, src in enumerate(sources):
            results[i] = _job(i, src)
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for i, src, items, err in ex.map(lambda p: _job(*p),
                                             list(enumerate(sources))):
                results[i] = (i, src, items, err)

    entries, failures = [], []
    for i, src, items, err in results:
        if err is not None:
            failures.append({"id": src["id"], "name": src["name"], "error": err})
            if log:
                log(f"  ✗ {src['name']}: {err}")
            continue
        items.sort(key=lambda x: x["published"] or datetime.min.replace(tzinfo=timezone.utc),
                   reverse=True)
        entries.extend(items[:per_source_limit])
        if log:
            log(f"  ✓ {src['name']}: {len(items)} 条（取前 {min(len(items), per_source_limit)}）")
    entries.sort(key=lambda x: x["published"] or datetime.min.replace(tzinfo=timezone.utc),
                 reverse=True)
    return entries, failures
