"""数据库层 - SQLite 存储日程和提醒"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from contextvars import ContextVar

# 数据库路径（通过 context var 注入）
_db_path: ContextVar[str] = ContextVar("calendar_db_path", default="")


def get_db_path() -> str:
    """获取数据库路径"""
    path = _db_path.get()
    if not path:
        path = str(Path.home() / ".nanobot" / "calendar.db")
    return path


def set_db_path(path: str) -> None:
    """设置数据库路径"""
    _db_path.set(path)


def _get_conn() -> sqlite3.Connection:
    """获取数据库连接"""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """初始化数据库表"""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            location TEXT DEFAULT '',
            start_time TEXT NOT NULL,
            end_time TEXT DEFAULT '',
            all_day INTEGER DEFAULT 0,
            repeat_type TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER,
            cron_job_id TEXT DEFAULT '',
            remind_at TEXT NOT NULL,
            message TEXT NOT NULL,
            channel TEXT DEFAULT '',
            chat_id TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_events_start
            ON events(start_time);
        CREATE INDEX IF NOT EXISTS idx_reminders_status
            ON reminders(status);
        CREATE INDEX IF NOT EXISTS idx_reminders_event
            ON reminders(event_id);
    """)
    conn.commit()
    conn.close()


# ── 日程 CRUD ────────────────────────────────────────────

def create_event(
    title: str,
    start_time: str,
    end_time: str = "",
    description: str = "",
    location: str = "",
    all_day: bool = False,
    repeat_type: str = "",
) -> dict[str, Any]:
    """创建日程"""
    conn = _get_conn()
    cursor = conn.execute(
        """INSERT INTO events (title, description, location, start_time, end_time, all_day, repeat_type)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (title, description, location, start_time, end_time, int(all_day), repeat_type),
    )
    conn.commit()
    event_id = cursor.lastrowid
    row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    conn.close()
    return dict(row)


def query_events(
    date_from: str = "",
    date_to: str = "",
    keyword: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """查询日程"""
    conn = _get_conn()
    where = []
    params: list[Any] = []

    if date_from:
        where.append("start_time >= ?")
        params.append(date_from)
    if date_to:
        where.append("start_time <= ?")
        params.append(date_to + "T23:59:59")
    if keyword:
        where.append("(title LIKE ? OR description LIKE ?)")
        kw = f"%{keyword}%"
        params.extend([kw, kw])

    clause = " AND ".join(where) if where else "1=1"
    rows = conn.execute(
        f"SELECT * FROM events WHERE {clause} ORDER BY start_time ASC LIMIT ?",
        params + [limit],
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def find_conflicts(
    start_time: str,
    end_time: str = "",
    exclude_id: int = 0,
) -> list[dict[str, Any]]:
    """查找与给定时间段冲突的日程。

    冲突定义：两个时间段有重叠。
    若未提供 end_time，默认日程时长为 1 小时。
    exclude_id：排除某个日程（更新时排除自己）。
    """
    from datetime import datetime, timedelta

    try:
        start_dt = datetime.fromisoformat(start_time)
    except ValueError:
        return []

    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time)
        except ValueError:
            end_dt = start_dt + timedelta(hours=1)
    else:
        end_dt = start_dt + timedelta(hours=1)

    # 取当天所有日程做重叠判断
    day = start_dt.strftime("%Y-%m-%d")
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM events WHERE start_time >= ? AND start_time <= ? AND all_day = 0",
        (day + "T00:00:00", day + "T23:59:59"),
    ).fetchall()
    conn.close()

    conflicts = []
    for r in rows:
        e = dict(r)
        if e["id"] == exclude_id:
            continue
        try:
            e_start = datetime.fromisoformat(e["start_time"])
        except ValueError:
            continue
        if e["end_time"]:
            try:
                e_end = datetime.fromisoformat(e["end_time"])
            except ValueError:
                e_end = e_start + timedelta(hours=1)
        else:
            e_end = e_start + timedelta(hours=1)

        # 重叠判断：新开始 < 已有结束 且 新结束 > 已有开始
        if start_dt < e_end and end_dt > e_start:
            conflicts.append(e)

    return conflicts


def update_event(
    event_id: int,
    title: str = "",
    start_time: str = "",
    end_time: str = "",
    description: str = "",
    location: str = "",
    all_day: bool | None = None,
    repeat_type: str = "",
) -> dict[str, Any] | None:
    """更新日程"""
    conn = _get_conn()
    existing = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if not existing:
        conn.close()
        return None

    updates: dict[str, Any] = {}
    if title:
        updates["title"] = title
    if start_time:
        updates["start_time"] = start_time
    if end_time:
        updates["end_time"] = end_time
    if description:
        updates["description"] = description
    if location:
        updates["location"] = location
    if all_day is not None:
        updates["all_day"] = int(all_day)
    if repeat_type:
        updates["repeat_type"] = repeat_type

    if not updates:
        conn.close()
        return dict(existing)

    updates["updated_at"] = datetime.now().isoformat()

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [event_id]
    conn.execute(f"UPDATE events SET {set_clause} WHERE id = ?", values)
    conn.commit()

    row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    conn.close()
    return dict(row)


def delete_event(event_id: int) -> bool:
    """删除日程"""
    conn = _get_conn()
    cursor = conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted


# ── 提醒管理 ──────────────────────────────────────────────

def create_reminder(
    event_id: int,
    remind_at: str,
    message: str,
    cron_job_id: str = "",
    channel: str = "",
    chat_id: str = "",
) -> dict[str, Any]:
    """创建提醒记录（与 cron job 关联）"""
    conn = _get_conn()
    cursor = conn.execute(
        """INSERT INTO reminders (event_id, cron_job_id, remind_at, message, channel, chat_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (event_id, cron_job_id, remind_at, message, channel, chat_id),
    )
    conn.commit()
    reminder_id = cursor.lastrowid
    row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
    conn.close()
    return dict(row)


def list_reminders() -> list[dict[str, Any]]:
    """列出所有提醒"""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT r.*, e.title as event_title
           FROM reminders r LEFT JOIN events e ON r.event_id = e.id
           ORDER BY r.remind_at DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def cancel_reminder(reminder_id: int) -> bool:
    """取消提醒"""
    conn = _get_conn()
    cursor = conn.execute("UPDATE reminders SET status='cancelled' WHERE id = ?", (reminder_id,))
    conn.commit()
    updated = cursor.rowcount > 0
    conn.close()
    return updated


def get_upcoming_reminders(
    limit: int = 10,
) -> list[dict[str, Any]]:
    """获取即将到来的提醒"""
    conn = _get_conn()
    now = datetime.now().isoformat()
    rows = conn.execute(
        """SELECT r.*, e.title as event_title
           FROM reminders r LEFT JOIN events e ON r.event_id = e.id
           WHERE r.status = 'pending' AND r.remind_at >= ?
           ORDER BY r.remind_at ASC LIMIT ?""",
        (now, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
