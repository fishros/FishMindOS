"""
FishMindOS interaction layer.
Provides a simple terminal UI for chatting with the robot.
"""

from __future__ import annotations

import itertools
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fishmindos.config import get_config, resolve_config_path
from fishmindos.core.event_bus import global_event_bus
from fishmindos.world import WorldBuilder, WorldResolver, WorldStore


class Spinner:
    """Simple terminal spinner."""

    def __init__(self, message: str = "思考中"):
        self.message = message
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def stop(self):
        if not self._running:
            return
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=0.5)
        self._running = False
        sys.stdout.write("\r" + " " * (len(self.message) + 10) + "\r")
        sys.stdout.flush()

    def _animate(self):
        for dots in itertools.cycle(["", ".", "..", "..."]):
            if self._stop_event.is_set():
                break
            sys.stdout.write(f"\r{self.message}{dots}   ")
            sys.stdout.flush()
            time.sleep(0.3)


def sanitize_output(text: str) -> str:
    """Clean up leaked reasoning and malformed tool text."""
    if not text:
        return text

    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"</think>", "", text)
    text = re.sub(r"\*\*回复\*\*[:\s]*", "", text)
    text = re.sub(r"执行了:\s*\w+(,\s*\w+)*", "", text)
    text = re.sub(r"^#+\s+.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^---+$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n\n\n+", "\n\n", text)
    text = re.sub(r"<tool_call.*?>.*?</tool_call>", "", text, flags=re.DOTALL)
    text = re.sub(r"</?tool_call>", "", text)
    text = re.sub(r"<arg_key>.*?</arg_key>", "", text, flags=re.DOTALL)
    text = re.sub(r"<arg_value>.*?</arg_value>", "", text, flags=re.DOTALL)
    text = re.sub(r"^\s*调用了\s+\w+.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*location\s*$", "", text, flags=re.MULTILINE)
    return text.strip()


class TerminalUI:
    """Terminal UI with a lightweight color theme."""

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
        if not prefix:
            return text
        return f"{prefix}{text}{self.RESET}"

    def _label(self, key: str, style: str) -> str:
        return self._style(f"[{self.ICONS[key]}]", style)

    def _rule(self, title: str = "") -> None:
        line = "━" * 58
        print(self._style(line, "muted"))
        if title:
            print(self._style(title, "title"))
            print(self._style(line, "muted"))

    def print_header(self):
        config = get_config()
        identity = getattr(getattr(config, "app", None), "identity", "") or "助手"
        profile = getattr(getattr(config, "app", None), "prompt_profile", "") or "default"
        print()
        self._rule("FishMindOS")
        print(self._style("机器人智能控制系统", "accent"))
        print(self._style(f"身份: {identity}  |  Prompt Profile: {profile}", "muted"))
        self._rule()
        print()

    def print_help(self):
        print(self._style("示例指令", "accent"))
        print("  去会议室               导航到会议室")
        print("  地图26层，去大厅        指定地图后导航")
        print("  去楼下帮我拿个快递      复合任务")
        print("  你还有多少电            查询当前状态")
        print()
        print(self._style("控制命令", "accent"))
        print("  world   设置默认 world / 默认地图")
        print("  确认     继续 wait_confirm 后续流程")
        print("  停止     取消当前任务")
        print("  退出     结束对话")
        print()

    def print_user_prompt(self):
        if self._last_was_skill:
            print()
        print(f"{self._label('user', 'user')} ", end="", flush=True)

    def print_robot_response(self, text: str):
        print(f"{self._label('dog', 'dog')} {text}")
        self._last_was_skill = False

    def print_plan(self, steps: List[Dict[str, Any]]):
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
            else:
                lines.append(action or "unknown")
        if len(tasks) > 10:
            lines.append(f"... 还有 {len(tasks) - 10} 步")
        return lines

    def print_skill_start(self, skill_name: str, description: str = "", step_num: int = 0):
        number = f"[{step_num}] " if step_num > 0 else ""
        display_name = description or skill_name
        tail = f" {self._style(f'[{skill_name}]', 'muted')}" if description else ""
        print(f"{self._style(self.ICONS['skill'], 'muted')} {number}{display_name}{tail}")
        self._last_was_skill = True

    def print_skill_result(self, success: bool, message: str):
        label = self._label("success" if success else "error", "ok" if success else "err")
        print(f"   {label} {message}")

    def print_error(self, message: str):
        print(f"{self._label('error', 'err')} {message}")
        self._last_was_skill = False

    def print_info(self, message: str):
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


