"""
FishMindOS Adapters - 适配器层
提供统一的机器人API接口
"""

from fishmindos.adapters.base import (
    RobotAdapter,
    MapInfo,
    WaypointInfo,
    TaskInfo,
    RobotStatus,
    AdapterError,
)
from fishmindos.adapters.fishbot import FishBotAdapter, create_fishbot_adapter
from fishmindos.adapters.your_robot import YourRobotAdapter, create_your_robot_adapter

__all__ = [
    "RobotAdapter",
    "MapInfo",
    "WaypointInfo",
    "TaskInfo",
    "RobotStatus",
    "AdapterError",
    "FishBotAdapter",
    "create_fishbot_adapter",
    "YourRobotAdapter",
    "create_your_robot_adapter",
]
