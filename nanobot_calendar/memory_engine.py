"""
长期记忆引擎 —— 用户画像 + 偏好学习 + 情绪识别 + 关系状态

存储：workspace/user_profile.json
逻辑：每次 Agent 决策前，把记忆上下文注入 prompt

架构：
  user_profile.json ← 持久化存储
       ↑↓
  memory_engine.py ← 读写 + 分析
       ↑↓
  Agent tools（remember / my_profile）← 供 LLM 调用
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

PROFILE_PATH = Path.home() / ".nanobot" / "workspace" / "user_profile.json"


# ── 核心读写 ──────────────────────────────────────

def _load() -> dict[str, Any]:
    if PROFILE_PATH.exists():
        return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    return {}


def _save(data: dict[str, Any]) -> None:
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Agent 工具：记住信息 ──────────────────────────

def remember(key: str, value: str) -> str:
    """Agent 调用：记住一个用户事实"""
    data = _load()

    # 特殊处理偏好
    if key in ("meeting", "study", "exercise"):
        data.setdefault("preferences", {})[key] = value
        _save(data)
        return f"好的，记住了：你偏好 {_describe_pref(key)} ～"

    # 特殊处理习惯
    if key in ("sleep_time", "wake_time"):
        data.setdefault("habits", {})[key] = value
        _save(data)
        return f"记下了，{_describe_habit(key)} ～"

    # 固定日程
    if key == "fixed_schedule":
        try:
            item = json.loads(value)  # {"day":"Wed","time":"13:00-17:00","desc":"实验课"}
        except json.JSONDecodeError:
            item = {"desc": value}
        scheds = data.setdefault("fixed_schedules", [])
        scheds.append(item)
        _save(data)
        day_name = {"Mon":"周一","Tue":"周二","Wed":"周三","Thu":"周四","Fri":"周五","Sat":"周六","Sun":"周日"}
        day = day_name.get(item.get("day",""), item.get("day",""))
        return f"好的，已记录：{day} {item.get('time','')} {item.get('desc','')} 是你固定日程，以后安排会自动避开 ~"

    # 通用记忆
    mems = data.setdefault("memories", [])
    mems.append({"key": key, "value": value, "time": datetime.now().isoformat()})
    _save(data)
    return f"记住了：{key} — {value}"


# ── Agent 工具：查看画像 ──────────────────────────

def get_profile_text() -> str:
    """返回用户画像摘要，供 Agent 注入上下文。每次调用自动追踪关系。"""
    data = _load()
    track_conversation()  # 自动计数
    data = _load()  # 重新加载（track_conversation 会更新 level）
    if not data:
        return ""

    parts = ["[用户画像 — 请在决策时参考以下信息]"]

    # 习惯
    habits = data.get("habits", {})
    if habits.get("sleep_time") or habits.get("wake_time"):
        parts.append(f"作息: {habits.get('sleep_time','')}睡觉, {habits.get('wake_time','')}起床")

    # 偏好
    prefs = data.get("preferences", {})
    pref_lines = []
    for k, v in prefs.items():
        if v:
            pref_lines.append(f"{_describe_pref(k)}")
    if pref_lines:
        parts.append("偏好: " + "，".join(pref_lines))

    # 固定日程
    scheds = data.get("fixed_schedules", [])
    if scheds:
        day_name = {"Mon":"周一","Tue":"周二","Wed":"周三","Thu":"周四","Fri":"周五","Sat":"周六","Sun":"周日"}
        parts.append("固定日程（安排时自动避开）：")
        for s in scheds:
            day = day_name.get(s.get("day",""), s.get("day",""))
            parts.append(f"  - {day} {s.get('time','')} {s.get('desc','')}")

    # 关键记忆
    mems = data.get("memories", [])
    if mems:
        parts.append("用户提过的信息：")
        for m in mems[-10:]:  # 最近10条
            parts.append(f"  - {m['key']}: {m['value']}")

    # 关系
    rel = data.get("relationship", {})
    level = rel.get("level", "new")
    days = rel.get("total_conversations", 0)
    tone_map = {
        "new": "礼貌但保持距离，用'你'，别太熟络",
        "familiar": "轻松随意，用语气词和emoji，像认识一段时间的熟人",
        "close": "像老朋友一样闲聊，可以开玩笑、小吐槽、回忆过去的对话",
    }
    first_seen = rel.get("first_seen", "")
    try:
        from datetime import datetime
        days_since = (datetime.now() - datetime.strptime(first_seen, "%Y-%m-%d")).days
        parts.append(f"我们认识 {days_since} 天了，聊过 {days} 次。关系: {level}——")
        parts.append(f"语气应{tone_map.get(level, '')}")
        # 重要节点提示
        if days_since >= 7 and days_since < 14 and level != "familiar":
            parts.append("（关系升级了！从'新朋友'变成'熟人'，可以更随意一些了）")
        if days_since >= 30:
            parts.append("（已经是老朋友了，语气可以很随意，偶尔提一下'我们认识这么久了'）")
    except Exception:
        parts.append(f"关系: {level}（{days}次对话）— 语气应{tone_map.get(level, '')}")

    return "\n".join(parts)


# ── 偏好学习：从事件历史自动发现 ──────────────────

# 事件分类关键词
_CATEGORIES = {
    "study":    ["学习","课","书","习","读","写","考","作业","复习","预习","论文","报告"],
    "meeting":  ["会","议","汇报","讨论","评审","面试","答辩","周会","组会","站会"],
    "exercise": ["跑","运动","健身","锻炼","游泳","骑行","打球","瑜伽","爬山","散步","跳绳"],
    "meal":     ["饭","餐","吃","喝","聚餐","火锅","烤肉","食堂","外卖","午","晚"],
    "entertainment": ["玩","游戏","电影","剧","唱","逛","展","演出","音乐会","派对"],
    "health":   ["医","药","体检","牙","挂号","理疗","按摩"],
    "travel":   ["出行","飞","火车","高铁","旅","酒店","景点","游"],
}

_DAYS = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
_DAYS_CN = ["周一","周二","周三","周四","周五","周六","周日"]


def learn_from_history() -> list[dict[str, Any]]:
    """分析 events 表，自动发现规律。

    返回结构化洞察，每条包含：
      - category: 类别（study/meeting/exercise等）
      - finding: 发现描述
      - confidence: 置信度 0-1
      - suggestion: 是否建议自动更新画像
    """
    from nanobot_calendar import db

    events = db.query_events(limit=300)
    if len(events) < 5:
        return []  # 数据太少，无法分析

    findings: list[dict[str, Any]] = []

    # 1. 按类别 + 时段分析偏好
    for cat, keywords in _CATEGORIES.items():
        slot_counts = _count_slot(events, keywords)
        total = sum(slot_counts.values())
        if total >= 3:
            best = max(slot_counts, key=slot_counts.get)
            ratio = slot_counts[best] / total
            if ratio >= 0.5:  # 过半集中在一个时段
                slot_cn = {"morning":"上午","afternoon":"下午","evening":"晚上","night":"深夜"}
                findings.append({
                    "category": cat,
                    "finding": f"{_cat_name(cat)}偏好：{slot_cn.get(best, best)}（{slot_counts[best]}/{total}次，{int(ratio*100)}%）",
                    "confidence": ratio,
                    "suggestion": True,
                    "key": cat,
                    "value": _slot_to_pref(best),
                })

    # 2. 检测重复事件（同标题 + 同星期几 ≥ 2次 → 可能是固定日程）
    weekday_counts: dict[str, dict[str, int]] = {}
    for e in events:
        try:
            dt = datetime.fromisoformat(e["start_time"])
            wd = _DAYS[dt.weekday()]
        except (ValueError, IndexError):
            continue
        title = e["title"]
        weekday_counts.setdefault(title, {}).setdefault(wd, 0)
        weekday_counts[title][wd] += 1

    for title, days in weekday_counts.items():
        for day, cnt in days.items():
            if cnt >= 2:
                findings.append({
                    "category": "fixed_schedule",
                    "finding": f"「{title}」重复出现在{_DAYS_CN[_DAYS.index(day)]}（{cnt}次），可能是固定日程",
                    "confidence": min(0.7, cnt * 0.3),
                    "suggestion": True,
                    "key": "fixed_schedule",
                    "value": json.dumps({"day": day, "desc": title, "auto_detected": True}),
                })

    # 3. 检测空闲模式（哪天总没日程）
    day_event_counts: dict[str, int] = {d: 0 for d in _DAYS}
    for e in events:
        try:
            dt = datetime.fromisoformat(e["start_time"])
            wd = _DAYS[dt.weekday()]
        except (ValueError, IndexError):
            continue
        day_event_counts[wd] += 1

    # 找出几乎没有日程的星期几（可能用户偏好休息）
    busy_days = {d: c for d, c in day_event_counts.items() if c > 0}
    if len(busy_days) >= 4:
        free_days = [d for d, c in day_event_counts.items() if c == 0]
        if free_days:
            findings.append({
                "category": "habit",
                "finding": f"{'/'.join(_DAYS_CN[_DAYS.index(d)] for d in free_days)}通常没有日程，可能是休息日",
                "confidence": 0.6,
                "suggestion": False,
            })

    # 按置信度排序
    findings.sort(key=lambda f: f["confidence"], reverse=True)
    return findings


def apply_learned_preferences() -> list[str]:
    """自动将高置信度发现写入 user_profile.json，返回更新了什么的列表"""
    findings = learn_from_history()
    updated = []

    for f in findings:
        if not f.get("suggestion") or f["confidence"] < 0.6:
            continue
        if f["key"] == "fixed_schedule":
            result = remember("fixed_schedule", f["value"])
            updated.append(f["finding"])
        elif f["key"] in ("study", "meeting", "exercise", "meal"):
            data = _load()
            prefs = data.setdefault("preferences", {})
            if not prefs.get(f["key"]):  # 只在没设置过时自动更新
                prefs[f["key"]] = f["value"]
                _save(data)
                updated.append(f"自动设置{f['finding']}")

    return updated


# ── 情绪识别 ──────────────────────────────────────

def detect_emotion(text: str) -> dict[str, Any]:
    """轻量情绪识别，结合当前日程返回具体建议"""
    from nanobot_calendar import db

    text_lower = text.lower()

    moods = {
        "tired":    ["累", "困", "疲惫", "没精神", "好累", "乏"],
        "happy":    ["开心", "高兴", "好耶", "哈哈", "nice", "棒", "爽"],
        "stressed": ["压力", "焦虑", "紧张", "忙死了", "忙不过来", "崩溃"],
        "sad":      ["难过", "郁闷", "烦", "不开心", "丧"],
        "excited":  ["期待", "兴奋", "激动", "盼望"],
        "bored":    ["无聊", "没意思", "闲着"],
    }

    detected = "neutral"
    for mood, keywords in moods.items():
        if any(k in text_lower for k in keywords):
            detected = mood
            break

    if detected == "neutral":
        return {"emotion": "neutral", "confidence": 0.5, "suggestion": ""}

    # 结合日程生成具体建议
    today = datetime.now().strftime("%Y-%m-%d")
    events_today = db.query_events(date_from=today, date_to=today)
    pending = [e for e in events_today if e["status"] != "done"]

    suggestion = _build_contextual_suggestion(detected, pending)

    return {
        "emotion": detected,
        "confidence": 0.85,
        "pending_events": len(pending),
        "suggestion": suggestion,
    }


def _build_contextual_suggestion(mood: str, pending: list[dict]) -> str:
    """结合待办日程生成情绪对应建议"""
    base = {
        "tired":    "用户很累，语气要温暖。",
        "happy":    "用户心情好，可以轻松聊天。",
        "stressed": "用户压力大，少推任务多给减压建议。",
        "sad":      "语气要温暖安慰。",
        "excited":  "顺着用户的兴奋聊下去。",
        "bored":    "用户无聊，主动提议安排活动。",
    }.get(mood, "")

    if mood in ("tired", "stressed") and pending:
        titles = "、".join(e["title"] for e in pending[:3])
        return (
            f"{base}"
            f"用户今天还有 {len(pending)} 项待办（{titles}）。"
            f"主动建议：'要不要把不那么急的任务往后挪？'或者'今天早点休息，明天再安排？'。"
            f"总之减轻负担，别再加新任务。"
        )

    if mood == "bored" and not pending:
        return f"{base}今天没有待办日程，可以主动建议安排活动或推荐有趣的事。"

    if mood == "excited" and not pending:
        return f"{base}可以问问用户有什么好事发生，一起开心。"

    return base


# ── 关系追踪 ──────────────────────────────────────

def track_conversation():
    """每次对话后调用，自动更新关系数据"""
    data = _load()
    if not data:
        return
    rel = data.setdefault("relationship", {})
    rel["total_conversations"] = rel.get("total_conversations", 0) + 1
    if not rel.get("first_seen"):
        rel["first_seen"] = datetime.now().strftime("%Y-%m-%d")

    # 按天数升级关系
    cnt = rel["total_conversations"]
    try:
        days_since = (datetime.now() - datetime.strptime(rel["first_seen"], "%Y-%m-%d")).days
    except Exception:
        days_since = 0

    if days_since >= 30:
        rel["level"] = "close"
    elif days_since >= 7:
        rel["level"] = "familiar"
    else:
        rel["level"] = "new"

    _save(data)


# ── 反思：每日分析 ────────────────────────────────

def daily_reflection() -> str:
    """每日反思：分析完成率 + 发现规律 + 写入记忆。

    由 FriendBrain 晚上触发，或用户主动问'今天复盘一下'。
    """
    today = datetime.now().strftime("%Y-%m-%d")
    from nanobot_calendar import db

    events = db.query_events(date_from=today, date_to=today)
    completed = [e for e in events if e["status"] == "done"]
    pending = [e for e in events if e["status"] != "done"]
    total = len(events)

    # 把未完成的记录到用户记忆
    if pending:
        for e in pending[:3]:
            remember(f"未完成_{today}", f"{e['start_time'][11:16]} {e['title']}")

    # 运行偏好学习
    discoveries = learn_from_history()

    # 累计完成率
    data = _load()
    history = data.setdefault("completion_history", {})
    if total > 0:
        history[today] = {"total": total, "completed": len(completed), "rate": len(completed)/total}
    data.setdefault("total_reflections", 0)
    data["total_reflections"] += 1
    _save(data)

    # 生成报告
    lines = ["📊 今日复盘："]
    if total == 0:
        lines.append("今天没有日程，是轻松的一天～")
    else:
        rate = int(len(completed)/total*100) if total > 0 else 0
        lines.append(f"完成 {len(completed)}/{total}（{rate}%）")
        if pending:
            lines.append("未完成：")
            for e in pending[:5]:
                lines.append(f"  · {e['start_time'][11:16]} {e['title']}")

    # 发现的规律
    if discoveries:
        lines.append("")
        lines.append("🔍 新发现的规律：")
        for d in discoveries[:3]:
            lines.append(f"  · {d['finding']}")

    # 建议
    if pending:
        lines.append("")
        lines.append("💡 明天上午优先处理未完成项，效率更高～")

    return "\n".join(lines)


# ── 辅助函数 ──────────────────────────────────────

def _count_slot(events: list[dict], keywords: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in events:
        title = e["title"].lower()
        if not any(k in title for k in keywords):
            continue
        try:
            h = int(e["start_time"][11:13])
        except (ValueError, IndexError):
            continue
        if 6 <= h < 12:
            slot = "morning"
        elif 12 <= h < 17:
            slot = "afternoon"
        elif 17 <= h < 22:
            slot = "evening"
        else:
            slot = "night"
        counts[slot] = counts.get(slot, 0) + 1
    return counts


def _cat_name(cat: str) -> str:
    return {"study":"学习","meeting":"会议","exercise":"运动","meal":"用餐",
            "entertainment":"娱乐","health":"健康","travel":"出行"}.get(cat, cat)


def _slot_to_pref(slot: str) -> str:
    return {"morning":"morning","afternoon":"afternoon","evening":"evening","night":"night"}.get(slot, "")


def _describe_pref(key: str) -> str:
    return {"meeting":"下午开会","study":"晚上学习","exercise":"早上运动","":"未设置"}.get(key, key)


def _describe_habit(key: str) -> str:
    return {"sleep_time":"睡觉时间","wake_time":"起床时间"}.get(key, key)


def _emotion_suggestion(mood: str) -> str:
    return {
        "tired": "用户很累，建议减轻今天任务负担或延后。",
        "happy": "用户心情好，可以轻松互动。",
        "stressed": "用户压力大，优先提供减压建议，避免增加任务。",
        "sad": "用户情绪低落，语气要温暖，可以提议休息或放松。",
        "excited": "用户很兴奋，可以顺着话题聊。",
        "bored": "用户无聊，可以主动提议安排活动。",
    }.get(mood, "")
