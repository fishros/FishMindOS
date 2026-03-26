"""
Terminal interaction channel.
"""

from __future__ import annotations

import itertools
import re
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from fishmindos.config import get_config
from fishmindos.interaction.channels.base import InteractionChannel
from fishmindos.world import WorldBuilder, WorldStore

if TYPE_CHECKING:
    from fishmindos.interaction.manager import InteractionManager


class Spinner:
    """Simple terminal spinner."""

    def __init__(self, message: str = "思考中"):
        self.message = message
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=0.5)
        self._running = False
        sys.stdout.write("\r" + " " * (len(self.message) + 10) + "\r")
        sys.stdout.flush()

    def _animate(self) -> None:
        for dots in itertools.cycle(["", ".", "..", "..."]):
            if self._stop_event.is_set():
                break
            sys.stdout.write(f"\r{self.message}{dots}   ")
            sys.stdout.flush()
            time.sleep(0.3)


class TerminalUI:
    """Terminal UI renderer."""

    ICONS = {
        "dog": "DOG",
        "user": "YOU",
        "skill": ">>",
        "success": "OK",
        "error": "ERR",
        "info": "::",
        "plan": "PLAN",
        "number": ["1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9."],
    }
    STYLES = {
        "title": "\033[1;36m",
        "muted": "\033[90m",
        "user": "\033[1;34m",
        "dog": "\033[1;32m",
        "plan": "\033[1;35m",
        "info": "\033[36m",
        "ok": "\033[32m",
        "err": "\033[31m",
        "accent": "\033[1;37m",
    }
    RESET = "\033[0m"

    def __init__(self, use_colors: bool = True):
        self.use_colors = bool(use_colors and sys.stdout.isatty())
        self._last_was_skill = False

    def _style(self, text: str, style: str) -> str:
        if not self.use_colors:
            return text
        prefix = self.STYLES.get(style, "")
        return f"{prefix}{text}{self.RESET}" if prefix else text

    def _label(self, key: str, style: str) -> str:
        return self._style(f"[{self.ICONS[key]}]", style)

    def _rule(self, title: str = "") -> None:
        line = "═" * 58
        print(self._style(line, "muted"))
        if title:
            print(self._style(title, "title"))
            print(self._style(line, "muted"))

    def print_header(self) -> None:
        config = get_config()
        identity = getattr(getattr(config, "app", None), "identity", "") or "助手"
        profile = getattr(getattr(config, "app", None), "prompt_profile", "") or "default"
        print()
        self._rule("FishMindOS")
        print(self._style("机器狗智能控制系统", "accent"))
        print(self._style(f"身份: {identity}  |  Prompt Profile: {profile}", "muted"))
        self._rule()
        print()

    def print_help(self) -> None:
        print(self._style("示例指令", "accent"))
        print("  去会议室               导航到会议室")
        print("  地图26层，去大厅       指定地图后导航")
        print("  去楼下帮我拿个快递     复合任务")
        print("  你还有多少电           查询当前状态")
        print()
        print(self._style("控制命令", "accent"))
        print("  world   设置默认 world / 默认地图")
        print("  确认     继续 wait_confirm 后续流程")
        print("  停止     取消当前任务")
        print("  退出     结束对话")
        print()

    def print_user_prompt(self) -> None:
        if self._last_was_skill:
            print()
        print(f"{self._label('user', 'user')} ", end="", flush=True)

    def print_robot_response(self, text: str) -> None:
        print(f"{self._label('dog', 'dog')} {text}")
        self._last_was_skill = False

    def print_plan(self, steps: List[Dict[str, Any]]) -> None:
        print(self._style(f"[{self.ICONS['plan']}] 执行规划", "plan"))
        for i, step in enumerate(steps, 1):
            skill_name = step.get("skill", "")
            desc = self._get_skill_desc(skill_name) or skill_name
            params = step.get("params", {})
            number = self.ICONS["number"][i - 1] if i <= len(self.ICONS["number"]) else f"{i}."

            if skill_name == "submit_mission" and isinstance(params.get("tasks"), list):
                print(f"  {number} {desc}")
                for task_line in self._format_mission_task_lines(params["tasks"]):
                    print(self._style(f"     · {task_line}", "muted"))
                continue

            detail = self._format_plan_params(skill_name, params)
            if detail:
                print(f"  {number} {desc}  {self._style(detail, 'muted')}")
            else:
                print(f"  {number} {desc}")
        print()
        self._last_was_skill = False

    def _format_plan_params(self, skill_name: str, params: Dict[str, Any]) -> str:
        if not isinstance(params, dict) or not params:
            return ""
        items = []
        for key, value in params.items():
            if skill_name == "submit_mission" and key == "tasks":
                continue
            text = str(value)
            if len(text) > 40:
                text = text[:37] + "..."
            items.append(f"{key}={text}")
        return ", ".join(items)

    def _format_mission_task_lines(self, tasks: List[Dict[str, Any]]) -> List[str]:
        lines: List[str] = []
        for task in tasks[:10]:
            if not isinstance(task, dict):
                lines.append(str(task))
                continue
            action = str(task.get("action", "")).lower()
            if action == "goto":
                lines.append(f"goto -> {task.get('target', '?')}")
            elif action == "dock":
                lines.append("dock -> 回充")
            elif action == "light":
                color = task.get("color") or task.get("code") or "?"
                lines.append(f"light -> {color}")
            elif action == "speak":
                text = str(task.get("text", ""))
                if len(text) > 24:
                    text = text[:21] + "..."
                lines.append(f"speak -> {text}")
            elif action == "wait_confirm":
                lines.append("wait_confirm -> 等待人工确认")
            elif action == "query":
                lines.append("query -> 查询状态")
            elif action == "stop_nav":
                lines.append("stop_nav -> 停止导航")
            else:
                lines.append(action or "unknown")
        if len(tasks) > 10:
            lines.append(f"... 还有 {len(tasks) - 10} 步")
        return lines

    def print_skill_start(self, skill_name: str, step_num: int = 0) -> None:
        number = f"[{step_num}] " if step_num > 0 else ""
        desc = self._get_skill_desc(skill_name) or skill_name
        print(f"{self._style(self.ICONS['skill'], 'muted')} {number}{desc} {self._style(f'[{skill_name}]', 'muted')}")
        self._last_was_skill = True

    def print_skill_result(self, success: bool, message: str) -> None:
        label = self._label("success" if success else "error", "ok" if success else "err")
        print(f"   {label} {message}")

    def print_error(self, message: str) -> None:
        print(f"{self._label('error', 'err')} {message}")
        self._last_was_skill = False

    def print_info(self, message: str) -> None:
        print(f"{self._label('info', 'info')} {message}")
        self._last_was_skill = False

    def _get_skill_desc(self, skill_name: str) -> str:
        desc_map = {
            "light_set": "灯光",
            "light_on": "开灯",
            "light_off": "关灯",
            "nav_start": "启动导航",
            "nav_stop": "停止导航",
            "nav_goto_location": "前往",
            "nav_goto_waypoint": "前往路点",
            "motion_stand": "站立",
            "motion_lie_down": "趴下",
            "system_battery": "查看电量",
            "system_status": "查看状态",
            "world_list_locations": "列出可用地点",
            "smart_navigate": "智能导航",
            "submit_mission": "任务流执行",
        }
        return desc_map.get(skill_name, "")