class InteractionManager:
    """Manage terminal interaction with the brain."""

    def __init__(self, brain=None, config_path: str | Path | None = None):
        self.brain = brain
        self.ui = TerminalUI()
        self.spinner: Optional[Spinner] = None
        self.conversation_history: List[Dict] = []
        self.session_context: Dict[str, Any] = {}
        self._running = False
        self._cancel_event = threading.Event()
        self._current_skill = None
        self.config_path = resolve_config_path(config_path)
        self._async_mission_active = False
        global_event_bus.subscribe("mission_completed", self._on_async_mission_done)
        global_event_bus.subscribe("mission_failed", self._on_async_mission_done)

    def set_brain(self, brain):
        self.brain = brain

    def start(self):
        self._running = True
        self.ui.print_header()
        self.ui.print_help()

        while self._running:
            try:
                if not self._async_mission_active:
                    self.ui.print_user_prompt()
                user_input = input().strip()

                if not user_input:
                    continue

                if self._handle_special_command(user_input):
                    continue

                self._process_input(user_input)

            except KeyboardInterrupt:
                print()
                break
            except EOFError:
                break

        self._running = False
        print()
        print("再见!")

    def stop(self):
        self._running = False

    def _on_async_mission_done(self, data=None) -> None:
        self._async_mission_active = False
        if not self._running:
            return
        sys.stdout.write("\n")
        sys.stdout.flush()
        self.ui.print_user_prompt()

    def _get_adapter(self):
        if self.brain and hasattr(self.brain, "adapter"):
            return self.brain.adapter
        return None

    def _sync_world_to_brain(self, resolver: WorldResolver) -> None:
        if not self.brain:
            return

        session = self.brain.session_context
        session["world"] = resolver
        session["world_model"] = resolver
        session["world_enabled"] = True
        session["world_summary"] = resolver.describe()
        session["world_prompt"] = resolver.describe_for_prompt(limit=50)
        session["world_name"] = getattr(resolver.world, "name", "default")
        session["world_default_map"] = resolver.world.default_map_name or resolver.world.default_map_id
        session["world_known_locations"] = resolver.list_known_locations()
        session["world_adapter_fallback"] = resolver.adapter_fallback

    def _build_world_profile_path(self, map_name: str) -> Path:
        safe_name = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", map_name).strip("_")
        if not safe_name:
            safe_name = "default_world"
        return Path.cwd() / "fishmindos" / "world" / "profiles" / f"{safe_name}.json"

    def _resolve_world_path(self, world_path: str | Path) -> Path:
        resolved = Path(world_path)
        if not resolved.is_absolute():
            resolved = Path.cwd() / resolved
        return resolved

    def _reload_world(self, world_path: Path, config) -> WorldResolver:
        soul = self.brain.session_context.get("soul") if self.brain else None
        resolver = WorldResolver.from_path(
            world_path,
            adapter=self._get_adapter(),
            soul=soul,
            auto_switch_map=config.world.auto_switch_map,
            prefer_current_map=config.world.prefer_current_map,
            adapter_fallback=config.world.adapter_fallback,
        )
        self._sync_world_to_brain(resolver)
        return resolver

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
        resolver = self._reload_world(world_path, config)
        self.ui.print_info(f"已保存 world 描述，当前默认地图: {resolver.world.default_map_name or resolver.world.default_map_id or '未设置'}")
        return True

    def _configure_default_world_interactive(self) -> bool:
        adapter = self._get_adapter()
        if adapter is None:
            self.ui.print_error("适配器未初始化，无法设置默认 world")
            return True

        config = get_config()
        current_world_name = self.brain.session_context.get("world_name") if self.brain else None
        current_default_map = self.brain.session_context.get("world_default_map") if self.brain else None
        current_world_path = self._resolve_world_path(config.world.path) if getattr(config.world, "path", None) else None

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
        world_path = self._build_world_profile_path(selected_map.name)

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
        config.save_to_file(self.config_path)

        resolver = self._reload_world(world_path, config)

        self.ui.print_info(
            f"已将 {selected_map.name} 设为默认 world，后续将优先使用 {world.name}。"
        )
        self.ui.print_info(f"world 文件: {relative_world_path}")

        edit_now = input(":: 是否现在补充地点语义信息（描述/别名/类别/用途/关系）？(y/N): ").strip().lower()
        if edit_now in {"y", "yes", "是"}:
            return self._edit_world_locations_interactive(world_path, config)
        return True

    def _handle_special_command(self, text: str) -> bool:
        text_lower = text.lower()

        if text_lower in ["exit", "quit", "q", "退出", "bye"]:
            self._running = False
            return True

        if text_lower in ["help", "h", "帮助", "?"]:
            self.ui.print_help()
            return True

        if text_lower in ["/stop", "stop", "停止", "取消", "cancel"]:
            if self.brain:
                self.brain.cancel()
                self.ui.print_info("已停止")
            return True

        if text_lower in ["确认", "confirm", "/confirm", "继续", "ok"]:
            global_event_bus.publish(
                "human_confirmed",
                {
                    "source": "interaction",
                    "input": text,
                    "time": datetime.now().isoformat(timespec="seconds"),
                },
            )
            self.ui.print_info("已发送人工确认事件（human_confirmed）")
            return True

        if text_lower in ["world", "/world", "设置world", "切换world", "默认world", "world设置"]:
            return self._configure_default_world_interactive()

        if text_lower.startswith("python") or text_lower.startswith("py "):
            self.ui.print_error("这是启动命令，不是有效的机器人指令。请输入自然语言指令。")
            return True

        if any(cmd in text_lower for cmd in ["pip ", "cd ", "ls", "dir", "cmd", "bash"]):
            self.ui.print_error("这是系统命令，不是有效的机器人指令。请输入自然语言指令。")
            return True

        return False

    def _process_input(self, text: str):
        print()
        spinner: Optional[Spinner] = None
        try:
            if not self.brain:
                self.ui.print_error("大脑未初始化")
                return

            spinner = Spinner("思考中")
            spinner.start()

            all_responses = []
            current_step = 0
            final_response = None
            had_action = False
            had_error = False
            mission_pending_response = False

            if hasattr(self.brain, "think"):
                for resp in self.brain.think(text):
                    if not isinstance(resp, dict):
                        resp_dict = {
                            "type": resp.type,
                            "content": resp.content,
                            "metadata": resp.metadata or {},
                        }
                    else:
                        resp_dict = resp

                    all_responses.append(resp_dict)
                    response_type = resp_dict.get("type", "text")

                    if spinner:
                        spinner.stop()
                        spinner = None

                    if response_type == "plan":
                        steps = resp_dict.get("metadata", {}).get("steps", [])
                        self.ui.print_plan(steps)
                        self.ui.print_info("执行中...")

                    elif response_type == "action":
                        current_step += 1
                        had_action = True
                        skill_name = resp_dict.get("metadata", {}).get("skill", "")
                        desc = self.ui._get_skill_desc(skill_name)
                        self.ui.print_skill_start(skill_name, desc, current_step)

                    elif response_type == "result":
                        success = resp_dict.get("metadata", {}).get("success", False)
                        message = resp_dict.get("content", "")
                        self.ui.print_skill_result(success, message)
                        if not success:
                            had_error = True
                        skill_name = resp_dict.get("metadata", {}).get("skill", "")
                        if success and skill_name == "submit_mission":
                            result_data = resp_dict.get("metadata", {}).get("data")
                            if isinstance(result_data, dict):
                                result_tasks = result_data.get("tasks")
                                if isinstance(result_tasks, list):
                                    planned_tasks = None
                                    for previous in reversed(all_responses):
                                        if previous.get("type") != "plan":
                                            continue
                                        steps = previous.get("metadata", {}).get("steps", [])
                                        for step in steps:
                                            if step.get("skill") == "submit_mission":
                                                params = step.get("params", {})
                                                if isinstance(params, dict) and isinstance(params.get("tasks"), list):
                                                    planned_tasks = params.get("tasks")
                                                    break
                                        if planned_tasks is not None:
                                            break
                                    if planned_tasks != result_tasks:
                                        self.ui.print_info("实际任务流:")
                                        for task_line in self.ui._format_mission_task_lines(result_tasks):
                                            print(self.ui._style(f"  · {task_line}", "muted"))
                            mission_pending_response = bool(
                                result_data.get("pending", True)
                                if isinstance(result_data, dict)
                                else True
                            )
                            if mission_pending_response:
                                self._async_mission_active = True
                                final_response = "任务已提交，正在执行中，请等待导航/回调事件。"

                    elif response_type == "text":
                        raw_text = resp_dict.get("content", "")
                        cleaned_text = sanitize_output(raw_text)
                        if not cleaned_text and str(raw_text).strip():
                            cleaned_text = str(raw_text).strip()
                        if not (
                            mission_pending_response
                            and cleaned_text == "本轮操作已执行完成。"
                        ):
                            final_response = cleaned_text

                    elif response_type == "error":
                        self.ui.print_error(resp_dict.get("content", ""))
                        had_error = True
            else:
                if spinner:
                    spinner.stop()
                    spinner = None
                self.ui.print_error("大脑没有 think 方法")
                return

            if spinner:
                spinner.stop()
                spinner = None

            if not all_responses:
                self.ui.print_error("未收到大脑输出。请重试，或简化指令后再试。")
                return

            if final_response and not had_error:
                self.ui.print_robot_response(final_response)
            elif had_action and not had_error:
                self.ui.print_robot_response("本轮操作已执行完成。")
            elif not had_error:
                self.ui.print_robot_response("我刚才没有生成有效回复，请再试一次。")

            self.conversation_history.append(
                {
                    "input": text,
                    "responses": all_responses,
                    "time": datetime.now().isoformat(),
                }
            )

        except Exception as e:
            if spinner:
                spinner.stop()
                spinner = None
            self.ui.print_error(f"错误: {str(e)}")
            import traceback

            traceback.print_exc()
        finally:
            if spinner:
                spinner.stop()


def create_interaction_manager(brain=None) -> InteractionManager:
    """Factory helper for the terminal interaction manager."""
    return InteractionManager(brain)
