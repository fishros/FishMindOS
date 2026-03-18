from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal


ResponseMode = Literal["json", "text", "binary"]


@dataclass(frozen=True, slots=True)
class NavOperationSpec:
    action: str
    method: str
    path: str
    description: str
    properties: dict[str, dict[str, Any]]
    required: tuple[str, ...] = ()
    path_params: tuple[str, ...] = ()
    query_params: tuple[str, ...] = ()
    body_params: tuple[str, ...] = ()
    file_params: tuple[str, ...] = ()
    response_mode: ResponseMode = "json"
    use_auth: bool = False
    capture_token: bool = False
    extra_body: bool = False


@dataclass(frozen=True, slots=True)
class NavSkillGroupSpec:
    name: str
    description: str
    operations: tuple[NavOperationSpec, ...]


def _string(description: str, enum: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string", "description": description}
    if enum:
        schema["enum"] = enum
    return schema


def _integer(description: str) -> dict[str, Any]:
    return {"type": "integer", "description": description}


def _number(description: str) -> dict[str, Any]:
    return {"type": "number", "description": description}


def _boolean(description: str) -> dict[str, Any]:
    return {"type": "boolean", "description": description}


def _object(description: str, properties: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "description": description,
        "additionalProperties": True,
    }
    if properties:
        schema["properties"] = properties
    return schema


def _array(description: str, items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "description": description, "items": items}


def _point_pose(description: str) -> dict[str, Any]:
    return {
        "type": "object",
        "description": description,
        "properties": {
            "x": _number("X 坐标。"),
            "y": _number("Y 坐标。"),
            "z": _number("Z 坐标。"),
            "roll": _number("Roll 姿态。"),
            "pitch": _number("Pitch 姿态。"),
            "yaw": _number("Yaw 姿态。"),
        },
        "required": ["x", "y", "z", "roll", "pitch", "yaw"],
        "additionalProperties": False,
    }


def _zone_points(description: str) -> dict[str, Any]:
    return _array(
        description,
        {
            "type": "object",
            "properties": {
                "x": _number("X 坐标。"),
                "y": _number("Y 坐标。"),
            },
            "required": ["x", "y"],
            "additionalProperties": False,
        },
    )


USERNAME = _string("登录用户名。")
PASSWORD = _string("登录密码。")
NAME = _string("名称。")
DESCRIPTION = _string("描述文本。")
TEXT = _string("文本内容。")
VALUE = _string("值。字符串、数字、布尔或 JSON 文本都可以。")
PROGRAM = _string("Blockly 程序 JSON 字符串。")
KEY = _string("任务 key。")
MAP_ID = _integer("地图 ID。")
MAP_NAME = _string("地图名称。")
FROM_MAP_ID = _integer("来源地图 ID。")
FROM_MAP_NAME = _string("来源地图名称。")
WAYPOINT_ID = _integer("路点 ID。")
WAYPOINT_NAME = _string("路点名称。")
WAYPOINT_IDS = _array("路点 ID 列表。", {"type": "integer"})
ZONE_ID = _integer("区域 ID。")
ROUTE_ID = _integer("巡检路线 ID。")
TASK_ID = _integer("任务 ID。")
TASK_REF_NAME = _string("任务名称。")
TEMPLATE_ID = _integer("模板 ID。")
KB_ID = _integer("知识库 ID。")
IP_ID = _integer("巡检点 ID。")
REPORT_ID = _string("报告 ID。")
FILENAME = _string("文件名。")
FILE_PATH = _string("本地文件路径。")
SAVE_TO = _string("可选，本地保存路径。")
TIMEOUT = _number("等待超时时间，单位秒。")
SINCE = _number("起始时间戳。")
LIMIT = _integer("返回数量上限。")
FLAG = _string("任务 flag。")
MOCK_AI = _string("mock_ai 标志。")
TASK_NAME = _string("生成的新任务名称。")
TASK_DESCRIPTION = _string("生成的新任务描述。")
ENV_TYPE = _string("地图环境类型。", ["indoor", "outdoor", "mixed"])
INIT_METHOD = _string("建图方式或初始化方式。")
PRESET_START_POINT = _string("预设起点，字符串或 JSON 文本。")
POINT = _point_pose("完整目标位姿。")
WAYPOINT_POINT = _point_pose("路点位姿。")
DISTANCE_TOLERANCE = _number("距离容差。")
ANGLE_TOLERANCE = _number("角度容差。")
SPEED = _number("速度或速度倍率。")
ORDER = _integer("排序号。")
INSPECTION_ORDER = _integer("巡检顺序。")
OBSTACLE_HANDLING = _string("避障策略。", ["bypass", "stop"])
WAYPOINT_TYPE = _string("路点类型，仅当设为回充点时填 dock。", ["dock"])
INCLUDE_INACTIVE = _boolean("是否包含未激活区域。")
ZONE_TYPE = _string("区域类型。", ["forbidden", "slow", "stop"])
ZONE_POINTS = _zone_points("区域多边形点列表。")
Z_MIN = _number("区域最小高度。")
Z_MAX = _number("区域最大高度。")
IS_ACTIVE = _boolean("是否启用。")
SPEED_LIMIT = _number("限速区速度上限。")
THRESHOLD = _number("低电阈值，1 到 100。")
ID_FILTER = _integer("可选，按 ID 过滤。")
X = _number("目标点 X 坐标。")
Y = _number("目标点 Y 坐标。")
Z = _number("目标点 Z 坐标。")
ROLL = _number("目标点 Roll。")
PITCH = _number("目标点 Pitch。")
YAW = _number("目标点 Yaw。")
TARGET_ID = _integer("目标点 ID。")
ON = _boolean("是否开灯。传 false 可关灯。")
CODE = _integer("灯光编码。")
VOLUME = _number("音量，0 到 1。")
DRY_RUN = _boolean("是否只生成计划而不真正执行。")
ZONE_NAME = _string("区域名称。")
WAYPOINTS = _array("巡检路线中的路点 ID 列表。", {"type": "integer"})
CONTENT = _string("正文内容。")


def _op(
    action: str,
    method: str,
    path: str,
    description: str,
    properties: dict[str, dict[str, Any]] | None = None,
    *,
    required: tuple[str, ...] = (),
    path_params: tuple[str, ...] = (),
    query_params: tuple[str, ...] = (),
    body_params: tuple[str, ...] = (),
    file_params: tuple[str, ...] = (),
    response_mode: ResponseMode = "json",
    use_auth: bool = False,
    capture_token: bool = False,
    extra_body: bool = False,
) -> NavOperationSpec:
    return NavOperationSpec(
        action=action,
        method=method,
        path=path,
        description=description,
        properties=properties or {},
        required=required,
        path_params=path_params,
        query_params=query_params,
        body_params=body_params,
        file_params=file_params,
        response_mode=response_mode,
        use_auth=use_auth,
        capture_token=capture_token,
        extra_body=extra_body,
    )


def _group(name: str, description: str, *operations: NavOperationSpec) -> NavSkillGroupSpec:
    return NavSkillGroupSpec(name=name, description=description, operations=operations)


ROBOT_AUTH = _group(
    "robot_auth",
    "机器人认证与当前用户信息查询。action 可选: login, user_info。",
    _op(
        "login",
        "POST",
        "/api/nav/login",
        "使用用户名和密码登录，并缓存 token。",
        {"username": USERNAME, "password": PASSWORD},
        required=("username", "password"),
        body_params=("username", "password"),
        capture_token=True,
    ),
    _op(
        "user_info",
        "GET",
        "/api/nav/user_info",
        "查询当前登录用户信息。",
        use_auth=True,
    ),
)


ROBOT_SETTINGS = _group(
    "robot_settings",
    "设备设置、核心设置和电池阈值管理。action 可选: get_device_id, list_settings, get_setting, create_setting, update_setting, delete_setting, list_core_settings, get_core_setting, update_core_setting, get_battery_low_threshold, update_battery_low_threshold。",
    _op("get_device_id", "GET", "/api/nav/device_id", "查询设备 ID。"),
    _op("list_settings", "GET", "/api/nav/settings", "列出 nav_app 设置项。"),
    _op(
        "get_setting",
        "GET",
        "/api/nav/setting/{name}",
        "查询单个设置项。",
        {"name": NAME},
        required=("name",),
        path_params=("name",),
    ),
    _op(
        "create_setting",
        "POST",
        "/api/nav/setting",
        "创建设置项。",
        {"name": NAME, "value": VALUE},
        required=("name", "value"),
        body_params=("name", "value"),
    ),
    _op(
        "update_setting",
        "PUT",
        "/api/nav/setting/{name}",
        "更新设置项。",
        {"name": NAME, "value": VALUE},
        required=("name", "value"),
        path_params=("name",),
        body_params=("value",),
    ),
    _op(
        "delete_setting",
        "DELETE",
        "/api/nav/setting/{name}",
        "删除设置项。",
        {"name": NAME},
        required=("name",),
        path_params=("name",),
    ),
    _op("list_core_settings", "GET", "/api/nav/core_settings", "列出核心设置。"),
    _op(
        "get_core_setting",
        "GET",
        "/api/nav/core_settings/{name}",
        "查询单个核心设置。",
        {"name": NAME},
        required=("name",),
        path_params=("name",),
    ),
    _op(
        "update_core_setting",
        "PUT",
        "/api/nav/core_settings/{name}",
        "更新核心设置。",
        {"name": NAME, "value": VALUE},
        required=("name", "value"),
        path_params=("name",),
        body_params=("value",),
    ),
    _op("get_battery_low_threshold", "GET", "/api/nav/battery/low_threshold", "查询低电阈值。"),
    _op(
        "update_battery_low_threshold",
        "PUT",
        "/api/nav/battery/low_threshold",
        "更新低电阈值。",
        {"threshold": THRESHOLD},
        required=("threshold",),
        body_params=("threshold",),
    ),
)


ROBOT_TASKS = _group(
    "robot_tasks",
    "真实任务管理。action 可选: list, create, get, delete, update_program, run, cancel, cancel_all。",
    _op("list", "GET", "/api/nav/tasks", "列出任务。", {"map_id": MAP_ID}, query_params=("map_id",)),
    _op(
        "create",
        "POST",
        "/api/nav/tasks",
        "创建任务。",
        {"name": NAME, "description": DESCRIPTION},
        required=("name",),
        body_params=("name", "description"),
    ),
    _op(
        "get",
        "GET",
        "/api/nav/tasks/{task_id}",
        "查询任务详情。",
        {"task_id": TASK_ID, "task_name": TASK_REF_NAME},
        required=("task_id",),
        path_params=("task_id",),
    ),
    _op(
        "delete",
        "DELETE",
        "/api/nav/tasks/{task_id}",
        "删除任务。",
        {"task_id": TASK_ID, "task_name": TASK_REF_NAME},
        required=("task_id",),
        path_params=("task_id",),
    ),
    _op(
        "update_program",
        "PUT",
        "/api/nav/tasks/{task_id}/program",
        "更新任务程序。",
        {"task_id": TASK_ID, "task_name": TASK_REF_NAME, "program": PROGRAM},
        required=("task_id", "program"),
        path_params=("task_id",),
        body_params=("program",),
    ),
    _op(
        "run",
        "POST",
        "/api/nav/tasks/{task_id}/run",
        "执行任务。",
        {"task_id": TASK_ID, "task_name": TASK_REF_NAME, "flag": FLAG, "dry_run": DRY_RUN, "mock_ai": MOCK_AI},
        required=("task_id",),
        path_params=("task_id",),
        body_params=("flag", "dry_run", "mock_ai"),
    ),
    _op(
        "cancel",
        "POST",
        "/api/nav/tasks/{task_id}/cancel",
        "取消任务。",
        {"task_id": TASK_ID, "task_name": TASK_REF_NAME},
        required=("task_id",),
        path_params=("task_id",),
    ),
    _op("cancel_all", "POST", "/api/nav/tasks/cancel_all", "取消所有任务。"),
)


ROBOT_AUDIO_TASKS = _group(
    "robot_audio_tasks",
    "音频任务管理。action 可选: list, create, get, update, delete, update_program, trigger, run_stream。",
    _op("list", "GET", "/api/nav/audio_tasks", "列出音频任务。"),
    _op(
        "create",
        "POST",
        "/api/nav/audio_tasks",
        "创建音频任务。",
        {"name": NAME, "description": DESCRIPTION, "key": KEY},
        required=("name",),
        body_params=("name", "description", "key"),
    ),
    _op(
        "get",
        "GET",
        "/api/nav/audio_tasks/{task_id}",
        "查询音频任务。",
        {"task_id": TASK_ID},
        required=("task_id",),
        path_params=("task_id",),
    ),
    _op(
        "update",
        "PUT",
        "/api/nav/audio_tasks/{task_id}",
        "更新音频任务。",
        {"task_id": TASK_ID, "name": NAME, "description": DESCRIPTION, "key": KEY},
        required=("task_id",),
        path_params=("task_id",),
        body_params=("name", "description", "key"),
    ),
    _op(
        "delete",
        "DELETE",
        "/api/nav/audio_tasks/{task_id}",
        "删除音频任务。",
        {"task_id": TASK_ID},
        required=("task_id",),
        path_params=("task_id",),
    ),
    _op(
        "update_program",
        "PUT",
        "/api/nav/audio_tasks/{task_id}/program",
        "更新音频任务程序。",
        {"task_id": TASK_ID, "program": PROGRAM},
        required=("task_id", "program"),
        path_params=("task_id",),
        body_params=("program",),
    ),
    _op(
        "trigger",
        "POST",
        "/api/nav/audio_tasks/trigger",
        "触发音频任务。",
        {"key": KEY, "text": TEXT},
        required=("key",),
        body_params=("key", "text"),
    ),
    _op(
        "run_stream",
        "POST",
        "/api/nav/audio_tasks/run_stream",
        "流式运行音频任务，返回 SSE 文本。",
        {"key": KEY, "text": TEXT, "save_to": SAVE_TO},
        required=("key",),
        body_params=("key", "text"),
        response_mode="text",
    ),
)


ROBOT_KB = _group(
    "robot_kb",
    "知识库管理。action 可选: list, create, get, update, delete。",
    _op("list", "GET", "/api/nav/kb", "列出知识库。"),
    _op(
        "create",
        "POST",
        "/api/nav/kb",
        "创建知识库。",
        {"name": NAME, "description": DESCRIPTION, "content": CONTENT},
        required=("name",),
        body_params=("name", "description", "content"),
    ),
    _op(
        "get",
        "GET",
        "/api/nav/kb/{kb_id}",
        "查询知识库。",
        {"kb_id": KB_ID},
        required=("kb_id",),
        path_params=("kb_id",),
    ),
    _op(
        "update",
        "PUT",
        "/api/nav/kb/{kb_id}",
        "更新知识库。",
        {"kb_id": KB_ID, "name": NAME, "description": DESCRIPTION, "content": CONTENT},
        required=("kb_id",),
        path_params=("kb_id",),
        body_params=("name", "description", "content"),
    ),
    _op(
        "delete",
        "DELETE",
        "/api/nav/kb/{kb_id}",
        "删除知识库。",
        {"kb_id": KB_ID},
        required=("kb_id",),
        path_params=("kb_id",),
    ),
)


ROBOT_TEMPLATES = _group(
    "robot_templates",
    "任务模板管理。action 可选: list, create, get, delete, update_program, generate_task。",
    _op("list", "GET", "/api/nav/templates", "列出模板。"),
    _op(
        "create",
        "POST",
        "/api/nav/templates",
        "创建模板。",
        {"name": NAME, "description": DESCRIPTION},
        required=("name",),
        body_params=("name", "description"),
    ),
    _op(
        "get",
        "GET",
        "/api/nav/templates/{template_id}",
        "查询模板。",
        {"template_id": TEMPLATE_ID},
        required=("template_id",),
        path_params=("template_id",),
    ),
    _op(
        "delete",
        "DELETE",
        "/api/nav/templates/{template_id}",
        "删除模板。",
        {"template_id": TEMPLATE_ID},
        required=("template_id",),
        path_params=("template_id",),
    ),
    _op(
        "update_program",
        "PUT",
        "/api/nav/templates/{template_id}/program",
        "更新模板程序。",
        {"template_id": TEMPLATE_ID, "program": PROGRAM},
        required=("template_id", "program"),
        path_params=("template_id",),
        body_params=("program",),
    ),
    _op(
        "generate_task",
        "POST",
        "/api/nav/templates/generate",
        "从模板生成任务。",
        {"template_id": TEMPLATE_ID, "task_name": TASK_NAME, "task_description": TASK_DESCRIPTION},
        required=("template_id", "task_name"),
        body_params=("template_id", "task_name", "task_description"),
    ),
)


ROBOT_INSPECTION_POINTS = _group(
    "robot_inspection_points",
    "巡检点管理。action 可选: list, create, get, delete, update_program。",
    _op("list", "GET", "/api/nav/inspection_points", "列出巡检点。", {"map_id": MAP_ID}, query_params=("map_id",)),
    _op(
        "create",
        "POST",
        "/api/nav/inspection_points",
        "创建巡检点。",
        {"name": NAME, "map_id": MAP_ID},
        required=("name", "map_id"),
        body_params=("name", "map_id"),
    ),
    _op(
        "get",
        "GET",
        "/api/nav/inspection_points/{ip_id}",
        "查询巡检点。",
        {"ip_id": IP_ID},
        required=("ip_id",),
        path_params=("ip_id",),
    ),
    _op(
        "delete",
        "DELETE",
        "/api/nav/inspection_points/{ip_id}",
        "删除巡检点。",
        {"ip_id": IP_ID},
        required=("ip_id",),
        path_params=("ip_id",),
    ),
    _op(
        "update_program",
        "PUT",
        "/api/nav/inspection_points/{ip_id}/program",
        "更新巡检点程序。",
        {"ip_id": IP_ID, "program": PROGRAM},
        required=("ip_id", "program"),
        path_params=("ip_id",),
        body_params=("program",),
    ),
)


ROBOT_AUDIO = _group(
    "robot_audio",
    "机器人音频能力。action 可选: list_bgm, upload_bgm, delete_bgm, play_bgm, stop_bgm, get_bgm_status, tts_synthesize, tts_play, get_audio_status, get_audio_state。",
    _op("list_bgm", "GET", "/api/nav/bgm/list", "列出背景音文件。"),
    _op(
        "upload_bgm",
        "POST",
        "/api/nav/bgm/upload",
        "上传背景音文件。",
        {"file_path": FILE_PATH},
        required=("file_path",),
        file_params=("file_path",),
    ),
    _op(
        "delete_bgm",
        "POST",
        "/api/nav/bgm/delete",
        "删除背景音文件。",
        {"name": NAME},
        required=("name",),
        body_params=("name",),
    ),
    _op(
        "play_bgm",
        "POST",
        "/api/nav/bgm/play",
        "播放背景音。",
        {"name": NAME, "volume": VOLUME},
        required=("name",),
        body_params=("name", "volume"),
    ),
    _op("stop_bgm", "POST", "/api/nav/bgm/stop", "停止背景音。"),
    _op("get_bgm_status", "GET", "/api/nav/bgm/status", "查询背景音状态。"),
    _op(
        "tts_synthesize",
        "POST",
        "/api/nav/tts/synthesize",
        "合成语音到文件。",
        {"text": TEXT, "filename": FILENAME},
        required=("text",),
        body_params=("text", "filename"),
    ),
    _op(
        "tts_play",
        "POST",
        "/api/nav/tts/play",
        "直接播报文本。",
        {"text": TEXT},
        required=("text",),
        body_params=("text",),
    ),
    _op("get_audio_status", "GET", "/api/nav/audio/status", "查询音频状态。"),
    _op("get_audio_state", "GET", "/api/nav/audio/state", "查询音频状态快照。"),
)


ROBOT_LIGHT = _group(
    "robot_light",
    "灯光查询与设置。action 可选: list_modes, set。",
    _op("list_modes", "GET", "/api/nav/light/list", "列出灯光模式。"),
    _op(
        "set",
        "POST",
        "/api/nav/light/set",
        "设置灯光。",
        {"on": ON, "code": CODE},
        body_params=("on", "code"),
    ),
)


ROBOT_REPORTS = _group(
    "robot_reports",
    "巡检报告查询、下载和删除。action 可选: list, view_html, download_file, delete, download_pdf。",
    _op("list", "GET", "/api/nav/reports/list", "列出报告。"),
    _op(
        "view_html",
        "GET",
        "/api/nav/reports/view/{report_id}",
        "查看 HTML 报告内容。",
        {"report_id": REPORT_ID, "save_to": SAVE_TO},
        required=("report_id",),
        path_params=("report_id",),
        response_mode="text",
    ),
    _op(
        "download_file",
        "GET",
        "/api/nav/reports/file/{report_id}/{filename}",
        "下载报告附件。",
        {"report_id": REPORT_ID, "filename": FILENAME, "save_to": SAVE_TO},
        required=("report_id", "filename"),
        path_params=("report_id", "filename"),
        response_mode="binary",
    ),
    _op(
        "delete",
        "DELETE",
        "/api/nav/reports/{report_id}",
        "删除报告。",
        {"report_id": REPORT_ID},
        required=("report_id",),
        path_params=("report_id",),
    ),
    _op(
        "download_pdf",
        "GET",
        "/api/nav/reports/pdf/{report_id}",
        "下载 PDF 报告。",
        {"report_id": REPORT_ID, "save_to": SAVE_TO},
        required=("report_id",),
        path_params=("report_id",),
        response_mode="binary",
    ),
)


ROBOT_MAPS = _group(
    "robot_maps",
    "地图管理。action 可选: list, create, cancel_create, finish_create, continue_save, get, update, delete, get_2d, get_3d, get_show_3d, show_3d。",
    _op("list", "GET", "/api/nav/maps/list", "列出地图。", {"id": ID_FILTER}, query_params=("id",)),
    _op(
        "create",
        "POST",
        "/api/nav/maps/create",
        "创建地图。",
        {"name": NAME, "env_type": ENV_TYPE, "description": DESCRIPTION, "init_method": INIT_METHOD},
        required=("name",),
        body_params=("name", "env_type", "description", "init_method"),
    ),
    _op(
        "cancel_create",
        "POST",
        "/api/nav/maps/create/cancel",
        "取消当前建图。",
        {"map_id": MAP_ID},
        body_params=("map_id",),
    ),
    _op(
        "finish_create",
        "POST",
        "/api/nav/maps/create/finish",
        "完成建图并保存。",
        {"map_id": MAP_ID},
        required=("map_id",),
        body_params=("map_id",),
    ),
    _op(
        "continue_save",
        "POST",
        "/api/nav/maps/{map_id}/continue_save",
        "续建并保存地图。",
        {"map_id": MAP_ID},
        required=("map_id",),
        path_params=("map_id",),
    ),
    _op(
        "get",
        "GET",
        "/api/nav/maps/{map_id}",
        "查询地图详情。",
        {"map_id": MAP_ID},
        required=("map_id",),
        path_params=("map_id",),
    ),
    _op(
        "update",
        "PUT",
        "/api/nav/maps/{map_id}",
        "更新地图。",
        {
            "map_id": MAP_ID,
            "name": NAME,
            "init_method": INIT_METHOD,
            "preset_start_point": PRESET_START_POINT,
            "description": DESCRIPTION,
        },
        required=("map_id",),
        path_params=("map_id",),
        body_params=("name", "init_method", "preset_start_point", "description"),
    ),
    _op(
        "delete",
        "DELETE",
        "/api/nav/maps/{map_id}",
        "删除地图。",
        {"map_id": MAP_ID},
        required=("map_id",),
        path_params=("map_id",),
    ),
    _op(
        "get_2d",
        "GET",
        "/api/nav/maps/{map_id}/2d_map",
        "下载 2D 地图图片。",
        {"map_id": MAP_ID, "save_to": SAVE_TO},
        required=("map_id",),
        path_params=("map_id",),
        response_mode="binary",
    ),
    _op(
        "get_3d",
        "GET",
        "/api/nav/maps/{map_id}/3d_map",
        "下载 3D 地图文件。",
        {"map_id": MAP_ID, "save_to": SAVE_TO},
        required=("map_id",),
        path_params=("map_id",),
        response_mode="binary",
    ),
    _op(
        "get_show_3d",
        "GET",
        "/api/nav/maps/{map_id}/show_3d",
        "查询 3D 展示状态。",
        {"map_id": MAP_ID},
        required=("map_id",),
        path_params=("map_id",),
    ),
    _op(
        "show_3d",
        "POST",
        "/api/nav/maps/{map_id}/show_3d",
        "触发 3D 展示。",
        {"map_id": MAP_ID},
        required=("map_id",),
        path_params=("map_id",),
    ),
)


ROBOT_NAVIGATION = _group(
    "robot_navigation",
    "导航控制与状态查询。action 可选: start, stop, goto_waypoint, goto_point, dock_to_waypoint, stop_goto_waypoint, pause_goto_waypoint, resume_goto_waypoint, get_current_position, get_state。",
    _op(
        "start",
        "POST",
        "/api/nav/nav/start",
        "启动地图导航。",
        {"map_id": MAP_ID, "map_name": MAP_NAME, "waypoint_ids": WAYPOINT_IDS},
        body_params=("map_id", "waypoint_ids"),
    ),
    _op("stop", "POST", "/api/nav/nav/stop", "停止导航。"),
    _op(
        "goto_waypoint",
        "POST",
        "/api/nav/nav/goto_waypoint",
        "导航到指定路点。",
        {
            "waypoint_id": WAYPOINT_ID,
            "waypoint_name": WAYPOINT_NAME,
            "map_id": MAP_ID,
            "map_name": MAP_NAME,
            "speed": SPEED,
            "distance_tolerance": DISTANCE_TOLERANCE,
            "angle_tolerance": ANGLE_TOLERANCE,
            "obstacle_handling": OBSTACLE_HANDLING,
        },
        required=("waypoint_id",),
        body_params=("waypoint_id", "speed", "distance_tolerance", "angle_tolerance", "obstacle_handling"),
    ),
    _op(
        "goto_point",
        "POST",
        "/api/nav/nav/goto_point",
        "导航到指定坐标点。",
        {
            "x": X,
            "y": Y,
            "z": Z,
            "roll": ROLL,
            "pitch": PITCH,
            "yaw": YAW,
            "speed": SPEED,
            "distance_tolerance": DISTANCE_TOLERANCE,
            "angle_tolerance": ANGLE_TOLERANCE,
            "obstacle_handling": OBSTACLE_HANDLING,
            "target_id": TARGET_ID,
        },
        required=("x", "y"),
        body_params=(
            "x",
            "y",
            "z",
            "roll",
            "pitch",
            "yaw",
            "speed",
            "distance_tolerance",
            "angle_tolerance",
            "obstacle_handling",
            "target_id",
        ),
    ),
    _op(
        "dock_to_waypoint",
        "POST",
        "/api/nav/nav/dock_to_waypoint",
        "导航并回充到指定路点。",
        {
            "waypoint_id": WAYPOINT_ID,
            "waypoint_name": WAYPOINT_NAME,
            "map_id": MAP_ID,
            "map_name": MAP_NAME,
            "speed": SPEED,
            "distance_tolerance": DISTANCE_TOLERANCE,
            "angle_tolerance": ANGLE_TOLERANCE,
            "obstacle_handling": OBSTACLE_HANDLING,
        },
        required=("waypoint_id",),
        body_params=("waypoint_id", "speed", "distance_tolerance", "angle_tolerance", "obstacle_handling"),
    ),
    _op("stop_goto_waypoint", "POST", "/api/nav/nav/stop_goto_waypoint", "停止当前到路点的导航。"),
    _op("pause_goto_waypoint", "POST", "/api/nav/nav/pause_goto_waypoint", "暂停当前到路点的导航。"),
    _op("resume_goto_waypoint", "POST", "/api/nav/nav/resume_goto_waypoint", "恢复当前到路点的导航。"),
    _op("get_current_position", "GET", "/api/nav/nav/current_position", "查询当前位置。"),
    _op("get_state", "GET", "/api/nav/nav/state", "查询导航状态。"),
)


ROBOT_WAYPOINTS = _group(
    "robot_waypoints",
    "路点管理。action 可选: list, create, create_current_position, get, update, delete, clear, copy_from_map。",
    _op(
        "list",
        "GET",
        "/api/nav/maps/{map_id}/waypoints",
        "列出地图路点。",
        {"map_id": MAP_ID, "map_name": MAP_NAME},
        required=("map_id",),
        path_params=("map_id",),
    ),
    _op(
        "create",
        "POST",
        "/api/nav/maps/{map_id}/waypoints",
        "创建路点。",
        {
            "map_id": MAP_ID,
            "map_name": MAP_NAME,
            "name": NAME,
            "point": WAYPOINT_POINT,
            "distance_tolerance": DISTANCE_TOLERANCE,
            "angle_tolerance": ANGLE_TOLERANCE,
            "speed": SPEED,
            "order": ORDER,
            "obstacle_handling": OBSTACLE_HANDLING,
            "type": WAYPOINT_TYPE,
        },
        required=("map_id", "name", "point"),
        path_params=("map_id",),
        body_params=("name", "point", "distance_tolerance", "angle_tolerance", "speed", "order", "obstacle_handling", "type"),
    ),
    _op(
        "create_current_position",
        "POST",
        "/api/nav/maps/{map_id}/waypoints/current_position",
        "将当前位置保存为路点。",
        {
            "map_id": MAP_ID,
            "map_name": MAP_NAME,
            "name": NAME,
            "distance_tolerance": DISTANCE_TOLERANCE,
            "angle_tolerance": ANGLE_TOLERANCE,
            "speed": SPEED,
            "order": ORDER,
            "obstacle_handling": OBSTACLE_HANDLING,
        },
        required=("map_id", "name"),
        path_params=("map_id",),
        body_params=("name", "distance_tolerance", "angle_tolerance", "speed", "order", "obstacle_handling"),
    ),
    _op(
        "get",
        "GET",
        "/api/nav/maps/{map_id}/waypoints/{waypoint_id}",
        "查询路点详情。",
        {"map_id": MAP_ID, "map_name": MAP_NAME, "waypoint_id": WAYPOINT_ID, "waypoint_name": WAYPOINT_NAME},
        required=("map_id", "waypoint_id"),
        path_params=("map_id", "waypoint_id"),
    ),
    _op(
        "update",
        "PUT",
        "/api/nav/maps/{map_id}/waypoints/{waypoint_id}",
        "更新路点。",
        {
            "map_id": MAP_ID,
            "map_name": MAP_NAME,
            "waypoint_id": WAYPOINT_ID,
            "waypoint_name": WAYPOINT_NAME,
            "name": NAME,
            "point": WAYPOINT_POINT,
            "distance_tolerance": DISTANCE_TOLERANCE,
            "angle_tolerance": ANGLE_TOLERANCE,
            "speed": SPEED,
            "order": ORDER,
            "inspection_order": INSPECTION_ORDER,
            "obstacle_handling": OBSTACLE_HANDLING,
            "type": WAYPOINT_TYPE,
        },
        required=("map_id", "waypoint_id"),
        path_params=("map_id", "waypoint_id"),
        body_params=(
            "name",
            "point",
            "distance_tolerance",
            "angle_tolerance",
            "speed",
            "order",
            "inspection_order",
            "obstacle_handling",
            "type",
        ),
    ),
    _op(
        "delete",
        "DELETE",
        "/api/nav/maps/{map_id}/waypoints/{waypoint_id}",
        "删除路点。",
        {"map_id": MAP_ID, "map_name": MAP_NAME, "waypoint_id": WAYPOINT_ID, "waypoint_name": WAYPOINT_NAME},
        required=("map_id", "waypoint_id"),
        path_params=("map_id", "waypoint_id"),
    ),
    _op(
        "clear",
        "DELETE",
        "/api/nav/maps/{map_id}/waypoints/clear",
        "清空地图路点。",
        {"map_id": MAP_ID, "map_name": MAP_NAME},
        required=("map_id",),
        path_params=("map_id",),
    ),
    _op(
        "copy_from_map",
        "POST",
        "/api/nav/maps/{map_id}/waypoints/copy_from/{from_map_id}",
        "从其他地图复制路点。",
        {"map_id": MAP_ID, "map_name": MAP_NAME, "from_map_id": FROM_MAP_ID, "from_map_name": FROM_MAP_NAME},
        required=("map_id", "from_map_id"),
        path_params=("map_id", "from_map_id"),
    ),
)


ROBOT_DOCK = _group(
    "robot_dock",
    "回充点管理。action 可选: get, set, clear。",
    _op(
        "get",
        "GET",
        "/api/nav/maps/{map_id}/dock_waypoint",
        "查询回充点。",
        {"map_id": MAP_ID, "map_name": MAP_NAME},
        required=("map_id",),
        path_params=("map_id",),
    ),
    _op(
        "set",
        "PUT",
        "/api/nav/maps/{map_id}/dock_waypoint",
        "设置回充点。",
        {"map_id": MAP_ID, "map_name": MAP_NAME, "waypoint_id": WAYPOINT_ID, "waypoint_name": WAYPOINT_NAME},
        required=("map_id", "waypoint_id"),
        path_params=("map_id",),
        body_params=("waypoint_id",),
    ),
    _op(
        "clear",
        "DELETE",
        "/api/nav/maps/{map_id}/dock_waypoint",
        "清除回充点。",
        {"map_id": MAP_ID, "map_name": MAP_NAME},
        required=("map_id",),
        path_params=("map_id",),
    ),
)


ROBOT_PATROL_ROUTES = _group(
    "robot_patrol_routes",
    "巡检路线管理。action 可选: list, create, update, delete。",
    _op(
        "list",
        "GET",
        "/api/nav/maps/{map_id}/patrol_routes",
        "列出巡检路线。",
        {"map_id": MAP_ID},
        required=("map_id",),
        path_params=("map_id",),
    ),
    _op(
        "create",
        "POST",
        "/api/nav/maps/{map_id}/patrol_routes",
        "创建巡检路线。",
        {"map_id": MAP_ID, "name": NAME, "waypoints": WAYPOINTS},
        required=("map_id", "name", "waypoints"),
        path_params=("map_id",),
        body_params=("name", "waypoints"),
    ),
    _op(
        "update",
        "PUT",
        "/api/nav/maps/{map_id}/patrol_routes/{route_id}",
        "更新巡检路线。",
        {"map_id": MAP_ID, "route_id": ROUTE_ID, "name": NAME, "waypoints": WAYPOINTS, "is_active": IS_ACTIVE},
        required=("map_id", "route_id"),
        path_params=("map_id", "route_id"),
        body_params=("name", "waypoints", "is_active"),
    ),
    _op(
        "delete",
        "DELETE",
        "/api/nav/maps/{map_id}/patrol_routes/{route_id}",
        "删除巡检路线。",
        {"map_id": MAP_ID, "route_id": ROUTE_ID},
        required=("map_id", "route_id"),
        path_params=("map_id", "route_id"),
    ),
)


ROBOT_EVENTS = _group(
    "robot_events",
    "导航事件查询与等待。action 可选: poll, history, state, wait_arrival, wait_nav_started, wait_dock_complete。",
    _op("poll", "GET", "/api/nav/events/poll", "轮询事件。", {"timeout": TIMEOUT, "since": SINCE}, query_params=("timeout", "since")),
    _op("history", "GET", "/api/nav/events/history", "查询历史事件。", {"limit": LIMIT, "since": SINCE}, query_params=("limit", "since")),
    _op("state", "GET", "/api/nav/events/state", "查询事件状态。"),
    _op(
        "wait_arrival",
        "POST",
        "/api/nav/events/wait_arrival",
        "等待到达指定路点。",
        {"waypoint_id": WAYPOINT_ID, "timeout": TIMEOUT},
        required=("waypoint_id",),
        body_params=("waypoint_id", "timeout"),
    ),
    _op(
        "wait_nav_started",
        "POST",
        "/api/nav/events/wait_nav_started",
        "等待导航启动。",
        {"timeout": TIMEOUT},
        body_params=("timeout",),
    ),
    _op(
        "wait_dock_complete",
        "POST",
        "/api/nav/events/wait_dock_complete",
        "等待回充完成。",
        {"timeout": TIMEOUT},
        body_params=("timeout",),
    ),
)


ROBOT_STATUS = _group(
    "robot_status",
    "机器人整体状态查询。action 可选: health, status, current_pose, arrived, charging_status, battery_soc。",
    _op("health", "GET", "/api/nav/status/health", "查询健康状态。"),
    _op("status", "GET", "/api/nav/status", "查询总状态。"),
    _op("current_pose", "GET", "/api/nav/status/current_pose", "查询当前位姿。"),
    _op("arrived", "GET", "/api/nav/status/arrived", "查询是否到达目标。"),
    _op("charging_status", "GET", "/api/nav/status", "查询当前是否在充电。"),
    _op("battery_soc", "GET", "/api/nav/status", "查询当前电量。"),
)


ROBOT_ZONES = _group(
    "robot_zones",
    "区域管理。action 可选: list, create, update, delete。需要额外传 zone_type=forbidden/slow/stop。",
    _op(
        "list",
        "GET",
        "/api/nav/maps/{map_id}/{zone_type}_zones",
        "列出指定类型区域。",
        {"map_id": MAP_ID, "map_name": MAP_NAME, "zone_type": ZONE_TYPE, "include_inactive": INCLUDE_INACTIVE},
        required=("map_id", "zone_type"),
        path_params=("map_id", "zone_type"),
        query_params=("include_inactive",),
    ),
    _op(
        "create",
        "POST",
        "/api/nav/maps/{map_id}/{zone_type}_zones",
        "创建区域。",
        {
            "map_id": MAP_ID,
            "zone_type": ZONE_TYPE,
            "name": ZONE_NAME,
            "points": ZONE_POINTS,
            "z_min": Z_MIN,
            "z_max": Z_MAX,
            "is_active": IS_ACTIVE,
            "speed_limit": SPEED_LIMIT,
        },
        required=("map_id", "zone_type", "points"),
        path_params=("map_id", "zone_type"),
        body_params=("name", "points", "z_min", "z_max", "is_active", "speed_limit"),
    ),
    _op(
        "update",
        "PUT",
        "/api/nav/maps/{map_id}/{zone_type}_zones/{zone_id}",
        "更新区域。",
        {
            "map_id": MAP_ID,
            "zone_type": ZONE_TYPE,
            "zone_id": ZONE_ID,
            "name": ZONE_NAME,
            "points": ZONE_POINTS,
            "z_min": Z_MIN,
            "z_max": Z_MAX,
            "is_active": IS_ACTIVE,
            "speed_limit": SPEED_LIMIT,
        },
        required=("map_id", "zone_type", "zone_id"),
        path_params=("map_id", "zone_type", "zone_id"),
        body_params=("name", "points", "z_min", "z_max", "is_active", "speed_limit"),
    ),
    _op(
        "delete",
        "DELETE",
        "/api/nav/maps/{map_id}/{zone_type}_zones/{zone_id}",
        "删除区域。",
        {"map_id": MAP_ID, "zone_type": ZONE_TYPE, "zone_id": ZONE_ID},
        required=("map_id", "zone_type", "zone_id"),
        path_params=("map_id", "zone_type", "zone_id"),
    ),
)


NAV_SKILL_GROUPS: tuple[NavSkillGroupSpec, ...] = (
    ROBOT_AUTH,
    ROBOT_SETTINGS,
    ROBOT_TASKS,
    ROBOT_AUDIO_TASKS,
    ROBOT_KB,
    ROBOT_TEMPLATES,
    ROBOT_INSPECTION_POINTS,
    ROBOT_AUDIO,
    ROBOT_LIGHT,
    ROBOT_REPORTS,
    ROBOT_MAPS,
    ROBOT_NAVIGATION,
    ROBOT_WAYPOINTS,
    ROBOT_DOCK,
    ROBOT_PATROL_ROUTES,
    ROBOT_EVENTS,
    ROBOT_STATUS,
    ROBOT_ZONES,
)


def build_group_input_schema(group: NavSkillGroupSpec) -> dict[str, Any]:
    properties: dict[str, dict[str, Any]] = {
        "action": {
            "type": "string",
            "enum": [operation.action for operation in group.operations],
            "description": "操作类型。可选值见 enum。",
        }
    }
    include_save_to = False
    for operation in group.operations:
        if operation.response_mode in ("text", "binary"):
            include_save_to = True
        for key, value in operation.properties.items():
            properties.setdefault(key, deepcopy(value))
    if include_save_to:
        properties.setdefault("save_to", deepcopy(SAVE_TO))

    return {
        "type": "object",
        "properties": properties,
        "required": ["action"],
        "additionalProperties": False,
    }
