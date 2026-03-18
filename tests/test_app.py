from __future__ import annotations

import os
from pathlib import Path
import pytest

from fishmindos import FishMindOSApp
from fishmindos.agent_core import AgentCoreRuntime, LLMTaskPlanner
from fishmindos.agent_core.llm import OpenAICompatibleLLMClient
from fishmindos.agent_core.planner import HybridTaskPlanner, QuickCommandPlanner
from fishmindos.config import get_config_value, load_runtime_config
from fishmindos.execution_runtime import TaskExecutor
from fishmindos.interaction import InteractionLayer
from fishmindos.mcp import LocalMCPClient, LocalMCPServer, PromptResourceCatalog
from fishmindos.models import InteractionEvent, PlannedSkillCall, TaskSequence
from fishmindos.skill_runtime import SkillRegistry, register_nav_api_skills
from fishmindos.skill_runtime.nav_api import NavAPIClient, NavAPIError, NavAPIResult
from fishmindos.skill_runtime.rosbridge_api import RosbridgeError


class RecordingNavAPIClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.token: str | None = None

    def request_json(
        self,
        method: str,
        path: str,
        *,
        query: dict | None = None,
        json_body: dict | None = None,
        use_auth: bool = False,
        capture_token: bool = False,
        timeout_sec: int | float | None = None,
    ) -> NavAPIResult:
        self.calls.append(
            {
                "kind": "json",
                "method": method,
                "path": path,
                "query": query,
                "json_body": json_body,
                "use_auth": use_auth,
                "capture_token": capture_token,
                "timeout_sec": timeout_sec,
            }
        )
        if path == "/api/nav/login":
            if capture_token:
                self.token = "token-123"
            payload = {"message": "ok", "token": "token-123"}
        elif path == "/api/nav/nav/state":
            payload = {"code": 200, "msg": "ok", "data": {"nav_running": True}}
        elif path == "/api/nav/nav/current_position":
            payload = {"code": 200, "msg": "ok", "data": {"x": 1.0, "y": 2.0, "yaw": 0.5}}
        elif path == "/api/nav/maps/list":
            payload = {
                "code": 200,
                "msg": "获取地图列表成功",
                "data": {
                    "maps": [
                        {"id": 26, "name": "26层"},
                        {"id": 3, "name": "大厅"},
                    ]
                },
            }
        elif path == "/api/nav/tasks":
            payload = {
                "code": 200,
                "msg": "获取任务列表成功",
                "data": {
                    "tasks": [
                        {"id": 4, "name": "拍照任务"},
                        {"id": 5, "name": "迎宾任务"},
                        {"id": 6, "name": "巡逻任务"},
                        {"id": 7, "name": "回充任务"},
                    ]
                },
            }
        elif path == "/api/nav/maps/26/waypoints":
            payload = {
                "code": 200,
                "msg": "ok",
                "data": {"waypoints": [{"id": 101, "name": "回充点"}, {"id": 102, "name": "厨房门口"}, {"id": 103, "name": "前台"}]},
            }
        elif path == "/api/nav/maps/3/waypoints":
            payload = {
                "code": 200,
                "msg": "ok",
                "data": {"waypoints": [{"id": 201, "name": "大厅"}, {"id": 202, "name": "前台"}]},
            }
        elif path == "/api/nav/maps/26/dock_waypoint":
            payload = {"code": 200, "msg": "ok", "data": {"map_id": 26, "waypoint_id": 101, "name": "回充点"}}
        elif path == "/api/nav/maps/26/stop_zones":
            payload = {
                "code": 200,
                "msg": "ok",
                "data": {"zones": [{"id": 301, "name": "厨房", "points": [{"x": 1.0, "y": 2.0}, {"x": 3.0, "y": 4.0}]}]},
            }
        elif path == "/api/nav/maps/26/slow_zones":
            payload = {"code": 200, "msg": "ok", "data": {"zones": []}}
        elif path == "/api/nav/maps/26/forbidden_zones":
            payload = {"code": 200, "msg": "ok", "data": {"zones": []}}
        elif path == "/api/nav/tasks/4":
            payload = {"code": 200, "msg": "ok", "data": {"id": 4, "name": "拍照任务", "description": "去指定位置完成拍照。"}}
        else:
            payload = {"code": 200, "msg": "ok", "data": json_body or query or {"path": path}}
        return NavAPIResult(200, f"http://robot{path}", "application/json", {}, payload)

    def request_text(
        self,
        method: str,
        path: str,
        *,
        query: dict | None = None,
        json_body: dict | None = None,
        use_auth: bool = False,
        timeout_sec: int | float | None = None,
    ) -> NavAPIResult:
        self.calls.append(
            {
                "kind": "text",
                "method": method,
                "path": path,
                "query": query,
                "json_body": json_body,
                "use_auth": use_auth,
                "timeout_sec": timeout_sec,
            }
        )
        return NavAPIResult(200, f"http://robot{path}", "text/plain", {}, "event: done\ndata: ok\n")

    def request_binary(
        self,
        method: str,
        path: str,
        *,
        query: dict | None = None,
        use_auth: bool = False,
        timeout_sec: int | float | None = None,
    ) -> NavAPIResult:
        self.calls.append(
            {
                "kind": "binary",
                "method": method,
                "path": path,
                "query": query,
                "use_auth": use_auth,
                "timeout_sec": timeout_sec,
            }
        )
        return NavAPIResult(200, f"http://robot{path}", "application/pdf", {}, b"PDFDATA")

    def upload_file(
        self,
        method: str,
        path: str,
        *,
        files: dict[str, str],
        fields: dict | None = None,
        use_auth: bool = False,
        timeout_sec: int | float | None = None,
    ) -> NavAPIResult:
        self.calls.append(
            {
                "kind": "upload",
                "method": method,
                "path": path,
                "files": files,
                "fields": fields,
                "use_auth": use_auth,
                "timeout_sec": timeout_sec,
            }
        )
        payload = {"code": 0, "msg": "uploaded", "data": {"files": files, "fields": fields or {}}}
        return NavAPIResult(200, f"http://robot{path}", "application/json", {}, payload)

    def save_binary(self, payload: bytes, save_to: str) -> str:
        path = Path(save_to)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return str(path)

    def save_text(self, payload: str, save_to: str) -> str:
        path = Path(save_to)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        return str(path)


