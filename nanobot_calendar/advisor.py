"""
智能日程建议引擎 —— 借鉴 akashic-agent Drift 机制

Agent 空闲时分析用户的日程模式，生成关怀型建议。
不是简单的时间提醒，而是基于「日程结构」的洞察。

分析维度：
  1. 高强度预警 —— 某天日程过多/连续多天满档 → 建议休息
  2. 空闲利用 —— 大块空闲时段 → 建议安排或留白
  3. 提醒缺失 —— 重要日程没设提醒 → 建议补充
  4. 作息健康 —— 深夜/过早日程 → 健康提示
  5. 饮食规律 —— 缺少用餐相关日程 → 温馨提示

每条建议带 priority，由 ProactiveBrain 决定是否推送。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from nanobot_calendar import db


# 单日日程数阈值：超过视为高强度
_BUSY_THRESHOLD = 4
# 连续高强度天数阈值
_STREAK_THRESHOLD = 3


def analyze() -> list[dict[str, Any]]:
    """分析最近日程，返回建议列表。

    每条建议格式：
      {"id": 唯一标识, "priority": 1-5, "category": 类别, "message": 文本}
    """
    suggestions: list[dict[str, Any]] = []
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    # 取未来 7 天日程
    week_end = (now + timedelta(days=7)).strftime("%Y-%m-%d")
    events = db.query_events(date_from=today, date_to=week_end, limit=100)

    # 按天分组
    by_day: dict[str, list[dict]] = {}
    for e in events:
        day = e["start_time"][:10]
        by_day.setdefault(day, []).append(e)

    # ── 维度1：高强度预警 ──
    busy_days = [d for d, evs in by_day.items() if len(evs) >= _BUSY_THRESHOLD]
    for day in busy_days:
        cnt = len(by_day[day])
        suggestions.append({
            "id": f"busy:{day}",
            "priority": 4,
            "category": "高强度预警",
            "message": f"💪 {_friendly_date(day)} 你安排了 {cnt} 个日程，比较紧凑，记得留出休息和吃饭时间哦~",
        })

    # ── 维度2：连续满档 → 建议休息 ──
    sorted_days = sorted(by_day.keys())
    streak = _max_consecutive_busy(sorted_days, by_day)
    if streak >= _STREAK_THRESHOLD:
        suggestions.append({
            "id": f"streak:{today}",
            "priority": 5,
            "category": "健康关怀",
            "message": f"🌿 我注意到你已经连续 {streak} 天日程排得很满了，要不要给自己留半天空闲放松一下？长期高强度对身体不好~",
        })

    # ── 维度3：今日空闲时段利用 ──
    today_events = by_day.get(today, [])
    if today_events and now.hour < 20:
        free_slots = _find_free_slots(today_events, now)
        if free_slots:
            slot = free_slots[0]
            suggestions.append({
                "id": f"free:{today}:{slot[0]}",
                "priority": 2,
                "category": "时间利用",
                "message": f"⏳ 你今天 {slot[0]}-{slot[1]} 有段空闲时间，需要安排学习或放松吗？",
            })

    # ── 维度4：作息健康（深夜/过早日程）──
    for e in events:
        try:
            h = int(e["start_time"][11:13])
        except (ValueError, IndexError):
            continue
        sid = f"latenight:{e['id']}"
        if h >= 23 or h <= 5:
            suggestions.append({
                "id": sid,
                "priority": 3,
                "category": "作息健康",
                "message": f"🌙 「{e['title']}」安排在 {e['start_time'][11:16]}，时间偏晚，注意休息别太累~",
            })

    # ── 维度5：重要日程缺提醒 ──
    for e in events:
        if e["start_time"] <= now.isoformat():
            continue
        conn = db._get_conn()
        has_rem = conn.execute(
            "SELECT COUNT(*) FROM reminders WHERE event_id=? AND status='pending'",
            (e["id"],),
        ).fetchone()[0]
        conn.close()
        # 只对含关键词的"重要"日程提示
        if not has_rem and _is_important(e["title"]):
            suggestions.append({
                "id": f"noremind:{e['id']}",
                "priority": 3,
                "category": "提醒建议",
                "message": f"🔔 「{e['title']}」({e['start_time'][:16]}) 看起来挺重要，要不要设个提醒避免错过？",
            })

    # 按优先级降序
    suggestions.sort(key=lambda s: s["priority"], reverse=True)
    return suggestions


# ── 辅助函数 ──────────────────────────────────────

def _friendly_date(day: str) -> str:
    """2026-07-01 → 明天 / 周三 等"""
    try:
        d = datetime.fromisoformat(day + "T00:00:00").date()
        today = datetime.now().date()
        delta = (d - today).days
        if delta == 0:
            return "今天"
        if delta == 1:
            return "明天"
        if delta == 2:
            return "后天"
        week = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        return f"{day[5:]}（{week[d.weekday()]}）"
    except Exception:
        return day


def _max_consecutive_busy(sorted_days: list[str], by_day: dict) -> int:
    """计算最长连续高强度天数"""
    if not sorted_days:
        return 0
    max_streak = cur = 0
    prev_date = None
    for day in sorted_days:
        if len(by_day[day]) < _BUSY_THRESHOLD:
            cur = 0
            prev_date = None
            continue
        d = datetime.fromisoformat(day + "T00:00:00").date()
        if prev_date and (d - prev_date).days == 1:
            cur += 1
        else:
            cur = 1
        prev_date = d
        max_streak = max(max_streak, cur)
    return max_streak


def _find_free_slots(events: list[dict], now: datetime) -> list[tuple[str, str]]:
    """找出今天剩余的空闲时段（至少2小时）"""
    # 收集已占用时段
    busy = []
    for e in events:
        try:
            s = datetime.fromisoformat(e["start_time"])
            if e["end_time"]:
                en = datetime.fromisoformat(e["end_time"])
            else:
                en = s + timedelta(hours=1)
            busy.append((s, en))
        except ValueError:
            continue
    busy.sort()

    # 从当前时间到 22:00 找空隙
    day_end = now.replace(hour=22, minute=0, second=0, microsecond=0)
    cursor = now
    free = []
    for s, en in busy:
        if s > cursor and (s - cursor).total_seconds() >= 7200:  # ≥2小时
            free.append((cursor.strftime("%H:%M"), s.strftime("%H:%M")))
        cursor = max(cursor, en)
    if cursor < day_end and (day_end - cursor).total_seconds() >= 7200:
        free.append((cursor.strftime("%H:%M"), day_end.strftime("%H:%M")))
    return free


def _is_important(title: str) -> bool:
    """判断日程是否"重要"（值得提醒）"""
    keywords = ["会议", "面试", "考试", "答辩", "汇报", "评审", "体检",
                "约", "见", "deadline", "ddl", "截止", "报告", "演讲"]
    return any(k in title.lower() for k in keywords)
