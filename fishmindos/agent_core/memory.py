from __future__ import annotations

from collections import deque
from typing import Any


class MemoryStore:
    """轻量内存：保存最近任务与事件。"""

    def __init__(self, max_events: int = 200) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)

    def add(self, event: dict[str, Any]) -> None:
        self._events.append(event)

    def recent(self, n: int = 20) -> list[dict[str, Any]]:
        return list(self._events)[-n:]
