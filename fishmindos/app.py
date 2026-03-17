from __future__ import annotations

from datetime import datetime

from fishmindos.agent_core import DialogueGenerator, IntentParser, MemoryStore, TaskPlanner
from fishmindos.execution_runtime import TaskExecutor
from fishmindos.interaction import TextAdapter
from fishmindos.models import TaskStatus
from fishmindos.skill_runtime import SkillOS, SkillRegistry, register_builtin_skills
from fishmindos.world_model import WorldModel


class FishMindOSApp:
    """FishMindOS 初版可运行框架。"""

    def __init__(self, skills_dir: str = "skill_store") -> None:
        self.adapter = TextAdapter()
        self.intent_parser = IntentParser()
        self.dialogue = DialogueGenerator()
        self.planner = TaskPlanner()
        self.memory = MemoryStore()

        self.world_model = WorldModel()
        self.world_model.add_location("行政", "office")
        self.world_model.add_location("厕所", "toilet")

        self.registry = SkillRegistry()
        register_builtin_skills(self.registry)

        self.skill_os = SkillOS(skills_dir=skills_dir)
        self.skill_os.load_plugins(self.registry)

        self.executor = TaskExecutor(self.registry)

    def generate_reusable_skill(self, name: str, response_text: str, description: str = "") -> str:
        """由 OS 生成并保存脚本技能，下次启动自动复用。"""
        path = self.skill_os.generate_skill_script(
            name=name,
            response_text=response_text,
            description=description,
        )
        self.skill_os.load_plugins(self.registry)
        return str(path)

    def run_text(self, text: str, robot_id: str = "dog-01") -> dict:
        event = self.adapter.parse(text=text, robot_id=robot_id)
        intent = self.intent_parser.parse(event)

        task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        plan = self.planner.make_plan(
            intent=intent,
            task_id=task_id,
            pickup_text=self.dialogue.pickup_script(intent),
            dropoff_text=self.dialogue.dropoff_script(intent),
        )

        status, execution_events = self.executor.execute(plan, context={"world_model": self.world_model})
        for item in execution_events:
            self.memory.add({"task_id": item.task_id, "step_id": item.step_id, "detail": item.detail})

        return {
            "task_id": task_id,
            "intent": intent,
            "plan": plan,
            "status": TaskStatus(status).value,
            "events": execution_events,
            "skills": self.registry.names(),
        }
