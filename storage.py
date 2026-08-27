# -*- coding: utf-8 -*-
"""存储层：SQLite 持久化，URL 去重（重复抓取时更新指标与评分）。"""

import json
import os
import sqlite3

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    url          TEXT UNIQUE NOT NULL,
    title        TEXT NOT NULL,
    source       TEXT,
    source_type  TEXT,
    category     TEXT,
    summary      TEXT,
    metrics      TEXT,
    published_at TEXT,
    fetched_at   TEXT,
    item_date    TEXT,
    score        REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_items_date ON items(item_date);
CREATE INDEX IF NOT EXISTS idx_items_cat  ON items(category);

-- GitHub 仓库 star 数每日快照，用于计算日增/周增星
CREATE TABLE IF NOT EXISTS repo_snapshots (
    url   TEXT NOT NULL,
    date  TEXT NOT NULL,
    stars INTEGER,
    PRIMARY KEY (url, date)
);

-- 数据源健康状态
CREATE TABLE IF NOT EXISTS source_health (
    source     TEXT PRIMARY KEY,
    last_ok    TEXT,
    last_fail  TEXT,
    last_error TEXT,
    fail_streak INTEGER DEFAULT 0,
    total_ok   INTEGER DEFAULT 0,
    total_fail INTEGER DEFAULT 0
);

-- 翻译缓存：相同原文复用结果，避免重复打后端（尤其免密钥接口限流严重）
CREATE TABLE IF NOT EXISTS trans_cache (
    src  TEXT PRIMARY KEY,
    zh   TEXT
);
"""


def _conn():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _conn() as conn:
        conn.executescript(_SCHEMA)
        # 旧库兼容：已存在的表不会因 IF NOT EXISTS 重建，这里补齐新增列
        try:
            conn.execute("ALTER TABLE source_health ADD COLUMN last_error TEXT")
        except sqlite3.OperationalError:
            pass  # 列已存在


def save_items(items, item_date):
    """写入当日条目；URL 已存在则更新指标/评分/摘要。返回新增条数。"""
    new_cnt = 0
    with _conn() as conn:
        for it in items:
            cur = conn.execute(
                """
                INSERT INTO items (url, title, source, source_type, category,
                                   summary, metrics, published_at, fetched_at,
                                   item_date, score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    title        = excluded.title,
                    category     = excluded.category,
                    summary      = excluded.summary,
                    metrics      = excluded.metrics,
                    score        = excluded.score,
                    fetched_at   = excluded.fetched_at
                """,
                (it["url"], it["title"], it.get("source"), it.get("source_type"),
                 it.get("category"), it.get("summary_final", ""),
                 json.dumps(it.get("metrics") or {}, ensure_ascii=False),
                 it.get("published_at"), it.get("fetched_at"),
                 item_date, it.get("score", 0)),
            )
            if cur.rowcount == 1:  # 新插入
                new_cnt += 1
    return new_cnt


def load_items(item_date):
    """读取某天全部条目，按热度降序。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM items WHERE item_date = ? ORDER BY score DESC",
            (item_date,),
        ).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        try:
            d["metrics"] = json.loads(d.get("metrics") or "{}")
        except json.JSONDecodeError:
            d["metrics"] = {}
        items.append(d)
    return items


def global_stats():
    """库内总量统计（用于报告页脚）。"""
    with _conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    return {"total_items": total}


# ---------------------------------------------------------------- star 快照
def get_star_deltas(items, item_date):
    """对比历史快照，返回 {url: 日增星数}（无历史记录则为 0）。"""
    deltas = {}
    with _conn() as conn:
        for it in items:
            stars = (it.get("metrics") or {}).get("stars")
            if not stars:
                continue
            row = conn.execute(
                "SELECT stars FROM repo_snapshots WHERE url = ? AND date < ? "
                "ORDER BY date DESC LIMIT 1",
                (it["url"], item_date),
            ).fetchone()
            deltas[it["url"]] = max(0, stars - row["stars"]) if row else 0
    return deltas


