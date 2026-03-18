from __future__ import annotations

import json
import re
from typing import Any
from urllib import parse as urlparse

from fishmindos.skill_runtime.base import Skill
from fishmindos.skill_runtime.dog_motion import DogMotionSkill
from fishmindos.skill_runtime.entity_matcher import EntityMatch, best_entity_match, normalize_entity_text, unique_references
from fishmindos.skill_runtime.nav_api import NavAPIClient, NavAPIError, NavAPIResult
from fishmindos.skill_runtime.rosbridge_api import RosbridgeClient, RosbridgeError
from fishmindos.skill_runtime.nav_skill_specs import (
    NAV_SKILL_GROUPS,
    NavOperationSpec,
    NavSkillGroupSpec,
    build_group_input_schema,
)
from fishmindos.skill_runtime.registry import SkillRegistry


JSONISH_FIELDS = {"value", "program", "preset_start_point"}
FULL_LIST_KEYWORDS = ("所有", "全部", "全都", "完整", "完整列出", "一一", "逐个")
TASK_FOLLOWUP_KEYWORDS = ("描述", "详情", "内容", "信息", "名字")
TASK_REFERENCE_PATTERNS = (
    r"任务\s*([^\s，。,.!?？:：]+?)\s*的?(?:描述|详情|内容|信息|名字)",
    r"任务\s*([^\s，。,.!?？:：]+)",
    r"名字叫\s*([^\s，。,.!?？:：]+)",
)
TASK_PRONOUNS = ("它", "这个任务", "刚才那个任务", "上一个任务", "该任务")
MAP_REFERENCE_PATTERNS = (
    r"地图(?:为|是|叫|名为|名称为|名称是)\s*([^\s，。,.!?？:：]+)",
    r"地图\s*([^\s，。,.!?？:：]+)",
)
LIGHT_CODE_MESSAGES = {
    11: "灯已经打开了。",
    12: "黄灯已经打开了。",
    13: "绿灯已经打开了。",
    21: "红灯已经切到慢闪。",
    22: "黄灯已经切到慢闪。",
    23: "绿灯已经切到慢闪。",
    31: "红灯已经切到快闪。",
    32: "黄灯已经切到快闪。",
    33: "绿灯已经切到快闪。",
    60: "灯已经关闭了。",
}
LIGHT_OFF_CODE = 60
LIGHT_TOPIC = "/light_control"
LIGHT_MSG_TYPE = "std_msgs/msg/Int32"
BMS_STATE_TOPIC = "/bms_state"
BMS_SOC_TOPIC = "/bms_soc"
BMS_MSG_TYPE = "std_msgs/msg/Float32"
WAYPOINT_REFERENCE_PATTERNS = (
    r"(?:去|前往|导航到|到)\s*(?:地图\s*)?([^\s，。！？!?]+?)\s*(?:路点|点位)",
    r"(?:去|前往|导航到)\s*(?:([^的，。！？!?]+?)的)?([^，。！？!?]+)$",
)
LOCATION_PRONOUNS = ("这里", "那里", "那个地方", "刚才那个地方", "上一处位置")
DOCK_REFERENCE_KEYWORDS = ("回充点", "充电点", "回充站", "充电桩")
ZONE_TYPES = ("stop", "slow", "forbidden")


