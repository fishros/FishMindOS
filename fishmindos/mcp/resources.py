from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MCPResourceSpec:
    uri: str
    name: str
    description: str
    path: Path
    mime_type: str = "text/markdown"


class PromptResourceCatalog:
    """Expose local prompt files as MCP-style resources."""

    def __init__(self, resources: tuple[MCPResourceSpec, ...]) -> None:
        self._resources = {item.uri: item for item in resources}

    @classmethod
    def from_repo_root(cls, repo_root: str | Path | None = None) -> PromptResourceCatalog:
        root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
        return cls(
            (
                MCPResourceSpec(
                    uri="fishmindos://prompt/identity",
                    name="IDENTITY.md",
                    description="Robot identity and self-reference policy.",
                    path=root / "IDENTITY.md",
                ),
                MCPResourceSpec(
                    uri="fishmindos://prompt/soul",
                    name="SOUL.md",
                    description="Dialogue style, tone, and reply boundary rules.",
                    path=root / "SOUL.md",
                ),
                MCPResourceSpec(
                    uri="fishmindos://prompt/user",
                    name="USER.md",
                    description="User preferences and interaction goals.",
                    path=root / "USER.md",
                ),
                MCPResourceSpec(
                    uri="fishmindos://prompt/agent",
                    name="AGENT.md",
                    description="Agent identity, planning policy, and safety rules.",
                    path=root / "AGENT.md",
                ),
                MCPResourceSpec(
                    uri="fishmindos://prompt/tools",
                    name="TOOLS.md",
                    description="Tool semantics and natural-language mapping guidance.",
                    path=root / "TOOLS.md",
                ),
                MCPResourceSpec(
                    uri="fishmindos://prompt/task-spec",
                    name="TASK_SPEC.md",
                    description="Task planning and execution contract.",
                    path=root / "TASK_SPEC.md",
                ),
            )
        )

    def list_resources(self) -> list[dict[str, str]]:
        return [
            {
                "uri": item.uri,
                "name": item.name,
                "description": item.description,
                "mimeType": item.mime_type,
            }
            for item in self._resources.values()
        ]

    def read_resource(self, uri: str) -> dict[str, str]:
        resource = self._resources.get(uri)
        if resource is None:
            raise KeyError(f"Unknown MCP resource: {uri}")
        return {
            "uri": resource.uri,
            "name": resource.name,
            "description": resource.description,
            "mimeType": resource.mime_type,
            "text": self._read_file(resource.path),
        }

    def read_planning_bundle(self) -> dict[str, str]:
        bundle = {
            "identity": "",
            "soul": "",
            "user": "",
            "agent": "",
            "tools": "",
            "task_spec": "",
        }
        uri_to_key = {
            "fishmindos://prompt/identity": "identity",
            "fishmindos://prompt/soul": "soul",
            "fishmindos://prompt/user": "user",
            "fishmindos://prompt/agent": "agent",
            "fishmindos://prompt/tools": "tools",
            "fishmindos://prompt/task-spec": "task_spec",
        }
        for uri, key in uri_to_key.items():
            try:
                bundle[key] = self.read_resource(uri)["text"]
            except KeyError:
                bundle[key] = ""
        return bundle

    @staticmethod
    @lru_cache(maxsize=16)
    def _read_file(path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()
