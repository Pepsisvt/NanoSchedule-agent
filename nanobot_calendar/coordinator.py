"""
多 Agent 协作协调器 —— 功能三核心

架构（借鉴 nanobot spawn + multi-agent pattern）：

    用户提复杂问题（"明天适合户外运动吗？"）
                ↓
        主 Agent（协调者）
        ┌───────┼───────┐
        ↓       ↓       ↓
   日程Agent  天气Agent  建议Agent
   (查空闲)  (查天气)  (综合分析)
        └───────┼───────┘
                ↓
        综合建议 → 回复用户

三个"Agent"的实现：
- 日程Agent：query_events 查找空闲时段
- 天气Agent：web_search 获取天气（或 mock）
- 建议Agent：advisor.analyze + LLM 综合
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ContextAware, RequestContext
from nanobot.agent.tools.schema import (
    StringSchema,
    tool_parameters_schema,
)

from nanobot_calendar import advisor, db


_MULTI_AGENT_PARAMS = tool_parameters_schema(
    question=StringSchema(
        "用户的问题，如'明天适合户外运动吗'、'这周哪天适合安排聚会'"
    ),
    required=["question"],
    description=(
        "多 Agent 协作：调度日程Agent/天气Agent/建议Agent 协同回答复杂决策问题。"
        "当用户问涉及多重信息综合判断时调用（户外活动建议、聚会安排、旅行建议等）。"
    ),
)


@tool_parameters(_MULTI_AGENT_PARAMS)
class CoordinatorTool(Tool, ContextAware):
    """多 Agent 协作协调器"""

    def __init__(self):
        self._channel = ""
        self._chat_id = ""

    def set_context(self, ctx: RequestContext) -> None:
        self._channel = ctx.channel or ""
        self._chat_id = ctx.chat_id or ""

    @property
    def name(self) -> str:
        return "multi_agent_decide"

    @property
    def description(self) -> str:
        return (
            "多 Agent 协作决策。调度日程Agent、天气Agent、建议Agent 协同工作，"
            "综合多维度信息回答复杂问题。当用户问题需要综合日程+天气+建议判断时调用。"
            "例如：'明天适合户外运动吗'、'这周哪天有空聚餐'、'周末适合郊游吗'。"
        )

    async def execute(self, question: str, **kwargs: Any) -> str:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        # ── Agent 1: 日程Agent —— 查未来3天空闲 ──
        end_date = (now + timedelta(days=3)).strftime("%Y-%m-%d")
        events = db.query_events(date_from=today, date_to=end_date, limit=50)

        by_day: dict[str, list[dict]] = {}
        for e in events:
            by_day.setdefault(e["start_time"][:10], []).append(e)

        schedule_report = _schedule_agent_report(by_day, today, end_date)

        # ── Agent 2: 建议Agent —— 分析日程模式 ──
        suggestions = advisor.analyze()
        advice_report = _advice_agent_report(suggestions)

        # ── Agent 3: 天气Agent —— 调用 web_search ──
        weather_report = (
            "[天气Agent] 请主Agent使用 web_search 工具搜索目标城市天气。"
            "关键词：'{城市} 天气 2026年'。将天气结果与本报告合并后回复用户。"
        )

        # ── 综合报告 ──
        return _build_coordination_report(
            question, schedule_report, weather_report, advice_report
        )


def _schedule_agent_report(
    by_day: dict[str, list[dict]], start: str, end: str
) -> str:
    """日程Agent：分析每日空闲和繁忙度"""
    lines = [f"[日程Agent] 已分析 {start} ~ {end} 的日程："]
    if not by_day:
        lines.append("  这3天暂无日程安排，时间非常自由！")
        return "\n".join(lines)

    for i in range(3):
        day = (datetime.fromisoformat(start) + timedelta(days=i)).strftime("%Y-%m-%d")
        week = ["周一","周二","周三","周四","周五","周六","周日"][
            (datetime.fromisoformat(day)).weekday()
        ]
        day_events = by_day.get(day, [])
        cnt = len(day_events)
        load = "空闲" if cnt == 0 else "轻松" if cnt <= 2 else "适中" if cnt <= 4 else "繁忙"
        lines.append(f"  {day}（{week}）: {cnt}个日程 [{load}]")
        for e in day_events:
            t = e["start_time"][11:16]
            lines.append(f"    {t} {e['title']}")
    return "\n".join(lines)


def _advice_agent_report(suggestions: list[dict]) -> str:
    """建议Agent：分析相关建议"""
    lines = [f"[建议Agent] 分析完成，相关建议（共{len(suggestions)}条）："]
    if not suggestions:
        lines.append("  日程安排合理，无需特别提醒。")
        return "\n".join(lines)
    for s in suggestions[:3]:  # 只取 top 3
        lines.append(f"  • [{s['priority']}★] {s['message']}")
    return "\n".join(lines)


def _build_coordination_report(
    question: str, schedule: str, weather: str, advice: str
) -> str:
    """构建综合协调报告"""
    return (
        f"╔══ 多 Agent 协作报告 ══╗\n"
        f"问题: {question}\n\n"
        f"{schedule}\n\n"
        f"{advice}\n\n"
        f"{weather}\n\n"
        f"[协调者] 请主 Agent 基于以上三个 Agent 的报告，"
        f"用自然、亲切的语气综合回答用户的问题。\n"
        f"如果涉及天气，请先用 web_search 工具搜索目标城市的天气（如'北京 天气 2026年7月'），"
        f"然后将天气信息与日程信息合并后回复用户。\n"
        f"回复格式：先给结论（如'明天下午3点最适合，有太阳且你有空'），"
        f"再展示各 Agent 的分析依据。\n"
        f"╚══════════════════╝"
    )
