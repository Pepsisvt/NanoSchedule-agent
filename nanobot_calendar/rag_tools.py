"""
RAG 工具 —— 让 Agent 能使用向量检索记忆

提供:
  - rag_remember: 语义记住信息
  - rag_search: 搜索相关记忆
  - rag_context: 获取对话上下文（自动注入）

与 memory_tools.py 的区别:
  - memory_tools: JSON 精确匹配，适合"用户叫什么名字"
  - rag_tools: 向量语义检索，适合"上次那个饭局是什么时候"
"""

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ContextAware, RequestContext
from nanobot.agent.tools.schema import IntegerSchema, StringSchema, tool_parameters_schema

from nanobot_calendar.rag_memory import get_rag


_REMEMBER_PARAMS = tool_parameters_schema(
    key=StringSchema("", description="记忆的分类标签，如'饮食习惯'、'重要日期'"),
    value=StringSchema("", description="具体信息内容，如'用户喜欢吃川菜'、'7月5日生日'"),
    required=["key", "value"],
    description="用向量记忆引擎记住一条信息，支持后续语义检索。语义相似的问法也能匹配到。",
)


@tool_parameters(_REMEMBER_PARAMS)
class RAGRememberTool(Tool):
    """语义记忆工具"""

    @property
    def name(self) -> str:
        return "rag_remember"

    @property
    def description(self) -> str:
        return (
            "语义记忆工具。用自然语言记住用户信息，后续用不同问法也能检索到。"
            "比如记住了'用户喜欢吃川菜'，以后用户问'我想吃辣的'也能匹配到。"
        )

    async def execute(self, key: str, value: str, **kwargs: Any) -> str:
        rag = get_rag()
        return rag.remember(key, value)


_SEARCH_PARAMS = tool_parameters_schema(
    query=StringSchema("", description="搜索查询，用自然语言描述你想找什么"),
    k=IntegerSchema(5, description="返回结果数量，默认5条"),
    required=["query"],
    description="语义搜索历史记忆。用自然语言描述查找内容，返回最相关的记忆。",
)


@tool_parameters(_SEARCH_PARAMS)
class RAGSearchTool(Tool):
    """语义搜索工具"""

    @property
    def name(self) -> str:
        return "rag_search"

    @property
    def description(self) -> str:
        return (
            "语义搜索历史记忆。用户问'上次那个饭局'、'之前聊过的那个事'时调用。"
            "与 my_profile 不同，这个能做模糊语义匹配，不需要精确的关键词。"
        )

    async def execute(self, query: str, k: int = 5, **kwargs: Any) -> str:
        rag = get_rag()
        results = rag.search_with_threshold(query, k)
        if not results:
            return "[RAG] 没有找到相关记忆"

        lines = [f"[RAG] 找到 {len(results)} 条相关记忆："]
        for r in results:
            sim = f"{r['similarity']:.0%}"
            lines.append(f"  · {r['key']}: {r['value']} [{sim}]")
        return "\n".join(lines)


_CONTEXT_PARAMS = tool_parameters_schema(
    query=StringSchema("", description="当前对话的主题或用户问题，用于检索相关记忆"),
    required=["query"],
    description="获取与当前对话最相关的历史记忆，作为 LLM 的辅助上下文。",
)


@tool_parameters(_CONTEXT_PARAMS)
class RAGContextTool(Tool):
    """获取相关记忆上下文"""

    @property
    def name(self) -> str:
        return "rag_context"

    @property
    def description(self) -> str:
        return (
            "获取与当前对话主题最相关的历史记忆。在回答用户问题前调用，获取相关背景信息。"
            "例如用户说'我好像忘了什么事'，调用这个来查找可能相关的提醒和记忆。"
        )

    async def execute(self, query: str, **kwargs: Any) -> str:
        rag = get_rag()
        context = rag.get_context_for_prompt(query)
        if not context:
            return "[RAG] 暂无相关记忆"
        return context


RAG_TOOLS: list[type[Tool]] = [RAGRememberTool, RAGSearchTool, RAGContextTool]
