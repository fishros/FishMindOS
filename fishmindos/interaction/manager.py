"""
Core interaction orchestrator.

This module no longer owns terminal input/output. It accepts user text,
drives the brain, and emits structured events for channels to render.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fishmindos.config import resolve_config_path
from fishmindos.core.event_bus import global_event_bus
from fishmindos.world import WorldResolver


def sanitize_output(text: str) -> str:
    """Clean leaked reasoning / malformed tool text before sending to channels."""
    if not text:
        return text

    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"</think>", "", text)
    text = re.sub(r"\*\*回复\*\*[:\s]*", "", text)
    text = re.sub(r"执行了?\s*\w+(,\s*\w+)*", "", text)
    text = re.sub(r"^#+\s+.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^---+$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n\n\n+", "\n\n", text)
    text = re.sub(r"<tool_call.*?>.*?</tool_call>", "", text, flags=re.DOTALL)
    text = re.sub(r"</?tool_call>", "", text)
    text = re.sub(r"<arg_key>.*?</arg_key>", "", text, flags=re.DOTALL)
    text = re.sub(r"<arg_value>.*?</arg_value>", "", text, flags=re.DOTALL)
    text = re.sub(r"^\s*调用了\s+\w+.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*location\s*$", "", text, flags=re.MULTILINE)
    return text.strip()


InteractionListener = Callable[[Dict[str, Any]], None]


class InteractionManager:
    """Core interaction orchestrator shared by terminal and future remote channels."""

    def __init__(self, brain=None, config_path: str | Path | None = None):
        self.brain = brain
        self.conversation_history: List[Dict[str, Any]] = []
        self.session_context: Dict[str, Any] = {}
        self.config_path = resolve_config_path(config_path)
        self._async_mission_active = False
        self._listeners: List[InteractionListener] = []
        global_event_bus.subscribe("mission_completed", self._on_async_mission_done)
        global_event_bus.subscribe("mission_failed", self._on_async_mission_done)

    @property
    def is_async_mission_active(self) -> bool:
        return self._async_mission_active

    def set_brain(self, brain) -> None:
        self.brain = brain

    def add_listener(self, listener: InteractionListener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: InteractionListener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def emit(self, event_type: str, **payload: Any) -> Dict[str, Any]:
        event = {
            "type": event_type,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "payload": payload,
        }
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:
                continue
        return event

    def get_adapter(self):
        if self.brain and hasattr(self.brain, "adapter"):
            return self.brain.adapter
        return None

    def _on_async_mission_done(self, data=None) -> None:
        self._async_mission_active = False
        self.emit("async_mission_done", data=data)
        self.emit("prompt_ready")

    def _sync_world_to_brain(self, resolver: WorldResolver) -> None:
        if not self.brain:
            return

        session = self.brain.session_context
        session["world"] = resolver
        session["world_model"] = resolver
        session["world_enabled"] = True
        session["world_summary"] = resolver.describe()
        session["world_prompt"] = resolver.describe_for_prompt(limit=50)
        session["world_name"] = getattr(resolver.world, "name", "default")
        session["world_default_map"] = resolver.world.default_map_name or resolver.world.default_map_id
        session["world_known_locations"] = resolver.list_known_locations()
        session["world_adapter_fallback"] = resolver.adapter_fallback

    def build_world_profile_path(self, map_name: str) -> Path:
        safe_name = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", map_name).strip("_")
        if not safe_name:
            safe_name = "default_world"
        return Path.cwd() / "fishmindos" / "world" / "profiles" / f"{safe_name}.json"

    def resolve_world_path(self, world_path: str | Path) -> Path:
        resolved = Path(world_path)
        if not resolved.is_absolute():
            resolved = Path.cwd() / resolved
        return resolved

    def reload_world(self, world_path: Path, config) -> WorldResolver:
        soul = self.brain.session_context.get("soul") if self.brain else None
        resolver = WorldResolver.from_path(
            world_path,
            adapter=self.get_adapter(),
            soul=soul,
            auto_switch_map=config.world.auto_switch_map,
            prefer_current_map=config.world.prefer_current_map,
            adapter_fallback=config.world.adapter_fallback,
        )
        self._sync_world_to_brain(resolver)
        return resolver

    def cancel_current(self) -> None:
        if self.brain:
            self.brain.cancel()
            self.emit("info", message="已停止")

    def confirm_human(self, raw_input: str = "确认") -> None:
        global_event_bus.publish(
            "human_confirmed",
            {
                "source": "interaction",
                "input": raw_input,
                "time": datetime.now().isoformat(timespec="seconds"),
            },
        )
        self.emit("info", message="已发送人工确认事件（human_confirmed）")

    def handle_user_text(self, text: str) -> None:
        self.emit("thinking_started", message="思考中")

        all_responses: List[Dict[str, Any]] = []
        current_step = 0
        final_response: Optional[str] = None
        had_action = False
        had_error = False
        mission_pending_response = False
        thinking_stopped = False

        try:
            if not self.brain:
                self.emit("thinking_stopped")
                self.emit("error", message="大脑未初始化")
                return

            if not hasattr(self.brain, "think"):
                self.emit("thinking_stopped")
                self.emit("error", message="大脑没有 think 方法")
                return

            for resp in self.brain.think(text):
                if not isinstance(resp, dict):
                    resp_dict = {
                        "type": resp.type,
                        "content": resp.content,
                        "metadata": resp.metadata or {},
                    }
                else:
                    resp_dict = resp

                all_responses.append(resp_dict)
                response_type = resp_dict.get("type", "text")

                if not thinking_stopped:
                    self.emit("thinking_stopped")
                    thinking_stopped = True

                if response_type == "plan":
                    steps = resp_dict.get("metadata", {}).get("steps", [])
                    self.emit("plan", steps=steps)
                    self.emit("info", message="执行中...")

                elif response_type == "action":
                    current_step += 1
                    had_action = True
                    skill_name = resp_dict.get("metadata", {}).get("skill", "")
                    self.emit("action", skill_name=skill_name, step_num=current_step)

                elif response_type == "result":
                    metadata = resp_dict.get("metadata", {}) or {}
                    success = metadata.get("success", False)
                    message = resp_dict.get("content", "")
                    skill_name = metadata.get("skill", "")
                    result_data = metadata.get("data")
                    self.emit(
                        "result",
                        skill_name=skill_name,
                        success=success,
                        message=message,
                        data=result_data,
                    )
                    if not success:
                        had_error = True

                    if success and skill_name == "submit_mission" and isinstance(result_data, dict):
                        result_tasks = result_data.get("tasks")
                        if isinstance(result_tasks, list):
                            planned_tasks = None
                            for previous in reversed(all_responses):
                                if previous.get("type") != "plan":
                                    continue
                                steps = previous.get("metadata", {}).get("steps", [])
                                for step in steps:
                                    if step.get("skill") == "submit_mission":
                                        params = step.get("params", {})
                                        if isinstance(params, dict) and isinstance(params.get("tasks"), list):
                                            planned_tasks = params.get("tasks")
                                            break
                                if planned_tasks is not None:
                                    break
                            if planned_tasks != result_tasks:
                                self.emit("actual_mission_tasks", tasks=result_tasks)

                        mission_pending_response = bool(result_data.get("pending", True))
                        if mission_pending_response:
                            self._async_mission_active = True
                            final_response = "任务已提交，正在执行中，请等待导航/回调事件。"

                elif response_type == "text":
                    raw_text = resp_dict.get("content", "")
                    cleaned_text = sanitize_output(raw_text)
                    if not cleaned_text and str(raw_text).strip():
                        cleaned_text = str(raw_text).strip()
                    if not (
                        mission_pending_response
                        and cleaned_text == "本轮操作已执行完成。"
                    ):
                        final_response = cleaned_text

                elif response_type == "error":
                    self.emit("error", message=resp_dict.get("content", ""))
                    had_error = True

            if not thinking_stopped:
                self.emit("thinking_stopped")
                thinking_stopped = True

            if not all_responses:
                self.emit("error", message="未收到大脑输出。请重试，或简化指令后再试。")
                return

            if final_response and not had_error:
                self.emit("message", text=final_response)
            elif had_action and not had_error:
                self.emit("message", text="本轮操作已执行完成。")
            elif not had_error:
                self.emit("message", text="我刚才没有生成有效回复，请再试一次。")

            self.conversation_history.append(
                {
                    "input": text,
                    "responses": all_responses,
                    "time": datetime.now().isoformat(),
                }
            )

        except Exception as e:
            if not thinking_stopped:
                self.emit("thinking_stopped")
            self.emit("error", message=f"错误: {str(e)}")
        finally:
            self.emit("interaction_complete", async_mission_active=self._async_mission_active)


def create_interaction_manager(brain=None) -> InteractionManager:
    return InteractionManager(brain)