def write_star_snapshots(items, item_date):
    """记录当天各仓库的 star 快照。"""
    with _conn() as conn:
        for it in items:
            stars = (it.get("metrics") or {}).get("stars")
            if stars is None:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO repo_snapshots (url, date, stars) VALUES (?, ?, ?)",
                (it["url"], item_date, stars),
            )


# ---------------------------------------------------------------- 源健康
def update_source_health(statuses, item_date):
    """按当日逐源抓取结果更新健康表（记录失败原因）。"""
    with _conn() as conn:
        for st in statuses:
            err = (st.get("error") or "")[:300]
            if st["ok"]:
                conn.execute(
                    """
                    INSERT INTO source_health (source, last_ok, last_error, fail_streak, total_ok)
                    VALUES (?, ?, '', 0, 1)
                    ON CONFLICT(source) DO UPDATE SET
                        last_ok = excluded.last_ok,
                        last_error = '',
                        fail_streak = 0,
                        total_ok = total_ok + 1
                    """,
                    (st["name"], item_date),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO source_health (source, last_fail, last_error, fail_streak, total_fail)
                    VALUES (?, ?, ?, 1, 1)
                    ON CONFLICT(source) DO UPDATE SET
                        last_fail = excluded.last_fail,
                        last_error = excluded.last_error,
                        fail_streak = fail_streak + 1,
                        total_fail = total_fail + 1
                    """,
                    (st["name"], item_date, err),
                )


def get_source_alerts(min_streak):
    """返回连续失败达到 min_streak 天的数据源 [(名称, 连败天数, 失败原因)]。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT source, fail_streak, last_error FROM source_health "
            "WHERE fail_streak >= ? ORDER BY fail_streak DESC",
            (min_streak,),
        ).fetchall()
    return [(r["source"], r["fail_streak"], r["last_error"] or "") for r in rows]


# ---------------------------------------------------------------- 翻译缓存
def get_translation_cache(texts):
    """批量查询翻译缓存，返回 {原文: 译文}。"""
    if not texts:
        return {}
    out = {}
    with _conn() as conn:
        for t in texts:
            row = conn.execute(
                "SELECT zh FROM trans_cache WHERE src = ?", (t,)
            ).fetchone()
            if row:
                out[t] = row["zh"]
    return out


def save_translation_cache(pairs):
    """批量写入翻译缓存 [(原文, 译文)]。"""
    if not pairs:
        return
    with _conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO trans_cache (src, zh) VALUES (?, ?)", pairs
        )


# ---------------------------------------------------------------- 周报查询
def load_range(start_date, end_date):
    """读取日期区间内的全部条目，按热度降序。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM items WHERE item_date BETWEEN ? AND ? ORDER BY score DESC",
            (start_date, end_date),
        ).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        try:
            d["metrics"] = json.loads(d.get("metrics") or "{}")
        except json.JSONDecodeError:
            d["metrics"] = {}
        items.append(d)
    return items


def daily_counts(start_date, end_date):
    """区间内每日收录条数 [{date, count}]（含无数据的日期补 0 由调用方处理）。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT item_date AS date, COUNT(*) AS count FROM items "
            "WHERE item_date BETWEEN ? AND ? GROUP BY item_date ORDER BY date",
            (start_date, end_date),
        ).fetchall()
    return {r["date"]: r["count"] for r in rows}


def all_daily_counts():
    """所有已有日期的收录条数 {date: count}。供索引页/管理面板查询用。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT item_date AS date, COUNT(*) AS count FROM items "
            "GROUP BY item_date ORDER BY date"
        ).fetchall()
    return {r["date"]: r["count"] for r in rows}


def gh_weekly_gains(start_date, end_date, limit=10):
    """GitHub 周增星榜：窗口期内最大最小快照差值排序。"""
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT s.url,
                   MAX(s.stars) - MIN(s.stars) AS gain,
                   MAX(s.stars) AS stars,
                   (SELECT title FROM items i WHERE i.url = s.url
                     ORDER BY i.score DESC LIMIT 1) AS title
            FROM repo_snapshots s
            WHERE s.date BETWEEN ? AND ?
            GROUP BY s.url
            HAVING gain > 0
            ORDER BY gain DESC
            LIMIT ?
            """,
            (start_date, end_date, limit),
        ).fetchall()
    return [dict(r) for r in rows]
