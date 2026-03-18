from __future__ import annotations

from fishmindos.mcp import LocalMCPClient
from fishmindos.models import InteractionEvent, TaskSequence

from .planner import HybridTaskPlanner


class AgentCoreRuntime:
    """Receive interaction events and return an ordered task sequence."""

    def __init__(
        self,
        mcp_client: LocalMCPClient | None = None,
        planner: object | None = None,
    ) -> None:
        if planner is not None:
            self.planner = planner
        elif mcp_client is not None:
            self.planner = HybridTaskPlanner.from_env(mcp_client)
        else:
            self.planner = None

    def handle_event(self, event: InteractionEvent, on_tool_call: object = None) -> TaskSequence:
        if self.planner is None:
            raise RuntimeError("Agent core has no available planner.")
        return self.planner.plan_event(event, on_tool_call=on_tool_call)
