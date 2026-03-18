from __future__ import annotations

import re
from dataclasses import dataclass

from fishmindos.models import InteractionEvent, TaskSequence


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


@dataclass(slots=True)
class FastPathPlanner:
    """Handles only pure conversational replies (greetings, help, identity).
    Everything else is delegated to the LLM agentic planner.
    """

    @classmethod
    def from_env(cls) -> FastPathPlanner:
        return cls()

    def plan_event(self, event: InteractionEvent) -> TaskSequence | None:
        text = event.text.strip()
        if not text:
            return None
        return self._plan_dialogue(text)

    def _reply(self, text: str, reply_text: str) -> TaskSequence:
        return TaskSequence(goal=text, steps=[], planner_source="quick", reply_text=reply_text)

    def _plan_dialogue(self, text: str) -> TaskSequence | None:
        compact = _compact(text)
        if any(token in compact for token in ("你叫什么", "你是谁", "你的名字", "你是啥")):
            return self._reply(text, "汪，我是 FishMindOS 机器狗。")
        if any(token in compact for token in ("你会什么", "你能做什么", "你可以做什么", "有哪些能力", "能力介绍", "帮我做什么")):
            return self._reply(
                text,
                "汪，我能导航、查地图和路点、执行任务、创建导航任务、管理任务链、开关灯、站立趴下、播报和查询状态。",
            )
        if compact in {"你好", "你好呀", "嗨", "hi", "hello", "在吗", "你在吗"}:
            return self._reply(text, "汪，我在。")
        if compact in {"谢谢", "谢了", "thx", "thanks"}:
            return self._reply(text, "汪。")
        if compact in {"帮助", "help"}:
            return self._reply(
                text,
                "汪，你可以直接跟我说去哪里、执行哪个任务、创建任务链、开灯关灯、站立趴下，或者问我地图、任务和状态。",
            )
        return None
