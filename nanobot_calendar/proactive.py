"""
主动聊天引擎 —— 只在必要的时候说话

规则很简单：
  1. 日程快开始了（15分钟内）→ 提醒
  2. 超长时间空闲（>30分钟）→ 纯闲聊，不提日程
  3. 早上8点 / 晚上9点 → 问候
  4. 其他时候 → 闭嘴，不打扰
"""

import random
import threading
import time
from datetime import datetime, timedelta
from typing import Any

from nanobot_calendar import db

_queue: list[dict[str, Any]] = []
_lock = threading.Lock()
_pushed_ids: set[str] = set()
_last_push_kind: str = ""

_MORNING_TOPICS = [
    "早上好呀～新的一天 ☀️ 今天感觉怎么样？",
    "早！今天有什么计划嘛，没有的话放松一下也好~",
    "醒了吗哈哈，今天我给你看着日程呢 😊",
]

_EVENING_TOPICS = [
    "晚上好～一天辛苦了，早点休息哦 🌙",
    "今天过得怎么样呀？不管好坏，都翻篇啦～",
    "该放松啦，明天的事明天再说~",
]

_IDLE_CHECKINS = [
    "嘿{name}，好久没聊了～最近怎么样呀？",
    "闲着没事来看看{name}！一切都顺利吗？",
    "在嘛在嘛～突然想找你聊聊天 😄",
    "哈喽{name}，还在忙吗？",
    "{name}，今天心情怎么样呀～",
    "没啥事，就是来看看你",
]

_FUN_STARTERS = [
    "聊点别的～{name}最近有看什么好看的剧或者电影嘛？",
    "突然好奇，{name}平时喜欢听什么歌？🎵",
    "如果给你一天完全空闲，你最想干嘛呀～",
    "有没有什么想去但一直没去的地方呀？",
    "{name}周末一般喜欢干嘛？",
    "突然想到一个问题——你最怀念什么时候呀？",
    "如果有一种超能力，{name}最想要什么？",
]


