"""
Base interaction channel.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class InteractionChannel(ABC):
    """Consumes structured interaction events and optionally provides user input."""

    @abstractmethod
    def start(self) -> None:
        pass

    def stop(self) -> None:
        return

    @abstractmethod
    def handle_event(self, event: Dict[str, Any]) -> None:
        pass
