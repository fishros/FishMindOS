from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from fishmindos.skill_runtime.base import Skill
from fishmindos.skill_runtime.entity_matcher import best_entity_match
from fishmindos.skill_runtime.registry import SkillRegistry
from fishmindos.skill_runtime.task_chain_store import TaskChainStore


ZONE_TYPES = ("stop", "slow", "forbidden")
DOCK_KEYWORDS = ("回充点", "充电点", "回充站", "充电桩", "回桩")
TASK_TEMPLATE_DEDUPE_WINDOW_SEC = 120
_RECENT_TASK_TEMPLATE_CREATIONS: dict[str, tuple[int, float]] = {}


def _cleanup_recent_task_templates(now: float | None = None) -> None:
    current = now if now is not None else time.time()
    expired = [key for key, (_, deadline) in _RECENT_TASK_TEMPLATE_CREATIONS.items() if deadline <= current]
    for key in expired:
        _RECENT_TASK_TEMPLATE_CREATIONS.pop(key, None)


def _remember_recent_task_template(fingerprint: str, task_id: int) -> None:
    if not fingerprint:
        return
    _cleanup_recent_task_templates()
    _RECENT_TASK_TEMPLATE_CREATIONS[fingerprint] = (
        int(task_id),
        time.time() + TASK_TEMPLATE_DEDUPE_WINDOW_SEC,
    )


def _find_recent_task_template(fingerprint: str) -> int | None:
    _cleanup_recent_task_templates()
    cached = _RECENT_TASK_TEMPLATE_CREATIONS.get(fingerprint)
    if cached is None:
        return None
    return int(cached[0])


def _json_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()


def _create_blockly_id() -> str:
    millis = int(time.time() * 1000)
    return f"blk_{millis:x}_{hashlib.md5(str(millis).encode('utf-8')).hexdigest()[:8]}"


