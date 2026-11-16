# -*- coding: utf-8 -*-
"""信源体检：基于本地 DB 与 source-health.json 找出静默源/故障源/孤儿记录。

纯本地分析，不发网络请求（在线探活仍由 feeds 采集本身与手动 curl 完成）。
- 静默：启用的信源在近 N 天 DB 窗口内 0 条（低频博客与真失效都会出现，需人工区分）
- 故障：source-health.json 里 consecutive_fails 达阈值的源
- 孤儿：health 里有、feeds.json 里已删除的源 id
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEALTH_JSON = ROOT / "data" / "source-health.json"

FAIL_WARN = 2  # consecutive_fails 达到该值即列入故障榜


def _parse_dt(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def load_health():
    try:
        return json.loads(HEALTH_JSON.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def source_counts(entries, days):
    """统计窗口内每个 source_id 的条数与最新发布时间。entries 为 DB 回读条目。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    counts, latest = {}, {}
    for e in entries:
        sid = e.get("source_id") or ""
        if not sid:
            continue
        ts = _parse_dt(e.get("published"))
        # 最新发布时间用全量数据算（30 天保留窗口内的最后一条）
        if sid not in latest or (ts and (latest[sid] is None or ts > latest[sid])):
            latest[sid] = ts
        if ts and ts < cutoff:
            continue
        counts[sid] = counts.get(sid, 0) + 1
    return counts, latest


def _source_list(feeds_doc):
    """兼容两种形态：feeds.load_feeds 返回的 list，或完整 {"sources":[...]} dict。"""
    if isinstance(feeds_doc, dict):
        return feeds_doc.get("sources", [])
    return feeds_doc or []


def silent_sources(feeds_doc, entries, days=7):
    """返回启用但近 N 天 0 条的信源：[{id,name,group,last_published}]。"""
    counts, latest = source_counts(entries, days)
    out = []
    for s in _source_list(feeds_doc):
        if not s.get("enabled", True):
            continue
        sid = s.get("id", "")
        if counts.get(sid, 0) == 0:
            ts = latest.get(sid)
            out.append({
                "id": sid,
                "name": s.get("name", sid),
                "group": s.get("group", ""),
                "last_published": ts.isoformat(timespec="seconds") if ts else None,
            })
    out.sort(key=lambda x: (x["group"], x["name"]))
    return out


def failing_sources(feeds_doc, health=None):
    """health 中连续失败达阈值、且配置仍启用的源。"""
    health = load_health() if health is None else health
    enabled = {s["id"]: s for s in _source_list(feeds_doc) if s.get("enabled", True)}
    out = []
    for sid, rec in health.items():
        if sid not in enabled:
            continue
        fails = int(rec.get("consecutive_fails", 0) or 0)
        if fails >= FAIL_WARN:
            out.append({
                "id": sid,
                "name": enabled[sid].get("name", sid),
                "group": enabled[sid].get("group", ""),
                "consecutive_fails": fails,
                "last_error": str(rec.get("last_error", ""))[:120],
            })
    out.sort(key=lambda x: -x["consecutive_fails"])
    return out


def orphan_health(feeds_doc, health=None):
    """health 里残留、但 feeds.json 已不存在的源 id。"""
    health = load_health() if health is None else health
    live = {s.get("id") for s in _source_list(feeds_doc)}
    return sorted(sid for sid in health if sid not in live)


def run_check(feeds_doc, entries, days=7):
    """一次跑完三项，返回供 CLI/周报共用的结构化结果。"""
    return {
        "days": days,
        "silent": silent_sources(feeds_doc, entries, days),
        "failing": failing_sources(feeds_doc),
        "orphans": orphan_health(feeds_doc),
    }
