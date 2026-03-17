from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Skill(ABC):
    name: str

    @abstractmethod
    def run(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError
