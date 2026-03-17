from __future__ import annotations

from fishmindos.models import Intent


class DialogueGenerator:
    def pickup_script(self, intent: Intent) -> str:
        item = intent.item or "物品"
        return f"您好，我来领取一份{item}，请帮我放到我的载物区。"

    def dropoff_script(self, intent: Intent) -> str:
        item = intent.item or "物品"
        return f"您好，您需要的{item}已送到，请及时取用。"
