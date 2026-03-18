from __future__ import annotations

from typing import Any

from .server import LocalMCPServer


class LocalMCPClient:
    """Thin client wrapper so agent_core and execution_runtime do not depend on SkillRegistry directly."""

    def __init__(self, server: LocalMCPServer) -> None:
        self.server = server

    def list_tools(self) -> list[dict[str, Any]]:
        return self.server.list_tools()

    def has_tool(self, name: str) -> bool:
        return self.server.has_tool(name)

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.server.call_tool(name=name, arguments=arguments, context=context)

    def list_resources(self) -> list[dict[str, str]]:
        return self.server.list_resources()

    def read_resource(self, uri: str) -> dict[str, str]:
        return self.server.read_resource(uri)

    def read_planning_bundle(self) -> dict[str, str]:
        return self.server.read_planning_bundle()
