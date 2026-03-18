from __future__ import annotations

import itertools
import sys
import threading
import time

from fishmindos import FishMindOSApp


EXIT_COMMANDS = {"exit", "quit", "q", "退出"}
DEBUG_ON_COMMANDS = {"/debug on", "debug on"}
DEBUG_OFF_COMMANDS = {"/debug off", "debug off"}


TOOL_CALL_LABELS = {
    "robot_light": "调整灯光",
    "robot_motion": "执行动作",
    "robot_audio": "播报语音",
    "robot_navigation_assistant": "导航规划",
    "robot_navigation": "导航控制",
    "robot_task_assistant": "任务管理",
    "robot_task_chain": "任务链",
    "robot_status": "查询状态",
}


class Spinner:
    """Print an animated '.' / '..' / '...' indicator on the same line."""

    def __init__(self, prefix: str = "狗狗: 思考") -> None:
        self._prefix = prefix
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        for dots in itertools.cycle([".", "..", "..."]):
            if self._stop.is_set():
                break
            sys.stdout.write(f"\r{self._prefix}{dots}   ")
            sys.stdout.flush()
            time.sleep(0.4)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()
        sys.stdout.write("\r" + " " * 30 + "\r")
        sys.stdout.flush()


def on_tool_call(name: str, args: dict) -> None:
    label = TOOL_CALL_LABELS.get(name, name)
    action = args.get("action", "")
    sys.stdout.write(f"\r狗狗: [{label}] {action}...\n")
    sys.stdout.flush()


def format_reply(result: dict[str, object]) -> str:
    events = result.get("events", [])
    if not events:
        return "汪，我这边没有拿到可执行结果。"

    last_event = events[-1]
    detail = str(getattr(last_event, "detail", "")).strip()
    status = str(result.get("status", "")).strip().lower()

    if status == "success":
        return detail or "汪，已经处理好了。"
    if detail:
        return f"汪，这次没成功：{detail}"
    return "汪，这次执行失败了。"


def format_ack(prepared: dict[str, object]) -> str:
    plan = prepared["plan"]
    if not plan.steps:
        return ""

    first_step = plan.steps[0]
    skill = first_step.skill
    action = str(first_step.args.get("action", "")).strip()

    if skill == "robot_light":
        return "汪，我来开灯。" if first_step.args.get("on") is not False else "汪，我来关灯。"
    if skill == "robot_motion":
        if action == "list_presets":
            return "汪，我帮你看看我会哪些动作。"
        if action == "apply_preset":
            mapping = {"stand": "汪，我站起来。", "lie_down": "汪，我趴下。"}
            return mapping.get(str(first_step.args.get("preset", "")), "汪，我来做这个动作。")
    if skill == "robot_navigation_assistant":
        if action == "go_to_location":
            return f"汪，我去 {first_step.args.get('location_name')}。"
        if action == "start_map":
            return f"汪，我切到地图 {first_step.args.get('map_name')} 并启动导航。"
        if action == "current_position":
            return "汪，我看看我现在在哪。"
        if action == "navigation_status":
            return "汪，我看看导航状态。"
        if action == "list_maps":
            return "汪，我帮你看一下现在有哪些地图。"
        if action == "stop_navigation":
            return "汪，我先停下导航。"
        if action == "pause_navigation":
            return "汪，我先暂停导航。"
        if action == "resume_navigation":
            return "汪，我继续导航。"
    if skill == "robot_navigation":
        if action == "goto_waypoint":
            return f"汪，我去 {first_step.args.get('waypoint_id')} 号点位。"
        if action == "goto_point":
            return "汪，我去目标坐标。"
        if action == "get_current_position":
            return "汪，我看看我现在在哪。"
        if action == "get_state":
            return "汪，我看看导航状态。"
    if skill == "robot_status":
        if action == "charging_status":
            return "汪，我看看现在是不是在充电。"
        if action == "battery_soc":
            return "汪，我看看现在还有多少电。"
        return "汪，我看看现在的状态。"
    if skill == "robot_audio":
        return "汪，我来播报。"
    if skill == "robot_task_assistant":
        if action == "list_tasks":
            return "汪，我来看看现在有哪些任务。"
        if action == "describe_task":
            return "汪，我来看看这个任务的详情。"
        if action == "run_task":
            return "汪，我来执行这个任务。"
        if action == "cancel_task":
            return "汪，我来取消这个任务。"
        if action == "create_nav_task":
            return "汪，我来把这个导航任务记下来。"
    if skill == "robot_task_chain":
        if action == "list_chains":
            return "汪，我来看看记住了哪些任务链。"
        if action == "show_chain":
            return "汪，我来看看这条任务链。"
        if action == "delete_chain":
            return "汪，我来删掉这条任务链。"
        if action == "run_chain":
            return "汪，我来执行这条任务链。"
        if action == "save_chain":
            return "汪，我来把这条任务链记下来。"
    return "汪，我来处理。"


def print_debug(result: dict[str, object]) -> None:
    planner_source = str(result.get("planner_source", "unknown"))
    transports = result.get("transports", [])
    print(f"状态: {result['status']}")
    print(f"规划来源: {planner_source}")
    if transports:
        print(f"传输通道: {', '.join(str(item) for item in transports)}")
    print("计划:")
    for step in result["plan"].steps:
        print(f"- {step.id} {step.skill} {step.args}")
    print("执行:")
    for event in result["events"]:
        print(f"- [{event.status.value}] {event.step_id}: {event.detail}")


def main() -> None:
    app = FishMindOSApp()
    debug_mode = False
    print("FishMindOS robot console")
    print("直接和机器狗对话即可，输入 exit 退出。输入 /debug on 可查看调试信息。")

    while True:
        try:
            text = input("\n你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n系统: 结束。")
            return

        if not text:
            continue

        lowered = text.lower()
        if lowered in EXIT_COMMANDS:
            print("系统: 结束。")
            return
        if lowered in DEBUG_ON_COMMANDS:
            debug_mode = True
            print("系统: 已开启调试输出。")
            continue
        if lowered in DEBUG_OFF_COMMANDS:
            debug_mode = False
            print("系统: 已关闭调试输出。")
            continue

        spinner = Spinner()
        spinner.start()
        try:
            event = app.interaction.receive_text(text=text)
            prepared = app.plan_event(event, on_tool_call=on_tool_call)
            spinner.stop()
            ack = format_ack(prepared)
            if ack:
                print(f"狗狗: {ack}")
            result = app.execute_plan(prepared["plan"], prepared["sequence"])
        except Exception as exc:
            spinner.stop()
            import traceback
            print(f"系统: 出错了 — {exc}")
            print(traceback.format_exc())
            continue

        print(f"狗狗: {format_reply(result)}")
        if debug_mode:
            print_debug(result)


if __name__ == "__main__":
    main()
