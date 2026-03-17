from __future__ import annotations

import time
from typing import Any

from fishmindos.skill_runtime.base import Skill
from fishmindos.skill_runtime.registry import SkillRegistry


class NavigateToSkill(Skill):
    name = "navigate_to"

    def run(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        location = args["location"]
        world_model = context["world_model"]
        if not world_model.is_valid_location(location):
            return {"ok": False, "detail": f"未知地点: {location}"}
        return {"ok": True, "detail": f"已到达 {location}"}


class SpeakTextSkill(Skill):
    name = "speak_text"

    def run(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        text = args["text"]
        return {"ok": True, "detail": f"播报: {text}"}


class WaitForItemSkill(Skill):
    name = "wait_for_item"

    def run(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        timeout_sec = int(args.get("timeout_sec", 30))
        time.sleep(min(timeout_sec, 1))
        return {"ok": True, "detail": "物品装载完成"}


class QueryStatusSkill(Skill):
    name = "query_status"

    def run(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "detail": "机器人状态正常"}


class InspectAreaSkill(Skill):
    name = "inspect_area"

    def run(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "detail": "区域巡检完成"}


class GoHomeSkill(Skill):
    name = "go_home"

    def run(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "detail": "已返回待命点"}


def register_builtin_skills(registry: SkillRegistry) -> None:
    for skill in [
        NavigateToSkill(),
        SpeakTextSkill(),
        WaitForItemSkill(),
        QueryStatusSkill(),
        InspectAreaSkill(),
        GoHomeSkill(),
    ]:
        registry.register(skill)
