from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Skill(ABC):
    name: str
    description: str = ""
    input_schema: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}
    expose_as_tool: bool = False

    @abstractmethod
    def run(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def to_tool_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }
