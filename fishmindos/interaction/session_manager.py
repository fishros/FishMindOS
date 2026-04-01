"""
Session manager for interaction channels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class InteractionSession:
    """Runtime state for one interaction session."""

    session_id: str
    client_type: str = "unknown"
    session_context: Dict[str, Any] = field(default_factory=dict)
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    waiting_for_human: bool = False
    current_mission_id: Optional[str] = None
    async_mission_active: bool = False
    connected_channels: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    last_activity_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def touch(self) -> None:
        self.last_activity_at = datetime.now().isoformat(timespec="seconds")


class SessionManager:
    """Store and retrieve interaction sessions."""

    def __init__(self, session_template: Optional[Dict[str, Any]] = None):
        self._session_template = dict(session_template or {})
        self._sessions: Dict[str, InteractionSession] = {}

    def get(self, session_id: str) -> Optional[InteractionSession]:
        return self._sessions.get(session_id)

    def create_session(
        self,
        session_id: str,
        *,
        client_type: str = "unknown",
        initial_context: Optional[Dict[str, Any]] = None,
    ) -> InteractionSession:
        context = dict(self._session_template)
        if initial_context:
            context.update(initial_context)
        session = InteractionSession(
            session_id=session_id,
            client_type=client_type,
            session_context=context,
        )
        self._sessions[session_id] = session
        return session

    def get_or_create(
        self,
        session_id: str,
        *,
        client_type: str = "unknown",
        initial_context: Optional[Dict[str, Any]] = None,
    ) -> InteractionSession:
        existing = self.get(session_id)
        if existing is not None:
            existing.touch()
            if initial_context:
                existing.session_context.update(initial_context)
            return existing
        return self.create_session(
            session_id,
            client_type=client_type,
            initial_context=initial_context,
        )

    def touch(self, session_id: str) -> None:
        session = self.get(session_id)
        if session is not None:
            session.touch()

    def all_sessions(self) -> List[InteractionSession]:
        return list(self._sessions.values())

    def get_snapshot(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Return a JSON-serialisable state snapshot for the given session.

        Only scalar / primitive values from session_context are included so
        that the result can be sent directly over the wire (HTTP or WebSocket)
        without further serialisation work.
        """
        session = self.get(session_id)
        if session is None:
            return None
        ctx = session.session_context

        def _safe(value):
            """Return value if it is JSON-safe, else None."""
            if isinstance(value, (str, int, float, bool, type(None))):
                return value
            if isinstance(value, (list, tuple)):
                return [_safe(v) for v in value]
            if isinstance(value, dict):
                return {k: _safe(v) for k, v in value.items()}
            return None

        return {
            "session_id": session.session_id,
            "client_type": session.client_type,
            "created_at": session.created_at,
            "last_activity_at": session.last_activity_at,
            "waiting_for_human": session.waiting_for_human,
            "human_prompt_text": _safe(ctx.get("human_prompt_text")),
            "async_mission_active": session.async_mission_active,
            "current_mission_id": session.current_mission_id,
            "interaction_in_progress": _safe(ctx.get("interaction_in_progress", False)),
            "connected_channels": list(session.connected_channels),
            # ── Robot / world state (JSON-safe extracts) ──────────────
            "current_location": _safe(ctx.get("current_location")),
            "carrying_item": _safe(ctx.get("carrying_item")),
            "current_map": _safe(ctx.get("current_map")),
            "world_name": _safe(ctx.get("world_name")),
            "world_default_map": _safe(ctx.get("world_default_map")),
            "world_known_locations": _safe(ctx.get("world_known_locations", [])),
            "world_enabled": _safe(ctx.get("world_enabled", False)),
            "soul_enabled": _safe(ctx.get("soul_enabled", False)),
            "callback_enabled": _safe(ctx.get("callback_enabled", False)),
            "callback_event_count": _safe(ctx.get("callback_event_count", 0)),
            "callback_last_event": _safe(ctx.get("callback_last_event")),
            "callback_last_event_at": _safe(ctx.get("callback_last_event_at")),
            "ui_origin_client_type": _safe(ctx.get("interaction_origin_client_type")),
            "async_origin_client_type": _safe(ctx.get("async_origin_client_type")),
            "last_user_client_type": _safe(ctx.get("last_user_client_type")),
            "mission_tasks": _safe(ctx.get("mission_tasks", [])),
            "mission_step_statuses": _safe(ctx.get("mission_step_statuses", [])),
            "mission_current_step_index": _safe(ctx.get("mission_current_step_index")),
            "mission_progress_status": _safe(ctx.get("mission_progress_status")),
            "mission_progress_message": _safe(ctx.get("mission_progress_message")),
            "mission_progress_detail": _safe(ctx.get("mission_progress_detail")),
            "mission_progress_label": _safe(ctx.get("mission_progress_label")),
        }
