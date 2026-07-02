"""日程管理工具 - 日程 CRUD"""

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ContextAware, RequestContext
from nanobot.agent.tools.schema import (
    IntegerSchema,
    StringSchema,
    BooleanSchema,
    tool_parameters_schema,
)

from nanobot_calendar import db

# ── 创建日程 ──────────────────────────────────────────

_CREATE_EVENT_PARAMS = tool_parameters_schema(
    title=StringSchema("日程标题", max_length=200),
    start_time=StringSchema("开始时间，ISO 格式如 2026-06-25T14:00:00"),
    end_time=StringSchema("结束时间，ISO 格式，非必填"),
    event_desc=StringSchema("日程详情描述（可选）"),
    location=StringSchema("地点（可选）"),
    all_day=BooleanSchema(description="是否全天事件，默认 false"),
    repeat_type=StringSchema("重复类型：daily/weekly/monthly，非必填"),
    required=["title", "start_time"],
    description="创建新日程。Agent 应智能解析用户自然语言并转换为 ISO 时间格式。",
)


@tool_parameters(_CREATE_EVENT_PARAMS)
class CreateEventTool(Tool, ContextAware):
    """创建日程工具"""

    @property
    def name(self) -> str:
        return "create_event"

    @property
    def description(self) -> str:
        return (
            "创建一个新日程事件。需要标题和开始时间（ISO 格式）。"
            "例如：create_event(title='团队会议', start_time='2026-06-25T14:00:00', "
            "event_desc='讨论项目进度', location='会议室A')"
        )

    async def execute(
        self,
        title: str,
        start_time: str,
        end_time: str = "",
        event_desc: str = "",
        location: str = "",
        all_day: bool = False,
        repeat_type: str = "",
        **kwargs: Any,
    ) -> str:
        try:
            # 冲突检测：非全天事件创建前先查重叠
            conflict_warning = ""
            if not all_day:
                conflicts = db.find_conflicts(start_time, end_time)
                if conflicts:
                    parts = ["[警告] 检测到时间冲突："]
                    for c in conflicts:
                        t = c["start_time"][11:16]
                        end = f"-{c['end_time'][11:16]}" if c["end_time"] else ""
                        loc = f" @{c['location']}" if c["location"] else ""
                        parts.append(f"  • {t}{end} {c['title']}{loc}")
                    parts.append("（日程仍照常创建，如需调整请告知）")
                    conflict_warning = "\n".join(parts) + "\n\n"

            event = db.create_event(
                title=title,
                start_time=start_time,
                end_time=end_time,
                description=event_desc,
                location=location,
                all_day=all_day,
                repeat_type=repeat_type,
            )
            lines = []
            lines.append(f"[OK] 日程已创建 (ID: {event['id']})")
            lines.append(f"标题: {event['title']}")
            lines.append(f"时间: {event['start_time']}")
            if event["end_time"]:
                lines.append(f"  至: {event['end_time']}")
            if event["location"]:
                lines.append(f"地点: {event['location']}")
            if event["description"]:
                lines.append(f"备注: {event['description']}")
            if event["all_day"]:
                lines.append("[全天事件]")
            if event["repeat_type"]:
                lines.append(f"[重复: {event['repeat_type']}]")
            return conflict_warning + "\n".join(lines)
        except Exception as e:
            return f"[ERROR] 创建日程失败：{e}"


# ── 冲突检测（独立工具，供 Agent 主动调用）──────────────

_CHECK_CONFLICT_PARAMS = tool_parameters_schema(
    start_time=StringSchema("开始时间，ISO 格式如 2026-06-25T14:00:00"),
    end_time=StringSchema("结束时间，ISO 格式，不填默认1小时"),
    required=["start_time"],
    description="检查某个时间段是否与现有日程冲突。创建日程前可先调用确认。",
)


@tool_parameters(_CHECK_CONFLICT_PARAMS)
class CheckConflictTool(Tool, ContextAware):
    """检查时间冲突"""

    @property
    def name(self) -> str:
        return "check_conflict"

    @property
    def description(self) -> str:
        return (
            "检查指定时间段是否与现有日程冲突，返回冲突的日程列表。"
            "用户询问'某时间有空吗'或创建日程前可调用。"
        )

    async def execute(
        self, start_time: str, end_time: str = "", **kwargs: Any
    ) -> str:
        try:
            conflicts = db.find_conflicts(start_time, end_time)
            if not conflicts:
                return f"[空闲] {start_time[:16]} 这个时间段没有冲突，可以安排。"
            lines = [f"[冲突] {start_time[:16]} 已有 {len(conflicts)} 个日程："]
            for c in conflicts:
                t = c["start_time"][11:16]
                end = f"-{c['end_time'][11:16]}" if c["end_time"] else ""
                loc = f" @{c['location']}" if c["location"] else ""
                lines.append(f"  • {t}{end} {c['title']}{loc}")
            return "\n".join(lines)
        except Exception as e:
            return f"[ERROR] 冲突检查失败：{e}"


# ── 查询日程 ──────────────────────────────────────────

