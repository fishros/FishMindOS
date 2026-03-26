"""
系统控制技能
"""

from typing import Any, Dict
from fishmindos.core.models import SkillContext, SkillResult
from fishmindos.skills.base import Skill


class GetBatterySkill(Skill):
    """获取电量技能"""
    name = "system_battery"
    description = "获取机器狗电量信息"
    category = "system"
    
    parameters = {
        "type": "object",
        "properties": {},
        "required": []
    }
    
    def execute(self, params: Dict[str, Any], context: SkillContext) -> SkillResult:
        if not self.adapter:
            return SkillResult(False, "适配器未设置")
        
        battery = self.adapter.get_battery()
        soc = battery.get("soc")
        charging = battery.get("charging")
        error = battery.get("error")
        
        # 如果无法获取电量
        if soc is None:
            if error:
                return SkillResult(False, f"无法获取电量信息: {error}")
            else:
                return SkillResult(False, "电量接口不可用，请通过机器人面板查看电量")
        
        # 【改进】：正确处理 charging 状态
        # - charging=True: 正在充电
        # - charging=False: 未充电
        # - charging=None: 无法获取充电状态（WebSocket 未连接或数据未获取）
        if charging is True:
            status = "正在充电"
        elif charging is False:
            status = "未充电"
        else:
            status = "充电状态未知"
        
        message = f"当前电量约 {soc:.1f}%，{status}"
        
        return SkillResult(True, message, battery)


class GetStatusSkill(Skill):
    """获取状态技能"""
    name = "system_status"
    description = "获取机器狗整体状态"
    category = "system"
    
    parameters = {
        "type": "object",
        "properties": {},
        "required": []
    }
    
    def execute(self, params: Dict[str, Any], context: SkillContext) -> SkillResult:
        if not self.adapter:
            return SkillResult(False, "适配器未设置")
        
        status = self.adapter.get_status(force_refresh=True)
        
        parts = []
        if status.nav_running:
            parts.append("正在导航")
        else:
            parts.append("未在导航")
        
        if status.charging:
            parts.append("正在充电")
        
        if status.battery_soc is not None:
            parts.append(f"电量约 {status.battery_soc:.1f}%")
        
        message = "，".join(parts) + "。"
        
        return SkillResult(True, message, {
            "nav_running": status.nav_running,
            "charging": status.charging,
            "battery_soc": status.battery_soc,
            "pose": status.current_pose
        })

    def _sync_current_map(self, context: SkillContext) -> None:
        """把适配器读到的当前地图同步回上下文。"""
        try:
            nav_status = self.adapter.get_navigation_status()
        except Exception:
            return

        map_id = nav_status.get("current_map_id") or nav_status.get("map_id")
        if map_id is None:
            return

        current_map = context.get("current_map")
        if isinstance(current_map, dict) and current_map.get("id") == map_id:
            return

        map_name = None
        if hasattr(self.adapter, "resolve_current_map"):
            map_info = self.adapter.resolve_current_map()
            if map_info:
                map_id = map_info.id
                map_name = map_info.name
        elif hasattr(self.adapter, "get_map"):
            map_info = self.adapter.get_map(map_id)
            if map_info:
                map_name = map_info.name

        context.set("current_map", {
            "id": map_id,
            "name": map_name or str(map_id)
        })

    def execute(self, params: Dict[str, Any], context: SkillContext) -> SkillResult:
        if not self.adapter:
            return SkillResult(False, "适配器未设置")

        status = self.adapter.get_status(force_refresh=True)
        self._sync_current_map(context)

        query_text = str(context.user_text or context.get("last_input", "") or "")
        wants_battery = any(keyword in query_text for keyword in ["电量", "电池", "还有多少电", "多少电"])
        if wants_battery and status.battery_soc is None and hasattr(self.adapter, "get_battery"):
            try:
                battery = self.adapter.get_battery()
            except Exception:
                battery = {}
            if isinstance(battery, dict):
                soc = battery.get("soc")
                charging = battery.get("charging")
                if soc is not None:
                    status.battery_soc = soc
                if charging is not None:
                    status.charging = bool(charging)

        parts = []
        if status.nav_running:
            parts.append("正在导航")
        else:
            parts.append("未在导航")

        if status.charging:
            parts.append("正在充电")

        if status.battery_soc is not None:
            parts.append(f"电量约 {status.battery_soc:.1f}%")

        message = "，".join(parts) + "。"

        result = {
            "nav_running": status.nav_running,
            "charging": status.charging,
            "battery_soc": status.battery_soc,
            "pose": status.current_pose
        }
        try:
            nav_status = self.adapter.get_navigation_status()
            if isinstance(nav_status, dict):
                if nav_status.get("target_pose") is not None:
                    result["target_pose"] = nav_status.get("target_pose")
                if nav_status.get("target_waypoint_id") is not None:
                    result["target_waypoint_id"] = nav_status.get("target_waypoint_id")
                if nav_status.get("target_waypoint_name"):
                    result["target_waypoint_name"] = nav_status.get("target_waypoint_name")
                if nav_status.get("callback_event_count") is not None:
                    result["callback_event_count"] = nav_status.get("callback_event_count")
                if nav_status.get("last_event"):
                    result["last_event"] = nav_status.get("last_event")
        except Exception:
            pass
        current_map = context.get("current_map")
        if isinstance(current_map, dict):
            result["current_map"] = current_map

        return SkillResult(True, message, result)