class TaskFallbackNavAPIClient(RecordingNavAPIClient):
    def request_json(
        self,
        method: str,
        path: str,
        *,
        query: dict | None = None,
        json_body: dict | None = None,
        use_auth: bool = False,
        capture_token: bool = False,
        timeout_sec: int | float | None = None,
    ) -> NavAPIResult:
        self.calls.append(
            {
                "kind": "json",
                "method": method,
                "path": path,
                "query": query,
                "json_body": json_body,
                "use_auth": use_auth,
                "capture_token": capture_token,
                "timeout_sec": timeout_sec,
            }
        )
        if path == "/api/nav/tasks/123444":
            raise NavAPIError('Nav API HTTP 404: {"code":1,"data":null,"msg":"任务不存在"}')
        if path == "/api/nav/tasks/41":
            payload = {
                "code": 200,
                "msg": "ok",
                "data": {"id": 41, "name": "123444", "description": "这是测试任务。"},
            }
            return NavAPIResult(200, f"http://robot{path}", "application/json", {}, payload)
        if path == "/api/nav/tasks":
            payload = {
                "code": 200,
                "msg": "获取任务列表成功",
                "data": {
                    "tasks": [
                        {"id": 41, "name": "123444", "description": "这是测试任务。"},
                        {"id": 42, "name": "地铁站", "description": ""},
                    ]
                },
            }
            return NavAPIResult(200, f"http://robot{path}", "application/json", {}, payload)
        return super().request_json(
            method,
            path,
            query=query,
            json_body=json_body,
            use_auth=use_auth,
            capture_token=capture_token,
            timeout_sec=timeout_sec,
        )


class RecordingRosbridgeClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.fail_with: str | None = None
        self.topic_messages: dict[str, dict] = {
            "/bms_state": {"data": -1.2},
            "/bms_soc": {"data": 78.5},
        }

    def publish(
        self,
        topic: str,
        msg: dict,
        *,
        msg_type: str,
        repeat: int = 1,
        interval_ms: int = 60,
    ):
        if self.fail_with:
            raise RosbridgeError(self.fail_with)
        self.calls.append(
            {
                "kind": "publish",
                "topic": topic,
                "msg": msg,
                "msg_type": msg_type,
                "repeat": repeat,
                "interval_ms": interval_ms,
            }
        )
        return type(
            "PublishResult",
            (),
            {"topic": topic, "msg_type": msg_type, "message": msg, "repeat": repeat},
        )()

    def subscribe_once(
        self,
        topic: str,
        *,
        msg_type: str,
        timeout_sec: int | float | None = None,
    ):
        if self.fail_with:
            raise RosbridgeError(self.fail_with)
        message = self.topic_messages.get(topic, {"data": None})
        self.calls.append(
            {
                "kind": "subscribe",
                "topic": topic,
                "msg_type": msg_type,
                "timeout_sec": timeout_sec,
            }
        )
        return type(
            "SubscribeResult",
            (),
            {"topic": topic, "msg_type": msg_type, "message": message},
        )()


class StubToolClient:
    def plan_tool_calls(
        self,
        event: InteractionEvent,
        tools: list[dict],
        prompt_documents: dict | None = None,
    ) -> list[dict]:
        tool_names = {item["function"]["name"] for item in tools}
        assert "robot_navigation_assistant" in tool_names
        assert isinstance(prompt_documents, dict)
        assert "agent" in prompt_documents
        return [{"id": "call_1", "name": "robot_navigation_assistant", "arguments": {"action": "navigation_status"}}]