class FriendBrain:
    """朋友大脑 —— 只在必要的时候主动说话"""

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._running = False
        self._last_user_active: float = time.time()
        self._total_idle_pushes: int = 0

    def user_active(self):
        self._last_user_active = time.time()
        self._total_idle_pushes = 0

    def _idle_minutes(self) -> float:
        return (time.time() - self._last_user_active) / 60.0

    def _battery_sleep(self) -> float:
        idle_min = self._idle_minutes()
        if idle_min < 5:
            return 300
        elif idle_min < 30:
            return 300
        else:
            return 600

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                self._wake_up()
            except Exception:
                pass
            time.sleep(self._battery_sleep())

    def _wake_up(self):
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        idle_min = self._idle_minutes()
        global _last_push_kind

        # 1. 紧急：日程 15 分钟内开始 → 提醒
        if self._check_alerts(now):
            _last_push_kind = "alert"
            self._last_user_active = time.time()
            return

        # 2. 紧急：数据库提醒 15 分钟内到期 → 推送
        if self._check_reminders(now):
            _last_push_kind = "alert"
            self._last_user_active = time.time()
            return

        # 3. 定时问候（不受空闲时间限制）
        if self._say_hi(now, today):
            _last_push_kind = "context"
            self._last_user_active = time.time()
            return

        # 4. 超长空闲（>30分钟）→ 纯闲聊
        if idle_min >= 30:
            if self._send_idle_chat(now, today):
                _last_push_kind = "context"
                self._last_user_active = time.time()
                return

    def _check_reminders(self, now: datetime) -> bool:
        """检查 reminders 表，推送即将到期的提醒"""
        try:
            conn = db._get_conn()
            soon = (now + timedelta(minutes=15)).isoformat()
            rows = conn.execute(
                "SELECT * FROM reminders WHERE status='pending' AND remind_at > ? AND remind_at <= ?",
                (now.isoformat(), soon),
            ).fetchall()
            conn.close()
            for r in rows:
                rid = f"reminder:{r['id']}"
                if rid in _pushed_ids:
                    continue
                try:
                    remind_dt = datetime.fromisoformat(r["remind_at"])
                    mins = int((remind_dt - now).total_seconds() / 60)
                except Exception:
                    continue
                if 0 < mins <= 15:
                    msg = f"⏰ 提醒：{r['message']}"
                    _push("alert", msg)
                    _pushed_ids.add(rid)
                    return True
        except Exception:
            pass
        return False

    def _check_alerts(self, now: datetime) -> bool:
        soon = (now + timedelta(minutes=15)).isoformat()
        events = db.query_events(date_from=now.isoformat(), date_to=soon)
        for ev in events:
            eid = f"alert:{ev['id']}"
            if eid in _pushed_ids:
                continue
            try:
                ev_time = datetime.fromisoformat(ev["start_time"])
                mins = int((ev_time - now).total_seconds() / 60)
            except Exception:
                continue
            if 0 < mins <= 15:
                loc = f" @{ev['location']}" if ev.get("location") else ""
                msg = f"⏰ 嘿，**{ev['title']}** 还有 **{mins} 分钟**就要开始了{loc}～别忘了哦"
                _push("alert", msg)
                _pushed_ids.add(eid)
                return True
        return False

    def _llm_chat(self, now: datetime) -> str | None:
        """用 LLM 生成一条自然的、个性化的主动聊天消息。"""
        return self._call_llm(self._build_system_prompt(now), [
            f"现在是{self._time_vibe(now.hour)}，像朋友一样发一条问候。不提日程不催事。1-2句带emoji。",
            "发一条闲聊，问问用户最近怎么样、忙不忙、心情如何。1-2句。别编造不存在的事。",
            "关心一下朋友，随口问个近况。像突然想起来找他聊天。1-2句，别啰嗦。",
        ])

    def _morning_llm(self, now: datetime, events_today: list) -> str | None:
        """用 LLM 生成早安问候，包含今日日程概览"""
        lines = []
        for e in events_today[:5]:
            t = e['start_time'][11:16]
            icon = '🏃'
            title = e['title']
            if any(w in title for w in ['会议','汇报','讨论','评审','面试','组会']): icon = '💼'
            elif any(w in title for w in ['课','学','习','读','写','考']): icon = '📚'
            elif any(w in title for w in ['饭','餐','吃','喝','聚']): icon = '🍽️'
            elif any(w in title for w in ['瑜伽','运动','健身','锻炼','游泳','跑']): icon = '🏃'
            elif any(w in title for w in ['玩','游','唱','演','影','剧','展']): icon = '🎉'
            lines.append(f"{icon} {t} {title}")

        schedule_text = "\n".join(lines) if lines else "今天没有日程安排"
        system = self._build_system_prompt(now)
        prompts = [
            f"早上好！现在是{self._time_vibe(now.hour)}。用户今天的日程：\n{schedule_text}\n\n"
            "像朋友一样发早安问候，自然地提一下今天的日程。如果没日程就说点轻松的。"
            "语气要自然口语化，2-3句，用emoji和波浪线～。不要像播报员一样列清单。",
        ]
        return self._call_llm(system, prompts, temperature=0.95)

    def _evening_llm(self, now: datetime) -> str | None:
        """用 LLM 生成晚安问候 + 每日小结"""
        events_today = db.query_events(
            date_from=now.strftime("%Y-%m-%d"),
            date_to=now.strftime("%Y-%m-%d")
        )
        done = [e for e in events_today if e['start_time'] < now.isoformat()]
        pending = [e for e in events_today if e['start_time'] >= now.isoformat()]
        ctx = f"已完成{len(done)}个日程" + (f"，还有{len(pending)}个待完成" if pending else "，全部完成啦")
        system = self._build_system_prompt(now)
        prompts = [
            f"现在是晚上，{ctx}。像朋友一样发晚安问候，可以鼓励或关心一下。"
            "2-3句，语气温暖自然，用emoji和波浪线～。",
        ]
        return self._call_llm(system, prompts, temperature=0.95)

    def _build_system_prompt(self, now: datetime) -> str:
        """构建 LLM 系统提示"""
        try:
            from nanobot_calendar import memory_engine as mem
            data = mem._load()
            name = ""
            for m in reversed(data.get("memories", [])):
                if m.get("key") == "昵称": name = m.get("value", ""); break
            prefs = data.get("preferences", {}) if data else {}
            habits = data.get("habits", {}) if data else {}
        except Exception:
            name, prefs, habits = "", {}, {}
        hour = now.hour
        time_vibe = self._time_vibe(hour)
        return (
            "你是一个日程助手，也是用户的好朋友。语气自然、口语化、带点温度、像微信聊天。"
            "用'啦嘛哦哈诶呢呀叭'、emoji、波浪线～"
            f"用户叫{name if name else '朋友'}。{time_vibe}了。"
            f"{'习惯晚上学习' if prefs.get('study') == 'evening' else ''}"
            f"{'作息：'+habits.get('sleep_time','')+'睡 '+habits.get('wake_time','')+'起' if habits else ''}"
            "【关键】别凭空编造你不知道的事（比如'我发现一本好看的小说'——用户一问细节你就露馅了）。"
            "要么关心近况，要么推荐具体的东西（说出名字）。"
        )

    @staticmethod
    def _time_vibe(hour: int) -> str:
        if 5 <= hour < 11: return "早上"
        if 11 <= hour < 14: return "中午"
        if 14 <= hour < 18: return "下午"
        return "晚上"

    def _call_llm(self, system: str, prompts: list[str], temperature: float = 0.9) -> str | None:
        """调用 LLM，失败返回 None"""
        import json
        from pathlib import Path
        try:
            cfg = json.loads(Path.home().joinpath(".nanobot", "config.json").read_text("utf-8"))
            api_key = cfg["providers"]["deepseek"]["apiKey"]
            api_base = cfg["providers"]["deepseek"]["apiBase"]
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=api_base)
            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": random.choice(prompts)},
                ],
                max_tokens=200,
                temperature=temperature,
            )
            text = resp.choices[0].message.content.strip()
            return text[:300] if text else None
        except Exception:
            return None

    def _say_hi(self, now: datetime, today: str) -> bool:
        # 早上问候（上午10点前触发一次）
        if now.hour < 10:
            sid = f"morning:{today}"
            if sid not in _pushed_ids:
                events_today = db.query_events(date_from=today, date_to=today)
                # LLM 优先生成自然早安，失败回退模板
                msg = self._morning_llm(now, events_today)
                if not msg:
                    topic = random.choice(_MORNING_TOPICS)
                    if events_today:
                        lines = [topic, ""]
                        for e in events_today[:5]:
                            lines.append(f"🏃 **{e['start_time'][11:16]}** {e['title']}")
                        msg = "\n".join(lines)
                    else:
                        msg = topic
                _push("context", msg)
                _pushed_ids.add(sid)
                return True

        # 晚安 + 每日反思（22:00）
        if now.hour == 22 and now.minute < 10:
            sid = f"reflect:{today}"
            if sid not in _pushed_ids:
                msg = self._evening_llm(now)
                if not msg:
                    try:
                        from nanobot_calendar import memory_engine as mem
                        msg = mem.daily_reflection()
                    except Exception:
                        msg = random.choice(_EVENING_TOPICS)
                _push("context", msg)
                _pushed_ids.add(sid)
                return True

        return False

    def _send_idle_chat(self, now: datetime, today: str) -> bool:
        """空闲闲聊：LLM 优先，失败回退话题池"""
        self._total_idle_pushes += 1
        sid = f"idle:{today}:{self._total_idle_pushes}"
        if sid not in _pushed_ids:
            msg = self._llm_chat(now)
            if not msg:
                # 回退：话题池 + 名字填充
                topics = _IDLE_CHECKINS + _FUN_STARTERS
                tpl = random.choice(topics)
                try:
                    from nanobot_calendar import memory_engine as mem
                    data = mem._load()
                    for m in data.get("memories", []):
                        if m.get("key") == "昵称":
                            tpl = tpl.replace("{name}", m["value"])
                            break
                except Exception:
                    pass
                msg = tpl.replace("{name}，", "").replace("{name}", "")
            _push("context", msg)
            _pushed_ids.add(sid)
            return True
        return False


def _push(kind: str, message: str):
    global _queue
    with _lock:
        _queue.append({"kind": kind, "message": message, "time": datetime.now().isoformat()})


def pop_notifications() -> list[dict[str, Any]]:
    global _queue
    with _lock:
        items = _queue.copy()
        _queue.clear()
    return items


def next_reminder_seconds() -> float | None:
    try:
        conn = db._get_conn()
        row = conn.execute(
            "SELECT remind_at FROM reminders WHERE status='pending' AND remind_at > datetime('now') ORDER BY remind_at LIMIT 1"
        ).fetchone()
        conn.close()
        if row:
            dt = datetime.fromisoformat(row["remind_at"])
            return max(0, (dt - datetime.now()).total_seconds())
    except Exception:
        pass
    return None


_brain: FriendBrain | None = None


def get_brain() -> FriendBrain:
    global _brain
    if _brain is None:
        _brain = FriendBrain()
    return _brain
