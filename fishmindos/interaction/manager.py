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
from fishmindos.interaction import events as ev
from fishmindos.interaction.session_manager import InteractionSession, SessionManager
from fishmindos.world import WorldResolver


GENERIC_COMPLETION_TEXT = "本轮操作已执行完成。"


def sanitize_output(text: str) -> str:
    """Clean leaked reasoning / malformed tool text before sending to channels."""
    if not text:
        return text

    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"</think>", "", text)
    text = re.sub(r"\*\*回复\*\*[:\s]*", "", text)
    # Only strip standalone tool-summary lines, not normal user-facing sentences
    # such as “任务已提交，正在执行中...” or “本轮操作已执行完成。”
    text = re.sub(r"^\s*执行了?\s*\w+(,\s*\w+)*\s*$", "", text, flags=re.MULTILINE)
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
        self.session_context: Dict[str, Any] = {}
        self.config_path = resolve_config_path(config_path)
        base_context = dict(getattr(brain, "session_context", {}) or {})
        self.sessions = SessionManager(session_template=base_context)
        self._active_session_id: Optional[str] = None
        self._async_session_id: Optional[str] = None
        self._listeners: List[InteractionListener] = []
        self._world_admin = None
        global_event_bus.subscribe("mission_completed", self._on_async_mission_done)
        global_event_bus.subscribe("mission_failed", self._on_async_mission_done)
        global_event_bus.subscribe("human_confirm_required", self._on_human_confirm_required)
        global_event_bus.subscribe("mission_progress", self._on_mission_progress)

        if brain is not None:
            default_session = self.sessions.get_or_create(
                "terminal-default",
                client_type="terminal",
                initial_context=base_context,
            )
            default_session.session_context = getattr(brain, "session_context", default_session.session_context)
            self._activate_session("terminal-default")

    def set_brain(self, brain) -> None:
        self.brain = brain
        if self._active_session_id:
            session = self.sessions.get_or_create(self._active_session_id)
            if getattr(brain, "session_context", None) is not session.session_context:
                brain.session_context = session.session_context
                self.session_context = session.session_context

    def add_listener(self, listener: InteractionListener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: InteractionListener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def emit(self, event_type: str, session_id: Optional[str] = None, **payload: Any) -> Dict[str, Any]:
        event = {
            "type": event_type,
            "session_id": session_id,
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

    def get_session(self, session_id: str, client_type: str = "unknown") -> InteractionSession:
        session = self.sessions.get_or_create(session_id, client_type=client_type)
        session.session_context["session_id"] = session_id
        return session

    def get_session_context(self, session_id: str) -> Dict[str, Any]:
        return self.get_session(session_id).session_context

    def get_world_admin(self):
        if self._world_admin is None:
            from fishmindos.interaction.world_admin import WorldAdminService

            self._world_admin = WorldAdminService(self)
        return self._world_admin

    def _normalize_client_type(self, value: Any) -> str:
        normalized = str(value or "").strip().lower()
        return normalized if normalized in {"android", "terminal"} else ""

    def _session_origin_client(self, session_id: Optional[str], fallback: Optional[str] = None) -> str:
        normalized_fallback = self._normalize_client_type(fallback)
        if normalized_fallback:
            return normalized_fallback
        if not session_id:
            return ""
        session = self.sessions.get(session_id)
        if session is None:
            return ""
        ctx = session.session_context or {}
        for key in ("async_origin_client_type", "interaction_origin_client_type", "last_user_client_type"):
            normalized = self._normalize_client_type(ctx.get(key))
            if normalized:
                return normalized
        return self._normalize_client_type(getattr(session, "client_type", ""))

    def _sync_live_state_to_session(self, session: Optional[InteractionSession]) -> None:
        if session is None:
            return
        adapter = self.get_adapter()
        if adapter is None or not hasattr(adapter, "get_callback_state"):
            return
        try:
            callback_state = adapter.get_callback_state()
        except Exception:
            return
        if not isinstance(callback_state, dict):
            return

        ctx = session.session_context
        ctx["callback_event_count"] = callback_state.get("event_count", 0)
        ctx["callback_last_event"] = callback_state.get("last_event")
        ctx["callback_last_event_at"] = callback_state.get("last_event_at")

        if isinstance(callback_state.get("current_pose"), dict):
            ctx["callback_current_pose"] = callback_state.get("current_pose")

        if isinstance(callback_state.get("target_pose"), dict):
            ctx["callback_target_pose"] = callback_state.get("target_pose")

        current_map_id = callback_state.get("current_map_id")
        if current_map_id is not None:
            map_name = None
            if hasattr(adapter, "resolve_current_map") and getattr(adapter, "_connected", False):
                try:
                    map_info = adapter.resolve_current_map()
                except Exception:
                    map_info = None
                if map_info:
                    current_map_id = getattr(map_info, "id", current_map_id)
                    map_name = getattr(map_info, "name", None)
            ctx["current_map"] = {"id": current_map_id, "name": map_name or str(current_map_id)}

        arrived_waypoint_id = callback_state.get("arrived_waypoint_id")
        target_waypoint_name = callback_state.get("target_waypoint_name")
        if arrived_waypoint_id:
            ctx["pending_arrival"] = None
            ctx["last_waypoint"] = {"waypoint_id": arrived_waypoint_id, "name": target_waypoint_name}
            if target_waypoint_name:
                ctx["current_location"] = target_waypoint_name

        if callback_state.get("dock_complete_at"):
            ctx["current_location"] = "回充点"

    def get_session_snapshot(self, session_id: str) -> Optional[Dict[str, Any]]:
        session = self.sessions.get(session_id)
        if session is None:
            return None
        self._sync_live_state_to_session(session)
        return self.sessions.get_snapshot(session_id)

    def _emit_session_state(self, session_id: Optional[str]) -> None:
        if not session_id:
            return
        snapshot = self.get_session_snapshot(session_id)
        if snapshot is None:
            return
        payload = dict(snapshot)
        payload.pop("session_id", None)
        self.emit(ev.SESSION_STATE, session_id=session_id, **payload)

    def is_async_mission_active(self, session_id: Optional[str] = None) -> bool:
        if session_id:
            session = self.sessions.get(session_id)
            return bool(session.async_mission_active) if session else False
        if self._async_session_id:
            session = self.sessions.get(self._async_session_id)
            return bool(session.async_mission_active) if session else False
        return False

    def has_pending_session_work(self, session_id: str) -> bool:
        session = self.sessions.get(session_id)
        if session is None:
            return False
        return bool(
            session.async_mission_active
            or session.waiting_for_human
            or session.current_mission_id
        )

    def is_interaction_in_progress(self, session_id: str) -> bool:
        session = self.sessions.get(session_id)
        if session is None:
            return False
        return bool(session.session_context.get("interaction_in_progress"))

    def is_world_mutation_blocked(self, session_id: str) -> bool:
        return self.has_pending_session_work(session_id) or self.is_interaction_in_progress(session_id)

    def _activate_session(self, session_id: str, client_type: str = "unknown") -> InteractionSession:
        session = self.sessions.get_or_create(session_id, client_type=client_type)
        session.touch()
        session.session_context["session_id"] = session_id
        self._active_session_id = session_id
        self.session_context = session.session_context
        if self.brain is not None and getattr(self.brain, "session_context", None) is not session.session_context:
            self.brain.session_context = session.session_context
        return session

    def _on_async_mission_done(self, data=None) -> None:
        session_id = self._async_session_id or self._active_session_id or "terminal-default"
        session = self.sessions.get_or_create(session_id, client_type="terminal")
        source_client = self._session_origin_client(session_id)
        session.async_mission_active = False
        session.current_mission_id = None
        session.waiting_for_human = False
        session.session_context["waiting_for_human"] = False
        session.session_context["human_prompt_text"] = None
        session.session_context["async_origin_client_type"] = None
        self._async_session_id = None
        self.emit("async_mission_done", session_id=session_id, data=data, source_client=source_client)
        self._emit_session_state(session_id)
        self.emit("prompt_ready", session_id=session_id)

    def _on_human_confirm_required(self, data=None) -> None:
        payload = data if isinstance(data, dict) else {}
        session_id = str(
            payload.get("session_id")
            or self._async_session_id
            or self._active_session_id
            or "terminal-default"
        )
        prompt_text = str(
            payload.get("message")
            or payload.get("text")
            or "请确认后我再继续执行。"
        ).strip() or "请确认后我再继续执行。"

        session = self.sessions.get_or_create(session_id, client_type="terminal")
        session.waiting_for_human = True
        session.session_context["waiting_for_human"] = True
        session.session_context["human_prompt_text"] = prompt_text
        self.emit(
            "human_confirm_required",
            session_id=session_id,
            message=prompt_text,
            source_client=self._session_origin_client(session_id),
        )
        self._emit_session_state(session_id)

    def _on_mission_progress(self, data=None) -> None:
        payload = dict(data) if isinstance(data, dict) else {}
        session_id = str(
            payload.pop("session_id", None)
            or self._async_session_id
            or self._active_session_id
            or "terminal-default"
        )
        self.emit(
            "mission_progress",
            session_id=session_id,
            source_client=self._session_origin_client(session_id),
            **payload,
        )
        self._emit_session_state(session_id)

    def _sync_world_to_session(self, resolver: WorldResolver, session_id: Optional[str] = None) -> None:
        if not self.brain:
            return

        target_session = self._activate_session(session_id or self._active_session_id or "terminal-default")
        session_context = target_session.session_context
        session_context["world"] = resolver
        session_context["world_model"] = resolver
        session_context["world_enabled"] = True
        session_context["world_summary"] = resolver.describe()
        session_context["world_prompt"] = resolver.describe_for_prompt(limit=50)
        session_context["world_name"] = getattr(resolver.world, "name", "default")
        session_context["world_default_map"] = resolver.world.default_map_name or resolver.world.default_map_id
        session_context["world_known_locations"] = resolver.list_known_locations()
        session_context["world_adapter_fallback"] = resolver.adapter_fallback

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

    def reload_world(self, world_path: Path, config, session_id: Optional[str] = None) -> WorldResolver:
        target_session = self._activate_session(session_id or self._active_session_id or "terminal-default")
        soul = target_session.session_context.get("soul") if self.brain else None
        resolver = WorldResolver.from_path(
            world_path,
            adapter=self.get_adapter(),
            soul=soul,
            auto_switch_map=config.world.auto_switch_map,
            prefer_current_map=config.world.prefer_current_map,
            adapter_fallback=config.world.adapter_fallback,
        )
        self._sync_world_to_session(resolver, target_session.session_id)
        return resolver

    def cancel_current(self, session_id: str = "terminal-default") -> None:
        self._activate_session(session_id, client_type="terminal")
        if self.brain:
            self.brain.cancel()
            self.emit("info", session_id=session_id, message="已停止")

    def confirm_human(self, raw_input: str = "确认", session_id: str = "terminal-default") -> None:
        session = self._activate_session(session_id, client_type="terminal")
        session.waiting_for_human = False
        session.session_context["waiting_for_human"] = False
        session.session_context["human_prompt_text"] = None
        global_event_bus.publish(
            "human_confirmed",
            {
                "source": "interaction",
                "input": raw_input,
                "session_id": session_id,
                "time": datetime.now().isoformat(timespec="seconds"),
            },
        )
        self.emit("info", session_id=session_id, message="已发送人工确认事件（human_confirmed）")

    def handle_user_text(self, text: str, session_id: str = "terminal-default", client_type: str = "terminal") -> None:
        session = self._activate_session(session_id, client_type=client_type)
        session.waiting_for_human = False
        session.session_context["waiting_for_human"] = False
        session.session_context["human_prompt_text"] = None
        self.emit("thinking_started", session_id=session_id, message="思考中")

        all_responses: List[Dict[str, Any]] = []
        current_step = 0
        final_response: Optional[str] = None
        had_action = False
        had_error = False
        mission_pending_response = False
        thinking_stopped = False

        try:
            if not self.brain:
                self.emit("thinking_stopped", session_id=session_id)
                self.emit("error", session_id=session_id, message="大脑未初始化")
                return

            if not hasattr(self.brain, "think"):
                self.emit("thinking_stopped", session_id=session_id)
                self.emit("error", session_id=session_id, message="大脑没有 think 方法")
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
                    self.emit("thinking_stopped", session_id=session_id)
                    thinking_stopped = True

                if response_type == "plan":
                    steps = resp_dict.get("metadata", {}).get("steps", [])
                    self.emit("plan", session_id=session_id, steps=steps)
                    self.emit("info", session_id=session_id, message="执行中...")

                elif response_type == "action":
                    current_step += 1
                    had_action = True
                    skill_name = resp_dict.get("metadata", {}).get("skill", "")
                    self.emit("action", session_id=session_id, skill_name=skill_name, step_num=current_step)

                elif response_type == "result":
                    metadata = resp_dict.get("metadata", {}) or {}
                    success = metadata.get("success", False)
                    message = resp_dict.get("content", "")
                    skill_name = metadata.get("skill", "")
                    result_data = metadata.get("data")
                    self.emit(
                        "result",
                        session_id=session_id,
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
                                self.emit("actual_mission_tasks", session_id=session_id, tasks=result_tasks)

                        mission_pending_response = bool(result_data.get("pending", True))
                        if mission_pending_response:
                            session.async_mission_active = True
                            session.current_mission_id = datetime.now().isoformat(timespec="seconds")
                            self._async_session_id = session_id
                            final_response = "任务已提交，正在执行中，请等待导航/回调事件。"

                elif response_type == "preview":
                    # 任务开始前的预告，立即显示，不影响最终回复
                    preview_text = str(resp_dict.get("content", "")).strip()
                    if preview_text:
                        self.emit("message", session_id=session_id, text=preview_text)

                elif response_type == "text":
                    raw_text = resp_dict.get("content", "")
                    cleaned_text = sanitize_output(raw_text)
                    if not cleaned_text and str(raw_text).strip():
                        cleaned_text = str(raw_text).strip()
                    is_generic_completion = cleaned_text == GENERIC_COMPLETION_TEXT
                    if is_generic_completion and final_response and final_response != GENERIC_COMPLETION_TEXT:
                        continue
                    if not (mission_pending_response and is_generic_completion):
                        final_response = cleaned_text

                elif response_type == "error":
                    self.emit("error", session_id=session_id, message=resp_dict.get("content", ""))
                    had_error = True

            if not thinking_stopped:
                self.emit("thinking_stopped", session_id=session_id)
                thinking_stopped = True

            if not all_responses:
                self.emit("error", session_id=session_id, message="未收到大脑输出。请重试，或简化指令后再试。")
                return

            if final_response and not had_error:
                self.emit("message", session_id=session_id, text=final_response)
            elif had_action and not had_error:
                self.emit("message", session_id=session_id, text=GENERIC_COMPLETION_TEXT)
            elif not had_error:
                self.emit("message", session_id=session_id, text="我刚才没有生成有效回复，请再试一次。")

            session.conversation_history.append(
                {
                    "input": text,
                    "responses": all_responses,
                    "time": datetime.now().isoformat(),
                }
            )
            session.touch()

        except Exception as e:
            if not thinking_stopped:
                self.emit("thinking_stopped", session_id=session_id)
            self.emit("error", session_id=session_id, message=f"错误: {str(e)}")
        finally:
            self.emit("interaction_complete", session_id=session_id, async_mission_active=session.async_mission_active)


    def cancel_current(self, session_id: str = "terminal-default", client_type: str = "terminal") -> None:
        self._activate_session(session_id, client_type=client_type)
        if self.brain:
            self.brain.cancel()
            self.emit(
                "info",
                session_id=session_id,
                message="已停止",
                source_client=self._normalize_client_type(client_type),
            )
        self._emit_session_state(session_id)

    def confirm_human(
        self,
        raw_input: str = "确认",
        session_id: str = "terminal-default",
        client_type: str = "terminal",
    ) -> None:
        session = self._activate_session(session_id, client_type=client_type)
        session.waiting_for_human = False
        session.session_context["waiting_for_human"] = False
        session.session_context["human_prompt_text"] = None
        session.session_context["last_user_client_type"] = self._normalize_client_type(client_type)
        global_event_bus.publish(
            "human_confirmed",
            {
                "source": "interaction",
                "input": raw_input,
                "session_id": session_id,
                "time": datetime.now().isoformat(timespec="seconds"),
            },
        )
        self.emit(
            "info",
            session_id=session_id,
            message="已发送人工确认事件（human_confirmed）",
            source_client=self._normalize_client_type(client_type),
        )
        self._emit_session_state(session_id)

    def handle_user_text(self, text: str, session_id: str = "terminal-default", client_type: str = "terminal") -> None:
        session = self._activate_session(session_id, client_type=client_type)
        origin_client = self._normalize_client_type(client_type)
        session.session_context["last_user_client_type"] = origin_client
        session.session_context["interaction_origin_client_type"] = origin_client
        session.session_context["interaction_in_progress"] = True
        session.waiting_for_human = False
        session.session_context["waiting_for_human"] = False
        session.session_context["human_prompt_text"] = None
        self.emit(ev.USER_INPUT, session_id=session_id, text=text, source_client=origin_client)
        self.emit("thinking_started", session_id=session_id, message="思考中", source_client=origin_client)

        all_responses: List[Dict[str, Any]] = []
        current_step = 0
        final_response: Optional[str] = None
        had_action = False
        had_error = False
        mission_pending_response = False
        thinking_stopped = False

        try:
            if not self.brain:
                self.emit("thinking_stopped", session_id=session_id, source_client=origin_client)
                self.emit("error", session_id=session_id, message="大脑未初始化", source_client=origin_client)
                return

            if not hasattr(self.brain, "think"):
                self.emit("thinking_stopped", session_id=session_id, source_client=origin_client)
                self.emit("error", session_id=session_id, message="大脑没有 think 方法", source_client=origin_client)
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
                    self.emit("thinking_stopped", session_id=session_id, source_client=origin_client)
                    thinking_stopped = True

                if response_type == "plan":
                    steps = resp_dict.get("metadata", {}).get("steps", [])
                    self.emit("plan", session_id=session_id, steps=steps, source_client=origin_client)
                    self.emit("info", session_id=session_id, message="执行中...", source_client=origin_client)

                elif response_type == "action":
                    current_step += 1
                    had_action = True
                    skill_name = resp_dict.get("metadata", {}).get("skill", "")
                    self.emit(
                        "action",
                        session_id=session_id,
                        skill_name=skill_name,
                        step_num=current_step,
                        source_client=origin_client,
                    )

                elif response_type == "result":
                    metadata = resp_dict.get("metadata", {}) or {}
                    success = metadata.get("success", False)
                    message = resp_dict.get("content", "")
                    skill_name = metadata.get("skill", "")
                    result_data = metadata.get("data")
                    self.emit(
                        "result",
                        session_id=session_id,
                        skill_name=skill_name,
                        success=success,
                        message=message,
                        data=result_data,
                        source_client=origin_client,
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
                                self.emit(
                                    "actual_mission_tasks",
                                    session_id=session_id,
                                    tasks=result_tasks,
                                    source_client=origin_client,
                                )

                        mission_pending_response = bool(result_data.get("pending", True))
                        if mission_pending_response:
                            session.async_mission_active = True
                            session.current_mission_id = datetime.now().isoformat(timespec="seconds")
                            session.session_context["async_origin_client_type"] = origin_client
                            self._async_session_id = session_id
                            final_response = "任务已提交，正在执行中，请等待导航/回调事件。"

                elif response_type == "preview":
                    # 任务开始前的预告，立即显示，不影响最终回复
                    preview_text = str(resp_dict.get("content", "")).strip()
                    if preview_text:
                        self.emit("message", session_id=session_id, text=preview_text, source_client=origin_client)

                elif response_type == "text":
                    raw_text = resp_dict.get("content", "")
                    cleaned_text = sanitize_output(raw_text)
                    if not cleaned_text and str(raw_text).strip():
                        cleaned_text = str(raw_text).strip()
                    is_generic_completion = cleaned_text == GENERIC_COMPLETION_TEXT
                    if is_generic_completion and final_response and final_response != GENERIC_COMPLETION_TEXT:
                        continue
                    if not (mission_pending_response and is_generic_completion):
                        final_response = cleaned_text

                elif response_type == "error":
                    self.emit(
                        "error",
                        session_id=session_id,
                        message=resp_dict.get("content", ""),
                        source_client=origin_client,
                    )
                    had_error = True

            if not thinking_stopped:
                self.emit("thinking_stopped", session_id=session_id, source_client=origin_client)
                thinking_stopped = True

            if not all_responses:
                self.emit(
                    "error",
                    session_id=session_id,
                    message="未收到大脑输出。请重试，或简化指令后再试。",
                    source_client=origin_client,
                )
                return

            if final_response and not had_error:
                self.emit("message", session_id=session_id, text=final_response, source_client=origin_client)
            elif had_action and not had_error:
                self.emit(
                    "message",
                    session_id=session_id,
                    text=GENERIC_COMPLETION_TEXT,
                    source_client=origin_client,
                )
            elif not had_error:
                self.emit(
                    "message",
                    session_id=session_id,
                    text="我刚才没有生成有效回复，请再试一次。",
                    source_client=origin_client,
                )

            session.conversation_history.append(
                {
                    "input": text,
                    "responses": all_responses,
                    "time": datetime.now().isoformat(),
                }
            )
            session.touch()
            self._emit_session_state(session_id)

        except Exception as e:
            if not thinking_stopped:
                self.emit("thinking_stopped", session_id=session_id, source_client=origin_client)
            self.emit(
                "error",
                session_id=session_id,
                message=f"错误: {str(e)}",
                source_client=origin_client,
            )
        finally:
            session.session_context["interaction_in_progress"] = False
            self.emit(
                "interaction_complete",
                session_id=session_id,
                async_mission_active=session.async_mission_active,
                source_client=origin_client,
            )

def create_interaction_manager(brain=None) -> InteractionManager:
    return InteractionManager(brain)
