from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass(slots=True)
class InteractionEvent:
    text: str
    source: str
    robot_id: str
    context: dict[str, Any] = field(default_factory=dict)
    event_id: str = ""


@dataclass(slots=True)
class PlannedSkillCall:
    skill: str
    args: dict[str, Any]
    on_fail: str = "abort"


@dataclass(slots=True)
class TaskSequence:
    goal: str
    steps: list[PlannedSkillCall]
    planner_source: str = "unknown"
    reply_text: str | None = None


@dataclass(slots=True)
class PlanStep:
    id: str
    skill: str
    args: dict[str, Any]
    on_fail: str = "retry"


@dataclass(slots=True)
class TaskPlan:
    task_id: str
    goal: str
    steps: list[PlanStep]
    reply_text: str | None = None


@dataclass(slots=True)
class ExecutionEvent:
    task_id: str
    step_id: str
    skill: str
    status: TaskStatus
    detail: str
    data: Any = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