_QUERY_EVENTS_PARAMS = tool_parameters_schema(
    date_from=StringSchema("开始日期，ISO 格式如 2026-06-24"),
    date_to=StringSchema("结束日期，ISO 格式"),
    keyword=StringSchema("搜索关键词，匹配标题和描述"),
    limit=IntegerSchema(20, description="最多返回条数"),
    description="查询日程列表。不带参数时返回最近日程；传日期可按范围筛选。",
)


@tool_parameters(_QUERY_EVENTS_PARAMS)
class QueryEventsTool(Tool, ContextAware):
    """查询日程工具"""

    @property
    def name(self) -> str:
        return "query_events"

    @property
    def description(self) -> str:
        return (
            "查询日程列表。可选参数：date_from/date_to 按日期范围筛选，"
            "keyword 按关键词搜索。不传参数则返回全部最近日程。"
        )

    async def execute(
        self,
        date_from: str = "",
        date_to: str = "",
        keyword: str = "",
        limit: int = 20,
        **kwargs: Any,
    ) -> str:
        try:
            events = db.query_events(
                date_from=date_from,
                date_to=date_to,
                keyword=keyword,
                limit=limit,
            )
            if not events:
                scope = ""
                if date_from and date_to:
                    scope = f" {date_from} ~ {date_to}"
                elif keyword:
                    scope = f" (搜索: {keyword})"
                return f"[EMPTY] 没有找到日程{scope}"

            lines = [f"日程列表 (共 {len(events)} 条):"]
            for e in events:
                line = f"  [{e['id']}] {e['start_time'][:16]} | {e['title']}"
                if e["location"]:
                    line += f" @{e['location']}"
                if e["status"] == "pending":
                    line += " [待办]"
                elif e["status"] == "done":
                    line += " [已完成]"
                lines.append(line)
            return "\n".join(lines)
        except Exception as e:
            return f"[ERROR] 查询日程失败：{e}"


# ── 更新日程 ──────────────────────────────────────────

_UPDATE_EVENT_PARAMS = tool_parameters_schema(
    event_id=IntegerSchema(0, description="要修改的日程 ID"),
    title=StringSchema("新标题（可选）"),
    start_time=StringSchema("新开始时间（可选）"),
    end_time=StringSchema("新结束时间（可选）"),
    event_desc=StringSchema("新描述（可选）"),
    location=StringSchema("新地点（可选）"),
    all_day=BooleanSchema(description="是否全天（可选）"),
    repeat_type=StringSchema("重复类型（可选）"),
    required=["event_id"],
    description="修改已有日程。只需传 event_id 和要修改的字段。",
)


@tool_parameters(_UPDATE_EVENT_PARAMS)
class UpdateEventTool(Tool, ContextAware):
    """修改日程工具"""

    @property
    def name(self) -> str:
        return "update_event"

    @property
    def description(self) -> str:
        return "修改已有日程的字段。需要 event_id 以及要修改的字段名和值。"

    async def execute(
        self,
        event_id: int,
        title: str = "",
        start_time: str = "",
        end_time: str = "",
        event_desc: str = "",
        location: str = "",
        all_day: bool | None = None,
        repeat_type: str = "",
        **kwargs: Any,
    ) -> str:
        try:
            event = db.update_event(
                event_id=event_id,
                title=title,
                start_time=start_time,
                end_time=end_time,
                description=event_desc,
                location=location,
                all_day=all_day,
                repeat_type=repeat_type,
            )
            if event is None:
                return f"[ERROR] 未找到日程 ID={event_id}"
            lines = [f"[OK] 日程已更新 (ID: {event_id})"]
            lines.append(f"标题: {event['title']}")
            lines.append(f"时间: {event['start_time']}")
            return "\n".join(lines)
        except Exception as e:
            return f"[ERROR] 更新日程失败：{e}"


# ── 删除日程 ──────────────────────────────────────────

_DELETE_EVENT_PARAMS = tool_parameters_schema(
    event_id=IntegerSchema(0, description="要删除的日程 ID"),
    required=["event_id"],
    description="删除指定日程（同时会删除关联的提醒）。操作不可撤销，请先确认。",
)


@tool_parameters(_DELETE_EVENT_PARAMS)
class DeleteEventTool(Tool, ContextAware):
    """删除日程工具"""

    @property
    def name(self) -> str:
        return "delete_event"

    @property
    def description(self) -> str:
        return "删除指定 ID 的日程。此操作不可撤销，请先向用户确认。"

    async def execute(self, event_id: int, **kwargs: Any) -> str:
        try:
            ok = db.delete_event(event_id)
            if ok:
                return f"[OK] 日程 (ID: {event_id}) 已删除"
            return f"[ERROR] 未找到日程 ID={event_id}"
        except Exception as e:
            return f"[ERROR] 删除日程失败：{e}"


# ── 导出工具列表 ──────────────────────────────────────

CALENDAR_TOOLS: list[type[Tool]] = [
    CreateEventTool,
    QueryEventsTool,
    UpdateEventTool,
    DeleteEventTool,
    CheckConflictTool,
]