class GroupedNavSkill(Skill):
    expose_as_tool = False

    def __init__(
        self,
        group: NavSkillGroupSpec,
        client: NavAPIClient | None = None,
        realtime_client: RosbridgeClient | None = None,
    ) -> None:
        self.group = group
        self.client = client or NavAPIClient.from_env()
        self.realtime_client = realtime_client or RosbridgeClient.from_env()
        self.name = group.name
        self.expose_as_tool = self.name in {"robot_audio", "robot_light", "robot_status", "robot_auth"}
        self.description = group.description
        self.input_schema = build_group_input_schema(group)
        self._operations = {item.action: item for item in group.operations}

    def run(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        try:
            normalized_args = self._coerce_args(args)
        except ValueError as exc:
            return {"ok": False, "detail": str(exc)}

        action = str(normalized_args.get("action", "")).strip()
        operation = self._operations.get(action)
        if operation is None:
            return {"ok": False, "detail": f"Unsupported action '{action}' for skill {self.name}."}

        normalized_args = self._normalize_operation_args(operation, normalized_args)
        missing = self._missing_required_fields(operation, normalized_args)
        if missing:
            return {"ok": False, "detail": f"Missing required fields: {', '.join(missing)}"}

        try:
            if operation.file_params:
                return self._run_file_operation(operation, normalized_args, context)
            if operation.response_mode == "text":
                return self._run_text_operation(operation, normalized_args)
            if operation.response_mode == "binary":
                return self._run_binary_operation(operation, normalized_args)
            return self._run_json_operation(operation, normalized_args, context)
        except NavAPIError as exc:
            return {"ok": False, "detail": self._humanize_nav_api_error(str(exc))}

    def _missing_required_fields(self, operation: NavOperationSpec, args: dict[str, Any]) -> list[str]:
        missing: list[str] = []
        for field in operation.required:
            if args.get(field) not in (None, ""):
                continue
            if field == "task_id" and args.get("task_name") not in (None, ""):
                continue
            if field == "map_id" and args.get("map_name") not in (None, ""):
                continue
            if field == "waypoint_id" and args.get("waypoint_name") not in (None, ""):
                continue
            if field == "from_map_id" and args.get("from_map_name") not in (None, ""):
                continue
            missing.append(field)
        return missing

    def _run_json_operation(
        self,
        operation: NavOperationSpec,
        args: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if self.name == "robot_light" and operation.action == "set":
            return self._run_light_set_operation(args)
        if self.name == "robot_navigation" and operation.action == "start":
            return self._run_navigation_start_operation(operation, args, context)
        if self.name == "robot_navigation" and operation.action in {"goto_waypoint", "dock_to_waypoint"}:
            return self._run_navigation_waypoint_operation(operation, args, context)
        if self.name == "robot_status" and operation.action in {"status", "charging_status", "battery_soc"}:
            return self._run_status_snapshot_operation(operation, context)
        if self.name == "robot_tasks" and operation.action in {"get", "delete", "run", "cancel", "update_program"}:
            return self._run_task_reference_operation(operation, args, context)
        if self.name == "robot_waypoints" and operation.action in {"list", "create", "create_current_position", "get", "update", "delete", "clear", "copy_from_map"}:
            return self._run_waypoint_management_operation(operation, args, context)
        if self.name == "robot_dock" and operation.action in {"get", "set", "clear"}:
            return self._run_dock_operation(operation, args, context)
        if self.name == "robot_zones" and operation.action == "list":
            return self._run_zone_list_operation(operation, args, context)

        result = self.client.request_json(
            operation.method,
            self._build_path(operation, args),
            query=self._collect(operation.query_params, args),
            json_body=self._collect(operation.body_params, args) or None,
            use_auth=operation.use_auth,
            capture_token=operation.capture_token,
            timeout_sec=self._request_timeout_for_operation(operation, args),
        )
        return self._format_json_response(operation, result, context)

    def _run_task_reference_operation(
        self,
        operation: NavOperationSpec,
        args: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_args = self._resolve_task_reference_args(args, context)
        try:
            result = self.client.request_json(
                operation.method,
                self._build_path(operation, resolved_args),
                query=self._collect(operation.query_params, resolved_args),
                json_body=self._collect(operation.body_params, resolved_args) or None,
                use_auth=operation.use_auth,
                capture_token=operation.capture_token,
                timeout_sec=self._request_timeout_for_operation(operation, resolved_args),
            )
            formatted = self._format_json_response(operation, result, context)
            return self._attach_resolved_fields(
                formatted,
                {
                    "task_id": resolved_args.get("task_id"),
                    "task_name": resolved_args.get("task_name"),
                },
            )
        except NavAPIError as exc:
            if operation.action != "get":
                raise
            fallback = self._fallback_task_get_by_name(args=resolved_args, context=context, original_error=exc)
            if fallback is not None:
                return fallback
            raise

    def _fallback_task_get_by_name(
        self,
        args: dict[str, Any],
        context: dict[str, Any],
        original_error: NavAPIError,
    ) -> dict[str, Any] | None:
        if not self._is_not_found_error(original_error):
            return None

        task = self._find_task_by_reference(args=args, context=context)
        if task is None:
            return None

        return {
            "ok": True,
            "detail": self._task_description_message(task),
            "data": task,
        }

    def _resolve_task_reference_args(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        resolved = dict(args)
        explicit_name = str(args.get("task_name", "") or "").strip()
        explicit_id = resolved.get("task_id")
        if explicit_name:
            match = self._match_task_by_reference(explicit_name, context=context)
            if match is None:
                raise NavAPIError(f"没有找到名为 {explicit_name} 的任务。")
            resolved["task_id"] = int(match.item["id"])
            resolved["task_name"] = str(match.item.get("name", explicit_name))
            return resolved

        if explicit_id not in (None, ""):
            resolved["task_id"] = int(explicit_id)
            return resolved

        match = self._match_task_by_references(self._candidate_task_references(args=args, context=context), context=context)
        if match is not None:
            resolved["task_id"] = int(match.item["id"])
            if match.item.get("name") not in (None, ""):
                resolved["task_name"] = str(match.item.get("name"))
        return resolved

    def _match_task_by_reference(self, reference: str, context: dict[str, Any]) -> EntityMatch | None:
        return self._match_task_by_references([reference], context=context)

    def _match_task_by_references(self, references: list[str], context: dict[str, Any]) -> EntityMatch | None:
        if not references:
            return None
        tasks = self._fetch_tasks(context)
        return best_entity_match(tasks, references, label_keys=("name",), id_keys=("id", "task_id"))

    def _find_task_by_reference(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | None:
        match = self._match_task_by_references(self._candidate_task_references(args=args, context=context), context=context)
        return match.item if match is not None else None

    def _candidate_task_references(self, args: dict[str, Any], context: dict[str, Any]) -> list[str]:
        references: list[str] = []

        explicit_task_id = args.get("task_id")
        if explicit_task_id not in (None, ""):
            references.append(str(explicit_task_id))
        explicit_task_name = args.get("task_name")
        if explicit_task_name not in (None, ""):
            references.append(str(explicit_task_name))

        for key in ("user_text", "original_text", "task_goal", "text", "query"):
            value = context.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            for pattern in TASK_REFERENCE_PATTERNS:
                match = re.search(pattern, value)
                if match:
                    references.append(match.group(1).strip())
            references.append(value.strip())

        last_task = context.get("last_task")
        if isinstance(last_task, dict):
            if self._is_task_followup(context):
                if last_task.get("name") not in (None, ""):
                    references.append(str(last_task.get("name")))
                if last_task.get("id") not in (None, ""):
                    references.append(str(last_task.get("id")))
        return unique_references(references)

    def _run_navigation_waypoint_operation(
        self,
        operation: NavOperationSpec,
        args: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_args = self._resolve_waypoint_reference_args(args, context)
        result = self.client.request_json(
            operation.method,
            self._build_path(operation, resolved_args),
            query=self._collect(operation.query_params, resolved_args),
            json_body=self._collect(operation.body_params, resolved_args) or None,
            use_auth=operation.use_auth,
            capture_token=operation.capture_token,
        )
        formatted = self._format_json_response(operation, result, context)
        return self._attach_resolved_fields(
            formatted,
            {
                "map_id": resolved_args.get("map_id"),
                "map_name": resolved_args.get("map_name"),
                "waypoint_id": resolved_args.get("waypoint_id"),
                "waypoint_name": resolved_args.get("waypoint_name"),
            },
        )

    def _run_waypoint_management_operation(
        self,
        operation: NavOperationSpec,
        args: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_args = self._resolve_waypoint_reference_args(args, context)
        result = self.client.request_json(
            operation.method,
            self._build_path(operation, resolved_args),
            query=self._collect(operation.query_params, resolved_args),
            json_body=self._collect(operation.body_params, resolved_args) or None,
            use_auth=operation.use_auth,
            capture_token=operation.capture_token,
        )
        formatted = self._format_json_response(operation, result, context)
        return self._attach_resolved_fields(
            formatted,
            {
                "map_id": resolved_args.get("map_id"),
                "map_name": resolved_args.get("map_name"),
                "waypoint_id": resolved_args.get("waypoint_id"),
                "waypoint_name": resolved_args.get("waypoint_name"),
            },
        )

    def _run_dock_operation(
        self,
        operation: NavOperationSpec,
        args: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_args = self._resolve_waypoint_reference_args(args, context, waypoint_optional=True)
        result = self.client.request_json(
            operation.method,
            self._build_path(operation, resolved_args),
            query=self._collect(operation.query_params, resolved_args),
            json_body=self._collect(operation.body_params, resolved_args) or None,
            use_auth=operation.use_auth,
            capture_token=operation.capture_token,
        )
        formatted = self._format_json_response(operation, result, context)
        return self._attach_resolved_fields(
            formatted,
            {
                "map_id": resolved_args.get("map_id"),
                "map_name": resolved_args.get("map_name"),
                "waypoint_id": resolved_args.get("waypoint_id"),
                "waypoint_name": resolved_args.get("waypoint_name"),
            },
        )

    def _run_zone_list_operation(
        self,
        operation: NavOperationSpec,
        args: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_args = self._resolve_map_reference_args(args, context)
        result = self.client.request_json(
            operation.method,
            self._build_path(operation, resolved_args),
            query=self._collect(operation.query_params, resolved_args),
            json_body=self._collect(operation.body_params, resolved_args) or None,
            use_auth=operation.use_auth,
            capture_token=operation.capture_token,
        )
        formatted = self._format_json_response(operation, result, context)
        return self._attach_resolved_fields(
            formatted,
            {"map_id": resolved_args.get("map_id"), "map_name": resolved_args.get("map_name")},
        )

    def _resolve_map_reference_args(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        resolved = dict(args)
        explicit_map_name = str(args.get("map_name", "") or "").strip()
        explicit_map_id = resolved.get("map_id")

        if explicit_map_name:
            match = self._match_map_by_reference(explicit_map_name, context=context)
            if match is None:
                raise NavAPIError(f"没有找到名为 {explicit_map_name} 的地图。")
            resolved["map_id"] = int(match.item["id"])
            resolved["map_name"] = str(match.item.get("name", explicit_map_name))
            return resolved

        if explicit_map_id not in (None, ""):
            resolved["map_id"] = int(explicit_map_id)
            return resolved

        match = self._match_map_by_references(self._candidate_map_references(args=args, context=context), context=context)
        if match is not None:
            resolved["map_id"] = int(match.item["id"])
            resolved["map_name"] = str(match.item.get("name", match.reference))
        return resolved

    def _resolve_waypoint_reference_args(
        self,
        args: dict[str, Any],
        context: dict[str, Any],
        *,
        waypoint_optional: bool = False,
    ) -> dict[str, Any]:
        resolved = self._resolve_map_reference_args(args, context)
        explicit_waypoint_id = resolved.get("waypoint_id")
        explicit_waypoint_name = str(args.get("waypoint_name", "") or "").strip()

        if explicit_waypoint_id not in (None, ""):
            resolved["waypoint_id"] = int(explicit_waypoint_id)
            return resolved

        references = self._candidate_waypoint_references(args=args, context=context)
        if explicit_waypoint_name:
            references.insert(0, explicit_waypoint_name)
        references = unique_references(references)
        if not references:
            return resolved

        match = self._match_waypoint_by_references(
            references,
            context=context,
            map_id=resolved.get("map_id"),
            map_name=resolved.get("map_name"),
        )
        if match is None:
            if waypoint_optional:
                return resolved
            target = explicit_waypoint_name or references[0]
            raise NavAPIError(f"没有找到名为 {target} 的路点。")

        resolved["map_id"] = int(match.item["map_id"])
        resolved["map_name"] = str(match.item.get("map_name", resolved.get("map_name", "")) or "")
        resolved["waypoint_id"] = int(match.item["id"])
        resolved["waypoint_name"] = str(match.item.get("name", references[0]))
        return resolved

    def _candidate_map_references(self, args: dict[str, Any], context: dict[str, Any]) -> list[str]:
        references: list[str] = []
        for key in ("map_name", "map_id"):
            value = args.get(key)
            if value not in (None, ""):
                references.append(str(value))

        extracted = self._extract_map_reference(context)
        if extracted:
            references.append(extracted)

        last_map = context.get("last_map")
        if isinstance(last_map, dict):
            if last_map.get("name") not in (None, ""):
                references.append(str(last_map.get("name")))
            if last_map.get("id") not in (None, ""):
                references.append(str(last_map.get("id")))
        return unique_references(references)

    def _candidate_waypoint_references(self, args: dict[str, Any], context: dict[str, Any]) -> list[str]:
        references: list[str] = []
        for key in ("waypoint_name", "waypoint_id"):
            value = args.get(key)
            if value not in (None, ""):
                references.append(str(value))

        for key in ("user_text", "original_text", "task_goal", "text", "query"):
            value = context.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            for pattern in WAYPOINT_REFERENCE_PATTERNS:
                match = re.search(pattern, value)
                if not match:
                    continue
                groups = [item for item in match.groups() if item]
                if groups:
                    references.append(str(groups[-1]).strip())
            references.append(value.strip())

        last_waypoint = context.get("last_waypoint")
        if isinstance(last_waypoint, dict):
            if last_waypoint.get("name") not in (None, ""):
                references.append(str(last_waypoint.get("name")))
            if last_waypoint.get("id") not in (None, ""):
                references.append(str(last_waypoint.get("id")))
        return unique_references(references)

    def _match_map_by_reference(self, reference: str, context: dict[str, Any]) -> EntityMatch | None:
        return self._match_map_by_references([reference], context=context)

    def _match_map_by_references(self, references: list[str], context: dict[str, Any]) -> EntityMatch | None:
        if not references:
            return None
        return best_entity_match(self._fetch_maps(context), references, label_keys=("name",), id_keys=("id", "map_id"))

    def _match_waypoint_by_references(
        self,
        references: list[str],
        *,
        context: dict[str, Any],
        map_id: Any = None,
        map_name: Any = None,
    ) -> EntityMatch | None:
        if not references:
            return None
        candidate_maps: list[dict[str, Any]]
        if map_id not in (None, ""):
            candidate_maps = [{"id": int(map_id), "name": map_name or ""}]
        elif map_name not in (None, ""):
            map_match = self._match_map_by_reference(str(map_name), context=context)
            candidate_maps = [map_match.item] if map_match is not None else []
        else:
            last_map = context.get("last_map")
            if isinstance(last_map, dict) and last_map.get("id") is not None:
                candidate_maps = [last_map]
            else:
                candidate_maps = self._fetch_maps(context)

        best: EntityMatch | None = None
        for map_item in candidate_maps:
            waypoints = self._fetch_waypoints(map_item)
            enriched = []
            for waypoint in waypoints:
                if not isinstance(waypoint, dict):
                    continue
                item = dict(waypoint)
                item.setdefault("map_id", map_item.get("id"))
                item.setdefault("map_name", map_item.get("name"))
                enriched.append(item)
            match = best_entity_match(enriched, references, label_keys=("name",), id_keys=("id", "waypoint_id"))
            if match is not None and (best is None or match.score > best.score):
                best = match
        return best

    def _fetch_tasks(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        cached = context.get("last_task_list")
        if isinstance(cached, list) and cached:
            return [item for item in cached if isinstance(item, dict)]
        try:
            result = self.client.request_json("GET", "/api/nav/tasks")
        except NavAPIError:
            return []
        items = self._extract_collection(self._data_payload(result.data), ("tasks",))
        return [item for item in (items or []) if isinstance(item, dict)]

    def _fetch_maps(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        cached = context.get("last_map_list")
        if isinstance(cached, list) and cached:
            return [item for item in cached if isinstance(item, dict)]
        try:
            result = self.client.request_json("GET", "/api/nav/maps/list")
        except NavAPIError:
            return []
        items = self._extract_collection(self._data_payload(result.data), ("maps",))
        return [item for item in (items or []) if isinstance(item, dict)]

    def _fetch_waypoints(self, map_item: dict[str, Any]) -> list[dict[str, Any]]:
        map_id = map_item.get("id") or map_item.get("map_id")
        if map_id in (None, ""):
            return []
        try:
            result = self.client.request_json("GET", f"/api/nav/maps/{int(map_id)}/waypoints")
        except NavAPIError:
            return []
        items = self._extract_collection(self._data_payload(result.data), ("waypoints",))
        return [item for item in (items or []) if isinstance(item, dict)]

    @staticmethod
    def _attach_resolved_fields(result: dict[str, Any], extra_data: dict[str, Any]) -> dict[str, Any]:
        if not result.get("ok"):
            return result
        payload = result.get("data")
        data = dict(payload) if isinstance(payload, dict) else {}
        for key, value in extra_data.items():
            if value in (None, ""):
                continue
            data[key] = value
        result["data"] = data
        return result

    def _run_light_set_operation(self, args: dict[str, Any]) -> dict[str, Any]:
        code = self._resolve_light_code(args)
        try:
            result = self.realtime_client.publish(
                LIGHT_TOPIC,
                {"data": code},
                msg_type=LIGHT_MSG_TYPE,
                repeat=int(args.get("repeat", 1)),
                interval_ms=int(args.get("interval_ms", 40)),
            )
        except RosbridgeError as exc:
            return {"ok": False, "detail": self._humanize_realtime_error(str(exc))}

        return {
            "ok": True,
            "detail": LIGHT_CODE_MESSAGES.get(code, "灯光已经设置好了。"),
            "data": {"used_code": code, "publish": result.message},
        }

    def _run_navigation_start_operation(
        self,
        operation: NavOperationSpec,
        args: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_args = self._resolve_navigation_start_args(args, context)
        if resolved_args.get("map_id") in (None, ""):
            return {"ok": False, "detail": "启动导航需要地图 ID 或地图名称。"}

        result = self.client.request_json(
            operation.method,
            self._build_path(operation, resolved_args),
            query=self._collect(operation.query_params, resolved_args),
            json_body=self._collect(operation.body_params, resolved_args) or None,
            use_auth=operation.use_auth,
            capture_token=operation.capture_token,
        )
        return self._format_json_response(operation, result, context)

    def _resolve_navigation_start_args(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        resolved = dict(args)
        explicit_map_name = str(args.get("map_name", "") or "").strip()
        inferred_map_name = self._extract_map_reference(context)
        map_name = explicit_map_name or inferred_map_name

        if map_name:
            map_item = self._lookup_map_by_name(map_name)
            if map_item is None:
                raise NavAPIError(f"没有找到名为 {map_name} 的地图。")
            resolved["map_id"] = int(map_item["id"])
            resolved["map_name"] = str(map_item.get("name", map_name))
            return resolved

        map_id = resolved.get("map_id")
        if map_id not in (None, ""):
            resolved["map_id"] = int(map_id)
        return resolved

    def _lookup_map_by_name(self, map_name: str) -> dict[str, Any] | None:
        try:
            result = self.client.request_json("GET", "/api/nav/maps/list")
        except NavAPIError:
            return None

        maps = self._extract_collection(self._data_payload(result.data), ("maps",))
        if not maps:
            return None

        normalized_target = self._normalize_text(map_name)
        for item in maps:
            if not isinstance(item, dict):
                continue
            candidate_name = str(item.get("name", "") or "")
            if self._normalize_text(candidate_name) == normalized_target:
                return item
        for item in maps:
            if not isinstance(item, dict):
                continue
            candidate_name = str(item.get("name", "") or "")
            if normalized_target and normalized_target in self._normalize_text(candidate_name):
                return item
        return None

    def _extract_map_reference(self, context: dict[str, Any]) -> str:
        for key in ("user_text", "original_text", "task_goal", "text", "query"):
            value = context.get(key)
            if not isinstance(value, str):
                continue
            for pattern in MAP_REFERENCE_PATTERNS:
                match = re.search(pattern, value)
                if not match:
                    continue
                candidate = match.group(1).strip()
                if candidate and not candidate.isdigit():
                    return candidate
        return ""

    def _run_status_snapshot_operation(self, operation: NavOperationSpec, context: dict[str, Any]) -> dict[str, Any]:
        snapshot = self._collect_status_snapshot()
        if operation.action == "charging_status":
            detail = self._charging_message(snapshot)
            data = {
                "charging": snapshot.get("charging"),
                "bms_state": snapshot.get("bms_state"),
                "battery_soc": snapshot.get("battery_soc"),
            }
            return {"ok": True, "detail": detail, "data": data}
        if operation.action == "battery_soc":
            soc = snapshot.get("battery_soc")
            if soc is None:
                return {"ok": False, "detail": "暂时没有拿到电量数据。"}
            return {"ok": True, "detail": f"当前电量约为 {soc:.1f}%。", "data": {"battery_soc": soc}}

        detail_parts: list[str] = []
        nav_running = snapshot.get("nav_running")
        if nav_running is True:
            detail_parts.append("我现在正在导航")
        elif nav_running is False:
            detail_parts.append("我现在没有在导航")
        charging = snapshot.get("charging")
        if charging is True:
            detail_parts.append("正在充电")
        elif charging is False:
            detail_parts.append("当前没有在充电")
        soc = snapshot.get("battery_soc")
        if isinstance(soc, float):
            detail_parts.append(f"电量约 {soc:.1f}%")
        detail = "，".join(detail_parts) + "。" if detail_parts else "我查到当前状态了。"
        return {"ok": True, "detail": detail, "data": snapshot}

    def _collect_status_snapshot(self) -> dict[str, Any]:
        snapshot: dict[str, Any] = {}
        try:
            nav_state = self.client.request_json("GET", "/api/nav/nav/state")
            nav_payload = self._data_payload(nav_state.data)
            if isinstance(nav_payload, dict):
                snapshot.update(nav_payload)
        except NavAPIError:
            pass

        try:
            bms_state = self.realtime_client.subscribe_once(BMS_STATE_TOPIC, msg_type=BMS_MSG_TYPE).message.get("data")
            if isinstance(bms_state, (int, float)):
                snapshot["bms_state"] = float(bms_state)
                snapshot["charging"] = float(bms_state) > 0
        except RosbridgeError:
            pass

        try:
            bms_soc = self.realtime_client.subscribe_once(BMS_SOC_TOPIC, msg_type=BMS_MSG_TYPE).message.get("data")
            if isinstance(bms_soc, (int, float)):
                snapshot["battery_soc"] = float(bms_soc)
        except RosbridgeError:
            pass

        return snapshot

    @staticmethod
    def _charging_message(snapshot: dict[str, Any]) -> str:
        charging = snapshot.get("charging")
        soc = snapshot.get("battery_soc")
        suffix = f" 当前电量约 {soc:.1f}%。" if isinstance(soc, float) else ""
        if charging is True:
            return "我现在正在充电。" + (suffix.lstrip() if suffix else "")
        if charging is False:
            return "我现在没有在充电。" + (suffix.lstrip() if suffix else "")
        return "暂时还无法确认是否在充电。"

    @staticmethod
    def _humanize_realtime_error(detail: str) -> str:
        lowered = detail.lower()
        if "connection refused" in lowered:
            return "实时控制服务没连上，请确认 rosbridge 已启动。"
        if "timed out" in lowered:
            return "实时控制服务响应超时，请检查 rosbridge 或机器人状态。"
        if "missing dependency" in lowered:
            return "缺少 websocket-client 依赖，请先安装后再使用实时控制。"
        return detail

    @staticmethod
    def _humanize_nav_api_error(detail: str) -> str:
        lowered = detail.lower()
        if "timed out" not in lowered:
            return detail
        if "/api/nav/events/wait_nav_started" in lowered:
            return "等待导航启动超时，请确认导航服务已经启动，或稍后再试。"
        if "/api/nav/events/wait_arrival" in lowered:
            return "等待到达目标超时，可能还在路上，或者事件服务没有回报到达。"
        if "/api/nav/events/wait_dock_complete" in lowered:
            return "等待回充完成超时，请确认回充流程是否正常。"
        return "导航服务响应超时，请检查导航后端状态。"

    def _run_text_operation(self, operation: NavOperationSpec, args: dict[str, Any]) -> dict[str, Any]:
        result = self.client.request_text(
            operation.method,
            self._build_path(operation, args),
            query=self._collect(operation.query_params, args),
            json_body=self._collect(operation.body_params, args) or None,
            use_auth=operation.use_auth,
            timeout_sec=self._request_timeout_for_operation(operation, args),
        )
        save_to = args.get("save_to")
        if save_to:
            saved_path = self.client.save_text(result.data, str(save_to))
            return {
                "ok": True,
                "detail": f"结果已经保存到 {saved_path}。",
                "data": {"path": saved_path, "content_type": result.content_type, "url": result.url},
            }

        preview = self._compact_preview(result.data)
        return {
            "ok": True,
            "detail": preview or operation.description,
            "data": {"content_type": result.content_type, "url": result.url, "preview": preview},
        }

    def _run_binary_operation(self, operation: NavOperationSpec, args: dict[str, Any]) -> dict[str, Any]:
        result = self.client.request_binary(
            operation.method,
            self._build_path(operation, args),
            query=self._collect(operation.query_params, args),
            use_auth=operation.use_auth,
            timeout_sec=self._request_timeout_for_operation(operation, args),
        )
        save_to = args.get("save_to")
        payload = result.data if isinstance(result.data, bytes) else bytes(result.data)
        if save_to:
            saved_path = self.client.save_binary(payload, str(save_to))
            return {
                "ok": True,
                "detail": f"文件已经保存到 {saved_path}。",
                "data": {"path": saved_path, "size": len(payload), "content_type": result.content_type, "url": result.url},
            }

        return {
            "ok": True,
            "detail": f"已经拿到 {len(payload)} 字节的数据，需要的话可以加 save_to 保存文件。",
            "data": {"size": len(payload), "content_type": result.content_type, "url": result.url},
        }

    def _run_file_operation(
        self,
        operation: NavOperationSpec,
        args: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        files = {
            self._form_field_name(name): str(args[name])
            for name in operation.file_params
            if args.get(name) not in (None, "")
        }
        result = self.client.upload_file(
            operation.method,
            self._build_path(operation, args),
            files=files,
            fields=self._collect(operation.body_params, args),
            use_auth=operation.use_auth,
            timeout_sec=self._request_timeout_for_operation(operation, args),
        )
        return self._format_json_response(operation, result, context)

    def _request_timeout_for_operation(self, operation: NavOperationSpec, args: dict[str, Any]) -> int | float | None:
        if self.name != "robot_events":
            return None

        timeout_value = args.get("timeout")
        if timeout_value in (None, ""):
            return None

        try:
            requested_timeout = float(timeout_value)
        except (TypeError, ValueError):
            return None
        if requested_timeout <= 0:
            return None

        base_timeout = float(getattr(self.client, "timeout_sec", 15))
        return max(base_timeout, requested_timeout + 5.0)

    def _format_json_response(
        self,
        operation: NavOperationSpec,
        result: NavAPIResult,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        payload = result.data
        if not self._is_success(payload, result.status_code):
            return {
                "ok": False,
                "detail": self._error_message(payload, result.status_code),
                "data": self._data_payload(payload),
            }
        return {
            "ok": True,
            "detail": self._success_message(operation, payload, context),
            "data": self._data_payload(payload),
        }

    def _build_path(self, operation: NavOperationSpec, args: dict[str, Any]) -> str:
        values: dict[str, str] = {}
        for key in operation.path_params:
            raw_value = args.get(key)
            if raw_value in (None, ""):
                raise NavAPIError(f"Missing path parameter: {key}")
            values[key] = urlparse.quote(str(raw_value), safe="")
        try:
            return operation.path.format(**values)
        except KeyError as exc:
            raise NavAPIError(f"Missing path parameter: {exc.args[0]}") from exc

    @staticmethod
    def _collect(keys: tuple[str, ...], args: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key in keys:
            if args.get(key) not in (None, ""):
                payload[key] = args[key]
        return payload

    def _normalize_operation_args(self, operation: NavOperationSpec, args: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(args)
        if self.name == "robot_light" and operation.action == "set":
            normalized = self._normalize_light_args(normalized)
        return normalized

    @staticmethod
    def _normalize_light_args(args: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(args)
        on = normalized.get("on")
        code = normalized.get("code")
        if on is True and code in (None, ""):
            normalized["code"] = 11
            normalized.pop("on", None)
        elif on is False and code in (None, ""):
            normalized["code"] = LIGHT_OFF_CODE
            normalized.pop("on", None)
        elif on is True and code not in (None, ""):
            normalized.pop("on", None)
        elif on is False and code not in (None, ""):
            normalized.pop("on", None)
        return normalized

    @staticmethod
    def _form_field_name(arg_name: str) -> str:
        if arg_name.endswith("_path"):
            return arg_name[: -len("_path")]
        return arg_name

    @staticmethod
    def _resolve_light_code(args: dict[str, Any]) -> int:
        code = args.get("code")
        if code not in (None, ""):
            return int(code)
        on = args.get("on")
        if on is False:
            return LIGHT_OFF_CODE
        return 11

    def _success_message(self, operation: NavOperationSpec, payload: Any, context: dict[str, Any]) -> str:
        data = self._data_payload(payload)
        reply = self._conversation_message(operation, data, context)
        if reply:
            return reply

        message = self._message_from_payload(payload)
        preview = self._conversation_preview(data, context)
        if message and not self._is_generic_success_message(message):
            return f"{message}：{preview}" if preview else message
        return preview or operation.description

    def _conversation_message(
        self,
        operation: NavOperationSpec,
        data: Any,
        context: dict[str, Any],
    ) -> str:
        if operation.action == "login":
            return "登录成功。"
        if operation.action in {"get_current_position", "current_pose"} and isinstance(data, dict):
            return f"我现在在 x={data.get('x')}, y={data.get('y')}, yaw={data.get('yaw')}。"
        if operation.action == "get_state" and isinstance(data, dict):
            return "我现在正在导航。" if data.get("nav_running") else "我现在没有在导航。"

        if self.name == "robot_tasks" and operation.action == "get" and isinstance(data, dict):
            return self._task_description_message(data)

        if self.name == "robot_light" and operation.action == "set":
            if isinstance(data, dict):
                used_code = data.get("used_code")
                if used_code in LIGHT_CODE_MESSAGES:
                    return LIGHT_CODE_MESSAGES[used_code]
            return "灯光已经设置好了。"

        if self.name == "robot_navigation" and operation.action == "goto_waypoint":
            if isinstance(data, dict) and data.get("waypoint_id") is not None:
                return f"正在前往路点 {data.get('waypoint_id')}。"
            return "已经开始前往目标路点。"
        if self.name == "robot_navigation" and operation.action == "goto_point":
            return "已经开始前往目标坐标。"
        if self.name == "robot_navigation" and operation.action == "stop":
            return "已经停止导航。"
        if self.name == "robot_navigation" and operation.action == "pause_goto_waypoint":
            return "已经暂停导航。"
        if self.name == "robot_navigation" and operation.action == "resume_goto_waypoint":
            return "已经恢复导航。"

        if self.name == "robot_audio" and operation.action == "tts_play":
            return "好，我来播报。"

        collection_reply = self._conversation_collection_message(operation, data, context)
        if collection_reply:
            return collection_reply

        if self.name == "robot_auth" and operation.action == "user_info":
            preview = self._summarize_fields(data, ("username", "nickname", "name", "role"))
            return f"我查到当前登录用户是：{preview}。" if preview else "我查到当前登录用户信息了。"

        if self.name == "robot_settings" and operation.action == "get_device_id":
            device_id = self._extract_scalar(data, ("device_id", "id"))
            if device_id is not None:
                return f"设备 ID 是 {device_id}。"
        if self.name == "robot_settings" and operation.action in {"get_setting", "get_core_setting"}:
            preview = self._summarize_fields(data, ("name", "value", "key"))
            return f"我查到的设置是：{preview}。" if preview else "我查到这个设置项了。"
        if self.name == "robot_settings" and operation.action == "get_battery_low_threshold":
            threshold = self._extract_scalar(data, ("threshold", "value"))
            if threshold is not None:
                return f"当前低电量阈值是 {threshold}。"

        if self.name == "robot_status" and operation.action == "arrived":
            arrived = self._extract_bool(data, ("arrived", "is_arrived"))
            if arrived is True:
                return "我已经到达目标点了。"
            if arrived is False:
                return "我还没有到达目标点。"
        if self.name == "robot_status" and operation.action in {"health", "status"}:
            preview = self._summarize_fields(data, ("status", "state", "battery", "battery_level", "mode"))
            return f"我现在的状态是：{preview}。" if preview else "我查到当前状态了。"

        if self.name == "robot_events" and operation.action in {"state", "wait_arrival", "wait_nav_started", "wait_dock_complete"}:
            preview = self._summarize_fields(data, ("state", "event", "waypoint_id", "docked"))
            return f"事件状态是：{preview}。" if preview else "我查到事件状态了。"

        if operation.action == "get" and isinstance(data, dict):
            preview = self._summarize_fields(data)
            return f"我查到的详情是：{preview}。" if preview else ""

        return ""

    def _conversation_collection_message(
        self,
        operation: NavOperationSpec,
        data: Any,
        context: dict[str, Any],
    ) -> str:
        if self.name == "robot_maps" and operation.action == "list":
            return self._summarize_collection_reply("地图", self._extract_collection(data, ("maps",)), context)
        if self.name == "robot_waypoints" and operation.action == "list":
            return self._summarize_collection_reply("路点", self._extract_collection(data, ("waypoints",)), context)
        if self.name == "robot_tasks" and operation.action == "list":
            return self._summarize_collection_reply("任务", self._extract_collection(data, ("tasks",)), context)
        if self.name == "robot_audio_tasks" and operation.action == "list":
            return self._summarize_collection_reply("音频任务", self._extract_collection(data, ("tasks", "audio_tasks")), context)
        if self.name == "robot_reports" and operation.action == "list":
            return self._summarize_collection_reply("报告", self._extract_collection(data, ("reports",)), context, unit="份")
        if self.name == "robot_patrol_routes" and operation.action == "list":
            return self._summarize_collection_reply("巡检路线", self._extract_collection(data, ("routes", "patrol_routes")), context)
        if self.name == "robot_zones" and operation.action == "list":
            return self._summarize_collection_reply("区域", self._extract_collection(data, ("zones",)), context)
        if self.name == "robot_events" and operation.action in {"poll", "history"}:
            return self._summarize_collection_reply("事件", self._extract_collection(data, ("events",)), context, unit="条")
        if self.name == "robot_settings" and operation.action in {"list_settings", "list_core_settings"}:
            return self._summarize_collection_reply("设置项", self._extract_collection(data, ("settings",)), context)
        return ""

    def _conversation_preview(self, data: Any, context: dict[str, Any]) -> str:
        if data in (None, "", [], {}):
            return ""
        collection = self._extract_collection(data)
        if collection is not None:
            return self._summarize_collection_reply("记录", collection, context, unit="条")
        if isinstance(data, dict):
            preview = self._summarize_fields(data)
            return f"我查到这些信息：{preview}。" if preview else self._summarize_data(data)
        if isinstance(data, bool):
            return "结果是：是。" if data else "结果是：否。"
        if isinstance(data, (int, float, str)):
            return f"我查到的结果是：{self._format_value(data)}。"
        return self._summarize_data(data)

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

        list_values = [value for value in data.values() if isinstance(value, list)]
        if len(list_values) == 1:
            return list_values[0]
        return None

    def _summarize_collection_reply(
        self,
        label: str,
        items: list[Any] | None,
        context: dict[str, Any],
        unit: str = "个",
    ) -> str:
        if items is None:
            return ""
        if not items:
            return f"我这边还没查到{label}。"

        names = [name for item in items if (name := self._extract_item_label(item))]
        if self._wants_full_list(context) and names:
            return f"我查到 {len(items)} {unit}{label}，分别是：{'、'.join(names)}。"

        if names:
            preview = "、".join(names[:3])
            suffix = " 等" if len(items) > 3 else ""
            return f"我查到 {len(items)} {unit}{label}，当前有 {preview}{suffix}。"
        return f"我查到 {len(items)} {unit}{label}。"

    def _task_description_message(self, task: dict[str, Any]) -> str:
        label = task.get("name") or task.get("id") or "这个任务"
        description = str(task.get("description", "") or "").strip()
        if description:
            suffix = "" if description.endswith(("。", "！", "？", ".", "!", "?")) else "。"
            return f"任务 {label} 的描述是：{description}{suffix}"
        return f"任务 {label} 存在，但描述为空。"

    def _extract_item_label(self, item: Any) -> str:
        if isinstance(item, dict):
            for key in ("name", "title", "nickname", "filename", "key"):
                value = item.get(key)
                if value not in (None, ""):
                    return self._compact_preview(str(value))
            for key in ("id", "task_id", "report_id", "map_id", "waypoint_id"):
                value = item.get(key)
                if value not in (None, ""):
                    return f"ID {value}"
            return self._summarize_fields(item)
        if item not in (None, ""):
            return self._compact_preview(str(item))
        return ""

    def _summarize_fields(self, data: Any, preferred_keys: tuple[str, ...] = ()) -> str:
        if not isinstance(data, dict):
            return ""

        seen: set[str] = set()
        parts: list[str] = []
        keys = preferred_keys + tuple(data.keys())
        for key in keys:
            if key in seen or key not in data:
                continue
            value = data.get(key)
            if value in (None, "", [], {}):
                continue
            if isinstance(value, (dict, list)):
                continue
            seen.add(key)
            parts.append(f"{key}={self._format_value(value)}")
            if len(parts) >= 4:
                break
        return "，".join(parts)

    @staticmethod
    def _format_value(value: Any) -> str:
        if isinstance(value, bool):
            return "是" if value else "否"
        if isinstance(value, float):
            return f"{value:.3f}".rstrip("0").rstrip(".")
        return str(value)

    def _extract_scalar(self, data: Any, keys: tuple[str, ...]) -> Any:
        if isinstance(data, dict):
            for key in keys:
                if data.get(key) not in (None, ""):
                    return data.get(key)
            return None
        if data not in (None, "", [], {}):
            return data
        return None

    @staticmethod
    def _extract_bool(data: Any, keys: tuple[str, ...]) -> bool | None:
        if isinstance(data, bool):
            return data
        if isinstance(data, dict):
            for key in keys:
                value = data.get(key)
                if isinstance(value, bool):
                    return value
        return None

    @staticmethod
    def _message_from_payload(payload: Any) -> str:
        if isinstance(payload, dict):
            for key in ("msg", "message"):
                value = payload.get(key)
                if isinstance(value, str) and value:
                    return value
        return ""

    @staticmethod
    def _is_generic_success_message(message: str) -> bool:
        normalized = re.sub(r"\s+", " ", message).strip().lower()
        if normalized in {"ok", "success", "done"}:
            return True
        return "成功" in message or "已完成" in message

    @staticmethod
    def _data_payload(payload: Any) -> Any:
        if isinstance(payload, dict) and "data" in payload:
            return payload.get("data")
        return payload

    @staticmethod
    def _is_success(payload: Any, status_code: int) -> bool:
        if isinstance(payload, dict):
            if payload.get("error"):
                return False
            code = payload.get("code")
            if code is not None:
                return code in (0, 200)
        return 200 <= status_code < 300

    @staticmethod
    def _error_message(payload: Any, status_code: int) -> str:
        if isinstance(payload, dict):
            for key in ("msg", "message", "error"):
                value = payload.get(key)
                if isinstance(value, str) and value:
                    return value
        return f"Nav API request failed with status {status_code}."

    @staticmethod
    def _is_not_found_error(exc: NavAPIError) -> bool:
        text = str(exc)
        return "HTTP 404" in text or "不存在" in text

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"\s+", "", value).strip().lower()

    @staticmethod
    def _summarize_data(data: Any) -> str:
        if data in (None, "", [], {}):
            return ""
        if isinstance(data, str):
            return GroupedNavSkill._compact_preview(data)
        try:
            preview = json.dumps(data, ensure_ascii=False)
        except TypeError:
            preview = str(data)
        return preview if len(preview) <= 220 else f"{preview[:217]}..."

    @staticmethod
    def _compact_preview(text: str) -> str:
        compact = re.sub(r"\s+", " ", text).strip()
        return compact if len(compact) <= 220 else f"{compact[:217]}..."

    @staticmethod
    def _wants_full_list(context: dict[str, Any]) -> bool:
        for key in ("user_text", "original_text", "task_goal", "text", "query"):
            value = context.get(key)
            if not isinstance(value, str):
                continue
            if any(token in value for token in FULL_LIST_KEYWORDS):
                return True
        return False

    @staticmethod
    def _is_task_followup(context: dict[str, Any]) -> bool:
        for key in ("user_text", "original_text", "task_goal", "text", "query"):
            value = context.get(key)
            if not isinstance(value, str):
                continue
            if any(token in value for token in TASK_PRONOUNS + TASK_FOLLOWUP_KEYWORDS):
                return True
        return False

    def _coerce_args(self, args: dict[str, Any]) -> dict[str, Any]:
        properties = self.input_schema.get("properties", {})
        normalized: dict[str, Any] = {}
        for key, value in args.items():
            schema = properties.get(key)
            normalized[key] = self._coerce_value(key, value, schema)
        return normalized

    def _coerce_value(self, key: str, value: Any, schema: dict[str, Any] | None) -> Any:
        if value is None or schema is None:
            return value

        field_type = schema.get("type")
        if field_type == "integer":
            try:
                return int(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key} must be an integer.") from exc
        if field_type == "number":
            try:
                return float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key} must be a number.") from exc
        if field_type == "boolean":
            if isinstance(value, bool):
                return value
            lowered = str(value).strip().lower()
            if lowered in {"1", "true", "yes", "y", "on"}:
                return True
            if lowered in {"0", "false", "no", "n", "off"}:
                return False
            raise ValueError(f"{key} must be a boolean.")
        if field_type == "array":
            if isinstance(value, list):
                items = value
            elif isinstance(value, str):
                stripped = value.strip()
                if stripped.startswith("["):
                    items = json.loads(stripped)
                else:
                    items = [item.strip() for item in stripped.split(",") if item.strip()]
            else:
                raise ValueError(f"{key} must be an array.")
            item_schema = schema.get("items")
            return [self._coerce_value(key, item, item_schema) for item in items]
        if field_type == "object":
            if isinstance(value, dict):
                return value
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{key} must be a JSON object.") from exc
                if not isinstance(parsed, dict):
                    raise ValueError(f"{key} must be a JSON object.")
                return parsed
            raise ValueError(f"{key} must be an object.")
        if field_type == "string":
            if key in JSONISH_FIELDS and isinstance(value, str):
                return self._parse_jsonish_string(value)
            if isinstance(value, (dict, list)) and key in JSONISH_FIELDS:
                return value
            return str(value)
        return value

    @staticmethod
    def _parse_jsonish_string(value: str) -> Any:
        stripped = value.strip()
        if not stripped:
            return value
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return value
        if stripped.lower() in {"true", "false", "null"}:
            try:
                return json.loads(stripped.lower())
            except json.JSONDecodeError:
                return value
        if re.fullmatch(r"-?\d+(\.\d+)?", stripped):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return value
        return value

    def _resolve_navigation_start_args(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        return self._resolve_map_reference_args(args, context)

    def _lookup_map_by_name(self, map_name: str) -> dict[str, Any] | None:
        match = self._match_map_by_reference(map_name, context={})
        return match.item if match is not None else None

    @staticmethod
    def _normalize_text(value: str) -> str:
        return normalize_entity_text(value)


def register_nav_api_skills(
    registry: SkillRegistry,
    client: NavAPIClient | None = None,
    motion_client: Any | None = None,
) -> None:
    from fishmindos.skill_runtime.assistant_skills import register_macro_skills

    shared_client = client or NavAPIClient.from_env()
    shared_realtime_client = motion_client or RosbridgeClient.from_env()
    for group in NAV_SKILL_GROUPS:
        registry.register(GroupedNavSkill(group=group, client=shared_client, realtime_client=shared_realtime_client))
    registry.register(DogMotionSkill(client=shared_realtime_client))
    register_macro_skills(registry)