class GetChargingStatusSkill(Skill):
    """获取充电状态技能"""
    name = "system_charging"
    description = "获取充电状态"
    category = "system"
    
    parameters = {
        "type": "object",
        "properties": {},
        "required": []
    }
    
    def execute(self, params: Dict[str, Any], context: SkillContext) -> SkillResult:
        if not self.adapter:
            return SkillResult(False, "适配器未设置")
        
        # 【核心修改】：强制改为调用 get_battery()，从而触发底层的 WebSocket 电流检测！
        battery_data = self.adapter.get_battery()
        
        is_charging = battery_data.get("charging", False)
        soc = battery_data.get("soc")
        
        if is_charging:
            message = f"正在充电，当前电量约 {soc:.1f}%。" if soc is not None else "正在充电。"
        else:
            message = f"未在充电，当前电量约 {soc:.1f}%。" if soc is not None else "未在充电。"
        
        return SkillResult(True, message, {
            "charging": is_charging,
            "battery_soc": soc
        })


class GetPoseSkill(Skill):
    """获取位姿技能"""
    name = "system_pose"
    description = "获取当前位置和姿态"
    category = "system"
    
    parameters = {
        "type": "object",
        "properties": {},
        "required": []
    }
    
    def execute(self, params: Dict[str, Any], context: SkillContext) -> SkillResult:
        if not self.adapter:
            return SkillResult(False, "适配器未设置")
        
        status = self.adapter.get_status(force_refresh=True)
        pose = status.current_pose or {}
        
        x = pose.get("x", 0)
        y = pose.get("y", 0)
        yaw = pose.get("yaw", 0)
        
        message = f"当前位置: x={x:.2f}, y={y:.2f}, 朝向={yaw:.2f}"
        
        return SkillResult(True, message, pose)


class WaitEventSkill(Skill):
    """等待事件技能"""
    name = "system_wait"
    description = "等待特定事件完成（如导航启动、到达路点等）"
    category = "system"
    expose_as_tool = True  # 对LLM可见，支持等待任务完成
    
    parameters = {
        "type": "object",
        "properties": {
            "event_type": {
                "type": "string",
                "enum": ["nav_started", "arrival", "dock_complete"],
                "description": "事件类型"
            },
            "waypoint_id": {
                "type": "integer",
                "description": "目标路点ID（arrival事件需要）"
            },
            "timeout": {
                "type": "integer",
                "default": 60,
                "description": "超时时间（秒）"
            }
        },
        "required": ["event_type"]
    }
    
    def execute(self, params: Dict[str, Any], context: SkillContext) -> SkillResult:
        event_type = params.get("event_type")
        timeout = params.get("timeout", 300 if event_type != "nav_started" else 60)
        
        if not self.adapter:
            return SkillResult(False, "适配器未设置")
        
        if event_type == "nav_started":
            success = self.adapter.wait_nav_started(timeout)
            if success:
                return SkillResult(True, "导航已启动", {"event_type": event_type})
            return SkillResult(False, "等待导航启动超时")
        
        elif event_type == "arrival":
            waypoint_id = params.get("waypoint_id")
            if not waypoint_id:
                pending = context.get("pending_arrival") or context.get("last_waypoint")
                if isinstance(pending, dict):
                    waypoint_id = pending.get("waypoint_id") or pending.get("id")
            if not waypoint_id and hasattr(self.adapter, "get_callback_state"):
                callback_state = self.adapter.get_callback_state()
                waypoint_id = callback_state.get("target_waypoint_id")
            if not waypoint_id:
                return SkillResult(False, "arrival事件需要提供waypoint_id")
            success = self.adapter.wait_arrival(waypoint_id, timeout)
            if success:
                context.set("pending_arrival", None)
                return SkillResult(True, f"已到达路点 {waypoint_id}", {
                    "event_type": event_type,
                    "waypoint_id": waypoint_id
                })
            return SkillResult(False, "等待到达超时")
        
        elif event_type == "dock_complete":
            success = self.adapter.wait_dock_complete(timeout)
            if success:
                return SkillResult(True, "回充完成", {"event_type": event_type})
            return SkillResult(False, "等待回充超时")
        
        return SkillResult(False, f"未知事件类型: {event_type}")



