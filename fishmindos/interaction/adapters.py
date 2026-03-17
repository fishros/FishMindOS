from __future__ import annotations

from fishmindos.models import InteractionEvent


class TextAdapter:
    """最小输入适配器：将文本转成 InteractionEvent。"""

    def parse(self, text: str, robot_id: str = "dog-01") -> InteractionEvent:
        return InteractionEvent(text=text.strip(), source="text", robot_id=robot_id)
