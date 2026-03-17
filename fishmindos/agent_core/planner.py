from __future__ import annotations

from fishmindos.models import Intent, PlanStep, TaskPlan


class TaskPlanner:
    def make_plan(self, intent: Intent, task_id: str, pickup_text: str, dropoff_text: str) -> TaskPlan:
        if intent.task_type != "delivery" or not intent.pickup_location or not intent.dropoff_location:
            return TaskPlan(task_id=task_id, goal="无法识别任务", steps=[])

        steps = [
            PlanStep(id="s1", skill="navigate_to", args={"location": intent.pickup_location}),
            PlanStep(id="s2", skill="speak_text", args={"text": pickup_text}, on_fail="continue"),
            PlanStep(id="s3", skill="wait_for_item", args={"timeout_sec": 60}, on_fail="abort"),
            PlanStep(id="s4", skill="navigate_to", args={"location": intent.dropoff_location}),
            PlanStep(id="s5", skill="speak_text", args={"text": dropoff_text}, on_fail="continue"),
        ]
        goal = f"配送{intent.item or '物品'}"
        return TaskPlan(task_id=task_id, goal=goal, steps=steps)