def _build_blockly_block(
    block_type: str,
    *,
    fields: dict[str, Any] | None = None,
    next_block: dict[str, Any] | None = None,
    extra_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    block: dict[str, Any] = {"id": _create_blockly_id(), "type": block_type}
    if fields:
        block["fields"] = fields
    if extra_state:
        block["extraState"] = extra_state
    if next_block is not None:
        block["next"] = {"block": next_block}
    return block


def _chain_blockly_blocks(block_specs: list[dict[str, Any]]) -> dict[str, Any]:
    next_block: dict[str, Any] | None = None
    for spec in reversed(block_specs):
        next_block = _build_blockly_block(
            spec["type"],
            fields=spec.get("fields"),
            next_block=next_block,
            extra_state=spec.get("extraState"),
        )
    if next_block is not None:
        next_block["x"] = 180
        next_block["y"] = 80
    return next_block or {}


def _build_tts_speak_fields(text: str, wait: bool = True) -> dict[str, Any]:
    return {"DEVICE_ID": "", "TEXT": text, "WAIT": wait}


def _build_nav_start_fields(map_id: int) -> dict[str, Any]:
    return {"MAP": str(map_id)}


def _build_nav_waypoint_fields(
    map_id: int,
    waypoint_id: int,
    *,
    speed: float = 0.7,
    obstacle: str = "bypass",
    distance_tolerance: float = 0.1,
    angle_tolerance: float = 0.1,
) -> dict[str, Any]:
    return {
        "MAP": str(map_id),
        "WAYPOINT": str(waypoint_id),
        "SPEED": speed,
        "OBSTACLE": obstacle,
        "DIST_TOL": distance_tolerance,
        "ANG_TOL": angle_tolerance,
    }


def _build_nav_template_program(
    *,
    map_id: int,
    waypoint_ids: list[int],
    dock_waypoint_id: int | None = None,
    start_nav: bool = False,
    stand_first: bool = False,
    start_text: str | None = None,
    finish_text: str | None = None,
    wait_for_speech: bool = True,
    speed: float = 0.7,
    obstacle: str = "bypass",
    distance_tolerance: float = 0.1,
    angle_tolerance: float = 0.1,
) -> dict[str, Any]:
    block_specs: list[dict[str, Any]] = []
    if start_nav:
        block_specs.append({"type": "nav_start", "fields": _build_nav_start_fields(map_id)})
    if stand_first:
        block_specs.append({"type": "robot_stand"})
    if start_text:
        block_specs.append(
            {"type": "tts_speak", "fields": _build_tts_speak_fields(start_text, wait=wait_for_speech)}
        )
    for waypoint_id in waypoint_ids:
        block_specs.append(
            {
                "type": "nav_to_waypoint_adv",
                "fields": _build_nav_waypoint_fields(
                    map_id,
                    waypoint_id,
                    speed=speed,
                    obstacle=obstacle,
                    distance_tolerance=distance_tolerance,
                    angle_tolerance=angle_tolerance,
                ),
            }
        )
    if dock_waypoint_id is not None:
        block_specs.append(
            {
                "type": "nav_dock",
                "fields": _build_nav_waypoint_fields(
                    map_id,
                    dock_waypoint_id,
                    speed=speed,
                    obstacle=obstacle,
                    distance_tolerance=distance_tolerance,
                    angle_tolerance=angle_tolerance,
                ),
            }
        )
    if finish_text:
        block_specs.append(
            {"type": "tts_speak", "fields": _build_tts_speak_fields(finish_text, wait=wait_for_speech)}
        )
    if not block_specs:
        raise ValueError("导航任务模板至少要有一个动作块。")

    return {
        "blocks": {
            "languageVersion": 0,
            "blocks": [_chain_blockly_blocks(block_specs)],
        }
    }


class NavigationAssistantSkill(Skill):
    name = "robot_navigation_assistant"
    description = (
        "High-level semantic navigation tool. Use human-readable map names and location names directly. "
        "The runtime will resolve maps, waypoints, dock points, and named zones internally."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "go_to_location",
                    "start_map",
                    "stop_navigation",
                    "pause_navigation",
                    "resume_navigation",
                    "current_position",
                    "navigation_status",
                    "list_locations",
                    "list_maps",
                ],
            },
            "location_name": {"type": "string"},
            "map_name": {"type": "string"},
            "location_type": {"type": "string", "enum": ["auto", "waypoint", "dock", "zone"]},
        },
        "required": ["action"],
        "additionalProperties": False,
    }
    expose_as_tool = True

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def run(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action", "")).strip()
        if action == "go_to_location":
            return self._go_to_location(args, context)
        if action == "start_map":
            return self._call("robot_navigation", {"action": "start", "map_name": args.get("map_name")}, context)
        if action == "stop_navigation":
            return self._call("robot_navigation", {"action": "stop"}, context)
        if action == "pause_navigation":
            return self._call("robot_navigation", {"action": "pause_goto_waypoint"}, context)
        if action == "resume_navigation":
            return self._call("robot_navigation", {"action": "resume_goto_waypoint"}, context)
        if action == "current_position":
            return self._call("robot_navigation", {"action": "get_current_position"}, context)
        if action == "navigation_status":
            return self._call("robot_navigation", {"action": "get_state"}, context)
        if action == "list_maps":
            return self._call("robot_maps", {"action": "list"}, context)
        if action == "list_locations":
            return self._list_locations(args, context)
        return {"ok": False, "detail": f"Unsupported action '{action}' for tool {self.name}."}

    def _go_to_location(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        location_name = str(args.get("location_name", "") or "").strip()
        if not location_name:
            return {"ok": False, "detail": "请告诉我要去哪里。"}

        map_name = str(args.get("map_name", "") or "").strip()
        location_type = str(args.get("location_type", "auto") or "auto").strip() or "auto"

        if location_type == "dock":
            return self._go_to_dock(location_name=location_name, map_name=map_name, context=context)
        if location_type == "zone":
            return self._go_to_zone(location_name=location_name, map_name=map_name, context=context)
        if location_type == "waypoint":
            return self._go_to_waypoint(location_name=location_name, map_name=map_name, context=context)

        if any(token in location_name for token in DOCK_KEYWORDS):
            dock_result = self._go_to_dock(location_name=location_name, map_name=map_name, context=context)
            if dock_result.get("ok"):
                return dock_result

        waypoint_result = self._go_to_waypoint(location_name=location_name, map_name=map_name, context=context)
        if waypoint_result.get("ok"):
            return waypoint_result

        zone_result = self._go_to_zone(location_name=location_name, map_name=map_name, context=context)
        if zone_result.get("ok"):
            return zone_result

        return {"ok": False, "detail": f"我还没找到“{location_name}”对应的位置。"}

    def _go_to_waypoint(self, *, location_name: str, map_name: str, context: dict[str, Any]) -> dict[str, Any]:
        result = self._call(
            "robot_navigation",
            {"action": "goto_waypoint", "waypoint_name": location_name, "map_name": map_name},
            context,
        )
        if result.get("ok"):
            data = result.get("data")
            if isinstance(data, dict) and data.get("waypoint_name"):
                result["detail"] = f"我准备前往 {data.get('waypoint_name')}。"
        return result

    def _go_to_dock(self, *, location_name: str, map_name: str, context: dict[str, Any]) -> dict[str, Any]:
        for candidate_map in self._candidate_map_names(map_name, context):
            dock_result = self._call("robot_dock", {"action": "get", "map_name": candidate_map}, context)
            if not dock_result.get("ok"):
                continue
            data = dock_result.get("data")
            if not isinstance(data, dict):
                continue
            waypoint_id = data.get("waypoint_id") or data.get("id")
            if waypoint_id in (None, ""):
                continue
            nav_args: dict[str, Any] = {"action": "dock_to_waypoint", "waypoint_id": int(waypoint_id)}
            if data.get("map_id") not in (None, ""):
                nav_args["map_id"] = int(data["map_id"])
            if data.get("map_name") not in (None, ""):
                nav_args["map_name"] = str(data["map_name"])
            result = self._call("robot_navigation", nav_args, context)
            if result.get("ok"):
                result["detail"] = f"我准备前往 {location_name} 并执行回充。"
            return result
        return {"ok": False, "detail": f"我还没有找到“{location_name}”的回充点信息。"}

    def _go_to_zone(self, *, location_name: str, map_name: str, context: dict[str, Any]) -> dict[str, Any]:
        zone = self._match_zone(location_name=location_name, map_name=map_name, context=context)
        if zone is None:
            return {"ok": False, "detail": f"我还没找到名为“{location_name}”的区域。"}
        point = self._zone_target_point(zone)
        if point is None:
            return {"ok": False, "detail": f"区域“{location_name}”暂时没有可导航的坐标。"}

        result = self._call(
            "robot_navigation",
            {"action": "goto_point", "x": point["x"], "y": point["y"], "target_id": point.get("target_id")},
            context,
        )
        if result.get("ok"):
            result["detail"] = f"我准备前往区域 {location_name}。"
        return result

    def _match_zone(self, *, location_name: str, map_name: str, context: dict[str, Any]) -> dict[str, Any] | None:
        for candidate_map in self._candidate_map_names(map_name, context):
            for zone_type in ZONE_TYPES:
                result = self._call(
                    "robot_zones",
                    {
                        "action": "list",
                        "map_name": candidate_map,
                        "zone_type": zone_type,
                        "include_inactive": True,
                    },
                    context,
                )
                if not result.get("ok"):
                    continue
                items = self._extract_collection(result.get("data"), preferred_keys=("zones",))
                match = best_entity_match(items or [], [location_name], label_keys=("name", "title"), id_keys=("id", "zone_id"))
                if match is None:
                    continue
                zone = dict(match.item)
                zone.setdefault("zone_type", zone_type)
                data = result.get("data")
                if isinstance(data, dict):
                    if data.get("map_id") not in (None, ""):
                        zone.setdefault("map_id", data["map_id"])
                    if data.get("map_name") not in (None, ""):
                        zone.setdefault("map_name", data["map_name"])
                return zone
        return None

    def _list_locations(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        map_name = str(args.get("map_name", "") or "").strip()
        if not map_name:
            return self._call("robot_maps", {"action": "list"}, context)

        parts: list[str] = []
        waypoint_result = self._call("robot_waypoints", {"action": "list", "map_name": map_name}, context)
        if waypoint_result.get("ok"):
            parts.append(str(waypoint_result.get("detail", "")).strip())

        for zone_type in ZONE_TYPES:
            zone_result = self._call(
                "robot_zones",
                {"action": "list", "map_name": map_name, "zone_type": zone_type, "include_inactive": True},
                context,
            )
            if zone_result.get("ok"):
                parts.append(str(zone_result.get("detail", "")).strip())

        parts = [item for item in parts if item]
        if not parts:
            return {"ok": False, "detail": f"我暂时还没拿到地图“{map_name}”的位置列表。"}
        return {"ok": True, "detail": " ".join(parts), "data": {"map_name": map_name}}

    def _candidate_map_names(self, map_name: str, context: dict[str, Any]) -> list[str]:
        names: list[str] = []
        if map_name:
            names.append(map_name)
        last_map = context.get("last_map")
        if isinstance(last_map, dict) and last_map.get("name"):
            names.append(str(last_map["name"]))

        result = self._call("robot_maps", {"action": "list"}, context)
        maps = self._extract_collection(result.get("data"), preferred_keys=("maps",)) if result.get("ok") else []
        for item in maps or []:
            if isinstance(item, dict) and item.get("name"):
                names.append(str(item["name"]))

        deduped: list[str] = []
        seen: set[str] = set()
        for item in names:
            normalized = item.strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(item)
        return deduped

    def _call(self, skill_name: str, arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        skill = self.registry.get(skill_name)
        if skill is None:
            return {"ok": False, "detail": f"Tool not found: {skill_name}"}
        payload = {key: value for key, value in arguments.items() if value not in (None, "")}
        return skill.run(payload, context)

    @staticmethod
    def _zone_target_point(zone: dict[str, Any]) -> dict[str, Any] | None:
        points = zone.get("points")
        if not isinstance(points, list) or not points:
            return None
        valid_points = [item for item in points if isinstance(item, dict) and item.get("x") is not None and item.get("y") is not None]
        if not valid_points:
            return None
        x = sum(float(item["x"]) for item in valid_points) / len(valid_points)
        y = sum(float(item["y"]) for item in valid_points) / len(valid_points)
        return {"x": x, "y": y, "target_id": zone.get("id") or zone.get("zone_id")}

    @staticmethod
    def _extract_collection(data: Any, preferred_keys: tuple[str, ...] = ()) -> list[Any] | None:
        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            return None
        for key in preferred_keys + ("items", "list", "rows", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        return None


class TaskAssistantSkill(Skill):
    name = "robot_task_assistant"
    description = (
        "High-level task tool. Use task names directly for listing, describing, running, canceling, "
        "and creating navigation tasks from natural language."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "list_tasks",
                    "describe_task",
                    "run_task",
                    "cancel_task",
                    "create_nav_task",
                ],
            },
            "task_name": {"type": "string"},
            "task_id": {"type": "integer"},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "map_name": {"type": "string"},
            "waypoint_names": {"type": "array", "items": {"type": "string"}},
            "dock_waypoint_name": {"type": "string"},
            "start_nav": {"type": "boolean"},
            "stand_first": {"type": "boolean"},
            "start_text": {"type": "string"},
            "finish_text": {"type": "string"},
            "wait_for_speech": {"type": "boolean"},
        },
        "required": ["action"],
        "additionalProperties": False,
    }
    expose_as_tool = True

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def run(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action", "")).strip()
        if action == "list_tasks":
            return self._call("robot_tasks", {"action": "list"}, context)
        if action == "describe_task":
            return self._call("robot_tasks", {"action": "get", "task_name": args.get("task_name"), "task_id": args.get("task_id")}, context)
        if action == "run_task":
            return self._call("robot_tasks", {"action": "run", "task_name": args.get("task_name"), "task_id": args.get("task_id")}, context)
        if action == "cancel_task":
            return self._call("robot_tasks", {"action": "cancel", "task_name": args.get("task_name"), "task_id": args.get("task_id")}, context)
        if action == "create_nav_task":
            return self._create_nav_task(args, context)
        return {"ok": False, "detail": f"Unsupported action '{action}' for tool {self.name}."}

    def _create_nav_task(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        name = str(args.get("name", "") or "").strip()
        if not name:
            return {"ok": False, "detail": "请先告诉我任务叫什么名字。"}

        resolved_map = self._resolve_map(args, context)
        if resolved_map is None:
            return {"ok": False, "detail": "请告诉我要在哪张地图上创建这个任务。"}

        waypoint_names = [str(item).strip() for item in args.get("waypoint_names", []) if str(item).strip()]
        dock_waypoint_name = str(args.get("dock_waypoint_name", "") or "").strip()
        start_nav = bool(args.get("start_nav") is True)
        stand_first = bool(args.get("stand_first") is True)
        start_text = str(args.get("start_text", "") or "").strip() or None
        finish_text = str(args.get("finish_text", "") or "").strip() or None
        wait_for_speech = True if args.get("wait_for_speech") is None else bool(args.get("wait_for_speech"))

        waypoint_ids: list[int] = []
        for waypoint_name in waypoint_names:
            waypoint = self._match_waypoint(resolved_map, waypoint_name, context)
            if waypoint is None:
                return {"ok": False, "detail": f"我还没找到“{waypoint_name}”这个点位。"}
            waypoint_ids.append(int(waypoint["id"]))

        dock_waypoint_id: int | None = None
        if dock_waypoint_name:
            dock_waypoint = self._match_waypoint(resolved_map, dock_waypoint_name, context)
            if dock_waypoint is None:
                return {"ok": False, "detail": f"我还没找到“{dock_waypoint_name}”这个回充点。"}
            dock_waypoint_id = int(dock_waypoint["id"])

        if not any([start_nav, stand_first, waypoint_ids, dock_waypoint_id, start_text, finish_text]):
            return {"ok": False, "detail": "我还没看懂任务里的动作顺序。"}

        description = str(args.get("description", "") or "").strip() or f"导航任务：{name}（地图 {resolved_map['name']}）"
        fingerprint = _json_fingerprint(
            {
                "name": name,
                "description": description,
                "map_id": int(resolved_map["id"]),
                "waypoint_ids": waypoint_ids,
                "dock_waypoint_id": dock_waypoint_id,
                "start_nav": start_nav,
                "stand_first": stand_first,
                "start_text": start_text,
                "finish_text": finish_text,
                "wait_for_speech": wait_for_speech,
            }
        )
        cached_task_id = _find_recent_task_template(fingerprint)
        if cached_task_id is not None:
            step_count = int(start_nav) + int(stand_first) + len(waypoint_ids) + int(dock_waypoint_id is not None) + int(bool(start_text)) + int(bool(finish_text))
            return {
                "ok": True,
                "detail": f"我刚刚已经记住过任务“{name}”了，任务 ID 是 {cached_task_id}。",
                "data": {
                    "id": cached_task_id,
                    "name": name,
                    "map_id": int(resolved_map["id"]),
                    "map_name": str(resolved_map["name"]),
                    "waypoint_ids": waypoint_ids,
                    "dock_waypoint_id": dock_waypoint_id,
                    "step_count": step_count,
                    "description": description,
                    "reused_existing_task": True,
                },
            }

        create_result = self._call("robot_tasks", {"action": "create", "name": name, "description": description}, context)
        if not create_result.get("ok"):
            return create_result
        created_task = self._extract_payload_dict(create_result.get("data"))
        task_id = created_task.get("id") or created_task.get("task_id")
        if task_id in (None, ""):
            return {"ok": False, "detail": "任务虽然创建了，但我没有拿到任务 ID。"}

        program = _build_nav_template_program(
            map_id=int(resolved_map["id"]),
            waypoint_ids=waypoint_ids,
            dock_waypoint_id=dock_waypoint_id,
            start_nav=start_nav,
            stand_first=stand_first,
            start_text=start_text,
            finish_text=finish_text,
            wait_for_speech=wait_for_speech,
        )
        update_result = self._call(
            "robot_tasks",
            {"action": "update_program", "task_id": int(task_id), "program": program},
            context,
        )
        if not update_result.get("ok"):
            return update_result

        _remember_recent_task_template(fingerprint, int(task_id))
        step_count = int(start_nav) + int(stand_first) + len(waypoint_ids) + int(dock_waypoint_id is not None) + int(bool(start_text)) + int(bool(finish_text))
        return {
            "ok": True,
            "detail": f"我已经记住任务“{name}”了，共 {step_count} 步，任务 ID 是 {int(task_id)}。",
            "data": {
                "id": int(task_id),
                "name": name,
                "map_id": int(resolved_map["id"]),
                "map_name": str(resolved_map["name"]),
                "waypoint_ids": waypoint_ids,
                "dock_waypoint_id": dock_waypoint_id,
                "description": description,
                "program": program,
                "step_count": step_count,
            },
        }

    def _resolve_map(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | None:
        explicit_map_name = str(args.get("map_name", "") or "").strip()
        maps_result = self._call("robot_maps", {"action": "list"}, context)
        maps = self._extract_collection(maps_result.get("data"), preferred_keys=("maps",)) if maps_result.get("ok") else []
        if not maps:
            return None

        if explicit_map_name:
            match = best_entity_match(maps, [explicit_map_name], label_keys=("name",), id_keys=("id", "map_id"))
            return dict(match.item) if match is not None else None

        last_map = context.get("last_map")
        if isinstance(last_map, dict):
            references = [last_map.get("name"), last_map.get("id")]
            match = best_entity_match(maps, references, label_keys=("name",), id_keys=("id", "map_id"))
            if match is not None:
                return dict(match.item)
        return None

    def _match_waypoint(self, map_item: dict[str, Any], waypoint_name: str, context: dict[str, Any]) -> dict[str, Any] | None:
        waypoint_result = self._call(
            "robot_waypoints",
            {"action": "list", "map_id": int(map_item["id"]), "map_name": map_item.get("name")},
            context,
        )
        waypoints = self._extract_collection(waypoint_result.get("data"), preferred_keys=("waypoints",)) if waypoint_result.get("ok") else []
        if not waypoints:
            return None
        match = best_entity_match(waypoints, [waypoint_name], label_keys=("name",), id_keys=("id", "waypoint_id"))
        return dict(match.item) if match is not None else None

    def _call(self, skill_name: str, arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        payload = {key: value for key, value in arguments.items() if value not in (None, "", [])}
        skill = self.registry.get(skill_name)
        if skill is None:
            return {"ok": False, "detail": f"Tool not found: {skill_name}"}
        return skill.run(payload, context)

    @staticmethod
    def _extract_payload_dict(data: Any) -> dict[str, Any]:
        if isinstance(data, dict):
            nested = data.get("task")
            if isinstance(nested, dict):
                return nested
            return data
        return {}

    @staticmethod
    def _extract_collection(data: Any, preferred_keys: tuple[str, ...] = ()) -> list[Any] | None:
        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            return None
        for key in preferred_keys + ("items", "list", "rows", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        return None


class TaskChainSkill(Skill):
    name = "robot_task_chain"
    description = (
        "High-level task-chain tool. Save, inspect, delete, and run local task chains made of macro robot actions."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["save_chain", "list_chains", "show_chain", "delete_chain", "run_chain", "run_steps"],
            },
            "name": {"type": "string"},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "skill": {"type": "string"},
                        "args": {"type": "object", "additionalProperties": True},
                        "on_fail": {"type": "string"},
                    },
                    "required": ["skill", "args"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }
    expose_as_tool = True

    def __init__(self, registry: SkillRegistry, store: TaskChainStore | None = None) -> None:
        self.registry = registry
        self.store = store or TaskChainStore.from_env()

    def run(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action", "")).strip()
        if action == "save_chain":
            return self._save_chain(args)
        if action == "list_chains":
            return self._list_chains()
        if action == "show_chain":
            return self._show_chain(args)
        if action == "delete_chain":
            return self._delete_chain(args)
        if action == "run_chain":
            return self._run_chain(args, context)
        if action == "run_steps":
            return self._run_steps(args, context)
        return {"ok": False, "detail": f"Unsupported action '{action}' for tool {self.name}."}

    def _save_chain(self, args: dict[str, Any]) -> dict[str, Any]:
        name = str(args.get("name", "") or "").strip()
        if not name:
            return {"ok": False, "detail": "请先告诉我任务链叫什么名字。"}
        steps = args.get("steps")
        if not isinstance(steps, list) or not steps:
            return {"ok": False, "detail": "请告诉我任务链里要按什么顺序做。"}
        saved = self.store.save_chain(name, steps)
        chain = saved["chain"]
        if saved["replaced"]:
            detail = f"我已经更新任务链“{chain.name}”了，共 {len(chain.steps)} 步。"
        else:
            detail = f"我已经记住任务链“{chain.name}”了，共 {len(chain.steps)} 步。"
        return {
            "ok": True,
            "detail": detail,
            "data": {
                "name": chain.name,
                "steps": chain.steps,
                "created_at": chain.created_at,
                "updated_at": chain.updated_at,
            },
        }

    def _list_chains(self) -> dict[str, Any]:
        chains = self.store.list_chains()
        if not chains:
            return {"ok": True, "detail": "我现在还没有记住任何任务链。", "data": {"chains": []}}
        preview = "、".join(chain.name for chain in chains[:5])
        suffix = " 等" if len(chains) > 5 else ""
        return {
            "ok": True,
            "detail": f"我记得 {len(chains)} 条任务链，当前有 {preview}{suffix}。",
            "data": {
                "chains": [
                    {
                        "name": chain.name,
                        "steps": chain.steps,
                        "created_at": chain.created_at,
                        "updated_at": chain.updated_at,
                    }
                    for chain in chains
                ]
            },
        }

    def _show_chain(self, args: dict[str, Any]) -> dict[str, Any]:
        name = str(args.get("name", "") or "").strip()
        if not name:
            return {"ok": False, "detail": "请告诉我要看哪条任务链。"}
        chain = self.store.get_chain(name)
        if chain is None:
            return {"ok": False, "detail": f"我还没记住任务链“{name}”。"}
        steps_text = "；".join(
            f"{index}.{self._describe_step(step)}" for index, step in enumerate(chain.steps, start=1)
        )
        return {
            "ok": True,
            "detail": f"任务链“{chain.name}”共 {len(chain.steps)} 步：{steps_text}。",
            "data": {
                "name": chain.name,
                "steps": chain.steps,
                "created_at": chain.created_at,
                "updated_at": chain.updated_at,
            },
        }

    def _delete_chain(self, args: dict[str, Any]) -> dict[str, Any]:
        name = str(args.get("name", "") or "").strip()
        if not name:
            return {"ok": False, "detail": "请告诉我要删哪条任务链。"}
        deleted = self.store.delete_chain(name)
        if not deleted:
            return {"ok": False, "detail": f"我还没记住任务链“{name}”。"}
        return {"ok": True, "detail": f"我已经删掉任务链“{name}”了。", "data": {"name": name}}

    def _run_chain(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        name = str(args.get("name", "") or "").strip()
        if not name:
            return {"ok": False, "detail": "请告诉我要执行哪条任务链。"}
        chain = self.store.get_chain(name)
        if chain is None:
            return {"ok": False, "detail": f"我还没记住任务链“{name}”。"}

        return self._execute_steps(
            steps=chain.steps,
            context=context,
            chain_name=name,
            payload={
                "name": name,
                "steps": chain.steps,
                "created_at": chain.created_at,
                "updated_at": chain.updated_at,
            },
        )

    def _run_steps(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        steps = args.get("steps")
        if not isinstance(steps, list) or not steps:
            return {"ok": False, "detail": "请告诉我要按什么顺序执行。"}
        sanitized = self.store._sanitize_steps(steps)
        return self._execute_steps(
            steps=sanitized,
            context=context,
            chain_name="临时任务链",
            payload={"steps": sanitized},
        )

    def _execute_steps(
        self,
        *,
        steps: list[dict[str, Any]],
        context: dict[str, Any],
        chain_name: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        local_context = dict(context)
        parts: list[str] = []
        for index, step in enumerate(steps, start=1):
            skill_name = str(step.get("skill", "")).strip()
            skill = self.registry.get(skill_name)
            if skill is None:
                return {"ok": False, "detail": f"任务链“{chain_name}”第 {index} 步找不到工具 {skill_name}。"}

            result = skill.run(dict(step.get("args", {})), local_context)
            if not result.get("ok"):
                return {
                    "ok": False,
                    "detail": f"任务链“{chain_name}”第 {index} 步失败：{str(result.get('detail', '')).strip()}",
                    "data": {"name": chain_name, "step_index": index, "step": step},
                }
            self._update_context_from_result(local_context, skill_name, result.get("data"))

            wait_result = self._wait_if_needed(step=step, result=result, context=local_context)
            if wait_result is not None and not wait_result.get("ok"):
                return {
                    "ok": False,
                    "detail": f"任务链“{chain_name}”第 {index} 步等待失败：{str(wait_result.get('detail', '')).strip()}",
                    "data": {"name": chain_name, "step_index": index, "step": step},
                }

            detail = str(result.get("detail", "")).strip().rstrip("。")
            if detail:
                parts.append(detail)

        summary = "，".join(parts[:3])
        detail = f"任务链“{chain_name}”已经执行完成了。"
        if summary:
            detail = f"{detail} {summary}。"
        return {
            "ok": True,
            "detail": detail,
            "data": payload,
        }

    def _wait_if_needed(self, *, step: dict[str, Any], result: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | None:
        events_skill = self.registry.get("robot_events")
        if events_skill is None:
            return None

        skill_name = str(step.get("skill", "")).strip()
        step_args = step.get("args", {})
        if not isinstance(step_args, dict):
            return None
        data = result.get("data")
        if not isinstance(data, dict):
            return None

        if skill_name == "robot_navigation":
            action = str(step_args.get("action", "")).strip()
            if action == "start":
                return events_skill.run({"action": "wait_nav_started", "timeout": 60}, context)
            if action == "goto_waypoint" and data.get("waypoint_id") not in (None, ""):
                return events_skill.run({"action": "wait_arrival", "waypoint_id": int(data["waypoint_id"]), "timeout": 300}, context)
            if action == "dock_to_waypoint":
                return events_skill.run({"action": "wait_dock_complete", "timeout": 300}, context)

        if skill_name == "robot_navigation_assistant":
            action = str(step_args.get("action", "")).strip()
            location_name = str(step_args.get("location_name", "") or "")
            location_type = str(step_args.get("location_type", "") or "")
            if action == "start_map":
                return events_skill.run({"action": "wait_nav_started", "timeout": 60}, context)
            if action == "go_to_location":
                if location_type == "dock" or any(token in location_name for token in DOCK_KEYWORDS):
                    return events_skill.run({"action": "wait_dock_complete", "timeout": 300}, context)
                if data.get("waypoint_id") not in (None, ""):
                    return events_skill.run({"action": "wait_arrival", "waypoint_id": int(data["waypoint_id"]), "timeout": 300}, context)
        return None

    @staticmethod
    def _describe_step(step: dict[str, Any]) -> str:
        skill = str(step.get("skill", "")).strip()
        args = step.get("args", {})
        if not isinstance(args, dict):
            return skill
        action = str(args.get("action", "")).strip()
        if skill == "robot_motion" and action == "apply_preset":
            mapping = {"stand": "站立", "lie_down": "趴下"}
            return mapping.get(str(args.get("preset", "")), "动作")
        if skill == "robot_light" and action == "set":
            if args.get("on") is False:
                return "关灯"
            code = args.get("code")
            return f"设置灯光 {code}" if code is not None else "设置灯光"
        if skill == "robot_navigation_assistant" and action == "go_to_location":
            return f"去 {args.get('location_name')}"
        if skill == "robot_navigation_assistant" and action == "start_map":
            return f"启动地图 {args.get('map_name')}"
        if skill == "robot_audio" and action == "tts_play":
            return f"播报“{args.get('text')}”"
        if skill == "robot_task_assistant" and action == "run_task":
            return f"执行任务 {args.get('task_name') or args.get('task_id')}"
        if skill == "robot_task_assistant" and action == "cancel_task":
            return f"取消任务 {args.get('task_name') or args.get('task_id')}"
        return f"{skill} {args}"

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


def register_macro_skills(registry: SkillRegistry) -> None:
    registry.register(NavigationAssistantSkill(registry))
    registry.register(TaskAssistantSkill(registry))
    registry.register(TaskChainSkill(registry, TaskChainStore.from_env()))
