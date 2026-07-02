"""提醒工具 - 数据库存储 + 前端轮询"""

from __future__ import annotations

from typing import Any
from datetime import datetime

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ContextAware, RequestContext
from nanobot.agent.tools.schema import (
    IntegerSchema,
    StringSchema,
    tool_parameters_schema,
)

from nanobot_calendar import db


# ── 设置提醒 ──────────────────────────────────────────

_SETUP_REMINDER_PARAMS = tool_parameters_schema(
    message=StringSchema("提醒内容"),
    remind_at=StringSchema(
        "提醒时间，ISO 格式如 2026-06-25T14:00:00"
    ),
    event_id=IntegerSchema(0, description="关联的日程 ID（可选）"),
    required=["message", "remind_at"],
    description="设置定时提醒。前端每5秒轮询检查到期提醒。",
)


@tool_parameters(_SETUP_REMINDER_PARAMS)
class SetupReminderTool(Tool, ContextAware):
    """设置提醒

    - 飞书等稳定渠道：用 nanobot cron 主动推送到手机
    - 网页(websocket)：存数据库，前端轮询弹窗
    """

    def __init__(self, cron_service=None, default_timezone="Asia/Shanghai"):
        self._cron = cron_service
        self._tz = default_timezone
        self._channel = ""
        self._chat_id = ""
        self._session_key = ""

    @classmethod
    def create(cls, ctx):
        return cls(
            cron_service=getattr(ctx, "cron_service", None),
            default_timezone=getattr(ctx, "timezone", "Asia/Shanghai"),
        )

    def set_context(self, ctx: RequestContext) -> None:
        self._channel = ctx.channel or ""
        self._chat_id = ctx.chat_id or ""
        self._session_key = ctx.session_key or ""

    @property
    def name(self) -> str:
        return "setup_reminder"

    @property
    def description(self) -> str:
        return "设置定时提醒。如 setup_reminder(message='开会', remind_at='2026-06-25T14:00:00')"

    async def execute(
        self, message: str, remind_at: str, event_id: int = 0, **kwargs: Any
    ) -> str:
        try:
            dt = datetime.fromisoformat(remind_at)

            # 存入数据库
            reminder = db.create_reminder(
                event_id=event_id,
                remind_at=remind_at,
                message=message,
                channel=self._channel or "websocket",
                chat_id=self._chat_id or "",
            )

            # 飞书等稳定渠道：用 cron 主动推送
            # websocket 渠道 chat_id 会变，继续用前端轮询
            pushed_via = "前端轮询弹窗"
            if (
                self._cron
                and self._channel
                and self._channel != "websocket"
                and self._chat_id
                and self._session_key
            ):
                from zoneinfo import ZoneInfo
                from nanobot.cron.types import CronSchedule

                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=ZoneInfo(self._tz))
                at_ms = int(dt.timestamp() * 1000)

                job = self._cron.add_job(
                    name=f"reminder:{reminder['id']}:{message[:20]}",
                    schedule=CronSchedule(kind="at", at_ms=at_ms),
                    message=f"⏰ 提醒：{message}",
                    delete_after_run=True,
                    session_key=self._session_key,
                    origin_channel=self._channel,
                    origin_chat_id=self._chat_id,
                )
                # 回写 cron job id
                conn = db._get_conn()
                conn.execute(
                    "UPDATE reminders SET cron_job_id=? WHERE id=?",
                    (job.id, reminder["id"]),
                )
                conn.commit()
                conn.close()
                pushed_via = f"{self._channel} 主动推送"

            return (
                f"[OK] 提醒已设置 (ID: {reminder['id']})\n"
                f"内容: {message}\n"
                f"时间: {remind_at}\n"
                f"推送方式: {pushed_via}"
            )
        except ValueError:
            return f"[ERROR] 时间格式错误: '{remind_at}'。请用 ISO 格式: YYYY-MM-DDTHH:MM:SS"
        except Exception as e:
            return f"[ERROR] 设置提醒失败: {e}"


# ── 查看提醒 ──────────────────────────────────────────

_LIST_REMINDERS_PARAMS = tool_parameters_schema(
    description="列出所有提醒及其状态",
)


@tool_parameters(_LIST_REMINDERS_PARAMS)
class ListRemindersTool(Tool, ContextAware):
    @property
    def name(self) -> str:
        return "list_reminders"

    @property
    def description(self) -> str:
        return "列出所有已设置的提醒和状态"

    async def execute(self, **kwargs: Any) -> str:
        try:
            reminders = db.list_reminders()
            if not reminders:
                return "暂无提醒"
            lines = [f"提醒列表 ({len(reminders)} 条):"]
            for r in reminders:
                icon = {"pending": "[待触发]", "sent": "[已推送]", "cancelled": "[已取消]"}.get(
                    r["status"], ""
                )
                lines.append(
                    f"  [{r['id']}] {icon} {r['remind_at'][:16]} | {r['message']}"
                )
            return "\n".join(lines)
        except Exception as e:
            return f"[ERROR] {e}"


# ── 取消提醒 ──────────────────────────────────────────

_CANCEL_REMINDER_PARAMS = tool_parameters_schema(
    reminder_id=IntegerSchema(0, description="要取消的提醒 ID"),
    required=["reminder_id"],
    description="取消指定提醒",
)


@tool_parameters(_CANCEL_REMINDER_PARAMS)
class CancelReminderTool(Tool, ContextAware):
    @property
    def name(self) -> str:
        return "cancel_reminder"

    @property
    def description(self) -> str:
        return "取消已设置的提醒"

    async def execute(self, reminder_id: int, **kwargs: Any) -> str:
        try:
            ok = db.cancel_reminder(reminder_id)
            if ok:
                return f"[OK] 提醒 (ID: {reminder_id}) 已取消"
            return f"[ERROR] 未找到提醒 ID={reminder_id}"
        except Exception as e:
            return f"[ERROR] 取消失败: {e}"


# ── 即将到来的提醒 ────────────────────────────────────

_UPCOMING_PARAMS = tool_parameters_schema(
    limit=IntegerSchema(5, description="最多返回条数"),
    description="查看即将到来的提醒",
)


@tool_parameters(_UPCOMING_PARAMS)
class UpcomingRemindersTool(Tool, ContextAware):
    @property
    def name(self) -> str:
        return "upcoming_reminders"

    @property
    def description(self) -> str:
        return "列出即将到来的提醒"

    async def execute(self, limit: int = 5, **kwargs: Any) -> str:
        try:
            reminders = db.get_upcoming_reminders(limit=limit)
            if not reminders:
                return "暂无即将到来的提醒"
            now = datetime.now()
            lines = ["即将到来的提醒:"]
            for r in reminders:
                dt = datetime.fromisoformat(r["remind_at"])
                delta = dt - now
                hours = delta.total_seconds() / 3600
                timing = (
                    f"{int(delta.total_seconds() / 60)} 分钟后"
                    if hours < 1
                    else f"{int(hours)} 小时后" if hours < 24
                    else f"{int(hours / 24)} 天后"
                )
                lines.append(f"  [{r['id']}] {timing} — {r['message']}")
            return "\n".join(lines)
        except Exception as e:
            return f"[ERROR] {e}"


REMINDER_TOOLS: list[type[Tool]] = [
    SetupReminderTool,
    ListRemindersTool,
    CancelReminderTool,
    UpcomingRemindersTool,
]
