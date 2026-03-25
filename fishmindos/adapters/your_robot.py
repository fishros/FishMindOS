"""
Reference adapter template for integrating a different robot API into FishMindOS.

This file is intentionally written as a readable template rather than a production
adapter. The goal is to show which methods matter, what each method should return,
and where a new vendor API needs to be mapped.

How to use this template:

1. Copy this file and rename the class/factory if needed.
2. Replace the placeholder endpoint paths with your real API paths.
3. Update `_is_success_response()` and `_extract_data()` to match your response shape.
4. Fill in any optional capabilities your robot supports:
   - light control
   - audio / TTS
   - docking
   - callback or websocket state sync

FishMindOS will call the adapter through the `RobotAdapter` interface, so once this
file is correctly implemented, the rest of the system can stay unchanged.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from fishmindos.adapters.base import (
    AdapterError,
    MapInfo,
    RobotAdapter,
    RobotStatus,
    TaskInfo,
    WaypointInfo,
)


class YourRobotAPIError(AdapterError):
    """Raised when the vendor API returns an error or cannot be reached."""


@dataclass
class YourRobotConfig:
    """Connection settings for the vendor robot API."""

    host: str = "127.0.0.1"
    port: int = 8080
    protocol: str = "http"
    api_key: str = ""
    timeout: int = 15

    @property
    def base_url(self) -> str:
        return f"{self.protocol}://{self.host}:{self.port}"


class YourRobotAdapter(RobotAdapter):
    """
    Reference adapter for a custom robot.

    The current implementation is a template with placeholder endpoint paths.
    It is designed to be easy to read and modify, not to match a specific vendor.

    Minimum methods you usually need for FishMindOS:
    - connect / disconnect
    - list_maps / list_waypoints
    - start_navigation / stop_navigation
    - navigate_to or goto_waypoint
    - get_navigation_status
    - get_basic_status

    Optional but recommended:
    - execute_docking_async
    - play_audio
    - set_light
    - callback or websocket state sync
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8080,
        api_key: str = "",
        protocol: str = "http",
        timeout: int = 15,
        **_: Any,
    ) -> None:
        self.config = YourRobotConfig(
            host=host,
            port=port,
            protocol=protocol,
            api_key=api_key,
            timeout=timeout,
        )
        self._connected = False
        self._current_map_id: Optional[int] = None
        self._current_map_name: Optional[str] = None
        self._nav_running = False
        self._charging = False
        self._battery_soc: Optional[float] = None
        self._current_pose: Dict[str, Any] = {"x": 0.0, "y": 0.0, "yaw": 0.0}

    @property
    def vendor_name(self) -> str:
        return "YourRobot"

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _build_url(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> str:
        url = f"{self.config.base_url}{endpoint}"
        if params:
            query = urllib.parse.urlencode(params)
            url = f"{url}?{query}"
        return url

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.config.api_key:
            # Replace this header if your API uses a different auth scheme.
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _is_success_response(self, payload: Dict[str, Any]) -> bool:
        """
        Normalize the vendor success condition.

        Replace this method if your API uses something else, for example:
        - payload["success"] is True
        - payload["code"] == 200
        - payload["status"] == "ok"
        """

        if "success" in payload:
            return bool(payload.get("success"))
        if "code" in payload:
            return payload.get("code") in {0, 200}
        return True

    def _extract_data(self, payload: Dict[str, Any]) -> Any:
        """
        Normalize the vendor data field.

        Replace this method if your API uses:
        - payload["result"]
        - payload["data"]["items"]
        - payload itself as the response body
        """

        if "data" in payload:
            return payload.get("data")
        if "result" in payload:
            return payload.get("result")
        return payload

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = self._build_url(endpoint, params=params)
        body = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(
            url,
            data=body,
            headers=self._headers(),
            method=method.upper(),
        )

        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout) as response:
                raw = response.read().decode("utf-8")
                payload = json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raise YourRobotAPIError(f"HTTP {exc.code}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise YourRobotAPIError(f"request failed: {exc.reason}") from exc
        except Exception as exc:
            raise YourRobotAPIError(f"request failed: {exc}") from exc

        if not isinstance(payload, dict):
            raise YourRobotAPIError("API response is not a JSON object")
        if not self._is_success_response(payload):
            raise YourRobotAPIError(str(payload))
        return payload

    # ------------------------------------------------------------------
    # Basic connection and status
    # ------------------------------------------------------------------

    def connect(self) -> Dict[str, Any]:
        """
        Ping a cheap health/status endpoint.

        Replace `/api/robot/status` with a real endpoint that proves the robot API
        is reachable. The return value should stay structured because the startup UI
        prints it directly.
        """

        result = {
            "success": False,
            "status": "offline",
            "details": {},
        }
        try:
            payload = self._request("GET", "/api/robot/status")
            data = self._extract_data(payload) or {}
            self._connected = True
            self._battery_soc = data.get("battery_soc", self._battery_soc)
            self._charging = bool(data.get("charging", self._charging))
            self._nav_running = bool(data.get("nav_running", self._nav_running))
            result["success"] = True
            result["status"] = "online"
            result["details"] = data if isinstance(data, dict) else {"raw": data}
            return result
        except Exception as exc:
            result["details"]["error"] = str(exc)
            return result

    def disconnect(self) -> None:
        self._connected = False

    def get_basic_status(self) -> Dict[str, Any]:
        """
        FishMindOS uses this for high-level status answers and `query` actions.

        If your robot exposes several endpoints, you can merge them here.
        """

        try:
            payload = self._request("GET", "/api/robot/status")
            data = self._extract_data(payload) or {}
            if isinstance(data, dict):
                self._battery_soc = data.get("battery_soc", self._battery_soc)
                self._charging = bool(data.get("charging", self._charging))
                self._nav_running = bool(data.get("nav_running", self._nav_running))
                pose = data.get("current_pose") or {}
                if isinstance(pose, dict) and pose:
                    self._current_pose = {
                        "x": float(pose.get("x", self._current_pose.get("x", 0.0)) or 0.0),
                        "y": float(pose.get("y", self._current_pose.get("y", 0.0)) or 0.0),
                        "yaw": float(pose.get("yaw", self._current_pose.get("yaw", 0.0)) or 0.0),
                    }
                return {
                    "nav_running": self._nav_running,
                    "charging": self._charging,
                    "battery_soc": self._battery_soc,
                    "current_pose": self._current_pose,
                }
        except Exception:
            pass

        return {
            "nav_running": self._nav_running,
            "charging": self._charging,
            "battery_soc": self._battery_soc,
            "current_pose": self._current_pose,
        }

    def get_navigation_status(self) -> Dict[str, Any]:
        """
        Replace `/api/navigation/status` with your robot's navigation status endpoint.
        """

        try:
            payload = self._request("GET", "/api/navigation/status")
            data = self._extract_data(payload) or {}
            if isinstance(data, dict):
                self._nav_running = bool(data.get("nav_running", self._nav_running))
                self._current_map_id = data.get("current_map_id", self._current_map_id)
                return data
        except Exception:
            pass

        return {
            "nav_running": self._nav_running,
            "current_map_id": self._current_map_id,
        }

    # ------------------------------------------------------------------
    # Maps and waypoints
    # ------------------------------------------------------------------

    def list_maps(self) -> List[MapInfo]:
        """
        Replace `/api/maps` with your map-list endpoint and adapt field names below.
        """

        try:
            payload = self._request("GET", "/api/maps")
            data = self._extract_data(payload) or []
            items = data.get("maps", data) if isinstance(data, dict) else data
            result: List[MapInfo] = []
            for item in items or []:
                result.append(
                    MapInfo(
                        id=int(item["id"]),
                        name=str(item["name"]),
                        description=str(item.get("description", "")),
                    )
                )
            return result
        except Exception:
            return []

    def get_map(self, map_id: int) -> Optional[MapInfo]:
        try:
            payload = self._request("GET", f"/api/maps/{map_id}")
            data = self._extract_data(payload) or {}
            return MapInfo(
                id=int(data["id"]),
                name=str(data["name"]),
                description=str(data.get("description", "")),
            )
        except Exception:
            return None

    def list_waypoints(self, map_id: int) -> List[WaypointInfo]:
        """
        Replace `/api/maps/{map_id}/waypoints` with your real waypoint-list endpoint.
        """

        try:
            payload = self._request("GET", f"/api/maps/{map_id}/waypoints")
            data = self._extract_data(payload) or []
            items = data.get("waypoints", data) if isinstance(data, dict) else data
            result: List[WaypointInfo] = []
            for item in items or []:
                result.append(
                    WaypointInfo(
                        id=int(item["id"]),
                        name=str(item["name"]),
                        map_id=int(item.get("map_id", map_id)),
                        x=float(item.get("x", 0.0) or 0.0),
                        y=float(item.get("y", 0.0) or 0.0),
                        z=float(item.get("z", 0.0) or 0.0),
                        yaw=float(item.get("yaw", 0.0) or 0.0),
                        type=str(item.get("type", "normal")),
                    )
                )
            return result
        except Exception:
            return []

    def get_waypoint(self, waypoint_id: int) -> Optional[WaypointInfo]:
        try:
            payload = self._request("GET", f"/api/waypoints/{waypoint_id}")
            data = self._extract_data(payload) or {}
            return WaypointInfo(
                id=int(data["id"]),
                name=str(data["name"]),
                map_id=int(data.get("map_id", 0)),
                x=float(data.get("x", 0.0) or 0.0),
                y=float(data.get("y", 0.0) or 0.0),
                z=float(data.get("z", 0.0) or 0.0),
                yaw=float(data.get("yaw", 0.0) or 0.0),
                type=str(data.get("type", "normal")),
            )
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def start_navigation(self, map_id: int) -> bool:
        """
        Load or activate a map before waypoint navigation.

        If your robot does not require an explicit map-open step, you can simply:
        - store `self._current_map_id = map_id`
        - return True
        """

        try:
            self._request("POST", "/api/navigation/start", data={"map_id": map_id})
            self._current_map_id = map_id
            self._nav_running = True
            return True
        except Exception:
            return False

    def stop_navigation(self) -> bool:
        try:
            self._request("POST", "/api/navigation/stop")
            self._nav_running = False
            return True
        except Exception:
            return False

    def goto_waypoint(self, waypoint_id: int) -> bool:
        try:
            self._request("POST", "/api/navigation/goto_waypoint", data={"waypoint_id": waypoint_id})
            self._nav_running = True
            return True
        except Exception:
            return False

    def goto_point(self, x: float, y: float, yaw: float = 0.0) -> bool:
        try:
            self._request(
                "POST",
                "/api/navigation/goto_point",
                data={"x": x, "y": y, "yaw": yaw},
            )
            self._nav_running = True
            return True
        except Exception:
            return False

    def navigate_to(self, target: str) -> bool:
        """
        High-level semantic navigation used by MissionManager.

        There are two common implementation choices:

        Option A: your API already supports name-based navigation
            POST /api/navigation/goto_by_name {"target": "大厅"}

        Option B: resolve the name to a waypoint ID first, then call goto_waypoint()

        The template below implements Option B because it works for more vendors.
        """

        if not target:
            return False

        # Convention: if the target is a dock/charge point, route to docking.
        lowered = str(target).lower()
        if any(token in lowered for token in ("dock", "charge")) or any(
            token in str(target) for token in ("回充", "充电", "回桩")
        ):
            return self.execute_docking_async()

        map_id = self._current_map_id
        if map_id is None:
            maps = self.list_maps()
            if maps:
                map_id = maps[0].id
                self._current_map_id = map_id

        if map_id is None:
            return False

        for waypoint in self.list_waypoints(map_id):
            if waypoint.name == target or target in waypoint.name or waypoint.name in target:
                return self.goto_waypoint(waypoint.id)
        return False

    def execute_docking_async(self) -> bool:
        """
        Replace this with your robot's dock / charge / return-to-base API.

        If your robot has no docking capability, return False and avoid using `dock`
        in tasks for that deployment.
        """

        try:
            payload = {"map_id": self._current_map_id} if self._current_map_id is not None else None
            self._request("POST", "/api/navigation/dock", data=payload)
            self._nav_running = True
            return True
        except Exception:
            return False

    def wait_nav_started(self, timeout: int = 15) -> bool:
        """
        Optional helper used by submit_mission when a map must be activated first.

        If your API is synchronous and returns success only after navigation is ready,
        you can simply return True here.
        """

        return True

    def resolve_current_map(self) -> Optional[MapInfo]:
        if self._current_map_id is None:
            return None
        return MapInfo(
            id=int(self._current_map_id),
            name=str(self._current_map_name or self._current_map_id),
        )

    # ------------------------------------------------------------------
    # Human-facing actions
    # ------------------------------------------------------------------

    def prepare_for_movement(self) -> bool:
        """
        Called before `goto` / `dock`.

        Replace this if your robot must stand up, undock, unlock motors, or switch
        mode before navigation. Returning True is acceptable if no preparation is
        required.
        """

        return True

    def set_light(self, color: Any) -> bool:
        """
        Replace `/api/light/set` and the payload mapping with your vendor API.
        """

        try:
            self._request("POST", "/api/light/set", data={"color": color})
            return True
        except Exception:
            return False

    def play_audio(self, text: str) -> bool:
        """
        Replace `/api/audio/tts` with your TTS or speaker endpoint.
        """

        try:
            self._request("POST", "/api/audio/tts", data={"text": text})
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Task API (optional in many deployments)
    # ------------------------------------------------------------------

    def list_tasks(self) -> List[TaskInfo]:
        """
        If your robot does not expose a task API, returning [] is acceptable.
        """

        try:
            payload = self._request("GET", "/api/tasks")
            data = self._extract_data(payload) or []
            items = data.get("tasks", data) if isinstance(data, dict) else data
            result: List[TaskInfo] = []
            for item in items or []:
                result.append(
                    TaskInfo(
                        id=int(item["id"]),
                        name=str(item["name"]),
                        description=str(item.get("description", "")),
                        status=str(item.get("status", "idle")),
                    )
                )
            return result
        except Exception:
            return []

    def run_task(self, task_id: int) -> bool:
        try:
            self._request("POST", f"/api/tasks/{task_id}/run")
            return True
        except Exception:
            return False

    def cancel_task(self) -> bool:
        try:
            self._request("POST", "/api/tasks/cancel")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Optional callback / websocket integration
    # ------------------------------------------------------------------

    def handle_callback_event(self, event: Dict[str, Any]) -> None:
        """
        Update internal state from vendor callbacks or websocket events.

        Recommended mappings:
        - navigation started   -> self._nav_running = True
        - arrived              -> self._nav_running = False
        - dock completed       -> self._nav_running = False; self._charging = True
        - battery update       -> self._battery_soc = ...
        - pose update          -> self._current_pose = ...

        If you also publish EventBus events elsewhere, keep the state updates here.
        """

        event_name = str(event.get("event") or event.get("type") or "").lower()
        if event_name in {"arrived", "nav_arrived"}:
            self._nav_running = False
        elif event_name in {"dock_completed", "dock_success"}:
            self._nav_running = False
            self._charging = True


def create_your_robot_adapter(
    host: str = "127.0.0.1",
    port: int = 8080,
    api_key: str = "",
    protocol: str = "http",
    timeout: int = 15,
    **kwargs: Any,
) -> YourRobotAdapter:
    """
    Factory function used by external code when it wants a custom adapter instance.

    Typical usage:

        adapter = create_your_robot_adapter(
            host="10.0.0.20",
            port=8080,
            api_key="replace-me",
        )
    """

    return YourRobotAdapter(
        host=host,
        port=port,
        api_key=api_key,
        protocol=protocol,
        timeout=timeout,
        **kwargs,
    )
