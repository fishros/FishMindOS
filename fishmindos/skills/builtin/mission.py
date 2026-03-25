"""Mission submission skill."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from fishmindos.brain.mission_manager import MissionManager
from fishmindos.config import get_config
from fishmindos.core.event_bus import global_event_bus
from fishmindos.core.models import SkillContext, SkillResult
from fishmindos.skills.base import Skill


class SubmitMissionSkill(Skill):
    """Submit a structured mission and execute it with the deterministic executor."""

    name = "submit_mission"
    description = (
        "Convert user intent into a JSON mission task list and execute once. "
        "For move/light/speak/dock requests, call this tool exactly once."
    )
    category = "mission"

    parameters = {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "description": "Mission task list.",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["goto", "dock", "light", "speak", "wait_confirm", "query", "stop_nav"],
                            "description": "Action type.",
                        },
                        "target": {"type": "string", "description": "Target for goto."},
                        "color": {"type": "string", "description": "Light color for light action."},
                        "text": {"type": "string", "description": "Speech text for speak action."},
                        "timeout_sec": {"type": "integer", "description": "Optional timeout seconds."},
                    },
                    "required": ["action"],
                },
            }
        },
        "required": ["tasks"],
    }

    def __init__(self):
        super().__init__()
        self._mission_manager: Optional[MissionManager] = None
        self._mission_manager_adapter_id: Optional[int] = None

    def _normalize(self, text: str) -> str:
        return re.sub(r"\s+", "", str(text or "")).lower()

    def _coerce_int(self, value: Any) -> Any:
        try:
            if value is None or value == "":
                return None
            return int(value)
        except (TypeError, ValueError):
            return value

    def _is_dock_target(self, target: str) -> bool:
        normalized = self._normalize(target)
        return any(keyword in normalized for keyword in ("回充", "充电", "回桩", "dock"))

    def _has_explicit_wait_confirm_intent(self, user_text: str) -> bool:
        text = str(user_text or "").strip().lower()
        if not text:
            return False
        keywords = [
            "wait_confirm",
            "确认后",
            "等我",
            "等待",
            "等一下",
            "等会",
            "确认",
            "收到后",
            "完成后再",
            "再继续",
            "再出发",
            "放好后",
            "放完后",
            "拿走后",
        ]
        return any(k in text for k in keywords)

    def _extract_handover_item(self, user_text: str) -> Optional[str]:
        text = str(user_text or "").strip()
        normalized = re.sub(r"\s+", "", text)
        if not normalized:
            return None

        keywords = [
            "纸巾", "快递", "包裹", "外卖", "奶茶", "咖啡", "饮料", "文件",
            "钥匙", "充电器", "药", "包", "纸", "水", "饭", "物品", "东西",
        ]
        for keyword in keywords:
            if keyword in normalized:
                return keyword

        match = re.search(
            r"(?:拿|取|带|领|买|送)([^，。,.!?？！]{1,12}?)(?:然后|再|回|去|到|给|送|拿|取|充电|$)",
            normalized,
        )
        if match:
            candidate = match.group(1).strip("的了给帮我你他她它")
            if candidate:
                return candidate
        return None

    def _has_handover_intent(self, user_text: str) -> bool:
        normalized = self._normalize(user_text)
        if not normalized:
            return False
        if self._extract_handover_item(user_text) is None:
            return False
        verbs = ("拿", "取", "带", "领", "买", "送", "交")
        return any(verb in normalized for verb in verbs)

    def _speech_implies_human_handover(self, text: Any) -> bool:
        raw = str(text or "").strip().lower()
        if not raw:
            return False
        hints = [
            "请帮我",
            "请把",
            "放到",
            "放在",
            "放进",
            "拿走",
            "交给",
            "确认",
            "完成后",
        ]
        return any(h in raw for h in hints)

    def _sanitize_wait_confirm_tasks(self, tasks: List[Dict[str, Any]], context: SkillContext) -> List[Dict[str, Any]]:
        """Avoid auto-hanging on wait_confirm unless intent is explicit."""
        user_text = context.user_text or context.get("last_input", "")
        if self._has_explicit_wait_confirm_intent(user_text) or self._has_handover_intent(user_text):
            return tasks

        filtered: List[Dict[str, Any]] = []
        removed = 0

        for task in tasks:
            if not isinstance(task, dict):
                filtered.append(task)
                continue

            action = str(task.get("action", "")).lower()
            if action != "wait_confirm":
                filtered.append(task)
                continue

            # Keep explicit wait step if task itself marks mandatory.
            if bool(task.get("required")) or bool(task.get("force")):
                filtered.append(task)
                continue

            # Keep when the immediately previous action is a handover speech.
            prev = filtered[-1] if filtered else None
            if isinstance(prev, dict) and str(prev.get("action", "")).lower() == "speak":
                if self._speech_implies_human_handover(prev.get("text")):
                    filtered.append(task)
                    continue

            removed += 1

        if removed > 0:
            context.set("wait_confirm_auto_filtered", removed)
            print(f"[Mission] auto-filtered wait_confirm x{removed} (no explicit confirm intent)")

        return filtered

    def _ensure_handover_wait_confirm(self, tasks: List[Dict[str, Any]], context: SkillContext) -> List[Dict[str, Any]]:
        """Auto insert wait_confirm after handover speak if missing."""
        if not tasks:
            return tasks

        patched: List[Dict[str, Any]] = []
        inserted = 0
        total = len(tasks)
        for idx, task in enumerate(tasks):
            patched.append(task)
            if not isinstance(task, dict):
                continue

            action = str(task.get("action", "")).lower()
            if action != "speak":
                continue
            if not self._speech_implies_human_handover(task.get("text")):
                continue

            next_task = tasks[idx + 1] if idx + 1 < total else None
            next_action = str(next_task.get("action", "")).lower() if isinstance(next_task, dict) else ""
            if next_action == "wait_confirm":
                continue

            patched.append({"action": "wait_confirm"})
            inserted += 1

        if inserted > 0:
            context.set("wait_confirm_auto_inserted", inserted)
            print(f"[Mission] auto-inserted wait_confirm x{inserted} after handover speak")
        return patched

    def _ensure_pickup_handover(self, tasks: List[Dict[str, Any]], context: SkillContext) -> List[Dict[str, Any]]:
        """Inject a pickup handover step when the user asked to fetch an item but the LLM omitted it."""
        if not tasks:
            return tasks

        user_text = context.user_text or context.get("last_input", "")
        if not self._has_handover_intent(user_text):
            return tasks

        for task in tasks:
            if not isinstance(task, dict):
                continue
            action = str(task.get("action", "")).lower()
            if action == "wait_confirm":
                return tasks
            if action == "speak" and self._speech_implies_human_handover(task.get("text")):
                return tasks

        item = self._extract_handover_item(user_text) or "物品"
        patched: List[Dict[str, Any]] = []
        inserted = False
        for task in tasks:
            patched.append(task)
            if inserted or not isinstance(task, dict):
                continue
            action = str(task.get("action", "")).lower()
            if action != "goto":
                continue
            target = str(task.get("target", "")).strip()
            if not target or self._is_dock_target(target):
                continue
            patched.append({"action": "speak", "text": f"请帮我把{item}放到篮子上"})
            patched.append({"action": "wait_confirm"})
            inserted = True

        if inserted:
            context.set("pickup_handover_auto_inserted", True)
            print(f"[Mission] auto-inserted pickup handover for item={item}")
            return patched
        return tasks

    def _get_world_resolver(self, context: SkillContext):
        resolver = context.get("world") or context.get("world_model") or getattr(context, "world_model", None)
        if resolver and hasattr(resolver, "resolve_location"):
            return resolver
        return None

    def _match_map_from_adapter(self, map_name: str):
        if not self.adapter or not map_name:
            return None
        try:
            all_maps = self.adapter.list_maps()
        except Exception:
            return None

        for item in all_maps:
            if item.name == map_name:
                return item
        for item in all_maps:
            if map_name in item.name or item.name in map_name:
                return item

        input_numbers = re.findall(r"\d+", map_name or "")
        if input_numbers:
            for item in all_maps:
                map_numbers = re.findall(r"\d+", item.name or "")
                if any(num in map_numbers for num in input_numbers):
                    return item
        return None

    def _resolve_default_map(self, context: SkillContext) -> Tuple[Optional[int], Optional[str], str]:
        resolver = self._get_world_resolver(context)
        if resolver and hasattr(resolver, "get_default_map"):
            try:
                default_map = resolver.get_default_map()
            except Exception:
                default_map = None
            if default_map:
                map_id = self._coerce_int(getattr(default_map, "map_id", None))
                map_name = getattr(default_map, "name", None)
                if map_id is None and map_name:
                    matched = self._match_map_from_adapter(map_name)
                    if matched:
                        map_id = matched.id
                        map_name = matched.name
                return map_id, map_name, "world_default"

        world_default_map = context.get("world_default_map")
        if isinstance(world_default_map, dict):
            return self._coerce_int(world_default_map.get("id")), world_default_map.get("name"), "session_world_default"
        if isinstance(world_default_map, int):
            return world_default_map, None, "session_world_default"
        if isinstance(world_default_map, str) and world_default_map.strip():
            matched = self._match_map_from_adapter(world_default_map.strip())
            if matched:
                return matched.id, matched.name, "session_world_default"
            return None, world_default_map.strip(), "session_world_default"

        current_map = context.get("current_map")
        if isinstance(current_map, dict):
            return self._coerce_int(current_map.get("id")), current_map.get("name"), "session_current_map"

        return None, None, "none"

    def _resolve_first_task_map(self, tasks: List[Dict[str, Any]], context: SkillContext) -> Tuple[Optional[int], Optional[str]]:
        resolver = self._get_world_resolver(context)
        if not resolver:
            return None, None

        current_map = context.get("current_map")
        current_map_id = self._coerce_int(current_map.get("id")) if isinstance(current_map, dict) else None
        current_map_name = current_map.get("name") if isinstance(current_map, dict) else None

        for task in tasks:
            if not isinstance(task, dict):
                continue
            if str(task.get("action", "")).lower() != "goto":
                continue
            target = str(task.get("target", "")).strip()
            if not target or self._is_dock_target(target):
                continue

            try:
                resolved = resolver.resolve_location(
                    target,
                    current_map_id=current_map_id,
                    current_map_name=current_map_name,
                )
            except Exception:
                resolved = None

            if resolved and (getattr(resolved, "map_id", None) is not None or getattr(resolved, "map_name", None)):
                return self._coerce_int(getattr(resolved, "map_id", None)), getattr(resolved, "map_name", None)
        return None, None

    def _get_current_navigation_map(self) -> Tuple[Optional[int], Optional[str], bool]:
        current_map_id = None
        current_map_name = None
        nav_running = False

        if self.adapter and hasattr(self.adapter, "get_navigation_status"):
            try:
                nav_status = self.adapter.get_navigation_status()
            except Exception:
                nav_status = {}
            if isinstance(nav_status, dict):
                current_map_id = self._coerce_int(nav_status.get("current_map_id") or nav_status.get("map_id"))
                nav_running = bool(nav_status.get("nav_running"))

        if self.adapter and hasattr(self.adapter, "resolve_current_map"):
            try:
                current_map = self.adapter.resolve_current_map()
            except Exception:
                current_map = None
            if current_map:
                current_map_id = self._coerce_int(getattr(current_map, "id", current_map_id))
                current_map_name = getattr(current_map, "name", None) or current_map_name

        return current_map_id, current_map_name, nav_running

    def _normalize_tasks_with_world(self, tasks: List[Dict[str, Any]], context: SkillContext) -> List[Dict[str, Any]]:
        resolver = self._get_world_resolver(context)
        if not resolver:
            return tasks

        current_map = context.get("current_map")
        current_map_id = self._coerce_int(current_map.get("id")) if isinstance(current_map, dict) else None
        current_map_name = current_map.get("name") if isinstance(current_map, dict) else None

        normalized_tasks: List[Dict[str, Any]] = []
        for task in tasks:
            if not isinstance(task, dict):
                normalized_tasks.append(task)
                continue

            action = str(task.get("action", "")).lower()
            if action != "goto":
                normalized_tasks.append(task)
                continue

            target = str(task.get("target", "")).strip()
            if not target:
                normalized_tasks.append(task)
                continue

            if self._is_dock_target(target):
                patched = {"action": "dock"}
                if "timeout_sec" in task:
                    patched["timeout_sec"] = task.get("timeout_sec")
                if "timeout" in task:
                    patched["timeout"] = task.get("timeout")
                normalized_tasks.append(patched)
                continue

            try:
                resolved = resolver.resolve_location(
                    target,
                    current_map_id=current_map_id,
                    current_map_name=current_map_name,
                )
            except Exception:
                resolved = None

            if not resolved:
                normalized_tasks.append(task)
                continue

            if getattr(resolved, "location_type", "") == "dock":
                patched = {"action": "dock"}
                if "timeout_sec" in task:
                    patched["timeout_sec"] = task.get("timeout_sec")
                if "timeout" in task:
                    patched["timeout"] = task.get("timeout")
                normalized_tasks.append(patched)
                continue

            patched = dict(task)
            patched_target = getattr(resolved, "waypoint_name", None) or getattr(resolved, "name", None)
            if patched_target:
                patched["target"] = patched_target
            normalized_tasks.append(patched)

        return normalized_tasks

    def _ensure_navigation_ready(self, context: SkillContext, tasks: List[Dict[str, Any]]) -> Tuple[bool, str]:
        if not self.adapter:
            return False, "adapter not configured"
        if not hasattr(self.adapter, "start_navigation"):
            return True, ""

        needs_navigation = any(
            isinstance(task, dict) and str(task.get("action", "")).lower() in {"goto", "dock"}
            for task in tasks
        )
        if not needs_navigation:
            return True, ""

        target_map_id, target_map_name = self._resolve_first_task_map(tasks, context)
        if target_map_id is None and target_map_name:
            matched = self._match_map_from_adapter(target_map_name)
            if matched:
                target_map_id = matched.id
                target_map_name = matched.name

        if target_map_id is None:
            default_map_id, default_map_name, _ = self._resolve_default_map(context)
            target_map_id = default_map_id
            target_map_name = target_map_name or default_map_name

        if target_map_id is None and hasattr(self.adapter, "resolve_current_map"):
            try:
                current_map = self.adapter.resolve_current_map()
            except Exception:
                current_map = None
            if current_map:
                target_map_id = self._coerce_int(current_map.id)
                target_map_name = target_map_name or current_map.name

        if target_map_id is None:
            return False, "no available map, please set world default map first"

        current_map_id, current_map_name, _ = self._get_current_navigation_map()
        if current_map_id == self._coerce_int(target_map_id):
            context.set(
                "current_map",
                {"id": current_map_id, "name": current_map_name or target_map_name or str(target_map_id)},
            )
            return True, ""

        try:
            start_ok = self.adapter.start_navigation(int(target_map_id))
        except Exception as e:
            return False, f"auto start navigation failed (map_id={target_map_id}): {e}"
        if not start_ok:
            return False, f"auto start navigation failed (map_id={target_map_id})"

        wait_nav_started = getattr(self.adapter, "wait_nav_started", None)
        if callable(wait_nav_started):
            nav_start_timeout = 15
            try:
                cfg = get_config()
                nav_start_timeout = int(getattr(getattr(cfg, "mission", None), "nav_start_timeout_sec", 15) or 15)
            except Exception:
                nav_start_timeout = 15
            try:
                if not wait_nav_started(timeout=nav_start_timeout):
                    return False, f"navigation not ready or start timed out (map_id={target_map_id})"
            except Exception as e:
                return False, f"wait nav started failed (map_id={target_map_id}): {e}"

        context.set("current_map", {"id": target_map_id, "name": target_map_name or str(target_map_id)})
        return True, ""

    def _prepare_for_movement(self, tasks: List[Dict[str, Any]]) -> Tuple[bool, str]:
        if not self.adapter:
            return False, "adapter not configured"

        needs_movement = any(
            isinstance(task, dict) and str(task.get("action", "")).lower() in {"goto", "dock"}
            for task in tasks
        )
        if not needs_movement:
            return True, ""

        prepare = getattr(self.adapter, "prepare_for_movement", None)
        if not callable(prepare):
            return True, ""

        try:
            if not prepare():
                return False, "prepare for movement failed"
        except Exception as e:
            return False, f"prepare for movement failed: {e}"
        return True, ""

    def _get_mission_manager(self) -> MissionManager:
        adapter_id = id(self.adapter)
        if self._mission_manager is None or self._mission_manager_adapter_id != adapter_id:
            self._mission_manager = MissionManager(self.adapter, global_event_bus)
            self._mission_manager_adapter_id = adapter_id
        return self._mission_manager

    def execute(self, params: Dict[str, Any], context: SkillContext) -> SkillResult:
        tasks = params.get("tasks")
        if not isinstance(tasks, list):
            return SkillResult(False, "tasks must be a list")

        if not self.adapter:
            return SkillResult(False, "adapter not configured")

        # Keep only world/canonical normalization here. Task semantics should come from the LLM plan,
        # not from keyword-based rewrites at the skill layer.
        normalized_tasks = self._normalize_tasks_with_world(tasks, context)
        if not normalized_tasks:
            return SkillResult(False, "no executable tasks", {"tasks": []})
        prepared, prepare_reason = self._prepare_for_movement(normalized_tasks)
        if not prepared:
            return SkillResult(False, prepare_reason, {"tasks": normalized_tasks})
        ready, reason = self._ensure_navigation_ready(context, normalized_tasks)
        if not ready:
            return SkillResult(False, reason, {"tasks": normalized_tasks})

        manager = self._get_mission_manager()
        accepted = manager.submit_mission(normalized_tasks)
        if not accepted:
            detail = manager.last_error or "mission submit failed"
            return SkillResult(False, f"mission submit failed: {detail}", {"tasks": normalized_tasks})

        pending = True
        if hasattr(manager, "has_pending_work"):
            try:
                pending = bool(manager.has_pending_work())
            except Exception:
                pending = True
        else:
            pending = bool(getattr(manager, "is_busy", True) or getattr(manager, "waiting_for_human", False))

        if pending:
            return SkillResult(
                True,
                f"mission accepted (event-driven), steps={len(normalized_tasks)}",
                {"tasks": normalized_tasks, "mode": "event-driven", "pending": True},
            )

        return SkillResult(
            True,
            f"mission completed, steps={len(normalized_tasks)}",
            {"tasks": normalized_tasks, "mode": "completed", "pending": False},
        )
