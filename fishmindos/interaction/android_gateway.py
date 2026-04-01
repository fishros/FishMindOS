"""
Android HTTP + WebSocket gateway for FishMindOS.

Exposes a REST + WebSocket API so that Android (or any HTTP/WS client)
can interact with the FishMindOS backend without touching the existing
terminal channel.

Endpoints
---------
POST /api/session/create      — create or resume a named session
POST /api/chat/send           — send natural-language text (blocking until done)
POST /api/chat/confirm        — forward human-confirm signal
POST /api/chat/stop           — cancel current task
GET  /api/session/state       — poll current session snapshot
GET  /api/world/locations     — list known world locations for a session
WS   /api/events?session_id=  — subscribe to real-time structured events

All WS events share the same envelope that InteractionManager emits:
    {
        "type": "<event_type>",
        "session_id": "<str>",
        "timestamp": "<ISO-8601>",
        "payload": { ... }
    }

On WS connect the server immediately pushes a ``session_state`` event
carrying the full session snapshot so clients can restore their UI after
a reconnect (Phase 6 state recovery).

Threading model
---------------
``handle_user_text`` is synchronous / blocking.  The WS handler and REST
endpoints run on the asyncio event loop managed by uvicorn.  Blocking
calls are offloaded via ``loop.run_in_executor``.

``_on_event`` is invoked from the worker thread that runs
``handle_user_text``.  It uses ``loop.call_soon_threadsafe`` to safely
enqueue events into the asyncio.Queue that the WS send loop reads.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from fishmindos.config import get_config
from fishmindos.interaction.channels.base import InteractionChannel
from fishmindos.interaction import events as ev
from fishmindos.interaction.world_admin import (
    WorldAdminBusyError,
    WorldAdminError,
    WorldAdminNotFoundError,
)

if TYPE_CHECKING:
    from fishmindos.interaction.manager import InteractionManager

# ── Pydantic request models (module-level, Pydantic v2 compatible) ─────────────
# Defined here rather than inside _build_app so that Pydantic v2 can properly
# resolve type annotations without local-scope reference issues.
try:
    from pydantic import BaseModel as _BaseModel  # type: ignore[import]

    class CreateSessionReq(_BaseModel):
        session_id: Optional[str] = None
        client_type: str = "android"

    class ChatSendReq(_BaseModel):
        session_id: str
        text: str

    class ChatConfirmReq(_BaseModel):
        session_id: str
        input: str = "确认"

    class ChatStopReq(_BaseModel):
        session_id: str

    class SetDefaultWorldMapReq(_BaseModel):
        session_id: str
        map_id: int

    class UpdateWorldLocationReq(_BaseModel):
        session_id: str
        name: str
        map_id: Optional[int] = None
        map_name: Optional[str] = None
        waypoint_id: Optional[int] = None
        description: Optional[str] = None
        category: Optional[str] = None
        aliases: Optional[List[str]] = None
        task_hints: Optional[List[str]] = None
        relations: Optional[List[Dict[str, str]]] = None

    class WorldAiEnrichReq(_BaseModel):
        session_id: str

    _PYDANTIC_MODELS_READY = True
except ImportError:
    _PYDANTIC_MODELS_READY = False

# ── FastAPI / Starlette imports (module-level) ─────────────────────────────────
# IMPORTANT: these MUST be at module level, not inside _build_app().
# `from __future__ import annotations` turns all annotations into lazy strings.
# FastAPI calls get_type_hints(ws_events) at route registration time and looks
# up the string "WebSocket" in ws_events.__globals__ == android_gateway module
# globals.  If WebSocket is only a local variable inside _build_app(), the
# lookup fails silently and the WS route is registered broken → 403 on connect.
try:
    from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect  # type: ignore[import]
    from fastapi.responses import JSONResponse  # type: ignore[import]
    _FASTAPI_READY = True
except ImportError:
    _FASTAPI_READY = False


class AndroidGateway(InteractionChannel):
    """FastAPI-based HTTP + WebSocket gateway for Android clients."""

    def __init__(
        self,
        manager: "InteractionManager",
        host: str = "0.0.0.0",
        port: int = 8083,
    ) -> None:
        self.manager = manager
        self.host = host
        self.port = port
        # session_id -> [(asyncio.Queue, asyncio.AbstractEventLoop), ...]
        # Multiple Android devices may subscribe to the same session so they
        # can stay in sync and render the same task/confirm UI together.
        self._ws_connections: Dict[str, List[Tuple[asyncio.Queue, asyncio.AbstractEventLoop]]] = {}
        self._lock = threading.Lock()
        self._server_thread: Optional[threading.Thread] = None
        self._server = None
        self.manager.add_listener(self.handle_event)

    # ── Event routing ──────────────────────────────────────────────────

    def handle_event(self, event: Dict[str, Any]) -> None:
        """Required by InteractionChannel; delegates to internal router."""
        self._on_event(event)

    def _is_debug_enabled(self) -> bool:
        try:
            return bool(getattr(get_config().app, "debug", False))
        except Exception:
            return False

    def _debug_print(self, message: str) -> None:
        if self._is_debug_enabled():
            print(message, flush=True)

    def _on_event(self, event: Dict[str, Any]) -> None:
        """Route an interaction event to the matching WebSocket queue.

        Called from arbitrary threads; uses call_soon_threadsafe for safety.
        """
        session_id = event.get("session_id")
        event_type = event.get("type")
        with self._lock:
            if session_id is not None:
                targets = list(self._ws_connections.get(session_id, []))
            else:
                targets = [
                    conn
                    for connections in self._ws_connections.values()
                    for conn in connections
                ]

        self._debug_print(
            f"[AndroidGateway] route event type={event_type} session={session_id} targets={len(targets)}"
        )

        for conn in targets:
            queue, loop = conn
            try:
                loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception:
                pass  # queue full or loop closed — drop silently

    # ── Lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        self._server_thread = threading.Thread(
            target=self._run_server,
            daemon=True,
            name="android-gateway",
        )
        self._server_thread.start()

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.should_exit = True
            except Exception:
                pass
        try:
            self.manager.remove_listener(self.handle_event)
        except Exception:
            pass

    def _run_server(self) -> None:
        try:
            import uvicorn  # type: ignore[import]
        except ImportError:
            print(
                "[AndroidGateway] uvicorn not installed. "
                "Run: pip install fastapi uvicorn"
            )
            return

        app = self._build_app()
        config = uvicorn.Config(
            app,
            host=self.host,
            port=self.port,
            log_level="warning",
        )
        self._server = uvicorn.Server(config)
        asyncio.run(self._server.serve())

    # ── FastAPI application ────────────────────────────────────────────

    def _build_app(self):  # noqa: C901
        if not _PYDANTIC_MODELS_READY or not _FASTAPI_READY:
            raise RuntimeError(
                "fastapi/pydantic not installed. "
                "Run: pip install fastapi uvicorn pydantic"
            )

        app = FastAPI(title="FishMindOS Android Gateway", version="1.0.0")

        # Note: CORSMiddleware is intentionally NOT added here.
        # Android native apps (OkHttp/Retrofit) are not browser clients and do
        # not enforce CORS. Adding CORSMiddleware with starlette 1.0+ would also
        # intercept WebSocket upgrade requests and cause 403 when no Origin header
        # is present (typical for websocket-client / OkHttp WS connections).
        # If a browser-based client is ever needed, add CORS headers per-response
        # in a lightweight @app.middleware("http") instead.

        gateway = self  # capture for closures

        # ── Helper ──────────────────────────────────────────────────

        def _not_found(session_id: str) -> JSONResponse:
            return JSONResponse(
                status_code=404,
                content={"ok": False, "error": f"session '{session_id}' not found"},
            )

        def _not_found_error(message: str) -> JSONResponse:
            return JSONResponse(
                status_code=404,
                content={"ok": False, "error": message},
            )

        def _bad_request(message: str) -> JSONResponse:
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": message},
            )

        def _conflict(message: str) -> JSONResponse:
            return JSONResponse(
                status_code=409,
                content={"ok": False, "error": message},
            )

        # ── REST endpoints ───────────────────────────────────────────

        @app.post("/api/session/create")
        async def create_session(req: CreateSessionReq):
            sid = req.session_id or f"android-{uuid.uuid4().hex[:8]}"
            gateway.manager.get_session(sid, client_type=req.client_type)
            snapshot = gateway.manager.get_session_snapshot(sid)
            return {"ok": True, "session_id": sid, "state": snapshot}

        @app.post("/api/chat/send")
        async def chat_send(req: ChatSendReq):
            session = gateway.manager.sessions.get(req.session_id)
            if session is None:
                return _not_found(req.session_id)

            # Collect MESSAGE events emitted during handle_user_text so we can
            # return the reply text in the HTTP response body.  WS clients
            # still receive all events normally via _on_event.
            collected_messages: list = []

            def _collect(event: dict) -> None:
                if (
                    event.get("session_id") == req.session_id
                    and event.get("type") == ev.MESSAGE
                ):
                    text = event.get("payload", {}).get("text", "")
                    if text:
                        collected_messages.append(text)

            gateway.manager.add_listener(_collect)
            loop = asyncio.get_running_loop()
            try:
                # handle_user_text is blocking; run in thread pool.
                await loop.run_in_executor(
                    None,
                    gateway.manager.handle_user_text,
                    req.text,
                    req.session_id,
                    "android",
                )
            finally:
                gateway.manager.remove_listener(_collect)

            reply = collected_messages[0] if collected_messages else None
            return {"ok": True, "reply": reply}

        @app.post("/api/chat/confirm")
        async def chat_confirm(req: ChatConfirmReq):
            if gateway.manager.sessions.get(req.session_id) is None:
                return _not_found(req.session_id)
            print(
                f"[AndroidGateway] HTTP confirm session={req.session_id} input={req.input}",
                flush=True,
            )
            gateway.manager.confirm_human(req.input, session_id=req.session_id, client_type="android")
            return {"ok": True}

        @app.post("/api/chat/stop")
        async def chat_stop(req: ChatStopReq):
            if gateway.manager.sessions.get(req.session_id) is None:
                return _not_found(req.session_id)
            gateway.manager.cancel_current(req.session_id, client_type="android")
            return {"ok": True}

        @app.get("/api/session/state")
        async def session_state(session_id: str = Query(..., description="Session ID")):
            snapshot = gateway.manager.get_session_snapshot(session_id)
            if snapshot is None:
                return _not_found(session_id)
            return {"ok": True, "state": snapshot}

        @app.get("/api/world/locations")
        async def world_locations(session_id: str = Query(..., description="Session ID")):
            session = gateway.manager.sessions.get(session_id)
            if session is None:
                return _not_found(session_id)
            locations = session.session_context.get("world_known_locations", [])
            world_name = session.session_context.get("world_name", "")
            return {"ok": True, "world_name": world_name, "locations": locations}

        @app.get("/api/world/admin/state")
        async def world_admin_state(session_id: str = Query(..., description="Session ID")):
            try:
                return gateway.manager.get_world_admin().get_state(session_id)
            except WorldAdminNotFoundError as exc:
                return _not_found_error(str(exc))
            except WorldAdminError as exc:
                return _bad_request(str(exc))

        @app.post("/api/world/admin/default-map")
        async def world_admin_set_default_map(req: SetDefaultWorldMapReq):
            try:
                return gateway.manager.get_world_admin().set_default_map(req.session_id, req.map_id)
            except WorldAdminNotFoundError as exc:
                return _not_found_error(str(exc))
            except WorldAdminBusyError as exc:
                return _conflict(str(exc))
            except WorldAdminError as exc:
                return _bad_request(str(exc))

        @app.post("/api/world/admin/location/update")
        async def world_admin_update_location(req: UpdateWorldLocationReq):
            try:
                return gateway.manager.get_world_admin().update_location(
                    req.session_id,
                    name=req.name,
                    map_id=req.map_id,
                    map_name=req.map_name,
                    waypoint_id=req.waypoint_id,
                    description=req.description,
                    category=req.category,
                    aliases=req.aliases,
                    task_hints=req.task_hints,
                    relations=req.relations,
                )
            except WorldAdminNotFoundError as exc:
                return _not_found_error(str(exc))
            except WorldAdminBusyError as exc:
                return _conflict(str(exc))
            except WorldAdminError as exc:
                return _bad_request(str(exc))

        @app.post("/api/world/admin/ai-enrich")
        async def world_admin_ai_enrich(req: WorldAiEnrichReq):
            loop = asyncio.get_running_loop()
            try:
                return await loop.run_in_executor(
                    None,
                    gateway.manager.get_world_admin().batch_ai_enrich,
                    req.session_id,
                )
            except WorldAdminNotFoundError as exc:
                return _not_found_error(str(exc))
            except WorldAdminBusyError as exc:
                return _conflict(str(exc))
            except WorldAdminError as exc:
                return _bad_request(str(exc))

        # ── WebSocket endpoint ───────────────────────────────────────

        @app.websocket("/api/events")
        async def ws_events(
            websocket: WebSocket,
            session_id: str = Query(..., description="Session ID to subscribe"),
        ):
            await websocket.accept()
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue = asyncio.Queue(maxsize=256)
            connection = (queue, loop)

            with gateway._lock:
                gateway._ws_connections.setdefault(session_id, []).append(connection)

            # Phase 6: push current state immediately so the client can
            # restore its UI after a reconnect.
            snapshot = gateway.manager.get_session_snapshot(session_id)
            if snapshot:
                await websocket.send_json(
                    {
                        "type": ev.SESSION_STATE,
                        "session_id": session_id,
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                        "payload": snapshot,
                    }
                )

            try:
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=25.0)
                        event_type = event.get("type")
                        gateway._debug_print(
                            f"[AndroidGateway] send event type={event_type} session={session_id}"
                        )
                        await websocket.send_json(event)
                    except asyncio.TimeoutError:
                        # Keepalive ping — prevents silent drop by mobile NAT/proxy.
                        await websocket.send_json(
                            {
                                "type": ev.PING,
                                "timestamp": datetime.now().isoformat(timespec="seconds"),
                            }
                        )
            except (WebSocketDisconnect, Exception):
                pass
            finally:
                with gateway._lock:
                    connections = gateway._ws_connections.get(session_id)
                    if connections:
                        try:
                            connections.remove(connection)
                        except ValueError:
                            pass
                        if not connections:
                            gateway._ws_connections.pop(session_id, None)

        return app
