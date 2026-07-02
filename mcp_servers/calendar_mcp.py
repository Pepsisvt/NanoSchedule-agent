#!/usr/bin/env python
"""日程管理 MCP Server —— 标准 MCP 协议"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from nanobot_calendar import db

server = Server("calendar-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="create_event", description="创建日程", inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "日程标题"},
                "start_time": {"type": "string", "description": "开始时间(ISO格式)"},
                "end_time": {"type": "string", "description": "结束时间"},
                "location": {"type": "string", "description": "地点"},
                "event_desc": {"type": "string", "description": "备注"},
            },
            "required": ["title", "start_time"],
        }),
        Tool(name="query_events", description="查询日程", inputSchema={
            "type": "object",
            "properties": {
                "date_from": {"type": "string"},
                "date_to": {"type": "string"},
                "keyword": {"type": "string"},
                "limit": {"type": "integer"},
            },
        }),
        Tool(name="delete_event", description="删除日程(请先确认)", inputSchema={
            "type": "object",
            "properties": {"event_id": {"type": "integer"}},
            "required": ["event_id"],
        }),
        Tool(name="check_conflict", description="检查时间冲突", inputSchema={
            "type": "object",
            "properties": {
                "start_time": {"type": "string"},
                "end_time": {"type": "string"},
            },
            "required": ["start_time"],
        }),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "create_event":
        ev = db.create_event(
            title=arguments["title"], start_time=arguments["start_time"],
            end_time=arguments.get("end_time", ""),
            location=arguments.get("location", ""),
            description=arguments.get("event_desc", ""),
        )
        conflicts = db.find_conflicts(arguments["start_time"], arguments.get("end_time", ""))
        warn = f" | [冲突]{'、'.join(c['title'] for c in conflicts)}" if conflicts else ""
        return [TextContent(type="text", text=f"[OK] 已创建(ID:{ev['id']}) {ev['title']} @ {ev['start_time'][:16]}{warn}")]

    elif name == "query_events":
        events = db.query_events(
            date_from=arguments.get("date_from", ""),
            date_to=arguments.get("date_to", ""),
            keyword=arguments.get("keyword", ""),
            limit=arguments.get("limit", 20),
        )
        if not events:
            return [TextContent(type="text", text="没有日程")]
        lines = [f"共{len(events)}个日程："]
        for e in events[:20]:
            lines.append(f"  [{e['id']}] {e['start_time'][:16]} {e['title']}")
        return [TextContent(type="text", text="\n".join(lines))]

    elif name == "delete_event":
        ok = db.delete_event(arguments["event_id"])
        return [TextContent(type="text", text="[OK] 已删除" if ok else f"ID={arguments['event_id']}不存在")]

    elif name == "check_conflict":
        conflicts = db.find_conflicts(arguments["start_time"], arguments.get("end_time", ""))
        if not conflicts:
            return [TextContent(type="text", text="[空闲] 无冲突")]
        lines = [f"[冲突] {len(conflicts)}个："]
        for c in conflicts:
            lines.append(f"  {c['start_time'][:16]} {c['title']}")
        return [TextContent(type="text", text="\n".join(lines))]

    return [TextContent(type="text", text=f"未知工具: {name}")]


async def main():
    db_path = str(Path.home() / ".nanobot" / "calendar.db")
    db.set_db_path(db_path)
    db.init_db()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
