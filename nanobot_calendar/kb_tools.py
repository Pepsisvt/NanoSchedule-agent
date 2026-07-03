"""
知识库 + 对话历史 Agent 工具

提供:
  - kb_search: 搜索知识库文档
  - kb_ingest: 导入文本到知识库
  - conv_search: 搜索历史对话
"""

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import IntegerSchema, StringSchema, tool_parameters_schema


_KB_SEARCH_PARAMS = tool_parameters_schema(
    query=StringSchema("", description="搜索查询，用自然语言描述"),
    k=IntegerSchema(3, description="返回结果数量"),
    category=StringSchema("", description="可选，限定搜索类别"),
    required=["query"],
    description="搜索知识库文档。用户问'周三有什么课'、'校历上什么时候放假'时调用。",
)


@tool_parameters(_KB_SEARCH_PARAMS)
class KBSearchTool(Tool):
    @property
    def name(self) -> str:
        return "kb_search"

    @property
    def description(self) -> str:
        return (
            "搜索知识库中的文档资料。当用户询问课程安排、校历、规章制度等已导入知识库的信息时调用。"
            "与 web_search 不同，这个搜索的是本地已导入的文档。"
        )

    async def execute(self, query: str, k: int = 3, category: str = "", **kwargs: Any) -> str:
        from nanobot_calendar.knowledge_base import get_kb
        kb = get_kb()
        cat = category if category else None
        results = kb.search(query, k, category=cat)
        if not results:
            return "[KB] 知识库中未找到相关信息。你可以说'导入XX文件到知识库'来添加资料。"

        lines = [f"[知识库] 找到 {len(results)} 条："]
        for r in results:
            sim = f"{r['similarity']:.0%}"
            content = r["content"][:250].replace("\n", " ")
            lines.append(f"  [{sim}] {r['title']}: {content}")
        return "\n".join(lines)


_KB_INGEST_PARAMS = tool_parameters_schema(
    content=StringSchema("", description="要导入的文本内容"),
    title=StringSchema("", description="文档标题，如'课程表'、'校历2026'"),
    category=StringSchema("general", description="文档类别"),
    required=["content", "title"],
    description="将文本资料导入知识库，后续可通过 kb_search 检索。",
)


@tool_parameters(_KB_INGEST_PARAMS)
class KBIngestTool(Tool):
    @property
    def name(self) -> str:
        return "kb_ingest"

    @property
    def description(self) -> str:
        return (
            "将文本资料导入本地知识库。用户说'记住这个课表'、'把XX加到资料库里'时调用。"
            "导入后可通过 kb_search 语义检索。适合导入课程表、校历、规章制度等信息。"
        )

    async def execute(self, content: str, title: str, category: str = "general", **kwargs: Any) -> str:
        from nanobot_calendar.knowledge_base import get_kb
        kb = get_kb()
        return kb.ingest_text(content, title, category, source="agent")


_CONV_SEARCH_PARAMS = tool_parameters_schema(
    query=StringSchema("", description="搜索查询"),
    k=IntegerSchema(5, description="返回结果数量"),
    required=["query"],
    description="搜索历史对话记录。用户问'上次我们聊了什么'、'之前讨论过XX吗'时调用。",
)


@tool_parameters(_CONV_SEARCH_PARAMS)
class ConvSearchTool(Tool):
    @property
    def name(self) -> str:
        return "conv_search"

    @property
    def description(self) -> str:
        return (
            "搜索历史对话记录。用户说'上次聊过的那个'、'之前我们讨论过XX吗'时调用。"
            "基于语义匹配，不同问法也能找到相关历史对话。"
        )

    async def execute(self, query: str, k: int = 5, **kwargs: Any) -> str:
        from nanobot_calendar.conversation_indexer import get_indexer
        idx = get_indexer()
        idx.scan_and_index()  # 先增量索引
        return idx.search_formatted(query, k)


KB_TOOLS: list[type[Tool]] = [KBSearchTool, KBIngestTool, ConvSearchTool]
