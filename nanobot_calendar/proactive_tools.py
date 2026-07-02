"""主动推送控制工具 - 跨渠道的定时建议推送

借鉴 akashic-agent：通过 nanobot cron 注册周期性任务，
由 gateway 执行并投递到对应渠道（飞书/网页/CLI 均可）。

与 PWA 进程内的 ProactiveBrain 不同，这个走 gateway，
所以飞书也能收到主动推送。
"""

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ContextAware, RequestContext
from nanobot.agent.tools.schema import IntegerSchema, tool_parameters_schema


# 定时任务触发时，发给 Agent 的指令（必须是朋友闲聊风格！）
_BRIEFING_PROMPT = (
    "你现在要像朋友一样主动找用户聊聊天！先看看用户最近日程、有没有即将开始的事、"
    "有没有什么值得关心的。然后选一个开场：\n\n"
    "1) 日程提醒类：有会议快开始了就提醒一下\n"
    "2) 关心类：日程排太满了提醒休息，或者空了建议安排\n"
    "3) 闲聊类：如果没什么特别的，就随便问候一下（'嘿，在干嘛呢~'、'今天过得怎么样呀'）\n\n"
    "记住：语气要像朋友发微信，随便自然——用'啦嘛哦哈诶呢呀叭'、用emoji、用波浪线～"
    "不要长篇大论，2-3句话就够了。如果用户日程很合理没什么要说的，就随便问个好。\n"
    "不要用'定时推送'、'分析报告'、'主动建议'这类词——就像你突然想起来找他聊天一样。\n"
    "【重要】不要每次都说同一个话题！如果上次聊了吃饭/聚餐，这次换别的——关心心情、\n"
    "问问最近忙不忙、聊聊天气、推荐个电影……总之话题要轮换，别像复读机。\n"
    "【关键】不要凭空编造你其实不知道的事！比如别说'我发现一本好看的小说'（然后用户问哪本你就懵了）。\n"
    "要聊就聊你能接住的：问用户的近况、关心日程、或者直接推荐具体的东西（'最近《XX》挺火的，你看了吗'）。"
)


_ENABLE_PARAMS = tool_parameters_schema(
    interval_minutes=IntegerSchema(
        30, description="推送间隔（分钟）。演示可设2-3，日常建议60-120。"
    ),
    required=[],
    description="开启定时主动日程建议。Agent 会按设定间隔主动分析并推送建议到当前渠道。",
)


@tool_parameters(_ENABLE_PARAMS)
class EnableProactiveTool(Tool, ContextAware):
    """开启主动建议推送"""

    def __init__(self, cron_service=None):
        self._cron = cron_service
        self._channel = ""
        self._chat_id = ""
        self._session_key = ""

    @classmethod
    def create(cls, ctx):
        return cls(cron_service=getattr(ctx, "cron_service", None))

    def set_context(self, ctx: RequestContext) -> None:
        self._channel = ctx.channel or ""
        self._chat_id = ctx.chat_id or ""
        self._session_key = ctx.session_key or ""

    @property
    def name(self) -> str:
        return "enable_proactive"

    @property
    def description(self) -> str:
        return (
            "开启定时主动日程建议推送。用户说'开启主动提醒'、'定时给我建议'、"
            "'每隔X分钟提醒我看日程'时调用。参数 interval_minutes 为间隔分钟数。"
        )

    async def execute(self, interval_minutes: int = 30, **kwargs: Any) -> str:
        if not self._cron:
            return "[ERROR] cron 服务不可用，无法开启主动推送"
        if not (self._channel and self._chat_id and self._session_key):
            return "[ERROR] 需要从聊天会话中开启（飞书/网页）"

        # 网页端 chat_id 会随刷新变化，cron 投递不可靠
        # 网页已有 PWA 轮询引擎自动处理主动推送，无需 cron
        if self._channel == "websocket":
            return (
                "[提示] 网页端已自动启用主动建议推送（PWA 引擎，空闲约3分钟后自动分析）。\n"
                "无需手动开启。如需稳定的手机推送，请在飞书里开启此功能。"
            )

        try:
            from nanobot.cron.types import CronSchedule

            interval = max(1, interval_minutes)
            # 先移除已有的同名任务，避免重复
            for j in self._cron.list_jobs():
                if j.name == f"proactive:{self._chat_id[:12]}":
                    self._cron.remove_job(j.id)

            job = self._cron.add_job(
                name=f"proactive:{self._chat_id[:12]}",
                schedule=CronSchedule(kind="every", every_ms=interval * 60 * 1000),
                message=_BRIEFING_PROMPT,
                delete_after_run=False,
                session_key=self._session_key,
                origin_channel=self._channel,
                origin_chat_id=self._chat_id,
            )
            return (
                f"[OK] 已开启主动日程建议\n"
                f"间隔: 每 {interval} 分钟\n"
                f"渠道: {self._channel}\n"
                f"我会定期分析你的日程并主动推送建议~"
            )
        except Exception as e:
            return f"[ERROR] 开启失败: {e}"


_DISABLE_PARAMS = tool_parameters_schema(
    required=[],
    description="关闭定时主动日程建议推送。",
)


@tool_parameters(_DISABLE_PARAMS)
class DisableProactiveTool(Tool, ContextAware):
    """关闭主动建议推送"""

    def __init__(self, cron_service=None):
        self._cron = cron_service
        self._chat_id = ""

    @classmethod
    def create(cls, ctx):
        return cls(cron_service=getattr(ctx, "cron_service", None))

    def set_context(self, ctx: RequestContext) -> None:
        self._chat_id = ctx.chat_id or ""

    @property
    def name(self) -> str:
        return "disable_proactive"

    @property
    def description(self) -> str:
        return "关闭定时主动日程建议推送。用户说'关闭主动提醒'、'别再定时推送'时调用。"

    async def execute(self, **kwargs: Any) -> str:
        if not self._cron:
            return "[ERROR] cron 服务不可用"
        try:
            removed = 0
            for j in self._cron.list_jobs():
                if j.name == f"proactive:{self._chat_id[:12]}":
                    self._cron.remove_job(j.id)
                    removed += 1
            if removed:
                return "[OK] 已关闭主动日程建议推送"
            return "[提示] 当前没有开启主动推送"
        except Exception as e:
            return f"[ERROR] 关闭失败: {e}"


PROACTIVE_TOOLS: list[type[Tool]] = [EnableProactiveTool, DisableProactiveTool]
