"""智能建议工具 - 供 Agent 主动调用日程分析"""

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ContextAware
from nanobot.agent.tools.schema import tool_parameters_schema

from nanobot_calendar import advisor


_ANALYZE_PARAMS = tool_parameters_schema(
    description="分析用户最近的日程模式，给出关怀型智能建议（健康、时间利用、提醒等）。",
)


@tool_parameters(_ANALYZE_PARAMS)
class AnalyzeScheduleTool(Tool, ContextAware):
    """智能日程分析工具"""

    @property
    def name(self) -> str:
        return "analyze_schedule"

    @property
    def description(self) -> str:
        return (
            "分析用户最近 7 天的日程，给出智能建议。"
            "当用户问'帮我分析日程'、'有什么建议'、'我最近安排合理吗'时调用。"
            "返回多条建议，Agent 应整理成自然、关怀的语气回复。"
        )

    async def execute(self, **kwargs: Any) -> str:
        try:
            suggestions = advisor.analyze()
            if not suggestions:
                return (
                    "[分析结果] 你的日程安排得很合理，没有发现需要特别注意的地方。"
                    "劳逸结合，继续保持~"
                )
            lines = [f"[分析结果] 发现 {len(suggestions)} 条建议（按重要性排序）："]
            for s in suggestions:
                lines.append(f"  • [{s['category']}] {s['message']}")
            lines.append(
                "\n请把以上建议用自然、关怀的语气整理后告诉用户，"
                "可以适当合并相似建议，像贴心助理一样。"
            )
            return "\n".join(lines)
        except Exception as e:
            return f"[ERROR] 分析失败：{e}"


ADVISOR_TOOLS: list[type[Tool]] = [AnalyzeScheduleTool]
