from __future__ import annotations

from typing import Any

from fishmindos.mcp import LocalMCPClient
from fishmindos.models import ExecutionEvent, PlanStep, TaskPlan, TaskSequence, TaskStatus


class TaskExecutor:
    def __init__(self, mcp_client: LocalMCPClient) -> None:
        self.mcp_client = mcp_client

    def build_plan(self, task_id: str, sequence: TaskSequence) -> TaskPlan:
        steps = [
            PlanStep(
                id=f"s{index}",
                skill=item.skill,
                args=item.args,
                on_fail=item.on_fail,
            )
            for index, item in enumerate(sequence.steps, start=1)
        ]
        return TaskPlan(task_id=task_id, goal=sequence.goal, steps=steps, reply_text=sequence.reply_text)

    def execute(self, plan: TaskPlan, context: dict) -> tuple[TaskStatus, list[ExecutionEvent]]:
        events: list[ExecutionEvent] = []
        local_context = dict(context)

        if not plan.steps:
            if plan.reply_text:
                events.append(
                    ExecutionEvent(
                        task_id=plan.task_id,
                        step_id="reply",
                        skill="dialogue",
                        status=TaskStatus.SUCCESS,
                        detail=plan.reply_text,
                    )
                )
                return TaskStatus.SUCCESS, events
            events.append(
                ExecutionEvent(
                    task_id=plan.task_id,
                    step_id="none",
                    skill="",
                    status=TaskStatus.FAILED,
                    detail="Empty plan, nothing to execute.",
                )
            )
            return TaskStatus.FAILED, events

        for step in plan.steps:
            result = self.mcp_client.call_tool(step.skill, step.args, context=local_context)
            status = TaskStatus.SUCCESS if result.get("ok") else TaskStatus.FAILED
            events.append(
                ExecutionEvent(
                    task_id=plan.task_id,
                    step_id=step.id,
                    skill=step.skill,
                    status=status,
                    detail=str(result.get("detail", "")),
                    data=result.get("data"),
                )
            )

            if status is TaskStatus.FAILED and step.on_fail != "continue":
                return TaskStatus.FAILED, events
            if status is TaskStatus.FAILED:
                continue

            self._update_context_from_result(local_context, step.skill, result.get("data"))
            wait_result = self._wait_if_needed(step=step, result=result, context=local_context)
            if wait_result is not None and not wait_result.get("ok"):
                events.append(
                    ExecutionEvent(
                        task_id=plan.task_id,
                        step_id=f"{step.id}_wait",
                        skill="robot_events",
                        status=TaskStatus.FAILED,
                        detail=str(wait_result.get("detail", "")),
                        data=wait_result.get("data"),
                    )
                )
                return TaskStatus.FAILED, events

        return TaskStatus.SUCCESS, events

    def _wait_if_needed(
        self,
        *,
        step: PlanStep,
        result: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not self.mcp_client.has_tool("robot_events"):
            return None

        data = result.get("data")
        if not isinstance(data, dict):
            return None

        if step.skill == "robot_navigation":
            action = str(step.args.get("action", "")).strip()
            if action == "start":
                return self.mcp_client.call_tool("robot_events", {"action": "wait_nav_started", "timeout": 60}, context=context)
            if action == "goto_waypoint" and data.get("waypoint_id") not in (None, ""):
                return self.mcp_client.call_tool(
                    "robot_events",
                    {"action": "wait_arrival", "waypoint_id": int(data["waypoint_id"]), "timeout": 300},
                    context=context,
                )
            if action == "dock_to_waypoint":
                return self.mcp_client.call_tool("robot_events", {"action": "wait_dock_complete", "timeout": 300}, context=context)

        if step.skill == "robot_navigation_assistant":
            action = str(step.args.get("action", "")).strip()
            location_name = str(step.args.get("location_name", "") or "")
            location_type = str(step.args.get("location_type", "") or "")
            if action == "start_map":
                return self.mcp_client.call_tool("robot_events", {"action": "wait_nav_started", "timeout": 60}, context=context)
            if action == "go_to_location":
                if location_type == "dock" or any(token in location_name for token in ("回充点", "充电点", "回充站", "充电桩", "回桩")):
                    return self.mcp_client.call_tool("robot_events", {"action": "wait_dock_complete", "timeout": 300}, context=context)
                if data.get("waypoint_id") not in (None, ""):
                    return self.mcp_client.call_tool(
                        "robot_events",
                        {"action": "wait_arrival", "waypoint_id": int(data["waypoint_id"]), "timeout": 300},
                        context=context,
                    )
        return None

    @staticmethod
    def _update_context_from_result(context: dict[str, Any], skill_name: str, data: Any) -> None:
        if not isinstance(data, dict):
            return

        if skill_name in {"robot_navigation", "robot_navigation_assistant", "robot_dock"}:
            if data.get("map_id") not in (None, "") or data.get("map_name") not in (None, ""):
                context["last_map"] = {"id": data.get("map_id"), "name": data.get("map_name")}
            if data.get("waypoint_id") not in (None, "") or data.get("waypoint_name") not in (None, ""):
                context["last_waypoint"] = {
                    "id": data.get("waypoint_id"),
                    "name": data.get("waypoint_name"),
                    "map_id": data.get("map_id"),
                    "map_name": data.get("map_name"),
                }

        if skill_name in {"robot_tasks", "robot_task_assistant"} and (data.get("id") is not None or data.get("name") is not None):
            context["last_task"] = {"id": data.get("id") or data.get("task_id"), "name": data.get("name")}