class ListWorldLocationsSkill(Skill):
    """List known places from the current semantic world."""

    name = "world_list_locations"
    description = "列出当前 world 中可用的语义地点，支持按当前地图过滤，并可附带描述和别名。"
    category = "system"

    parameters = {
        "type": "object",
        "properties": {
            "current_map_only": {
                "type": "boolean",
                "description": "是否只列出当前地图下的地点，默认 true。",
            },
            "include_details": {
                "type": "boolean",
                "description": "是否返回地点描述和别名等详细信息，默认 true。",
            },
        },
        "required": [],
    }

    def execute(self, params: Dict[str, Any], context: SkillContext) -> SkillResult:
        resolver = context.get("world") or context.get("world_model") or getattr(context, "world_model", None)
        if not resolver or not hasattr(resolver, "world"):
            return SkillResult(False, "当前未启用 world，无法列出语义地点。")

        world = getattr(resolver, "world", None)
        locations = list(getattr(world, "locations", []) or [])
        if not locations:
            return SkillResult(False, "当前 world 里还没有配置任何地点。")

        current_map_only = bool(params.get("current_map_only", True))
        include_details = bool(params.get("include_details", True))

        current_map = context.get("current_map") or {}
        current_map_id = current_map.get("id") if isinstance(current_map, dict) else None
        current_map_name = current_map.get("name") if isinstance(current_map, dict) else None

        filtered = locations
        if current_map_only and (current_map_id is not None or current_map_name):
            current_map_name_text = str(current_map_name or "").strip()
            filtered = [
                item
                for item in locations
                if (
                    current_map_id is not None
                    and getattr(item, "map_id", None) == current_map_id
                )
                or (
                    current_map_name_text
                    and str(getattr(item, "map_name", "") or "").strip() == current_map_name_text
                )
                or (
                    getattr(item, "map_id", None) is None
                    and not getattr(item, "map_name", None)
                )
            ]
            if not filtered:
                filtered = locations

        items = []
        lines = []
        for item in filtered:
            name = str(getattr(item, "name", "") or "").strip() or "未命名地点"
            description = str(getattr(item, "description", "") or "").strip()
            aliases = [alias for alias in (getattr(item, "aliases", None) or []) if alias]
            items.append(
                {
                    "name": name,
                    "map_name": getattr(item, "map_name", None),
                    "map_id": getattr(item, "map_id", None),
                    "waypoint_name": getattr(item, "waypoint_name", None),
                    "waypoint_id": getattr(item, "waypoint_id", None),
                    "location_type": getattr(item, "location_type", "waypoint"),
                    "description": description,
                    "aliases": aliases,
                }
            )

            label = name
            if include_details:
                detail_parts = []
                if description:
                    detail_parts.append(description)
                if aliases:
                    detail_parts.append(f"别名: {'/'.join(aliases[:3])}")
                if detail_parts:
                    label = f"{name}（{'；'.join(detail_parts)}）"
            lines.append(f"- {label}")

        map_label = str(
            current_map_name
            or getattr(world, "default_map_name", None)
            or getattr(world, "name", "当前 world")
        ).strip()
        message = f"{map_label} 可用地点有 {len(filtered)} 个：\n" + "\n".join(lines)
        return SkillResult(True, message, {"locations": items, "count": len(filtered)})
