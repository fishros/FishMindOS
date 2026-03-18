from __future__ import annotations

from typing import Any

from fishmindos.skill_runtime import SkillRegistry

from .resources import PromptResourceCatalog


class LocalMCPServer:
    """In-process MCP-style server around registered skills and prompt resources."""

    def __init__(
        self,
        registry: SkillRegistry,
        resources: PromptResourceCatalog | None = None,
    ) -> None:
        self.registry = registry
        self.resources = resources or PromptResourceCatalog.from_repo_root()

    def list_tools(self) -> list[dict[str, Any]]:
        return self.registry.tool_definitions()

    def has_tool(self, name: str) -> bool:
        return self.registry.get(name) is not None

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        skill = self.registry.get(name)
        if skill is None:
            return {"ok": False, "detail": f"Tool not found: {name}"}
        return skill.run(arguments or {}, context or {})

    def list_resources(self) -> list[dict[str, str]]:
        return self.resources.list_resources()

    def read_resource(self, uri: str) -> dict[str, str]:
        return self.resources.read_resource(uri)

    def read_planning_bundle(self) -> dict[str, str]:
        return self.resources.read_planning_bundle()
