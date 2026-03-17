from __future__ import annotations

from fishmindos.models import ExecutionEvent, TaskPlan, TaskStatus
from fishmindos.skill_runtime.registry import SkillRegistry


class TaskExecutor:
    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def execute(self, plan: TaskPlan, context: dict) -> tuple[TaskStatus, list[ExecutionEvent]]:
        events: list[ExecutionEvent] = []

        if not plan.steps:
            events.append(
                ExecutionEvent(
                    task_id=plan.task_id,
                    step_id="none",
                    status=TaskStatus.FAILED,
                    detail="空计划，无法执行",
                )
            )
            return TaskStatus.FAILED, events

        for step in plan.steps:
            skill = self.registry.get(step.skill)
            if skill is None:
                events.append(
                    ExecutionEvent(
                        task_id=plan.task_id,
                        step_id=step.id,
                        status=TaskStatus.FAILED,
                        detail=f"技能不存在: {step.skill}",
                    )
                )
                return TaskStatus.FAILED, events

            result = skill.run(step.args, context)
            status = TaskStatus.SUCCESS if result.get("ok") else TaskStatus.FAILED
            events.append(
                ExecutionEvent(
                    task_id=plan.task_id,
                    step_id=step.id,
                    status=status,
                    detail=str(result.get("detail", "")),
                )
            )

            if status is TaskStatus.FAILED and step.on_fail != "continue":
                return TaskStatus.FAILED, events

        return TaskStatus.SUCCESS, events
