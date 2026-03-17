from __future__ import annotations

import re

from fishmindos.models import Intent, InteractionEvent


class IntentParser:
    """规则版意图解析器（后续可替换成 LLM）。"""

    def parse(self, event: InteractionEvent) -> Intent:
        text = event.text
        pickup = self._extract_between(text, "到", "拿")
        dropoff = self._extract_after(text, "送到")
        item = self._extract_between(text, "拿", "送到")

        return Intent(
            task_type="delivery" if (pickup and dropoff) else "unknown",
            pickup_location=pickup,
            dropoff_location=dropoff,
            item=item,
            raw_text=text,
        )

    @staticmethod
    def _extract_between(text: str, start: str, end: str) -> str | None:
        pattern = re.escape(start) + r"(.*?)" + re.escape(end)
        match = re.search(pattern, text)
        if not match:
            return None
        value = match.group(1).strip()
        return value or None

    @staticmethod
    def _extract_after(text: str, token: str) -> str | None:
        idx = text.find(token)
        if idx == -1:
            return None
        value = text[idx + len(token) :].strip()
        return value or None
