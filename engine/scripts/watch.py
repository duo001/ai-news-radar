# -*- coding: utf-8 -*-
"""关键词关注（watch）：用户关心的词命中时给资讯打 watch_hits 标记。

设计与 enrich.py 同一套哲学：纯规则、零 key、渲染层可对历史数据重算。
- 配置在 data/sources/watch.json，声明式：{"keywords": [{"term": "...", "enabled": true}]}
- 匹配范围：标题 + 摘要 + 中文译文（翻译库由调用方传入）
- 纯 ASCII 词加词边界（"mcp" 不会命中 "scmcp"），中文走子串
- 不修改任何采集/分类逻辑，只在条目上附加 watch_hits 列表
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WATCH_CONF = ROOT / "data" / "sources" / "watch.json"


def load_watch():
    """返回启用的关键词列表；配置缺失/损坏时返回空列表（功能静默关闭）。"""
    try:
        doc = json.loads(WATCH_CONF.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception:
        return []
    out = []
    for item in doc.get("keywords", []):
        term = str(item.get("term", "")).strip()
        if term and item.get("enabled", True):
            out.append(term)
    # 去重保序
    seen, uniq = set(), []
    for t in out:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            uniq.append(t)
    return uniq


def _is_ascii(text):
    try:
        text.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _compile(term):
    """ASCII 词加词边界；含中文等非 ASCII 字符时退化为大小写不敏感子串。"""
    if _is_ascii(term):
        return re.compile(r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])")
    return re.compile(re.escape(term.lower()))


def match_watch(entry, keywords=None, translations=None):
    """返回命中的关键词列表（保留配置里的原始写法），未命中返回 []。"""
    keywords = load_watch() if keywords is None else keywords
    if not keywords:
        return []
    parts = [entry.get("title") or "", entry.get("summary") or ""]
    tr = (translations or {}).get(entry.get("link", "")) or {}
    if tr:
        parts.append(tr.get("zh_title") or "")
        parts.append(tr.get("zh_summary") or "")
    blob = " \n".join(parts).lower()
    hits = []
    for term in keywords:
        if _compile(term).search(blob):
            hits.append(term)
    return hits


def attach_watch(entries, keywords=None, translations=None, log=None):
    """批量给条目附加 watch_hits 字段，返回命中条数。"""
    keywords = load_watch() if keywords is None else keywords
    n = 0
    for e in entries:
        hits = match_watch(e, keywords, translations)
        e["watch_hits"] = hits
        if hits:
            n += 1
    if log and keywords:
        log(f"  关键词关注：{len(keywords)} 个词，命中 {n} 条")
    return n


def summarize(entries):
    """统计命中情况，供报告头/周报使用。"""
    from collections import Counter
    c = Counter()
    for e in entries:
        for t in e.get("watch_hits", []):
            c[t] += 1
    return dict(c.most_common())
