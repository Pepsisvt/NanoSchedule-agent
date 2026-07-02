"""日程统计 API —— 为前端可视化提供数据"""
from datetime import datetime, timedelta
from typing import Any
from nanobot_calendar import db

_CATEGORIES = {
    "study":    ["学习","课","书","习","读","写","考","作业","复习","论文","报告"],
    "meeting":  ["会","议","汇报","讨论","评审","面试","答辩","周会","组会"],
    "exercise": ["跑","运动","健身","锻炼","游泳","骑行","打球","瑜伽","散步"],
    "meal":     ["饭","餐","吃","喝","聚餐","火锅","食堂","外卖"],
    "entertainment": ["玩","游戏","电影","剧","唱","逛","展","演出"],
    "other":    [],
}


def compute_stats() -> dict[str, Any]:
    """计算日程统计数据"""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    # 本周日程
    events = db.query_events(date_from=week_ago, date_to=today, limit=500)

    # 1. 类别分布
    cat_counts: dict[str, int] = {k: 0 for k in _CATEGORIES}
    for e in events:
        title = e["title"].lower()
        matched = False
        for cat, keywords in _CATEGORIES.items():
            if any(k in title for k in keywords):
                cat_counts[cat] += 1
                matched = True
                break
        if not matched:
            cat_counts["other"] += 1
    cat_data = [{"name": _cat_name(k), "count": v} for k, v in cat_counts.items() if v > 0]
    cat_data.sort(key=lambda x: x["count"], reverse=True)

    # 2. 每日完成率
    daily = {}
    for e in events:
        day = e["start_time"][:10]
        daily.setdefault(day, {"total": 0, "completed": 0})
        daily[day]["total"] += 1
        if e["status"] == "done":
            daily[day]["completed"] += 1
    daily_data = [
        {"date": d, "total": v["total"], "completed": v["completed"],
         "rate": round(v["completed"]/v["total"]*100) if v["total"] > 0 else 0}
        for d, v in sorted(daily.items())
    ]

    # 3. 时段分布
    slot_counts = {"morning": 0, "afternoon": 0, "evening": 0, "night": 0}
    for e in events:
        try:
            h = int(e["start_time"][11:13])
        except (ValueError, IndexError):
            continue
        if 6 <= h < 12: slot_counts["morning"] += 1
        elif 12 <= h < 17: slot_counts["afternoon"] += 1
        elif 17 <= h < 22: slot_counts["evening"] += 1
        else: slot_counts["night"] += 1
    slot_data = [{"name": "上午", "count": slot_counts["morning"]},
                 {"name": "下午", "count": slot_counts["afternoon"]},
                 {"name": "晚上", "count": slot_counts["evening"]},
                 {"name": "深夜", "count": slot_counts["night"]}]

    # 4. 概览
    completed_all = sum(1 for e in events if e["status"] == "done")
    completion_rate = round(completed_all / len(events) * 100) if events else 0

    return {
        "total_events": len(events),
        "completion_rate": completion_rate,
        "categories": cat_data,
        "daily": daily_data,
        "time_slots": slot_data,
    }


def _cat_name(cat: str) -> str:
    return {"study":"📚学习","meeting":"💼会议","exercise":"🏃运动",
            "meal":"🍽️用餐","entertainment":"🎉娱乐","other":"📝其他"}.get(cat, cat)