class StubGroupedPlanner:
    def plan_event(self, event: InteractionEvent) -> TaskSequence:
        return TaskSequence(
            goal=event.text,
            steps=[
                PlannedSkillCall(skill="robot_navigation", args={"action": "get_state"}),
                PlannedSkillCall(skill="robot_audio", args={"action": "tts_play", "text": "开始执行"}),
            ],
        )


class StubTaskListPlanner:
    def plan_event(self, event: InteractionEvent) -> TaskSequence:
        return TaskSequence(
            goal=event.text,
            steps=[PlannedSkillCall(skill="robot_tasks", args={"action": "list"})],
        )


class StubTaskDetailPlanner:
    def plan_event(self, event: InteractionEvent) -> TaskSequence:
        text = event.text
        task_id = 123444
        if "任务" in text:
            tail = text.split("任务", 1)[1]
            digits = "".join(ch for ch in tail if ch.isdigit())
            if digits:
                task_id = int(digits)
        elif isinstance(event.context.get("last_task"), dict) and event.context["last_task"].get("id") is not None:
            task_id = int(event.context["last_task"]["id"])

        return TaskSequence(
            goal=event.text,
            steps=[PlannedSkillCall(skill="robot_tasks", args={"action": "get", "task_id": task_id})],
        )


def build_mcp_client(tmp_path: Path | None = None) -> tuple[SkillRegistry, LocalMCPClient]:
    registry = SkillRegistry()
    register_nav_api_skills(
        registry,
        client=RecordingNavAPIClient(),
        motion_client=RecordingRosbridgeClient(),
    )
    resources = PromptResourceCatalog.from_repo_root(tmp_path or Path.cwd())
    server = LocalMCPServer(registry=registry, resources=resources)
    return registry, LocalMCPClient(server)


