from __future__ import annotations

from typing import Any

from fishmindos.models import InteractionEvent

from .adapters import TextAdapter


class InteractionLayer:
    """统一接收文本输入，并转换成 Agent Core 可消费的事件。"""

    def __init__(self, text_adapter: TextAdapter | None = None) -> None:
        self.text_adapter = text_adapter or TextAdapter()

    def receive_text(
        self,
        text: str,
        robot_id: str = "dog-01",
        context: dict[str, Any] | None = None,
    ) -> InteractionEvent:
        return self.text_adapter.parse(text=text, robot_id=robot_id, context=context)
