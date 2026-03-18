from __future__ import annotations

import json
import time
from contextlib import closing
from dataclasses import dataclass
from typing import Any

from fishmindos.config import get_section_config


class RosbridgeError(RuntimeError):
    """Raised when rosbridge realtime control cannot be used."""


@dataclass(slots=True)
class RosbridgePublishResult:
    topic: str
    msg_type: str
    message: dict[str, Any]
    repeat: int


@dataclass(slots=True)
class RosbridgeSubscribeResult:
    topic: str
    msg_type: str
    message: dict[str, Any]


@dataclass
class RosbridgeClient:
    ws_url: str
    timeout_sec: int = 5

    @classmethod
    def from_env(cls) -> RosbridgeClient:
        config = get_section_config("rosbridge")
        ws_url = str(config.get("ws_url", "")).strip()
        if not ws_url:
            scheme = str(config.get("scheme", "")).strip().lower()
            host = str(config.get("host", "")).strip()
            port = config.get("port", "")
            path = str(config.get("path", "/api/rt")).strip() or "/api/rt"

            nav_config = get_section_config("nav")
            if not host:
                host = str(nav_config.get("host", "")).strip() or "127.0.0.1"
            if not port:
                port = nav_config.get("port", 8888)

            if not scheme:
                nav_scheme = str(nav_config.get("scheme", "http")).strip().lower()
                scheme = "wss" if nav_scheme == "https" else "ws"

            normalized_path = path if path.startswith("/") else f"/{path}"
            ws_url = f"{scheme}://{host}:{int(port)}{normalized_path}"

        timeout_raw = config.get("timeout_sec", 5)
        try:
            timeout_sec = max(1, int(timeout_raw))
        except (TypeError, ValueError):
            timeout_sec = 5
        return cls(ws_url=ws_url, timeout_sec=timeout_sec)

    def publish(
        self,
        topic: str,
        msg: dict[str, Any],
        *,
        msg_type: str,
        repeat: int = 1,
        interval_ms: int = 60,
    ) -> RosbridgePublishResult:
        websocket = self._load_websocket_module()
        resolved_repeat = max(1, int(repeat))
        resolved_interval = max(0, int(interval_ms))

        try:
            with closing(websocket.create_connection(self.ws_url, timeout=self.timeout_sec)) as ws:
                ws.send(json.dumps({"op": "advertise", "topic": topic, "type": msg_type}, ensure_ascii=False))
                for index in range(resolved_repeat):
                    ws.send(json.dumps({"op": "publish", "topic": topic, "msg": msg}, ensure_ascii=False))
                    if resolved_interval and index < resolved_repeat - 1:
                        time.sleep(resolved_interval / 1000.0)
        except Exception as exc:  # pragma: no cover - network path
            raise RosbridgeError(f"Rosbridge unavailable: {exc}") from exc

        return RosbridgePublishResult(
            topic=topic,
            msg_type=msg_type,
            message=msg,
            repeat=resolved_repeat,
        )

    def subscribe_once(
        self,
        topic: str,
        *,
        msg_type: str,
        timeout_sec: int | float | None = None,
    ) -> RosbridgeSubscribeResult:
        websocket = self._load_websocket_module()
        resolved_timeout = float(timeout_sec or self.timeout_sec)

        try:
            with closing(websocket.create_connection(self.ws_url, timeout=resolved_timeout)) as ws:
                ws.settimeout(resolved_timeout)
                ws.send(json.dumps({"op": "subscribe", "topic": topic, "type": msg_type}, ensure_ascii=False))
                deadline = time.time() + resolved_timeout
                while time.time() < deadline:
                    raw = ws.recv()
                    payload = json.loads(raw)
                    if payload.get("op") != "publish" or payload.get("topic") != topic:
                        continue
                    message = payload.get("msg")
                    if not isinstance(message, dict):
                        raise RosbridgeError(f"Rosbridge returned invalid message payload for topic {topic}.")
                    return RosbridgeSubscribeResult(topic=topic, msg_type=msg_type, message=message)
        except RosbridgeError:
            raise
        except Exception as exc:  # pragma: no cover - network path
            raise RosbridgeError(f"Rosbridge unavailable: {exc}") from exc

        raise RosbridgeError(f"Rosbridge timed out waiting for topic {topic}.")

    @staticmethod
    def _load_websocket_module():
        try:
            import websocket  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on local env
            raise RosbridgeError(
                "Missing dependency 'websocket-client'. Install it with: pip install websocket-client"
            ) from exc
        return websocket
