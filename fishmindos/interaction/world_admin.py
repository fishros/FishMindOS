from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from fishmindos.config import FishMindConfig, set_config
from fishmindos.world import WorldBuilder, WorldStore


class WorldAdminError(RuntimeError):
    """Base error for world admin operations."""


class WorldAdminNotFoundError(WorldAdminError):
    """Raised when requested world data cannot be found."""


class WorldAdminBusyError(WorldAdminError):
    """Raised when world mutations are blocked by active session work."""


class WorldAdminService:
    """Shared world management logic for terminal and Android clients."""

    def __init__(self, manager) -> None:
        self.manager = manager

    def get_state(self, session_id: str) -> Dict[str, Any]:
        session = self._require_session(session_id)
        config = self._load_config()
        world_path = self._resolve_world_path(config)
        world = WorldStore(world_path).load()
        adapter = self._require_adapter()
        maps = adapter.list_maps()
        default_map = self._serialize_default_map(world.default_map_id, world.default_map_name)
        return {
            "ok": True,
            "session_id": session.session_id,
            "world_name": world.name,
            "world_path": self._path_for_response(world_path),
            "default_map": default_map,
            "maps": [self._serialize_map(item, default_map) for item in maps],
            "locations": [self._serialize_location(item) for item in world.locations],
        }

    def set_default_map(self, session_id: str, map_id: int) -> Dict[str, Any]:
        self._ensure_mutation_allowed(session_id)
        adapter = self._require_adapter()
        maps = adapter.list_maps()
        selected_map = next((item for item in maps if getattr(item, "id", None) == map_id), None)
        if selected_map is None:
            raise WorldAdminNotFoundError(f"地图 {map_id} 不存在")

        world_path = self.manager.build_world_profile_path(selected_map.name)
        world = WorldBuilder(adapter).import_map_to_world(
            world_path=world_path,
            map_id=selected_map.id,
            world_name=f"{selected_map.name}世界",
            replace_map_locations=True,
            set_default=True,
        )

        config = self._load_config()
        config.world.path = self._path_for_config(world_path)
        config.save_to_file(str(self.manager.config_path))
        set_config(config)

        self.manager.reload_world(world_path, config, session_id=session_id)
        self.manager._emit_session_state(session_id)

        state = self.get_state(session_id)
        state["message"] = f"已将 {selected_map.name} 设为默认 world，后续将优先使用 {world.name}。"
        return state

    def update_location(
        self,
        session_id: str,
        *,
        name: str,
        map_id: Optional[int] = None,
        map_name: Optional[str] = None,
        waypoint_id: Optional[int] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        task_hints: Optional[List[str]] = None,
        relations: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        self._ensure_mutation_allowed(session_id)
        config = self._load_config()
        world_path = self._resolve_world_path(config)
        store = WorldStore(world_path)
        world = store.load()
        location = self._find_location(
            world.locations,
            name=name,
            map_id=map_id,
            map_name=map_name,
            waypoint_id=waypoint_id,
        )
        if location is None:
            raise WorldAdminNotFoundError(f"未找到地点: {name}")

        if description is not None:
            location.description = description.strip()
        if category is not None:
            location.category = category.strip()
        if aliases is not None:
            location.aliases = self._normalize_csv_values(aliases)
        if task_hints is not None:
            location.task_hints = self._normalize_csv_values(task_hints)
        if relations is not None:
            location.relations = self._normalize_relations(relations)

        store.save(world)
        self.manager.reload_world(world_path, config, session_id=session_id)
        self.manager._emit_session_state(session_id)

        return {
            "ok": True,
            "message": f"已保存地点 {location.name}",
            "location": self._serialize_location(location),
            "state": self.get_state(session_id),
        }

    def batch_ai_enrich(self, session_id: str) -> Dict[str, Any]:
        self._ensure_mutation_allowed(session_id)
        config = self._load_config()
        world_path = self._resolve_world_path(config)
        store = WorldStore(world_path)
        world = store.load()

        targets = [
            loc
            for loc in world.locations
            if not loc.description or not list(getattr(loc, "aliases", None) or []) or not list(getattr(loc, "task_hints", None) or [])
        ]
        if not targets:
            return {
                "ok": True,
                "updated_count": 0,
                "total_count": 0,
                "message": "当前 world 已无需 AI 补全。",
                "state": self.get_state(session_id),
            }

        updated_count = 0
        for loc in targets:
            suggestion = self._suggest_location_semantics_with_llm(loc.name, world.name)
            if not suggestion:
                continue
            if suggestion.get("description") and not loc.description:
                loc.description = str(suggestion["description"]).strip()
            if suggestion.get("category") and not loc.category:
                loc.category = str(suggestion["category"]).strip()

            ai_aliases = self._normalize_csv_values(suggestion.get("aliases") or [])
            if ai_aliases:
                existing_aliases = list(loc.aliases or [])
                loc.aliases = existing_aliases + [item for item in ai_aliases if item not in existing_aliases]

            ai_hints = self._normalize_csv_values(suggestion.get("task_hints") or [])
            if ai_hints:
                existing_hints = list(loc.task_hints or [])
                loc.task_hints = existing_hints + [item for item in ai_hints if item not in existing_hints]

            updated_count += 1

        store.save(world)
        self.manager.reload_world(world_path, config, session_id=session_id)
        self.manager._emit_session_state(session_id)

        return {
            "ok": True,
            "updated_count": updated_count,
            "total_count": len(targets),
            "message": f"AI 补全完成，已更新 {updated_count}/{len(targets)} 个地点。",
            "state": self.get_state(session_id),
        }

    @staticmethod
    def parse_csv_values(raw: str) -> List[str]:
        return [value.strip() for value in str(raw or "").split(",") if value.strip()]

    @staticmethod
    def format_relations(relations: List[Dict[str, str]]) -> str:
        chunks = []
        for relation in list(relations or [])[:3]:
            relation_type = str(relation.get("type", "")).strip()
            target = str(relation.get("target", "")).strip()
            note = str(relation.get("note", "")).strip()
            if not relation_type or not target:
                continue
            chunk = f"{relation_type}:{target}"
            if note:
                chunk += f":{note}"
            chunks.append(chunk)
        return ", ".join(chunks)

    @classmethod
    def parse_relations(cls, raw: str) -> List[Dict[str, str]]:
        relations: List[Dict[str, str]] = []
        for item in cls.parse_csv_values(raw):
            parts = [part.strip() for part in item.split(":", 2)]
            if len(parts) < 2 or not parts[0] or not parts[1]:
                continue
            relation = {"type": parts[0], "target": parts[1]}
            if len(parts) == 3 and parts[2]:
                relation["note"] = parts[2]
            relations.append(relation)
        return relations

    def _require_session(self, session_id: str):
        session = self.manager.sessions.get(session_id)
        if session is None:
            raise WorldAdminNotFoundError(f"session '{session_id}' not found")
        return session

    def _require_adapter(self):
        adapter = self.manager.get_adapter()
        if adapter is None:
            raise WorldAdminError("适配器未初始化，无法读取或设置 world。")
        return adapter

    def _ensure_mutation_allowed(self, session_id: str) -> None:
        self._require_session(session_id)
        if self.manager.is_world_mutation_blocked(session_id):
            raise WorldAdminBusyError("当前会话正在执行任务、等待确认或思考中，请稍后再修改 world。")

    def _load_config(self) -> FishMindConfig:
        config = FishMindConfig.from_file(str(self.manager.config_path))
        set_config(config)
        return config

    def _resolve_world_path(self, config: FishMindConfig) -> Path:
        world_path = getattr(config.world, "path", None)
        if not world_path:
            raise WorldAdminError("未配置 world.path，无法管理 world。")
        return self.manager.resolve_world_path(world_path)

    def _path_for_config(self, path: Path) -> str:
        try:
            return path.relative_to(Path.cwd()).as_posix()
        except ValueError:
            return str(path)

    def _path_for_response(self, path: Path) -> str:
        try:
            return path.relative_to(Path.cwd()).as_posix()
        except ValueError:
            return str(path)

    def _serialize_default_map(self, map_id: Optional[int], map_name: Optional[str]) -> Dict[str, Any]:
        return {
            "id": map_id,
            "name": map_name,
        }

    def _serialize_map(self, map_info, default_map: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": getattr(map_info, "id", None),
            "name": getattr(map_info, "name", ""),
            "is_default": getattr(map_info, "id", None) == default_map.get("id")
            or getattr(map_info, "name", None) == default_map.get("name"),
        }

    def _serialize_location(self, location) -> Dict[str, Any]:
        return {
            "name": location.name,
            "map_id": location.map_id,
            "map_name": location.map_name,
            "waypoint_id": location.waypoint_id,
            "waypoint_name": location.waypoint_name,
            "location_type": location.location_type,
            "description": location.description,
            "category": location.category,
            "aliases": list(location.aliases or []),
            "task_hints": list(location.task_hints or []),
            "relations": self._normalize_relations(location.relations or []),
        }

    def _find_location(
        self,
        locations,
        *,
        name: str,
        map_id: Optional[int],
        map_name: Optional[str],
        waypoint_id: Optional[int],
    ):
        if map_id is not None and waypoint_id is not None:
            for item in locations:
                if item.map_id == map_id and item.waypoint_id == waypoint_id:
                    return item
        normalized_name = str(name or "").strip()
        normalized_map_name = str(map_name or "").strip()
        for item in locations:
            if item.name != normalized_name:
                continue
            if normalized_map_name and item.map_name and item.map_name != normalized_map_name:
                continue
            if map_id is not None and item.map_id is not None and item.map_id != map_id:
                continue
            return item
        return None

    def _normalize_csv_values(self, values: List[str]) -> List[str]:
        normalized: List[str] = []
        seen = set()
        for raw in list(values or []):
            value = str(raw or "").strip()
            if not value or value in seen:
                continue
            normalized.append(value)
            seen.add(value)
        return normalized

    def _normalize_relations(self, relations: List[Dict[str, str]]) -> List[Dict[str, str]]:
        normalized: List[Dict[str, str]] = []
        for relation in list(relations or []):
            relation_type = str(relation.get("type", "")).strip()
            target = str(relation.get("target", "")).strip()
            note = str(relation.get("note", "")).strip()
            if not relation_type or not target:
                continue
            item = {"type": relation_type, "target": target}
            if note:
                item["note"] = note
            normalized.append(item)
        return normalized

    def _suggest_location_semantics_with_llm(self, location_name: str, world_name: str) -> Optional[Dict[str, Any]]:
        brain = getattr(self.manager, "brain", None)
        llm = getattr(brain, "llm", None)
        if llm is None:
            raise WorldAdminError("LLM 未配置，无法执行 AI 补全。")
        try:
            from fishmindos.brain.llm_providers import LLMMessage
        except Exception as exc:
            raise WorldAdminError(f"LLM provider 不可用: {exc}") from exc

        system_msg = (
            "你是一个熟悉室内服务机器人场景的专家。"
            "根据地点名称和地图名，为该地点生成语义标注。"
            "只输出严格的 JSON 对象，不要任何解释和代码块标记。"
            "JSON 字段："
            "description（一句话描述，20字内），"
            "category（英文单词，例如 office/reception/toilet/kitchen/corridor/lab/meeting_room/warehouse/general/waypoint），"
            "aliases（尽量多的中文别名列表，至少3个），"
            "task_hints（机器人在此处常见任务列表，至少3条）。"
        )
        user_msg = f"地图名: {world_name}\n地点名: {location_name}"

        result_holder: List[Optional[Dict[str, Any]]] = [None]
        error_holder: List[Optional[str]] = [None]

        def _call() -> None:
            try:
                resp = llm.chat(
                    messages=[
                        LLMMessage(role="system", content=system_msg),
                        LLMMessage(role="user", content=user_msg),
                    ],
                    tools=None,
                    temperature=0.3,
                    max_tokens=600,
                    extra_body={"thinking": {"type": "enabled", "budget_tokens": 300}},
                )
                text = (resp.content or "").strip()
                if not text:
                    error_holder[0] = "LLM 返回了空内容"
                    return
                text = re.sub(r"^```[a-z]*\n?", "", text)
                text = re.sub(r"\n?```$", "", text).strip()
                if not text:
                    error_holder[0] = "LLM 返回空代码块"
                    return
                match = re.search(r"\{.*\}", text, re.DOTALL)
                if not match:
                    error_holder[0] = f"LLM 未返回 JSON: {text[:80]!r}"
                    return
                result_holder[0] = json.loads(match.group(0))
            except Exception as exc:
                error_holder[0] = str(exc)

        worker = threading.Thread(target=_call, daemon=True)
        worker.start()
        worker.join(timeout=40)

        if error_holder[0]:
            raise WorldAdminError(f"AI 补全失败: {error_holder[0]}")
        if result_holder[0] is None:
            raise WorldAdminError("AI 补全超时，请稍后再试。")
        return result_holder[0]