class TerminalChannel(InteractionChannel):
    """Terminal-backed interaction channel."""

    def __init__(self, manager: "InteractionManager", use_colors: bool = True):
        self.manager = manager
        self.ui = TerminalUI(use_colors=use_colors)
        self.spinner: Optional[Spinner] = None
        self._running = False
        self.manager.add_listener(self.handle_event)

    def start(self) -> None:
        self._running = True
        self.ui.print_header()
        self.ui.print_help()

        while self._running:
            try:
                if not self.manager.is_async_mission_active:
                    self.ui.print_user_prompt()
                user_input = input().strip()
                if not user_input:
                    continue
                if self._handle_special_command(user_input):
                    continue
                print()
                self.manager.handle_user_text(user_input)
            except KeyboardInterrupt:
                print()
                break
            except EOFError:
                break

        self.stop()
        print()
        print("再见!")

    def stop(self) -> None:
        self._running = False
        if self.spinner:
            self.spinner.stop()
            self.spinner = None

    def handle_event(self, event: Dict[str, Any]) -> None:
        event_type = event.get("type", "")
        payload = event.get("payload", {}) or {}

        if event_type == "thinking_started":
            if not self.spinner:
                self.spinner = Spinner(str(payload.get("message", "思考中")))
                self.spinner.start()
            return

        if event_type == "thinking_stopped":
            if self.spinner:
                self.spinner.stop()
                self.spinner = None
            return

        if event_type == "plan":
            self.ui.print_plan(payload.get("steps", []))
            return

        if event_type == "info":
            self.ui.print_info(str(payload.get("message", "")))
            return

        if event_type == "action":
            self.ui.print_skill_start(str(payload.get("skill_name", "")), int(payload.get("step_num", 0) or 0))
            return

        if event_type == "result":
            self.ui.print_skill_result(bool(payload.get("success", False)), str(payload.get("message", "")))
            return

        if event_type == "actual_mission_tasks":
            self.ui.print_info("实际任务流:")
            for task_line in self.ui._format_mission_task_lines(payload.get("tasks", [])):
                print(self.ui._style(f"  · {task_line}", "muted"))
            return

        if event_type == "message":
            self.ui.print_robot_response(str(payload.get("text", "")))
            return

        if event_type == "error":
            self.ui.print_error(str(payload.get("message", "")))
            return

        if event_type == "prompt_ready" and self._running:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self.ui.print_user_prompt()

    def _handle_special_command(self, text: str) -> bool:
        text_lower = text.lower()

        if text_lower in ["exit", "quit", "q", "退出", "bye"]:
            self._running = False
            return True

        if text_lower in ["help", "h", "帮助", "?"]:
            self.ui.print_help()
            return True

        if text_lower in ["/stop", "stop", "停止", "取消", "cancel"]:
            self.manager.cancel_current()
            return True

        if text_lower in ["确认", "confirm", "/confirm", "继续", "ok"]:
            self.manager.confirm_human(text)
            return True

        if text_lower in ["world", "/world", "设置world", "切换world", "默认world", "world设置"]:
            self._configure_default_world_interactive()
            return True

        if text_lower.startswith("python") or text_lower.startswith("py "):
            self.ui.print_error("这是启动命令，不是有效的机器人指令。请输入自然语言指令。")
            return True

        if any(cmd in text_lower for cmd in ["pip ", "cd ", "ls", "dir", "cmd", "bash"]):
            self.ui.print_error("这是系统命令，不是有效的机器人指令。请输入自然语言指令。")
            return True

        return False

    def _parse_csv_values(self, raw: str) -> List[str]:
        return [value.strip() for value in raw.split(",") if value.strip()]

    def _format_relations(self, relations: List[Dict[str, str]]) -> str:
        chunks = []
        for relation in relations[:3]:
            relation_type = relation.get("type", "").strip()
            target = relation.get("target", "").strip()
            note = relation.get("note", "").strip()
            if not relation_type or not target:
                continue
            chunk = f"{relation_type}:{target}"
            if note:
                chunk += f":{note}"
            chunks.append(chunk)
        return ", ".join(chunks)

    def _parse_relations(self, raw: str) -> List[Dict[str, str]]:
        relations: List[Dict[str, str]] = []
        for item in self._parse_csv_values(raw):
            parts = [part.strip() for part in item.split(":", 2)]
            if len(parts) < 2 or not parts[0] or not parts[1]:
                continue
            relation = {"type": parts[0], "target": parts[1]}
            if len(parts) == 3 and parts[2]:
                relation["note"] = parts[2]
            relations.append(relation)
        return relations

    def _edit_world_locations_interactive(self, world_path: Path, config) -> bool:
        store = WorldStore(world_path)
        world = store.load()
        if not world.locations:
            self.ui.print_info("当前 world 没有可编辑的地点。")
            return True

        print()
        self.ui.print_info(f"编辑 world 地点: {world.name}")
        self.ui.print_info("直接回车或输入 0 结束。留空表示保持不变，输入 - 表示清空。")
        self.ui.print_info("别名/用途可用英文逗号分隔，例如: 前台,接待处")
        self.ui.print_info("关系格式: 关系类型:目标[:备注]，例如: after_task_return:回充点, near:大厅")

        while True:
            print("可编辑地点:")
            for index, item in enumerate(world.locations, 1):
                description = f" / 描述: {item.description}" if item.description else ""
                aliases = f" / 别名: {', '.join(item.aliases[:3])}" if item.aliases else ""
                category = f" / 类别: {item.category}" if getattr(item, "category", "") else ""
                hints = f" / 用途: {', '.join(item.task_hints[:3])}" if getattr(item, "task_hints", None) else ""
                relations = f" / 关系: {self._format_relations(item.relations)}" if getattr(item, "relations", None) else ""
                print(f"  {index}. {item.name} [{item.location_type}]{category}{description}{aliases}{hints}{relations}")
            print("  0. 完成")

            selection = input(":: 请输入地点编号: ").strip()
            if selection in {"", "0"}:
                break
            if not selection.isdigit():
                self.ui.print_error("请输入有效的数字编号")
                continue

            index = int(selection)
            if index < 1 or index > len(world.locations):
                self.ui.print_error("编号超出范围")
                continue

            item = world.locations[index - 1]
            description = input(f":: 为 {item.name} 设置描述（当前: {item.description or '无'}）: ").strip()
            if description == "-":
                item.description = ""
            elif description:
                item.description = description

            category = input(
                f":: 为 {item.name} 设置类别（当前: {getattr(item, 'category', '') or '无'}）: "
            ).strip()
            if category == "-":
                item.category = ""
            elif category:
                item.category = category

            alias_text = input(
                f":: 为 {item.name} 设置别名（当前: {', '.join(item.aliases) or '无'}）: "
            ).strip()
            if alias_text == "-":
                item.aliases = []
            elif alias_text:
                item.aliases = self._parse_csv_values(alias_text)

            task_hint_text = input(
                f":: 为 {item.name} 设置用途提示（当前: {', '.join(getattr(item, 'task_hints', [])) or '无'}）: "
            ).strip()
            if task_hint_text == "-":
                item.task_hints = []
            elif task_hint_text:
                item.task_hints = self._parse_csv_values(task_hint_text)

            relation_text = input(
                f":: 为 {item.name} 设置关系（当前: {self._format_relations(getattr(item, 'relations', [])) or '无'}）: "
            ).strip()
            if relation_text == "-":
                item.relations = []
            elif relation_text:
                item.relations = self._parse_relations(relation_text)

            self.ui.print_info(f"已更新地点: {item.name}")
            print()

        store.save(world)
        resolver = self.manager.reload_world(world_path, config)
        self.ui.print_info(
            f"已保存 world 描述，当前默认地图: {resolver.world.default_map_name or resolver.world.default_map_id or '未设置'}"
        )
        return True

    def _configure_default_world_interactive(self) -> bool:
        adapter = self.manager.get_adapter()
        if adapter is None:
            self.ui.print_error("适配器未初始化，无法设置默认 world")
            return True

        config = get_config()
        current_world_name = self.manager.brain.session_context.get("world_name") if self.manager.brain else None
        current_default_map = self.manager.brain.session_context.get("world_default_map") if self.manager.brain else None
        current_world_path = self.manager.resolve_world_path(config.world.path) if getattr(config.world, "path", None) else None

        print()
        self.ui.print_info("默认 world 设置")
        if current_world_name or current_default_map:
            self.ui.print_info(
                f"当前 world: {current_world_name or 'default'} / 默认地图: {current_default_map or '未设置'}"
            )

        print("请选择操作:")
        print("  1. 选择默认地图并生成/刷新 world")
        if current_world_path and current_world_path.exists():
            print("  2. 编辑当前 world 的地点语义信息")
        print("  0. 取消")

        action = input(":: 请输入操作编号: ").strip()
        if action in {"", "0"}:
            self.ui.print_info("已取消 world 设置")
            return True
        if action == "2" and current_world_path and current_world_path.exists():
            return self._edit_world_locations_interactive(current_world_path, config)
        if action != "1":
            self.ui.print_error("请输入有效的操作编号")
            return True

        try:
            maps = adapter.list_maps()
        except Exception as e:
            self.ui.print_error(f"读取地图列表失败: {e}")
            return True

        if not maps:
            self.ui.print_error("当前没有可用地图，无法设置默认 world")
            return True

        print("请选择要绑定为默认 world 的地图:")
        for index, map_info in enumerate(maps, 1):
            marker = " *" if (map_info.id == current_default_map or map_info.name == current_default_map) else ""
            print(f"  {index}. {map_info.name} (ID: {map_info.id}){marker}")
        print("  0. 取消")

        selection = input(":: 请输入编号: ").strip()
        if selection in {"", "0"}:
            self.ui.print_info("已取消 world 设置")
            return True
        if not selection.isdigit():
            self.ui.print_error("请输入有效的数字编号")
            return True

        index = int(selection)
        if index < 1 or index > len(maps):
            self.ui.print_error("编号超出范围")
            return True

        selected_map = maps[index - 1]
        world_path = self.manager.build_world_profile_path(selected_map.name)

        try:
            builder = WorldBuilder(adapter)
            world = builder.import_map_to_world(
                world_path=world_path,
                map_id=selected_map.id,
                world_name=f"{selected_map.name}世界",
                replace_map_locations=True,
                set_default=True,
            )
        except Exception as e:
            self.ui.print_error(f"生成 world 失败: {e}")
            return True

        try:
            relative_world_path = world_path.relative_to(Path.cwd()).as_posix()
        except ValueError:
            relative_world_path = str(world_path)

        config.world.path = relative_world_path
        config.save_to_file(self.manager.config_path)

        resolver = self.manager.reload_world(world_path, config)
        self.ui.print_info(f"已将 {selected_map.name} 设为默认 world，后续将优先使用 {world.name}。")
        self.ui.print_info(f"world 文件: {relative_world_path}")

        edit_now = input(":: 是否现在补充地点语义信息（描述/别名/类别/用途/关系）？(y/N): ").strip().lower()
        if edit_now in {"y", "yes", "是"}:
            return self._edit_world_locations_interactive(world_path, config)
        return True
