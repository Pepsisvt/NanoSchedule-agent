#!/usr/bin/env python
"""记忆与画像 MCP Server —— 标准 MCP 协议"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from nanobot_calendar import memory_engine as mem

server = Server("memory-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="remember", description="记住用户信息。key=类型(sleep_time/study/fixed_schedule), value=值", inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["key", "value"],
        }),
        Tool(name="my_profile", description="查看用户画像：习惯、偏好、固定日程、关系状态", inputSchema={
            "type": "object", "properties": {},
        }),
        Tool(name="emotion_detect", description="检测用户情绪+结合日程给行动建议", inputSchema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }),
        Tool(name="daily_reflection", description="每日复盘：分析完成率、发现规律、写入记忆", inputSchema={
            "type": "object", "properties": {},
        }),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "remember":
            result = mem.remember(arguments["key"], arguments["value"])
        elif name == "my_profile":
            result = mem.get_profile_text() or "暂无画像"
        elif name == "emotion_detect":
            r = mem.detect_emotion(arguments["text"])
            result = f"[{r['emotion']}] 待办:{r.get('pending_events',0)}项 | {r['suggestion']}"
        elif name == "daily_reflection":
            result = mem.daily_reflection()
        else:
            result = f"未知工具: {name}"
        return [TextContent(type="text", text=result)]
    except Exception as e:
        return [TextContent(type="text", text=f"[ERROR] {e}")]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
