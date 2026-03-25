"""Non-blocking mission state machine driven by EventBus."""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from fishmindos.adapters.base import RobotAdapter
from fishmindos.config import get_config
from fishmindos.core.event_bus import global_event_bus as default_event_bus


class MissionManager:
    """Event-driven mission manager."""

    def __init__(self, adapter: RobotAdapter, global_event_bus=default_event_bus):
        self.adapter = adapter
        self.event_bus = global_event_bus
        self.current_mission_queue: List[Dict[str, Any]] = []
        self.is_busy = False
        self.waiting_for_human = False
        self.last_error: str = ""
        self._lock = threading.RLock()
        self._wait_reminder_thread: Optional[threading.Thread] = None
        self._wait_reminder_stop = threading.Event()
        self._last_speak_text: str = ""
        self._active_wait_confirm_text: str = ""
        self._awaiting_event: Optional[str] = None

        cfg = get_config()
        self._wait_reminder_enabled = bool(getattr(cfg.mission, "wait_confirm_reminder_enabled", True))
        self._wait_reminder_interval_sec = max(
            1,
            int(getattr(cfg.mission, "wait_confirm_reminder_interval_sec", 20) or 20),
        )
        self._wait_reminder_text = str(
            getattr(cfg.mission, "wait_confirm_reminder_text", "请确认后我再继续执行。")
            or "请确认后我再继续执行。"
        )

        self.event_bus.subscribe("nav_arrived", self._on_nav_arrived)
        self.event_bus.subscribe("dock_completed", self._on_dock_completed)
        self.event_bus.subscribe("action_failed", self._on_action_failed)
        self.event_bus.subscribe("human_confirmed", self._on_human_confirmed)

    def _log(self, message: str) -> None:
        print(f"\n{message}", flush=True)

    def _event_stream_ready(self) -> bool:
        checker = getattr(self.adapter, "_event_stream_enabled", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                return False
        return True

    def submit_mission(self, tasks: list) -> bool:
        """Accept mission tasks and trigger execution if idle."""
        if not isinstance(tasks, list):
            self.last_error = "tasks must be a list"
            return False

        with self._lock:
            if self.is_busy:
                self.current_mission_queue.extend(tasks)
                return True
            self.current_mission_queue = list(tasks)
            self.is_busy = True
            self.waiting_for_human = False
            self.last_error = ""
            self._last_speak_text = ""
            self._active_wait_confirm_text = ""
            self._awaiting_event = None
            self._stop_wait_confirm_reminder()

        self._execute_next()
        return True

    def has_pending_work(self) -> bool:
        """Whether the current mission still has unfinished async or queued work."""
        with self._lock:
            return bool(
                self.is_busy
                or self.waiting_for_human
                or self.current_mission_queue
                or bool(self._awaiting_event)
            )

    def _execute_next(self, event_data=None):
        """Dispatch next action without blocking waits."""
        with self._lock:
            if not self.is_busy:
                return
            if self.waiting_for_human:
                return
            if not self.current_mission_queue:
                self.is_busy = False
                self.waiting_for_human = False
                self._awaiting_event = None
                self._stop_wait_confirm_reminder()
                try:
                    self.adapter.play_audio("任务全部完成")
                except Exception:
                    pass
                self._log("[小脑] 任务全部完成")
                self.event_bus.publish("mission_completed", {"status": "completed"})
                return
            task = self.current_mission_queue.pop(0)

        if not isinstance(task, dict):
            self._on_action_failed({"error": "task item is not a dict"})
            return

        action = str(task.get("action", "")).lower()

        if action == "goto":
            target = task.get("target")
            try:
                ok = bool(self.adapter.navigate_to(target))
            except Exception as exc:
                ok = False
                self.last_error = f"goto failed: {exc}"
            if not ok:
                self.event_bus.publish("action_failed", {"action": "goto", "target": target})
                return
            if not self._event_stream_ready():
                self.last_error = "event stream unavailable for goto"
                self.event_bus.publish("action_failed", {"action": "goto", "target": target, "error": self.last_error})
                return
            with self._lock:
                self._awaiting_event = "nav_arrived"
            self._log(f"[小脑] 已下发前往 {target}，等待到达回调...")
            return

        if action == "dock":
            try:
                if hasattr(self.adapter, "execute_docking_async"):
                    ok = bool(self.adapter.execute_docking_async())
                else:
                    ok = bool(self.adapter.execute_docking())
            except Exception as exc:
                ok = False
                self.last_error = f"dock failed: {exc}"
            if not ok:
                self.event_bus.publish("action_failed", {"action": "dock"})
                return
            if not self._event_stream_ready():
                self.last_error = "event stream unavailable for dock"
                self.event_bus.publish("action_failed", {"action": "dock", "error": self.last_error})
                return
            with self._lock:
                self._awaiting_event = "dock_completed"
            self._log("[小脑] 已下发回充，等待回充完成回调...")
            return

        if action == "wait_confirm":
            reminder_text = str(task.get("reminder_text") or "").strip()
            if not reminder_text:
                reminder_text = str(self._last_speak_text or "").strip()
            if not reminder_text:
                reminder_text = self._wait_reminder_text
            with self._lock:
                self.waiting_for_human = True
                self._active_wait_confirm_text = reminder_text
                self._awaiting_event = "human_confirmed"
            self._start_wait_confirm_reminder(reminder_text)
            self._log("[小脑] 进入人机协同等待状态，悬停中...")
            return

        if action == "light":
            try:
                ok = bool(self.adapter.set_light(task.get("color")))
            except Exception as exc:
                ok = False
                self.last_error = f"light failed: {exc}"
            if not ok:
                self.event_bus.publish("action_failed", {"action": "light"})
                return
            self._execute_next()
            return

        if action == "speak":
            text = task.get("text")
            try:
                ok = bool(self.adapter.play_audio(text))
            except Exception as exc:
                ok = False
                self.last_error = f"speak failed: {exc}"
            if not ok:
                self.event_bus.publish("action_failed", {"action": "speak"})
                return
            self._last_speak_text = str(text or "").strip()
            self._execute_next()
            return

        if action == "query":
            try:
                status = self.adapter.get_basic_status()
                self._log(f"[小脑] status={status}")
            except Exception as exc:
                self.event_bus.publish("action_failed", {"action": "query", "error": str(exc)})
                return
            self._execute_next()
            return

        self.event_bus.publish("action_failed", {"action": action, "error": "unsupported action"})

    def _on_nav_arrived(self, data):
        with self._lock:
            if not self.is_busy or self.waiting_for_human or self._awaiting_event != "nav_arrived":
                return
            self._awaiting_event = None
        self._log("[小脑] 收到到达事件，触发下一步")
        time.sleep(0.5)
        self._execute_next(event_data=data)

    def _on_dock_completed(self, data):
        with self._lock:
            if not self.is_busy or self.waiting_for_human or self._awaiting_event != "dock_completed":
                return
            self._awaiting_event = None
        self._log("[小脑] 收到回充完成事件，触发下一步")
        time.sleep(0.5)
        self._execute_next(event_data=data)

    def _on_human_confirmed(self, data=None):
        with self._lock:
            if (
                not self.is_busy
                or not self.waiting_for_human
                or self._awaiting_event != "human_confirmed"
            ):
                return
            self.waiting_for_human = False
            self._active_wait_confirm_text = ""
            self._awaiting_event = None
        self._stop_wait_confirm_reminder()
        self._log("[小脑] 收到人类确认事件，继续执行下一步。")
        time.sleep(0.2)
        self._execute_next(event_data=data)

    def _on_action_failed(self, data):
        with self._lock:
            self.is_busy = False
            self.waiting_for_human = False
            self._active_wait_confirm_text = ""
            self._awaiting_event = None
        self._stop_wait_confirm_reminder()
        self.last_error = f"action failed: {data}"
        self._log(f"[小脑] 动作失败，任务终止: {data}")
        self.event_bus.publish("mission_failed", {"error": self.last_error, "detail": data})

    def _start_wait_confirm_reminder(self, reminder_text: str) -> None:
        if not self._wait_reminder_enabled:
            return
        self._stop_wait_confirm_reminder()
        self._wait_reminder_stop.clear()
        text_to_speak = str(reminder_text or "").strip() or self._wait_reminder_text

        def _loop() -> None:
            while not self._wait_reminder_stop.wait(self._wait_reminder_interval_sec):
                with self._lock:
                    if not self.is_busy or not self.waiting_for_human:
                        break
                try:
                    self.adapter.play_audio(text_to_speak)
                except Exception as exc:
                    self._log(f"[小脑] wait_confirm 提醒播报失败: {exc}")

        self._wait_reminder_thread = threading.Thread(
            target=_loop,
            name="mission-wait-confirm-reminder",
            daemon=True,
        )
        self._wait_reminder_thread.start()

    def _stop_wait_confirm_reminder(self) -> None:
        self._wait_reminder_stop.set()
        thread = self._wait_reminder_thread
        if thread and thread.is_alive():
            thread.join(timeout=0.2)
        self._wait_reminder_thread = None