def test_plugin_skill_persistent_and_reusable(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    app = FishMindOSApp(skills_dir=skills_dir)

    script_path = app.generate_reusable_skill(
        name="custom notify",
        response_text='custom plugin says "ok"',
        description="test plugin",
    )

    assert Path(script_path).exists()
    assert "custom_notify" in app.registry.names()

    app_restarted = FishMindOSApp(skills_dir=skills_dir)
    assert "custom_notify" in app_restarted.registry.names()
    result = app_restarted.registry.get("custom_notify").run({}, {})
    assert result["ok"] is True
    assert result["detail"] == 'custom plugin says "ok"'


def test_text_interaction_layer_builds_event() -> None:
    layer = InteractionLayer()
    event = layer.receive_text("机器人现在在哪", robot_id="dog-01", context={"session_id": "s_1"})

    assert event.text == "机器人现在在哪"
    assert event.source == "text"
    assert event.robot_id == "dog-01"
    assert event.context == {"session_id": "s_1"}


def test_registry_exposes_grouped_robot_tools() -> None:
    registry = SkillRegistry()
    register_nav_api_skills(
        registry,
        client=RecordingNavAPIClient(),
        motion_client=RecordingRosbridgeClient(),
    )

    tool_names = {item["function"]["name"] for item in registry.tool_definitions()}

    assert "robot_navigation_assistant" in tool_names
    assert "robot_task_assistant" in tool_names
    assert "robot_light" in tool_names
    assert "robot_motion" in tool_names
    assert "robot_navigation" not in tool_names
    assert "robot_maps" not in tool_names


def test_local_mcp_server_exposes_tools_and_resources(tmp_path: Path) -> None:
    (tmp_path / "AGENT.md").write_text("agent policy", encoding="utf-8")
    (tmp_path / "TOOLS.md").write_text("tool policy", encoding="utf-8")
    (tmp_path / "TASK_SPEC.md").write_text("task policy", encoding="utf-8")

    registry = SkillRegistry()
    register_nav_api_skills(
        registry,
        client=RecordingNavAPIClient(),
        motion_client=RecordingRosbridgeClient(),
    )
    server = LocalMCPServer(registry=registry, resources=PromptResourceCatalog.from_repo_root(tmp_path))
    client = LocalMCPClient(server)

    tool_names = {item["function"]["name"] for item in client.list_tools()}
    bundle = client.read_planning_bundle()

    assert "robot_navigation_assistant" in tool_names
    assert "robot_task_assistant" in tool_names
    assert bundle["agent"] == "agent policy"
    assert bundle["tools"] == "tool policy"
    assert bundle["task_spec"] == "task policy"


def test_robot_navigation_skill_builds_json_request() -> None:
    registry = SkillRegistry()
    client = RecordingNavAPIClient()
    register_nav_api_skills(registry, client=client, motion_client=RecordingRosbridgeClient())

    result = registry.get("robot_navigation").run(
        {"action": "goto_waypoint", "waypoint_id": "101", "speed": "0.8"},
        {},
    )

    assert result["ok"] is True
    assert client.calls[0]["path"] == "/api/nav/nav/goto_waypoint"
    assert client.calls[0]["json_body"] == {"waypoint_id": 101, "speed": 0.8}


def test_robot_navigation_start_can_resolve_map_name() -> None:
    registry = SkillRegistry()
    client = RecordingNavAPIClient()
    register_nav_api_skills(registry, client=client, motion_client=RecordingRosbridgeClient())

    result = registry.get("robot_navigation").run(
        {"action": "start", "map_name": "26层"},
        {"user_text": "开始导航，地图为26层"},
    )

    assert result["ok"] is True
    assert client.calls[-1]["path"] == "/api/nav/nav/start"
    assert client.calls[-1]["json_body"] == {"map_id": 26}


def test_robot_navigation_goto_waypoint_can_resolve_waypoint_name_fuzzily() -> None:
    registry = SkillRegistry()
    client = RecordingNavAPIClient()
    register_nav_api_skills(registry, client=client, motion_client=RecordingRosbridgeClient())

    result = registry.get("robot_navigation").run(
        {"action": "goto_waypoint", "map_name": "26", "waypoint_name": "回充"},
        {"user_text": "去 26 层的回充点"},
    )

    assert result["ok"] is True
    assert client.calls[-1]["path"] == "/api/nav/nav/goto_waypoint"
    assert client.calls[-1]["json_body"] == {"waypoint_id": 101}


def test_navigation_assistant_can_go_to_semantic_waypoint() -> None:
    registry = SkillRegistry()
    client = RecordingNavAPIClient()
    register_nav_api_skills(registry, client=client, motion_client=RecordingRosbridgeClient())

    result = registry.get("robot_navigation_assistant").run(
        {"action": "go_to_location", "location_name": "回充点", "map_name": "26层"},
        {"user_text": "去 26 层回充点"},
    )

    assert result["ok"] is True
    assert result["detail"] == "我准备前往 回充点 并执行回充。"
    assert client.calls[-1]["path"] == "/api/nav/nav/dock_to_waypoint"
    assert client.calls[-1]["json_body"] == {"waypoint_id": 101}


def test_navigation_assistant_can_go_to_named_zone() -> None:
    registry = SkillRegistry()
    client = RecordingNavAPIClient()
    register_nav_api_skills(registry, client=client, motion_client=RecordingRosbridgeClient())

    result = registry.get("robot_navigation_assistant").run(
        {"action": "go_to_location", "location_name": "厨房", "map_name": "26层", "location_type": "zone"},
        {"user_text": "去厨房"},
    )

    assert result["ok"] is True
    assert result["detail"] == "我准备前往区域 厨房。"
    assert client.calls[-1]["path"] == "/api/nav/nav/goto_point"
    assert client.calls[-1]["json_body"]["x"] == 2.0
    assert client.calls[-1]["json_body"]["y"] == 3.0


def test_task_assistant_can_describe_task_by_name() -> None:
    registry = SkillRegistry()
    client = RecordingNavAPIClient()
    register_nav_api_skills(registry, client=client, motion_client=RecordingRosbridgeClient())

    result = registry.get("robot_task_assistant").run(
        {"action": "describe_task", "task_name": "拍照"},
        {"user_text": "告诉我拍照任务的描述"},
    )

    assert result["ok"] is True
    assert "拍照任务" in result["detail"]
    assert client.calls[-1]["path"] == "/api/nav/tasks/4"


def test_robot_tasks_list_uses_conversational_summary() -> None:
    registry = SkillRegistry()
    client = RecordingNavAPIClient()
    register_nav_api_skills(registry, client=client, motion_client=RecordingRosbridgeClient())

    result = registry.get("robot_tasks").run({"action": "list"}, {})

    assert result["ok"] is True
    assert result["detail"] == "我查到 4 个任务，当前有 拍照任务、迎宾任务、巡逻任务 等。"


def test_robot_tasks_list_can_expand_all_items_when_requested() -> None:
    registry = SkillRegistry()
    client = RecordingNavAPIClient()
    register_nav_api_skills(registry, client=client, motion_client=RecordingRosbridgeClient())

    result = registry.get("robot_tasks").run({"action": "list"}, {"user_text": "列出所有的任务"})

    assert result["ok"] is True
    assert result["detail"] == "我查到 4 个任务，分别是：拍照任务、迎宾任务、巡逻任务、回充任务。"


def test_robot_tasks_get_can_fallback_to_name_lookup() -> None:
    registry = SkillRegistry()
    client = TaskFallbackNavAPIClient()
    register_nav_api_skills(registry, client=client, motion_client=RecordingRosbridgeClient())

    result = registry.get("robot_tasks").run(
        {"action": "get", "task_id": 123444},
        {"user_text": "告诉我任务123444的描述"},
    )

    assert result["ok"] is True
    assert result["detail"] == "任务 123444 的描述是：这是测试任务。"


def test_robot_zones_skill_builds_dynamic_path() -> None:
    registry = SkillRegistry()
    client = RecordingNavAPIClient()
    register_nav_api_skills(registry, client=client, motion_client=RecordingRosbridgeClient())

    result = registry.get("robot_zones").run(
        {"action": "delete", "map_id": "1", "zone_type": "slow", "zone_id": "2"},
        {},
    )

    assert result["ok"] is True
    assert client.calls[0]["path"] == "/api/nav/maps/1/slow_zones/2"


def test_robot_light_turn_on_maps_to_default_code() -> None:
    registry = SkillRegistry()
    client = RecordingNavAPIClient()
    realtime_client = RecordingRosbridgeClient()
    register_nav_api_skills(registry, client=client, motion_client=realtime_client)

    result = registry.get("robot_light").run({"action": "set", "on": True}, {})

    assert result["ok"] is True
    assert realtime_client.calls[0]["kind"] == "publish"
    assert realtime_client.calls[0]["topic"] == "/light_control"
    assert realtime_client.calls[0]["msg"] == {"data": 11}


def test_robot_status_can_answer_charging_state_from_rosbridge() -> None:
    registry = SkillRegistry()
    realtime_client = RecordingRosbridgeClient()
    register_nav_api_skills(registry, client=RecordingNavAPIClient(), motion_client=realtime_client)

    result = registry.get("robot_status").run({"action": "charging_status"}, {})

    assert result["ok"] is True
    assert result["detail"] == "我现在没有在充电。当前电量约 78.5%。"
    assert realtime_client.calls[0]["kind"] == "subscribe"
    assert realtime_client.calls[0]["topic"] == "/bms_state"


def test_robot_audio_upload_uses_file_form_field(tmp_path: Path) -> None:
    registry = SkillRegistry()
    client = RecordingNavAPIClient()
    register_nav_api_skills(registry, client=client, motion_client=RecordingRosbridgeClient())
    source = tmp_path / "demo.pcm"
    source.write_bytes(b"demo")

    result = registry.get("robot_audio").run({"action": "upload_bgm", "file_path": str(source)}, {})

    assert result["ok"] is True
    assert client.calls[0]["files"] == {"file": str(source)}


def test_robot_reports_binary_action_can_save_file(tmp_path: Path) -> None:
    registry = SkillRegistry()
    client = RecordingNavAPIClient()
    register_nav_api_skills(registry, client=client, motion_client=RecordingRosbridgeClient())
    target = tmp_path / "report.pdf"

    result = registry.get("robot_reports").run(
        {"action": "download_pdf", "report_id": "r1", "save_to": str(target)},
        {},
    )

    assert result["ok"] is True
    assert target.exists()
    assert target.read_bytes() == b"PDFDATA"


def test_robot_auth_login_caches_token() -> None:
    registry = SkillRegistry()
    client = RecordingNavAPIClient()
    register_nav_api_skills(registry, client=client, motion_client=RecordingRosbridgeClient())

    result = registry.get("robot_auth").run(
        {"action": "login", "username": "navsys", "password": "fishros"},
        {},
    )

    assert result["ok"] is True
    assert client.token == "token-123"


def test_robot_motion_apply_preset_publishes_cmd_vel() -> None:
    registry = SkillRegistry()
    motion_client = RecordingRosbridgeClient()
    register_nav_api_skills(
        registry,
        client=RecordingNavAPIClient(),
        motion_client=motion_client,
    )

    result = registry.get("robot_motion").run({"action": "apply_preset", "preset": "stand"}, {})

    assert result["ok"] is True
    assert motion_client.calls[0]["topic"] == "/cmd_vel"
    assert motion_client.calls[0]["msg"]["linear"]["z"] > 0
    assert motion_client.calls[0]["msg_type"] == "geometry_msgs/msg/Twist"


def test_robot_motion_connection_refused_is_humanized() -> None:
    registry = SkillRegistry()
    motion_client = RecordingRosbridgeClient()
    motion_client.fail_with = "Rosbridge unavailable: [Errno 111] Connection refused"
    register_nav_api_skills(
        registry,
        client=RecordingNavAPIClient(),
        motion_client=motion_client,
    )

    result = registry.get("robot_motion").run({"action": "apply_preset", "preset": "stand"}, {})

    assert result["ok"] is False
    assert result["detail"] == "机器狗实时控制服务没连上，请确认 rosbridge 已启动。"


def test_agent_core_can_build_llm_task_sequence_from_mcp_tools() -> None:
    registry, mcp_client = build_mcp_client()
    planner = LLMTaskPlanner(mcp_client=mcp_client, client=StubToolClient())
    agent_core = AgentCoreRuntime(planner=planner)
    event = InteractionEvent(text="帮我看一下机器人是否在导航", source="text", robot_id="dog-01")

    sequence = agent_core.handle_event(event)

    assert registry.has(sequence.steps[0].skill)
    assert len(sequence.steps) == 1
    assert sequence.steps[0].skill == "robot_navigation_assistant"
    assert sequence.steps[0].args == {"action": "navigation_status"}


def test_quick_command_planner_handles_turn_on_light() -> None:
    planner = QuickCommandPlanner()
    event = InteractionEvent(text="开灯", source="text", robot_id="dog-01")

    sequence = planner.plan_event(event)

    assert sequence is not None
    assert sequence.steps[0].skill == "robot_light"
    assert sequence.steps[0].args == {"action": "set", "code": 11}


def test_quick_command_planner_handles_start_navigation_by_map_name() -> None:
    planner = QuickCommandPlanner()
    event = InteractionEvent(text="开始导航，地图为26层", source="text", robot_id="dog-01")

    sequence = planner.plan_event(event)

    assert sequence is not None
    assert sequence.steps[0].skill == "robot_navigation_assistant"
    assert sequence.steps[0].args == {"action": "start_map", "map_name": "26层"}


def test_quick_command_planner_handles_charging_query() -> None:
    planner = QuickCommandPlanner()
    event = InteractionEvent(text="现在是否在充电", source="text", robot_id="dog-01")

    sequence = planner.plan_event(event)

    assert sequence is not None
    assert sequence.steps[0].skill == "robot_status"
    assert sequence.steps[0].args == {"action": "charging_status"}


def test_quick_command_planner_handles_stand_motion() -> None:
    planner = QuickCommandPlanner()
    event = InteractionEvent(text="站立", source="text", robot_id="dog-01")

    sequence = planner.plan_event(event)

    assert sequence is not None
    assert sequence.steps[0].skill == "robot_motion"
    assert sequence.steps[0].args == {"action": "apply_preset", "preset": "stand"}
    assert sequence.planner_source == "quick"


def test_hybrid_planner_can_work_without_llm_for_quick_commands() -> None:
    _, mcp_client = build_mcp_client()
    planner = HybridTaskPlanner(mcp_client=mcp_client, quick_planner=QuickCommandPlanner(), llm_planner=None)
    event = InteractionEvent(text="机器人现在在哪", source="text", robot_id="dog-01")

    sequence = planner.plan_event(event)

    assert sequence.steps[0].skill == "robot_navigation_assistant"
    assert sequence.steps[0].args == {"action": "current_position"}


def test_llm_client_can_fallback_to_content_json_steps() -> None:
    response = {
        "choices": [
            {
                "message": {
                    "content": '{"steps":[{"name":"robot_navigation","arguments":{"action":"get_state"}}]}'
                }
            }
        ]
    }

    calls = OpenAICompatibleLLMClient._extract_tool_calls(response)

    assert calls == [
        {"id": "content_call_1", "name": "robot_navigation", "arguments": {"action": "get_state"}}
    ]


def test_llm_client_can_build_system_prompt_from_documents() -> None:
    prompt = OpenAICompatibleLLMClient.build_system_prompt(
        prompt_mode="full",
        prompt_documents={
            "agent": "你是测试智能体。",
            "tools": "使用 robot_navigation 处理导航。",
            "task_spec": "任务步骤必须可执行。",
        },
    )

    assert "You are the FishMindOS task planner." in prompt
    assert "你是测试智能体。" in prompt
    assert "使用 robot_navigation 处理导航。" in prompt
    assert "任务步骤必须可执行。" in prompt


def test_llm_client_can_build_minimal_system_prompt() -> None:
    prompt = OpenAICompatibleLLMClient.build_system_prompt(prompt_mode="minimal")

    assert "You are the FishMindOS task planner." in prompt
    assert "Tool semantics:" not in prompt
    assert "Task contract:" not in prompt


def test_task_executor_builds_plan_from_task_sequence() -> None:
    _, mcp_client = build_mcp_client()
    executor = TaskExecutor(mcp_client)
    sequence = TaskSequence(
        goal="测试顺序",
        steps=[
            PlannedSkillCall(skill="robot_navigation", args={"action": "get_state"}),
            PlannedSkillCall(skill="robot_audio", args={"action": "tts_play", "text": "hello"}),
        ],
    )

    plan = executor.build_plan(task_id="task_001", sequence=sequence)

    assert plan.task_id == "task_001"
    assert len(plan.steps) == 2
    assert plan.steps[0].id == "s1"
    assert plan.steps[1].skill == "robot_audio"


def test_task_executor_calls_tools_through_mcp_client() -> None:
    _, mcp_client = build_mcp_client()
    executor = TaskExecutor(mcp_client)
    plan = executor.build_plan(
        task_id="task_001",
        sequence=TaskSequence(
            goal="查看状态",
            steps=[PlannedSkillCall(skill="robot_navigation", args={"action": "get_state"})],
        ),
    )

    status, events = executor.execute(plan, context={})

    assert status.value == "success"
    assert len(events) == 1
    assert "导航" in events[0].detail or "nav" in events[0].detail.lower()


def test_app_run_text_executes_llm_planned_sequence(tmp_path: Path) -> None:
    registry = SkillRegistry()
    register_nav_api_skills(
        registry,
        client=RecordingNavAPIClient(),
        motion_client=RecordingRosbridgeClient(),
    )
    app = FishMindOSApp(
        skills_dir=tmp_path / "skills",
        registry=registry,
        agent_core=AgentCoreRuntime(planner=StubGroupedPlanner()),
    )

    result = app.run_text("查看状态并播报")

    assert result["status"] == "success"
    assert result["sequence"].goal == "查看状态并播报"
    assert len(result["plan"].steps) == 2
    assert len(result["resources"]) == 6


def test_app_run_text_can_expand_full_task_list_when_user_requests_all(tmp_path: Path) -> None:
    registry = SkillRegistry()
    register_nav_api_skills(
        registry,
        client=RecordingNavAPIClient(),
        motion_client=RecordingRosbridgeClient(),
    )
    app = FishMindOSApp(
        skills_dir=tmp_path / "skills",
        registry=registry,
        agent_core=AgentCoreRuntime(planner=StubTaskListPlanner()),
    )

    result = app.run_text("列出所有的任务")

    assert result["status"] == "success"
    assert result["events"][0].detail == "我查到 4 个任务，分别是：拍照任务、迎宾任务、巡逻任务、回充任务。"


def test_app_run_text_can_use_task_context_for_followup_query(tmp_path: Path) -> None:
    registry = SkillRegistry()
    register_nav_api_skills(
        registry,
        client=TaskFallbackNavAPIClient(),
        motion_client=RecordingRosbridgeClient(),
    )
    app = FishMindOSApp(
        skills_dir=tmp_path / "skills",
        registry=registry,
        agent_core=AgentCoreRuntime(planner=StubTaskDetailPlanner()),
    )

    first = app.run_text("告诉我任务123444的描述")
    second = app.run_text("它的描述是什么")

    assert first["status"] == "success"
    assert first["events"][0].detail == "任务 123444 的描述是：这是测试任务。"
    assert second["status"] == "success"
    assert second["events"][0].detail == "任务 123444 的描述是：这是测试任务。"
    assert app.session_context["last_task"] == {"id": 41, "name": "123444", "description": "这是测试任务。"}


def test_app_plan_event_exposes_planner_source_and_transport(tmp_path: Path) -> None:
    app = FishMindOSApp(skills_dir=tmp_path / "skills")

    prepared = app.plan_event(app.interaction.receive_text("站立"))

    assert prepared["planner_source"] in {"llm", "quick"}
    assert prepared["transports"] == ["rosbridge"]


def test_app_classifies_light_and_charging_transport_as_rosbridge_when_needed(tmp_path: Path) -> None:
    app = FishMindOSApp(skills_dir=tmp_path / "skills")

    light_sequence = TaskSequence(goal="开灯", steps=[PlannedSkillCall(skill="robot_light", args={"action": "set", "code": 11})])
    charging_sequence = TaskSequence(goal="现在是否在充电", steps=[PlannedSkillCall(skill="robot_status", args={"action": "charging_status"})])
    status_sequence = TaskSequence(goal="看看状态", steps=[PlannedSkillCall(skill="robot_status", args={"action": "status"})])

    assert app.classify_transports(light_sequence) == ["rosbridge"]
    assert app.classify_transports(charging_sequence) == ["rosbridge"]
    assert app.classify_transports(status_sequence) == ["http", "rosbridge"]


def test_load_runtime_config_reads_json_file(tmp_path: Path) -> None:
    config_path = tmp_path / "fishmindos.config.json"
    config_path.write_text('{"llm":{"model":"test-model"}}', encoding="utf-8")

    data = load_runtime_config(config_path)

    assert data["llm"]["model"] == "test-model"


def test_get_config_value_prefers_env_over_file(tmp_path: Path) -> None:
    config_path = tmp_path / "fishmindos.config.json"
    config_path.write_text('{"llm":{"model":"file-model"}}', encoding="utf-8")
    os.environ["FISHMINDOS_LLM_MODEL"] = "env-model"
    try:
        value = get_config_value("llm", "model", "FISHMINDOS_LLM_MODEL", config_path=config_path)
    finally:
        os.environ.pop("FISHMINDOS_LLM_MODEL", None)

    assert value == "env-model"


def test_llm_client_can_use_provider_default_api_url(tmp_path: Path) -> None:
    config_path = tmp_path / "fishmindos.config.json"
    config_path.write_text(
        '{"llm":{"provider":"zhipu","model":"glm-5","api_key":"test-key","base_url":"","api_url":""}}',
        encoding="utf-8",
    )
    os.environ["FISHMINDOS_CONFIG_FILE"] = str(config_path)
    try:
        client = OpenAICompatibleLLMClient.from_env()
    finally:
        os.environ.pop("FISHMINDOS_CONFIG_FILE", None)

    assert client is not None
    assert client.provider == "zhipu"
    assert client.api_url == "https://open.bigmodel.cn/api/paas/v4/chat/completions"


def test_llm_client_can_use_claude_provider_default_api_url(tmp_path: Path) -> None:
    config_path = tmp_path / "fishmindos.config.json"
    config_path.write_text(
        '{"llm":{"provider":"claude","model":"claude-sonnet-4-20250514","api_key":"test-key"}}',
        encoding="utf-8",
    )
    os.environ["FISHMINDOS_CONFIG_FILE"] = str(config_path)
    try:
        client = OpenAICompatibleLLMClient.from_env()
    finally:
        os.environ.pop("FISHMINDOS_CONFIG_FILE", None)

    assert client is not None
    assert client.provider == "claude"
    assert client.api_url == "https://api.anthropic.com/v1/chat/completions"


def test_llm_client_can_build_api_url_from_base_url(tmp_path: Path) -> None:
    config_path = tmp_path / "fishmindos.config.json"
    config_path.write_text(
        '{"llm":{"provider":"custom","base_url":"https://example.com/v1","model":"demo-model","api_key":"test-key"}}',
        encoding="utf-8",
    )
    os.environ["FISHMINDOS_CONFIG_FILE"] = str(config_path)
    try:
        client = OpenAICompatibleLLMClient.from_env()
    finally:
        os.environ.pop("FISHMINDOS_CONFIG_FILE", None)

    assert client is not None
    assert client.api_url == "https://example.com/v1/chat/completions"


def test_nav_client_can_build_base_url_from_host_and_port(tmp_path: Path) -> None:
    config_path = tmp_path / "fishmindos.config.json"
    config_path.write_text(
        '{"nav":{"scheme":"http","host":"192.168.123.100","port":8888,"base_url":""}}',
        encoding="utf-8",
    )
    os.environ["FISHMINDOS_CONFIG_FILE"] = str(config_path)
    try:
        client = NavAPIClient.from_env()
    finally:
        os.environ.pop("FISHMINDOS_CONFIG_FILE", None)

    assert client.base_url == "http://192.168.123.100:8888"


def test_quick_command_planner_can_decompose_compound_navigation_request() -> None:
    planner = QuickCommandPlanner()
    event = InteractionEvent(text="开启导航，地图为26层，我想先去大厅，然后再回来充电", source="text", robot_id="dog-01")

    sequence = planner.plan_event(event)

    assert sequence is not None
    assert sequence.planner_source == "quick"
    assert [step.skill for step in sequence.steps] == [
        "robot_navigation_assistant",
        "robot_navigation_assistant",
        "robot_navigation_assistant",
    ]
    assert sequence.steps[0].args == {"action": "start_map", "map_name": "26层"}
    assert sequence.steps[1].args == {"action": "go_to_location", "location_name": "大厅", "map_name": "26层"}
    assert sequence.steps[2].args == {
        "action": "go_to_location",
        "location_name": "回充点",
        "location_type": "dock",
        "map_name": "26层",
    }


def test_app_run_text_can_execute_compound_navigation_sequence(tmp_path: Path) -> None:
    registry = SkillRegistry()
    client = RecordingNavAPIClient()
    register_nav_api_skills(
        registry,
        client=client,
        motion_client=RecordingRosbridgeClient(),
    )
    app = FishMindOSApp(skills_dir=tmp_path / "skills", registry=registry)

    result = app.run_text("开启导航，地图为26层，先去厨房门口，然后回来充电")

    assert result["status"] == "success"
    assert result["planner_source"] == "quick"
    assert len(result["plan"].steps) == 3
    assert result["plan"].steps[0].args == {"action": "start_map", "map_name": "26层"}
    assert result["plan"].steps[1].args == {"action": "go_to_location", "location_name": "厨房门口", "map_name": "26层"}
    assert result["plan"].steps[2].args == {
        "action": "go_to_location",
        "location_name": "回充点",
        "location_type": "dock",
        "map_name": "26层",
    }
    assert [call["path"] for call in client.calls if call["kind"] == "json"][:6] == [
        "/api/nav/maps/list",
        "/api/nav/nav/start",
        "/api/nav/events/wait_nav_started",
        "/api/nav/maps/list",
        "/api/nav/maps/26/waypoints",
        "/api/nav/nav/goto_waypoint",
    ]


def test_robot_events_wait_uses_extended_http_timeout() -> None:
    registry = SkillRegistry()
    client = RecordingNavAPIClient()
    register_nav_api_skills(
        registry,
        client=client,
        motion_client=RecordingRosbridgeClient(),
    )

    result = registry.get("robot_events").run({"action": "wait_nav_started", "timeout": 60}, {})

    assert result["ok"] is True
    assert client.calls[0]["path"] == "/api/nav/events/wait_nav_started"
    assert client.calls[0]["timeout_sec"] == 65.0


def test_nav_client_translates_timeout_into_nav_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _TimeoutResponse:
        def __enter__(self):
            raise TimeoutError("timed out")

        def __exit__(self, exc_type, exc, tb):
            return False

    def _raise_timeout(*args, **kwargs):
        return _TimeoutResponse()

    monkeypatch.setattr("fishmindos.skill_runtime.nav_api.request.urlopen", _raise_timeout)

    client = NavAPIClient(base_url="http://127.0.0.1:9002", timeout_sec=15)

    with pytest.raises(NavAPIError) as exc_info:
        client.request_json("POST", "/api/nav/events/wait_nav_started", json_body={"timeout": 60}, timeout_sec=65)

    assert str(exc_info.value) == "Nav API request timed out after 65s: /api/nav/events/wait_nav_started"
