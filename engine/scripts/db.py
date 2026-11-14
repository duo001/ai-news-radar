# -*- coding: utf-8 -*-
"""资讯 SQLite 存储层（零额外依赖，Python/Node 标准库自带）。

设计：
- 主存储：data/news.db，单表 news，link 为唯一键（跨采集增量 UPSERT）。
- 保留策略：每次写入后删除 RETENTION_DAYS 天之前的行，数据量恒定可控。
- 读取：按需 SELECT，支持按时间倒序、按 group 过滤、行数上限。
- 兼容：JSON 路径（plugin-news.json / news-*.json）保留为下游消费者接口，
  cmd_news 每次采集后从 SQLite 读出最新 N 天，回写 plugin-news.json。
"""
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "news.db"
RETENTION_DAYS = 30            # 保留天数，超期自动清理
DEFAULT_LIMIT = 2000           # 单次查询默认上限


def _connect(path=None):
    p = Path(path) if path else DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    return conn


DDL = """
CREATE TABLE IF NOT EXISTS news (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    link         TEXT NOT NULL UNIQUE,
    title        TEXT,
    summary      TEXT,
    published    TEXT,          -- ISO8601 字符串，保留时区信息
    source_id    TEXT,
    source_name  TEXT,
    group_name   TEXT,
    kind         TEXT DEFAULT 'rss',   -- 'rss' | 'deal'
    tags         TEXT,          -- JSON 数组字符串（deals 用）
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_news_published ON news(published DESC);
CREATE INDEX IF NOT EXISTS idx_news_group ON news(group_name);
CREATE INDEX IF NOT EXISTS idx_news_kind ON news(kind);
"""


def init_db(path=None):
    conn = _connect(path)
    try:
        conn.executescript(DDL)
        conn.commit()
    finally:
        conn.close()


def upsert_news(entries, path=None):
    """批量 UPSERT，link 相同的覆盖旧值（保持最新摘要/发布时间）。"""
    if not entries:
        return 0
    conn = _connect(path)
    try:
        conn.executescript(DDL)
        rows = [(
            e.get("link", ""), e.get("title", ""), e.get("summary", ""),
            e.get("published"), e.get("source_id", ""), e.get("source_name", ""),
            e.get("group", ""), e.get("kind", "rss"),
            json_dumps(e.get("tags")),
        ) for e in entries if e.get("link")]
        conn.executemany("""
            INSERT INTO news (link, title, summary, published, source_id,
                              source_name, group_name, kind, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(link) DO UPDATE SET
                title=excluded.title,
                summary=excluded.summary,
                published=excluded.published,
                source_id=excluded.source_id,
                source_name=excluded.source_name,
                group_name=excluded.group_name,
                kind=excluded.kind,
                tags=excluded.tags
        """, rows)
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def query_news(path=None, days=None, limit=DEFAULT_LIMIT, group=None, kind=None):
    """按需查询。days=N 只取最近 N 天；group/kind 可选过滤。"""
    conn = _connect(path)
    try:
        sql = ("SELECT link, title, summary, published, source_id, "
               "source_name, group_name, kind, tags FROM news")
        where = []
        params = []
        if days is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            where.append("(published IS NULL OR published >= ? OR published = '')")
            params.append(cutoff)
        if group:
            where.append("group_name = ?")
            params.append(group)
        if kind:
            where.append("kind = ?")
            params.append(kind)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY published IS NULL, published DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def prune_old(path=None, days=RETENTION_DAYS):
    """删除 RETENTION_DAYS 天之前的行；返回删除行数。"""
    conn = _connect(path)
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        cur = conn.execute("DELETE FROM news WHERE published < ? AND published IS NOT NULL", (cutoff,))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def count(path=None):
    conn = _connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
    finally:
        conn.close()


def _row_to_dict(r):
    return {
        "link": r["link"], "title": r["title"], "summary": r["summary"],
        "published": r["published"], "source_id": r["source_id"],
        "source_name": r["source_name"], "group": r["group_name"],
        "kind": r["kind"], "tags": json_loads(r["tags"]),
    }


def json_dumps(v):
    if not v:
        return None
    import json
    return json.dumps(v, ensure_ascii=False)


def json_loads(s):
    if not s:
        return None
    import json
    try:
        return json.loads(s)
    except Exception:
        return None