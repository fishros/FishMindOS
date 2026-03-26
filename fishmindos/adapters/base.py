"""
Adapter base classes and shared models.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class MapInfo:
    """Map metadata."""

    id: int
    name: str
    description: str = ""


@dataclass
class WaypointInfo:
    """Waypoint metadata."""

    id: int
    name: str
    map_id: int
    x: float
    y: float
    z: float = 0.0
    yaw: float = 0.0
    type: str = "normal"


@dataclass
class TaskInfo:
    """Task metadata."""

    id: int
    name: str
    description: str = ""
    status: str = "idle"
    program: dict | None = None


@dataclass
class RobotStatus:
    """High-level runtime status used by the brain and status skills."""

    nav_running: bool = False
    charging: bool = False
    battery_soc: Optional[float] = None
    current_pose: dict | None = None


class RobotAdapter(ABC):
    """Abstract robot adapter interface."""

    @property
    @abstractmethod
    def vendor_name(self) -> str:
        pass

    @abstractmethod
    def connect(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    def disconnect(self) -> None:
        pass

    @abstractmethod
    def list_maps(self) -> List[MapInfo]:
        pass

    @abstractmethod
    def get_map(self, map_id: int) -> Optional[MapInfo]:
        pass

    @abstractmethod
    def list_waypoints(self, map_id: int) -> List[WaypointInfo]:
        pass

    @abstractmethod
    def get_waypoint(self, waypoint_id: int) -> Optional[WaypointInfo]:
        pass

    @abstractmethod
    def start_navigation(self, map_id: int) -> bool:
        pass

    @abstractmethod
    def stop_navigation(self) -> bool:
        pass

    @abstractmethod
    def goto_waypoint(self, waypoint_id: int) -> bool:
        pass

    @abstractmethod
    def goto_point(self, x: float, y: float, yaw: float = 0.0) -> bool:
        pass

    @abstractmethod
    def get_navigation_status(self) -> dict:
        pass

    def get_status(self, force_refresh: bool = False) -> RobotStatus:
        """
        Return a summarized runtime status.

        Adapters may override this for richer behavior. The default implementation
        falls back to `get_basic_status()` when available.
        """

        basic_status_fn = getattr(self, "get_basic_status", None)
        if callable(basic_status_fn):
            data = basic_status_fn() or {}
            if isinstance(data, dict):
                return RobotStatus(
                    nav_running=bool(data.get("nav_running", False)),
                    charging=bool(data.get("charging", False)),
                    battery_soc=data.get("battery_soc"),
                    current_pose=data.get("current_pose"),
                )
        return RobotStatus()

    @abstractmethod
    def list_tasks(self) -> List[TaskInfo]:
        pass

    @abstractmethod
    def run_task(self, task_id: int) -> bool:
        pass

    @abstractmethod
    def cancel_task(self) -> bool:
        pass

    def navigate_to(self, target: str) -> bool:
        return False

    def execute_docking_async(self) -> bool:
        docking_fn = getattr(self, "execute_docking", None)
        if callable(docking_fn):
            try:
                return bool(docking_fn())
            except Exception:
                return False
        return False

    def set_callback_url(self, url: str, enable: bool = True) -> bool:
        print(f"[Adapter] 回调URL设置: {url} (enabled={enable})")
        self._callback_url = url if enable else None
        return True

    def send_callback(self, event_type: str, data: Dict[str, Any]) -> bool:
        import json
        import time
        import urllib.request

        url = getattr(self, "_callback_url", None)
        if not url:
            return False

        try:
            payload = {
                "event": event_type,
                "timestamp": time.time(),
                "data": data,
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=1.0) as response:
                return response.status == 200
        except Exception as e:
            print(f"[Adapter] 回调发送失败: {e}")
            return False

    def handle_callback_event(self, event: Dict[str, Any]) -> None:
        return

    def get_callback_state(self) -> Dict[str, Any]:
        return {}


class AdapterError(Exception):
    """Adapter-level error."""

