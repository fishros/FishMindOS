from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fishmindos.config import get_config_value


CURRENT_VERSION = 1


@dataclass(frozen=True, slots=True)
class StoredTaskChain:
    name: str
    steps: list[dict[str, Any]]
    created_at: str
    updated_at: str


class TaskChainStore:
    def __init__(self, storage_path: str | Path) -> None:
        self.storage_path = Path(storage_path)

    @classmethod
    def from_env(cls) -> TaskChainStore:
        raw_path = get_config_value(
            "task_chains",
            "storage_file",
            "FISHMINDOS_TASK_CHAINS_FILE",
            default="task_chains.json",
        )
        return cls(storage_path=Path(str(raw_path)))

    def list_chains(self) -> list[StoredTaskChain]:
        document = self._load_document()
        return [self._to_chain(entry) for entry in document["chains"]]

    def get_chain(self, name: str) -> StoredTaskChain | None:
        normalized_name = self._normalize_name(name)
        document = self._load_document()
        for entry in document["chains"]:
            if entry["name"] == normalized_name:
                return self._to_chain(entry)
        return None

    def save_chain(self, name: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
        normalized_name = self._normalize_name(name)
        normalized_steps = self._sanitize_steps(steps)
        document = self._load_document()
        now = datetime.now(timezone.utc).isoformat()

        existing_index = next(
            (index for index, item in enumerate(document["chains"]) if item["name"] == normalized_name),
            -1,
        )
        entry = {
            "name": normalized_name,
            "steps": normalized_steps,
            "created_at": document["chains"][existing_index]["created_at"] if existing_index >= 0 else now,
            "updated_at": now,
        }
        if existing_index >= 0:
            document["chains"][existing_index] = entry
        else:
            document["chains"].append(entry)

        self._save_document(document)
        return {"chain": self._to_chain(entry), "replaced": existing_index >= 0}

    def delete_chain(self, name: str) -> bool:
        normalized_name = self._normalize_name(name)
        document = self._load_document()
        next_chains = [item for item in document["chains"] if item["name"] != normalized_name]
        if len(next_chains) == len(document["chains"]):
            return False
        document["chains"] = next_chains
        self._save_document(document)
        return True

    def _load_document(self) -> dict[str, Any]:
        if not self.storage_path.exists():
            return {"version": CURRENT_VERSION, "chains": []}

        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Task chain file is not valid JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise ValueError("Task chain file must contain a JSON object.")

        raw_chains = payload.get("chains", [])
        if not isinstance(raw_chains, list):
            raw_chains = []

        chains: list[dict[str, Any]] = []
        for entry in raw_chains:
            if not isinstance(entry, dict):
                continue
            try:
                chains.append(
                    {
                        "name": self._normalize_name(entry.get("name", "")),
                        "steps": self._sanitize_steps(entry.get("steps", [])),
                        "created_at": self._normalize_timestamp(entry.get("created_at")),
                        "updated_at": self._normalize_timestamp(entry.get("updated_at")),
                    }
                )
            except ValueError:
                continue

        chains.sort(key=lambda item: item["name"])
        return {"version": CURRENT_VERSION, "chains": chains}

    def _save_document(self, document: dict[str, Any]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(f"{json.dumps(document, ensure_ascii=False, indent=2)}\n", encoding="utf-8")

    def _sanitize_steps(self, steps: Any) -> list[dict[str, Any]]:
        if not isinstance(steps, list) or not steps:
            raise ValueError("Task chain must contain at least one step.")

        normalized_steps: list[dict[str, Any]] = []
        for index, item in enumerate(steps, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"Task chain step {index} must be an object.")

            skill = str(item.get("skill", "")).strip()
            if not skill:
                raise ValueError(f"Task chain step {index} is missing skill.")

            args = item.get("args", {})
            if not isinstance(args, dict):
                raise ValueError(f"Task chain step {index} args must be an object.")

            on_fail = str(item.get("on_fail", "abort")).strip() or "abort"
            normalized_steps.append(
                {
                    "skill": skill,
                    "args": args,
                    "on_fail": on_fail,
                }
            )
        return normalized_steps

    @staticmethod
    def _normalize_name(value: Any) -> str:
        name = str(value or "").strip()
        if not name:
            raise ValueError("Task chain name is required.")
        return name

    @staticmethod
    def _normalize_timestamp(value: Any) -> str:
        text = str(value or "").strip()
        if text:
            return text
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _to_chain(entry: dict[str, Any]) -> StoredTaskChain:
        return StoredTaskChain(
            name=str(entry["name"]),
            steps=[dict(item) for item in entry["steps"]],
            created_at=str(entry["created_at"]),
            updated_at=str(entry["updated_at"]),
        )
