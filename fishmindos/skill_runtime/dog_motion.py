from __future__ import annotations

from typing import Any

from fishmindos.config import get_section_config
from fishmindos.skill_runtime.base import Skill

from .rosbridge_api import RosbridgeClient, RosbridgeError


DEFAULT_MOTION_PRESETS: dict[str, dict[str, float]] = {
    "stand": {"linear_z": 1.0},
    "lie_down": {"linear_z": -1.0},
}


class DogMotionSkill(Skill):
    name = "robot_motion"
    description = (
        "机器狗实时运动与姿态控制。"
        "action 可选: list_presets, apply_preset, cmd_vel, stop。"
        "底层通过 rosbridge 发布 /cmd_vel。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list_presets", "apply_preset", "cmd_vel", "stop"],
                "description": "动作类型。",
            },
            "preset": {
                "type": "string",
                "description": "预设动作名，例如 stand、lie_down。",
            },
            "linear_x": {"type": "number", "description": "前后速度。"},
            "linear_y": {"type": "number", "description": "横移速度。"},
            "linear_z": {"type": "number", "description": "姿态控制。>0 站立，<0 趴下。"},
            "angular_z": {"type": "number", "description": "偏航角速度。"},
            "repeat": {"type": "integer", "description": "重复发送次数。"},
            "interval_ms": {"type": "integer", "description": "每次发送间隔毫秒。"},
        },
        "required": ["action"],
        "additionalProperties": False,
    }
    expose_as_tool = True

    def __init__(
        self,
        client: RosbridgeClient | None = None,
        presets: dict[str, dict[str, float]] | None = None,
    ) -> None:
        self.client = client or RosbridgeClient.from_env()
        self.presets = self._load_presets()
        if presets:
            self.presets.update(presets)

    def run(self, args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action", "")).strip()
        try:
            if action == "list_presets":
                names = sorted(self.presets.keys())
                return {"ok": True, "detail": f"我能做这些动作：{', '.join(names)}。", "data": names}

            if action == "apply_preset":
                preset = str(args.get("preset", "")).strip()
                if not preset:
                    return {"ok": False, "detail": "缺少 preset。"}
                values = self.presets.get(preset)
                if values is None:
                    return {"ok": False, "detail": f"未知动作预设：{preset}"}
                result = self._publish_cmd_vel(values, args)
                return {
                    "ok": True,
                    "detail": self._preset_message(preset),
                    "data": {"preset": preset, "publish": result.message},
                }

            if action == "cmd_vel":
                values = self._resolve_cmd_vel(args)
                result = self._publish_cmd_vel(values, args)
                return {"ok": True, "detail": "运动控制指令已经发出。", "data": result.message}

            if action == "stop":
                result = self._publish_cmd_vel(
                    {"linear_x": 0.0, "linear_y": 0.0, "linear_z": 0.0, "angular_z": 0.0},
                    args,
                )
                return {"ok": True, "detail": "我先停下。", "data": result.message}
        except RosbridgeError as exc:
            return {"ok": False, "detail": self._humanize_error(str(exc))}

        return {"ok": False, "detail": f"Unsupported action '{action}' for skill {self.name}."}

    @staticmethod
    def _load_presets() -> dict[str, dict[str, float]]:
        config = get_section_config("rosbridge")
        raw = config.get("motion_presets", {})
        presets = {name: dict(values) for name, values in DEFAULT_MOTION_PRESETS.items()}
        if isinstance(raw, dict):
            for key, value in raw.items():
                if isinstance(value, dict):
                    presets[str(key)] = {str(k): float(v) for k, v in value.items() if v is not None}
        return presets

    def _publish_cmd_vel(self, values: dict[str, float], args: dict[str, Any]):
        message = {
            "linear": {
                "x": float(values.get("linear_x", 0.0)),
                "y": float(values.get("linear_y", 0.0)),
                "z": float(values.get("linear_z", 0.0)),
            },
            "angular": {
                "x": 0.0,
                "y": 0.0,
                "z": float(values.get("angular_z", 0.0)),
            },
        }
        repeat = int(args.get("repeat", 3))
        interval_ms = int(args.get("interval_ms", 80))
        return self.client.publish(
            "/cmd_vel",
            message,
            msg_type="geometry_msgs/msg/Twist",
            repeat=repeat,
            interval_ms=interval_ms,
        )

    @staticmethod
    def _resolve_cmd_vel(args: dict[str, Any]) -> dict[str, float]:
        return {
            "linear_x": float(args.get("linear_x", 0.0)),
            "linear_y": float(args.get("linear_y", 0.0)),
            "linear_z": float(args.get("linear_z", 0.0)),
            "angular_z": float(args.get("angular_z", 0.0)),
        }

    @staticmethod
    def _preset_message(preset: str) -> str:
        mapping = {
            "stand": "好，我来站立。",
            "lie_down": "好，我趴下。",
        }
        return mapping.get(preset, f"动作 {preset} 已经发出。")

    @staticmethod
    def _humanize_error(detail: str) -> str:
        lowered = detail.lower()
        if "missing dependency" in lowered:
            return "缺少 websocket-client 依赖，请先安装后再使用机器狗实时控制。"
        if "connection refused" in lowered:
            return "机器狗实时控制服务没连上，请确认 rosbridge 已启动。"
        return detail
