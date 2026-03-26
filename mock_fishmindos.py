"""
FishMindOS Mock - 真实 LLM + Mock Adapter
用于测试 LLM 决策能力，不控制真机器人
"""

import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

# 确保可以导入 fishmindos
sys.path.insert(0, str(Path(__file__).parent))

# 替换 adapters 模块中的 FishBotAdapter
import fishmindos.adapters as adapters_module
from fishmindos.adapters.base import RobotAdapter, MapInfo, WaypointInfo, TaskInfo, RobotStatus
from fishmindos.config import get_config
from fishmindos.core.event_bus import global_event_bus
from fishmindos.world import WorldStore

class MockFishBotAdapter(RobotAdapter):
    """
    Mock Adapter - 模拟所有 API 调用，不连接真机器人
    与真实 FishBotAdapter 接口完全一致
    """
    
    def __init__(self, 
                 nav_server_host: str = "127.0.0.1", nav_server_port: int = 9001,
                 nav_app_host: str = "127.0.0.1", nav_app_port: int = 9002,
                 rosbridge_host: str = "127.0.0.1", rosbridge_port: int = 9090,
                 rosbridge_path: str = "/api/rt",
                 status_cache_ttl_sec: float = 1.0,
                 **_: Any):
        
        self.nav_server_base = f"http://{nav_server_host}:{nav_server_port}"
        self.nav_app_base = f"http://{nav_app_host}:{nav_app_port}"
        self._connected = False
        self._current_map_id = None
        self._status_cache_ttl_sec = status_cache_ttl_sec
        self._mock_maps = []
        self._mock_waypoints = {}
        self._mock_waypoint_aliases: Dict[int, Dict[str, Dict[str, Any]]] = {}
        self._world_path: Optional[Path] = None
        self._world_path_mtime: Optional[float] = None
        
        self._nav_running = False
        self._current_pose = {"x": 0.0, "y": 0.0, "yaw": 0.0}
        self._battery = 85.0
        self._charging = False
        self._motion_ready = False
        self._state_lock = threading.RLock()
        self._mock_nav_delay_sec = 0.8
        self._mock_dock_delay_sec = 1.2
        self._refresh_mock_world(force=True)
        
        print(f"[MOCK] Adapter 初始化: {nav_server_host}:{nav_server_port}")
    
    @property
    def vendor_name(self) -> str:
        return "FishBot Navigator (MOCK)"
    
    def connect(self) -> dict:
        """健康检查"""
        print("[MOCK] 健康检查通过")
        self._connected = True
        return {
            "success": True,
            "nav_server": {"connected": True, "error": None},
            "nav_app": {"connected": True, "error": None},
            "rosbridge": {"connected": True, "error": None},
            "overall_status": "healthy"
        }
    
    def disconnect(self) -> None:
        self._connected = False
        print("[MOCK] 断开连接")

    def _event_stream_enabled(self) -> bool:
        return True

    def _default_mock_payload(self) -> tuple[list, dict]:
        maps = [{"id": 999, "name": "default", "description": "fallback mock map"}]
        waypoints = {
            999: [
                {"id": 99901, "name": "大厅", "x": 10.0, "y": 20.0, "aliases": []},
                {"id": 99902, "name": "卫生间", "x": 25.0, "y": 35.0, "aliases": ["厕所"]},
                {"id": 99903, "name": "路点3", "x": 18.0, "y": 12.0, "aliases": []},
                {"id": 99904, "name": "回充点", "x": 5.0, "y": 5.0, "aliases": ["充电点", "回充", "回桩"]},
            ]
        }
        return maps, waypoints

    def _resolve_world_path(self) -> Optional[Path]:
        try:
            cfg = get_config()
        except Exception:
            return None

        world_cfg = getattr(cfg, "world", None)
        if world_cfg is None or not getattr(world_cfg, "enabled", False):
            return None

        raw_path = getattr(world_cfg, "path", None)
        if not raw_path:
            return None

        world_path = Path(raw_path)
        if not world_path.is_absolute():
            world_path = Path.cwd() / world_path
        return world_path

    def _build_mock_data_from_world(self, world_path: Path) -> tuple[list, dict]:
        world = WorldStore(world_path).load()

        maps: list[dict[str, Any]] = []
        map_name_to_id: Dict[str, int] = {}
        next_map_id = 1000

        for item in world.maps:
            map_id = item.map_id if item.map_id is not None else next_map_id
            if item.map_id is None:
                next_map_id += 1
            map_name_to_id[item.name] = int(map_id)
            maps.append(
                {
                    "id": int(map_id),
                    "name": item.name,
                    "description": item.description or "",
                }
            )

        if world.default_map_name and world.default_map_name not in map_name_to_id:
            default_id = int(world.default_map_id or next_map_id)
            map_name_to_id[world.default_map_name] = default_id
            maps.append(
                {
                    "id": default_id,
                    "name": world.default_map_name,
                    "description": "default world map",
                }
            )
            next_map_id = max(next_map_id, default_id + 1)

        waypoints: Dict[int, list[dict[str, Any]]] = {}
        next_waypoint_id = 10000

        for loc in world.locations:
            map_id = loc.map_id
            if map_id is None and loc.map_name:
                map_id = map_name_to_id.get(loc.map_name)
            if map_id is None:
                if world.default_map_id is not None:
                    map_id = int(world.default_map_id)
                elif world.default_map_name:
                    map_id = map_name_to_id.get(world.default_map_name)
            if map_id is None:
                continue

            waypoint_id = loc.waypoint_id if loc.waypoint_id is not None else next_waypoint_id
            if loc.waypoint_id is None:
                next_waypoint_id += 1

            name = loc.waypoint_name or loc.name
            metadata = loc.metadata or {}
            entry = {
                "id": int(waypoint_id),
                "name": name,
                "display_name": loc.name,
                "x": float(metadata.get("x", 0.0) or 0.0),
                "y": float(metadata.get("y", 0.0) or 0.0),
                "z": float(metadata.get("z", 0.0) or 0.0),
                "yaw": float(metadata.get("yaw", 0.0) or 0.0),
                "aliases": list(dict.fromkeys([*(loc.aliases or []), loc.name, loc.waypoint_name])),
                "location_type": loc.location_type,
            }
            waypoints.setdefault(int(map_id), []).append(entry)

        if not maps or not waypoints:
            return self._default_mock_payload()

        return maps, waypoints

    def _rebuild_alias_index(self) -> None:
        self._mock_waypoint_aliases = {}
        for map_id, items in self._mock_waypoints.items():
            alias_map: Dict[str, Dict[str, Any]] = {}
            for wp in items:
                names = [wp.get("name"), wp.get("display_name"), *(wp.get("aliases") or [])]
                for name in names:
                    normalized = str(name or "").strip()
                    if normalized:
                        alias_map[normalized] = wp
            self._mock_waypoint_aliases[int(map_id)] = alias_map

    def _refresh_mock_world(self, force: bool = False) -> None:
        world_path = self._resolve_world_path()
        world_mtime = None
        if world_path and world_path.exists():
            world_mtime = world_path.stat().st_mtime

        if (
            not force
            and world_path == self._world_path
            and world_mtime is not None
            and world_mtime == self._world_path_mtime
            and self._mock_maps
            and self._mock_waypoints
        ):
            return

        if world_path and world_path.exists():
            maps, waypoints = self._build_mock_data_from_world(world_path)
            self._world_path = world_path
            self._world_path_mtime = world_mtime
        else:
            maps, waypoints = self._default_mock_payload()
            self._world_path = world_path
            self._world_path_mtime = world_mtime

        self._mock_maps = maps
        self._mock_waypoints = waypoints
        self._rebuild_alias_index()

        available_map_ids = [int(item["id"]) for item in self._mock_maps if item.get("id") is not None]
        if self._current_map_id not in available_map_ids:
            if available_map_ids:
                self._current_map_id = available_map_ids[0]

    def _find_waypoint(self, target: str) -> Optional[Dict[str, Any]]:
        if not target:
            return None
        self._refresh_mock_world()
        map_id = self._current_map_id or 51
        normalized_target = str(target).strip()
        alias_map = self._mock_waypoint_aliases.get(int(map_id), {})
        if normalized_target in alias_map:
            return alias_map[normalized_target]

        synonym_map = {
            "厕所": ["卫生间"],
            "卫生间": ["厕所"],
            "充电处": ["回充点", "充电点"],
            "充电点": ["回充点", "充电处"],
        }
        for synonym in synonym_map.get(normalized_target, []):
            if synonym in alias_map:
                return alias_map[synonym]

        waypoints = self._mock_waypoints.get(map_id, [])
        for wp in waypoints:
            name = str(wp.get("name") or "").strip()
            display_name = str(wp.get("display_name") or "").strip()
            if normalized_target in name or name in normalized_target:
                return wp
            if display_name and (normalized_target in display_name or display_name in normalized_target):
                return wp
        return None

    def _find_dock_waypoint(self, map_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        self._refresh_mock_world()
        target_map_id = map_id or self._current_map_id or 51
        for wp in self._mock_waypoints.get(target_map_id, []):
            names = [wp.get("name"), wp.get("display_name"), *(wp.get("aliases") or [])]
            joined = " ".join(str(item or "") for item in names).lower()
            if "回充" in joined or "充电" in joined or "dock" in joined:
                return wp
        return None

    def _publish_after_delay(self, delay_sec: float, event_type: str, payload: Dict[str, Any]) -> None:
        def _worker() -> None:
            time.sleep(delay_sec)
            print(f"[MOCK EVENT] {event_type} -> {payload}")
            global_event_bus.publish(event_type, payload)

        threading.Thread(
            target=_worker,
            name=f"mock-{event_type}",
            daemon=True,
        ).start()
    
    # ========== 地图操作 ==========
    def list_maps(self):
        self._refresh_mock_world()
        print("[MOCK] list_maps()")
        return [MapInfo(**m) for m in self._mock_maps]
    
    def start_navigation(self, map_id: int = None) -> bool:
        self._refresh_mock_world()
        if map_id is None:
            map_id = self._current_map_id or (self._mock_maps[0]["id"] if self._mock_maps else 1)
        print(f"[MOCK] start_navigation(map_id={map_id})")
        with self._state_lock:
            self._current_map_id = map_id
            self._nav_running = True
            self._charging = False
        return True
    
    def stop_navigation(self) -> bool:
        print("[MOCK] stop_navigation()")
        with self._state_lock:
            self._nav_running = False
        return True
    
    def get_navigation_status(self) -> dict:
        self._refresh_mock_world()
        return {
            "nav_running": self._nav_running,
            "current_map_id": self._current_map_id
        }
    
    # ========== 路点操作 ==========
    def list_waypoints(self, map_id: int):
        self._refresh_mock_world()
        print(f"[MOCK] list_waypoints(map_id={map_id})")
        waypoints = self._mock_waypoints.get(map_id, [])
        return [
            WaypointInfo(
                id=wp["id"],
                name=wp["name"],
                map_id=map_id,
                x=wp["x"],
                y=wp["y"],
                z=wp.get("z", 0.0),
                yaw=wp.get("yaw", 0.0),
                type=wp.get("location_type", "normal"),
            )
            for wp in waypoints
        ]
    
    def goto_waypoint(self, waypoint_id: int) -> bool:
        print(f"[MOCK] goto_waypoint(waypoint_id={waypoint_id})")
        return True
    
    def goto_location(self, location: str, location_type: str = "waypoint") -> bool:
        print(f"[MOCK] goto_location(location='{location}', type='{location_type}')")
        return True
    
    def goto_dock(self, map_id: int = None) -> bool:
        print(f"[MOCK] goto_dock(map_id={map_id})")
        return True

    def prepare_for_movement(self) -> bool:
        return self.motion_stand()

    def navigate_to(self, target: str) -> bool:
        self._refresh_mock_world()
        if not target:
            return False

        lowered = str(target).lower()
        if any(keyword in lowered or keyword in target for keyword in ["回充", "充电", "回桩", "dock"]):
            return self.execute_docking_async()

        waypoint = self._find_waypoint(str(target))
        if waypoint is None:
            print(f"[MOCK] navigate_to(target='{target}') - waypoint not found")
            return False

        print(f"[MOCK] navigate_to(target='{target}')")
        with self._state_lock:
            self._nav_running = True
            self._charging = False

        def _complete_navigation() -> None:
            with self._state_lock:
                self._current_pose = {"x": waypoint["x"], "y": waypoint["y"], "yaw": 0.0}
                self._nav_running = False
            self._publish_after_delay(
                0.0,
                "nav_arrived",
                {
                    "event": "mock_nav_arrived",
                    "target": waypoint["name"],
                    "waypoint_id": waypoint["id"],
                    "map_id": self._current_map_id,
                },
            )

        threading.Thread(
            target=lambda: (time.sleep(self._mock_nav_delay_sec), _complete_navigation()),
            name="mock-nav-arrival",
            daemon=True,
        ).start()
        return True

    def execute_docking_async(self) -> bool:
        self._refresh_mock_world()
        dock = self._find_dock_waypoint(self._current_map_id)
        print(f"[MOCK] execute_docking_async(map_id={self._current_map_id})")
        with self._state_lock:
            self._nav_running = True
            self._charging = False

        def _complete_docking() -> None:
            with self._state_lock:
                if dock is not None:
                    self._current_pose = {"x": dock["x"], "y": dock["y"], "yaw": 0.0}
                self._nav_running = False
                self._charging = True
            self._publish_after_delay(
                0.0,
                "dock_completed",
                {
                    "event": "mock_dock_completed",
                    "map_id": self._current_map_id,
                },
            )

        threading.Thread(
            target=lambda: (time.sleep(self._mock_dock_delay_sec), _complete_docking()),
            name="mock-dock-complete",
            daemon=True,
        ).start()
        return True

    def get_basic_status(self) -> dict:
        with self._state_lock:
            return {
                "nav_running": self._nav_running,
                "charging": self._charging,
                "battery_soc": self._battery,
                "current_pose": self._current_pose.copy(),
            }
    
    # ========== 运动控制 ==========
    def motion_stand(self) -> bool:
        print("[MOCK] motion_stand()")
        self._motion_ready = True
        return True
    
    def motion_lie_down(self) -> bool:
        print("[MOCK] motion_lie_down()")
        return True
    
    # ========== 灯光控制 ==========
    def set_light(self, code: int) -> bool:
        colors = {11: "红灯", 13: "绿灯", 0: "关灯"}
        print(f"[MOCK] set_light(code={code}) - {colors.get(code, '未知')}")
        return True
    
    # ========== 音频控制 ==========
    def play_audio(self, text: str) -> bool:
        print(f"[MOCK] play_audio('{text}')")
        return True
    
    # ========== 等待事件 ==========
    def wait_nav_started(self, timeout: int = 60) -> bool:
        print(f"[MOCK] wait_nav_started(timeout={timeout})")
        return True
    
    def wait_arrival(self, waypoint_id: int, timeout: int = 300) -> bool:
        print(f"[MOCK] wait_arrival(waypoint_id={waypoint_id})")
        return True
    
    def wait_dock_complete(self, timeout: int = 300) -> bool:
        print(f"[MOCK] wait_dock_complete(timeout={timeout})")
        return True
    
    # ========== 状态查询 ==========
    def get_status(self, force_refresh: bool = False):
        return RobotStatus(
            nav_running=self._nav_running,
            charging=self._charging,
            battery_soc=self._battery,
            current_pose=self._current_pose
        )
    
    def get_current_pose(self) -> dict:
        return self._current_pose.copy()
    
    # ========== 其他必需方法（快速实现）==========
    def get_map(self, map_id: int):
        self._refresh_mock_world()
        for m in self._mock_maps:
            if m["id"] == map_id:
                return MapInfo(**m)
        return None
    
    def get_waypoint(self, waypoint_id: int):
        self._refresh_mock_world()
        for map_waypoints in self._mock_waypoints.values():
            for wp in map_waypoints:
                if wp["id"] == waypoint_id:
                    return WaypointInfo(
                        id=wp["id"],
                        name=wp["name"],
                        map_id=self._current_map_id or 1,
                        x=wp["x"],
                        y=wp["y"],
                        z=wp.get("z", 0.0),
                        yaw=wp.get("yaw", 0.0),
                        type=wp.get("location_type", "normal"),
                    )
        return None
    
    def create_task(self, name: str, description: str = "", program: dict = None):
        print(f"[MOCK] create_task('{name}')")
        return TaskInfo(id=1, name=name, description=description)
    
    def delete_task(self, task_id: int) -> bool:
        print(f"[MOCK] delete_task({task_id})")
        return True
    
    def start_task(self, task_id: int) -> bool:
        print(f"[MOCK] start_task({task_id})")
        return True
    
    def stop_task(self, task_id: int) -> bool:
        print(f"[MOCK] stop_task({task_id})")
        return True
    
    def get_task_status(self, task_id: int):
        print(f"[MOCK] get_task_status({task_id})")
        return TaskInfo(id=task_id, name="mock_task", status="running")
    
    def goto_point(self, x: float, y: float, yaw: float = None) -> bool:
        print(f"[MOCK] goto_point(x={x}, y={y}, yaw={yaw})")
        return True
    
    def list_tasks(self):
        print("[MOCK] list_tasks()")
        return []
    
    def pause_navigation(self) -> bool:
        print("[MOCK] pause_navigation()")
        return True
    
    def resume_navigation(self) -> bool:
        print("[MOCK] resume_navigation()")
        return True
    
    def get_battery_status(self):
        print("[MOCK] get_battery_status()")
        return {"soc": 85.0, "charging": False}
    
    def run_task(self, task_id: int) -> bool:
        print(f"[MOCK] run_task({task_id})")
        return True
    
    def cancel_task(self) -> bool:
        print("[MOCK] cancel_task()")
        return True
    
    def get_battery(self):
        print("[MOCK] get_battery()")
        return {"soc": self._battery, "charging": self._charging}

    def get_mock_world(self):
        """返回用于规划测试的静态场景信息。"""
        map_lookup = {m["id"]: m["name"] for m in self._mock_maps}
        return {
            "current_map": map_lookup.get(self._current_map_id, "26层"),
            "map_aliases": {
                "楼下": "1层",
                "楼上": "26层",
            },
            "waypoints": {
                map_lookup.get(map_id, str(map_id)): [wp["name"] for wp in waypoints]
                for map_id, waypoints in self._mock_waypoints.items()
            }
        }


# 替换真实的 create_fishbot_adapter
original_create_fishbot_adapter = adapters_module.create_fishbot_adapter

def mock_create_fishbot_adapter(**kwargs):
    """工厂函数：创建 Mock Adapter"""
    return MockFishBotAdapter(**kwargs)

# Monkey patch
adapters_module.create_fishbot_adapter = mock_create_fishbot_adapter
adapters_module.FishBotAdapter = MockFishBotAdapter


# 现在导入真实的 FishMindOS
from fishmindos.__main__ import FishMindOS


def main():
    """主入口"""
    print("=" * 70)
    print(" FishMindOS Mock - 真实 LLM + Mock Adapter")
    print(" 测试 LLM 决策能力，不控制真机器人")
    print("=" * 70)
    print()
    print("观察重点:")
    print("  1. [PLAN] 工具序列是否正确")
    print("  2. 是否会多余调用 nav_start")
    print("  3. '完成后亮绿灯' 是否生成 system_wait + light_set")
    print("  4. 网络抖动时是否优雅处理")
    print()
    print("=" * 70)
    print()
    
    # 使用真实的 FishMindOS
    app = FishMindOS()
    
    if app.initialize():
        if app.brain:
            app.brain.session_context["current_map"] = {"id": 51, "name": "26层"}
            app.brain.session_context["current_location"] = "入口"
            app.brain.session_context["planning_only"] = True
            if hasattr(app.adapter, "get_mock_world"):
                app.brain.session_context["mock_world"] = app.adapter.get_mock_world()
            print("[MOCK] 默认上下文: 地图=26层, 位置=入口")
            print("[MOCK] 模式: 规划优先（禁用 nav_list_maps/nav_list_waypoints）")
        print("\n输入指令开始测试（输入 'exit' 退出）:\n")
        app.run()
    else:
        print("\n初始化失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
