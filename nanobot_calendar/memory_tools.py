"""长期记忆工具 —— 供 Agent 调用"""

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ContextAware, RequestContext
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema

from nanobot_calendar import memory_engine as mem


# ── remember：记住信息 ────────────────────────────

_REMEMBER_PARAMS = tool_parameters_schema(
    key=StringSchema("记忆的键，如 sleep_time / meeting / fixed_schedule / 昵称 / 爱好"),
    value=StringSchema("记忆的值，如 00:30 / afternoon / 周三实验课 / 小明"),
    required=["key", "value"],
    description=(
        "记住用户说的重要信息。用户说'我一般周三下午有实验'时调用 remember(key='fixed_schedule', value='{\"day\":\"Wed\",\"time\":\"13:00-17:00\",\"desc\":\"实验课\"}')"
        "用户说'我喜欢晚上学习'时调用 remember(key='study', value='evening')"
        "用户说'我一般12点睡'时调用 remember(key='sleep_time', value='00:00')"
        "用户分享个人喜好、习惯、固定安排时主动调用，不要等用户说'记住xxx'。"
    ),
)


@tool_parameters(_REMEMBER_PARAMS)
class RememberTool(Tool, ContextAware):
    """记住用户信息"""

    @property
    def name(self) -> str:
        return "remember"

    @property
    def description(self) -> str:
        return (
            "记住用户的重要信息（习惯、偏好、固定日程等）。"
            "当用户提到自己的作息、喜好、固定安排时主动调用。"
            "例如用户说'我周三下午都有实验'→ 立即 remember。"
        )

    async def execute(self, key: str, value: str, **kwargs: Any) -> str:
        try:
            return mem.remember(key, value)
        except Exception as e:
            return f"[ERROR] 记忆失败: {e}"


# ── my_profile：查看用户画像 ──────────────────────

_PROFILE_PARAMS = tool_parameters_schema(
    description="查看用户画像：习惯、偏好、固定日程、关系状态等。Agent 安排日程时应先调用此工具。",
)


@tool_parameters(_PROFILE_PARAMS)
class MyProfileTool(Tool, ContextAware):
    """查看用户画像"""

    @property
    def name(self) -> str:
        return "my_profile"

    @property
    def description(self) -> str:
        return (
            "查看用户画像信息：作息习惯、时间偏好、固定日程、个性化记忆等。"
            "安排日程或做决策时，应先调用此工具获取用户偏好。"
            "返回的固定日程需要自动避开。"
        )

    async def execute(self, **kwargs: Any) -> str:
        try:
            text = mem.get_profile_text()
            # 运行偏好学习
            discoveries = mem.learn_from_history()
            if discoveries:
                text += "\n\n[从你的日程中自动发现的规律]\n"
                for d in discoveries[:5]:
                    conf_bar = "█" * int(d["confidence"] * 5) + "░" * (5 - int(d["confidence"] * 5))
                    text += f"  · {d['finding']}  [{conf_bar}]\n"
                # 标记可以自动应用的
                to_apply = [d for d in discoveries if d.get("suggestion") and d["confidence"] >= 0.6]
                if to_apply:
                    text += f"\n有 {len(to_apply)} 条可以自动应用，需要我帮你更新画像吗？"
            return text or "暂无用户画像信息。"
        except Exception as e:
            return f"[ERROR] 读取画像失败: {e}"


# ── emotion_detect：情绪识别 ───────────────────────

_EMOTION_PARAMS = tool_parameters_schema(
    text=StringSchema("用户的原话，如'今天好累啊'、'压力太大了'"),
    required=["text"],
    description=(
        "检测用户消息中的情绪，并结合当前日程给出行动建议。"
        "当用户表达状态（累/开心/压力/烦/兴奋/无聊）时调用，"
        "不要仅回'注意休息'，而要主动提出具体行动建议。"
    ),
)


@tool_parameters(_EMOTION_PARAMS)
class EmotionDetectTool(Tool, ContextAware):
    """情绪检测工具"""

    @property
    def name(self) -> str:
        return "emotion_detect"

    @property
    def description(self) -> str:
        return (
            "检测用户当前情绪并结合日程给出具体建议。"
            "用户说'好累'、'压力大'、'好无聊'、'好开心'时调用。"
            "返回当前情绪类型和针对性的行动建议。"
        )

    async def execute(self, text: str, **kwargs: Any) -> str:
        try:
            result = mem.detect_emotion(text)
            if result["emotion"] == "neutral":
                return "[情绪] neutral — 用户情绪平稳，正常交流即可。"
            return (
                f"[情绪] {result['emotion']}（置信度 {int(result['confidence']*100)}%）\n"
                f"[待办] {result.get('pending_events', 0)} 项\n"
                f"[建议] {result['suggestion']}\n\n"
                f"请根据以上分析，用自然的语气回复用户。关键是主动给具体行动建议，"
                f"而不是笼统地说'注意休息'。"
            )
        except Exception as e:
            return f"[ERROR] 情绪检测失败: {e}"


# ── daily_reflection：每日复盘 ─────────────────────

_REFLECT_PARAMS = tool_parameters_schema(
    description="每日复盘：分析今天完成/未完成的日程，发现规律，写入长期记忆。用户说'复盘'、'总结今天'时调用。",
)


@tool_parameters(_REFLECT_PARAMS)
class DailyReflectionTool(Tool, ContextAware):
    """每日复盘工具"""

    @property
    def name(self) -> str:
        return "daily_reflection"

    @property
    def description(self) -> str:
        return (
            "每日复盘：分析今天的日程完成情况，自动发现规律，把未完成任务记入长期记忆。"
            "用户说'帮我复盘一下'、'总结今天'时调用。"
        )

    async def execute(self, **kwargs: Any) -> str:
        try:
            return mem.daily_reflection()
        except Exception as e:
            return f"[ERROR] 复盘失败: {e}"


# ── 导出 ──────────────────────────────────────────

MEMORY_TOOLS: list[type[Tool]] = [RememberTool, MyProfileTool, EmotionDetectTool, DailyReflectionTool]
