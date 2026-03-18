from __future__ import annotations

from typing import Any

from fishmindos.skill_runtime.base import Skill


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def has(self, name: str) -> bool:
        return name in self._skills

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    def names(self) -> list[str]:
        return sorted(self._skills.keys())

    def tool_definitions(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        for skill in self.all():
            if skill.expose_as_tool:
                tools.append(skill.to_tool_definition())
        return tools
