from __future__ import annotations

import re
from datetime import datetime

from fishmindos.agent_core import AgentCoreRuntime, MemoryStore
from fishmindos.execution_runtime import TaskExecutor
from fishmindos.interaction import InteractionLayer
from fishmindos.mcp import LocalMCPClient, LocalMCPServer, PromptResourceCatalog
from fishmindos.models import InteractionEvent, TaskPlan, TaskSequence, TaskStatus
from fishmindos.skill_runtime import SkillOS, SkillRegistry, register_nav_api_skills
from fishmindos.world_model import WorldModel


class FishMindOSApp:
    """Main application entry for text-driven robot control."""

    def __init__(
        self,
        skills_dir: str = "skill_store",
        registry: SkillRegistry | None = None,
        agent_core: AgentCoreRuntime | None = None,
    ) -> None:
        self.interaction = InteractionLayer()
        self.memory = MemoryStore()
        self.world_model = WorldModel()

        self.registry = registry or SkillRegistry()
        if registry is None:
            register_nav_api_skills(self.registry)

        self.skill_os = SkillOS(skills_dir=skills_dir)
        self.skill_os.load_plugins(self.registry)

        self.mcp_server = LocalMCPServer(
            registry=self.registry,
            resources=PromptResourceCatalog.from_repo_root(),
        )
        self.mcp_client = LocalMCPClient(self.mcp_server)

        self.executor = TaskExecutor(self.mcp_client)
        self.agent_core = agent_core or AgentCoreRuntime(mcp_client=self.mcp_client)
        self.session_context: dict[str, object] = {
            "last_task": None,
            "last_task_list": [],
            "last_map": None,
            "last_map_list": [],
            "last_waypoint": None,
            "last_waypoint_list": [],
        }

    def generate_reusable_skill(self, name: str, response_text: str, description: str = "") -> str:
        path = self.skill_os.generate_skill_script(
            name=name,
            response_text=response_text,
            description=description,
        )
        self.skill_os.load_plugins(self.registry)
        return str(path)

    @staticmethod
    def create_task_id() -> str:
        return f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    @staticmethod
    def classify_transports(sequence: TaskSequence) -> list[str]:
        transports: set[str] = set()
        for step in sequence.steps:
            if step.skill == "robot_motion":
                transports.add("rosbridge")
            elif step.skill == "robot_light" and step.args.get("action") == "set":
                transports.add("rosbridge")
            elif step.skill in {"robot_navigation_assistant", "robot_task_assistant"}:
                transports.add("http")
            elif step.skill == "robot_task_chain":
                transports.add("local")
            elif step.skill == "robot_status" and step.args.get("action") in {"status", "charging_status", "battery_soc"}:
                transports.update({"http", "rosbridge"} if step.args.get("action") == "status" else {"rosbridge"})
            elif step.skill.startswith("robot_"):
                transports.add("http")
            else:
                transports.add("local")
        return sorted(transports)

    def _build_interaction_context(self, original_text: str, extra_context: dict | None = None) -> dict[str, object]:
        merged = dict(extra_context or {})
        merged.setdefault("original_text", original_text)
        merged.setdefault("recent_events", self.memory.recent(8))
        for key in (
            "last_task",
            "last_task_list",
            "last_map",
            "last_map_list",
            "last_waypoint",
            "last_waypoint_list",
        ):
            if self.session_context.get(key) is not None:
                merged.setdefault(key, self.session_context.get(key))
        return merged

    def _build_execution_context(self, sequence: TaskSequence) -> dict[str, object]:
        context = {
            "world_model": self.world_model,
            "user_text": sequence.goal,
            "task_goal": sequence.goal,
            "recent_events": self.memory.recent(8),
        }
        for key in (
            "last_task",
            "last_task_list",
            "last_map",
            "last_map_list",
            "last_waypoint",
            "last_waypoint_list",
        ):
            if self.session_context.get(key) is not None:
                context[key] = self.session_context.get(key)
        return context

    def _resolve_contextual_text(self, text: str) -> str:
        last_task = self.session_context.get("last_task")
        if not isinstance(last_task, dict):
            return text

        compact = re.sub(r"\s+", "", text)
        if "任务" in compact:
            return text

        pronouns = ("它", "这个任务", "刚才那个任务", "上一个任务", "该任务")
        if not any(token in compact for token in pronouns):
            return text

        task_name = str(last_task.get("name") or last_task.get("id") or "").strip()
        if not task_name:
            return text

        if any(token in compact for token in ("描述", "详情", "内容", "信息")):
            return f"告诉我任务{task_name}的描述"
        if "名字" in compact:
            return f"告诉我任务{task_name}的名字"
        return f"告诉我任务{task_name}的详情"

    @staticmethod
    def _extract_task_list(data: object) -> list[dict]:
        if isinstance(data, dict):
            tasks = data.get("tasks")
            if isinstance(tasks, list):
                return [item for item in tasks if isinstance(item, dict)]
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    @staticmethod
    def _extract_map_list(data: object) -> list[dict]:
        if isinstance(data, dict):
            maps = data.get("maps")
            if isinstance(maps, list):
                return [item for item in maps if isinstance(item, dict)]
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    @staticmethod
    def _extract_waypoint_list(data: object) -> list[dict]:
        if isinstance(data, dict):
            waypoints = data.get("waypoints")
            if isinstance(waypoints, list):
                return [item for item in waypoints if isinstance(item, dict)]
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    def _update_session_context(self, sequence: TaskSequence, plan: TaskPlan, execution_events: list) -> None:
        for step, event in zip(plan.steps, execution_events):
            if getattr(event, "status", None) != TaskStatus.SUCCESS:
                continue
            action = str(step.args.get("action", "")).strip()
            data = getattr(event, "data", None)

            if step.skill in {"robot_tasks", "robot_task_assistant"}:
                if action in {"list", "list_tasks"}:
                    tasks = self._extract_task_list(data)
                    if tasks:
                        self.session_context["last_task_list"] = tasks
                elif action in {"get", "describe_task", "create_nav_task"} and isinstance(data, dict):
                    self.session_context["last_task"] = data

            if step.skill in {"robot_maps", "robot_navigation_assistant"}:
                if action in {"list", "list_maps"}:
                    maps = self._extract_map_list(data)
                    if maps:
                        self.session_context["last_map_list"] = maps

            if step.skill in {"robot_waypoints", "robot_navigation", "robot_navigation_assistant", "robot_dock"} and isinstance(data, dict):
                if data.get("map_id") not in (None, "") or data.get("map_name") not in (None, ""):
                    self.session_context["last_map"] = {
                        "id": data.get("map_id"),
                        "name": data.get("map_name"),
                    }
                if data.get("waypoint_id") not in (None, "") or data.get("waypoint_name") not in (None, ""):
                    self.session_context["last_waypoint"] = {
                        "id": data.get("waypoint_id"),
                        "name": data.get("waypoint_name"),
                        "map_id": data.get("map_id"),
                        "map_name": data.get("map_name"),
                    }

            if step.skill == "robot_waypoints" and action == "list":
                waypoints = self._extract_waypoint_list(data)
                if waypoints:
                    self.session_context["last_waypoint_list"] = waypoints

    def plan_event(self, event: InteractionEvent, task_id: str | None = None, on_tool_call: object = None) -> dict[str, object]:
        resolved_task_id = task_id or self.create_task_id()
        sequence = self.agent_core.handle_event(event, on_tool_call=on_tool_call)
        plan = self.executor.build_plan(task_id=resolved_task_id, sequence=sequence)
        return {
            "task_id": resolved_task_id,
            "sequence": sequence,
            "plan": plan,
            "planner_source": sequence.planner_source,
            "transports": self.classify_transports(sequence),
            "skills": self.registry.names(),
            "resources": self.mcp_client.list_resources(),
        }

    def execute_plan(self, plan: TaskPlan, sequence: TaskSequence) -> dict[str, object]:
        status, execution_events = self.executor.execute(
            plan,
            context=self._build_execution_context(sequence),
        )
        for item in execution_events:
            self.memory.add(
                {
                    "task_id": item.task_id,
                    "step_id": item.step_id,
                    "skill": item.skill,
                    "detail": item.detail,
                    "data": item.data,
                    "user_text": sequence.goal,
                }
            )
        self._update_session_context(sequence, plan, execution_events)

        return {
            "task_id": plan.task_id,
            "sequence": sequence,
            "plan": plan,
            "status": TaskStatus(status).value,
            "events": execution_events,
            "planner_source": sequence.planner_source,
            "transports": self.classify_transports(sequence),
            "skills": self.registry.names(),
            "resources": self.mcp_client.list_resources(),
        }

    def run_event(self, event: InteractionEvent) -> dict[str, object]:
        prepared = self.plan_event(event)
        return self.execute_plan(prepared["plan"], prepared["sequence"])

    def run_text(
        self,
        text: str,
        robot_id: str = "dog-01",
        context: dict | None = None,
    ) -> dict[str, object]:
        resolved_text = self._resolve_contextual_text(text)
        merged_context = self._build_interaction_context(text, context)
        if resolved_text != text:
            merged_context["resolved_from_context"] = True
            merged_context["resolved_text"] = resolved_text
        event = self.interaction.receive_text(text=resolved_text, robot_id=robot_id, context=merged_context)
        return self.run_event(event)
