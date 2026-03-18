from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_FILE = "fishmindos.config.json"


def resolve_config_path(config_path: str | Path | None = None) -> Path:
    if config_path is not None:
        return Path(config_path)

    env_path = os.getenv("FISHMINDOS_CONFIG_FILE")
    if env_path:
        return Path(env_path)

    return Path.cwd() / DEFAULT_CONFIG_FILE


def load_runtime_config(config_path: str | Path | None = None) -> dict[str, Any]:
    path = resolve_config_path(config_path)
    if not path.exists():
        return {}

    raw_text = path.read_text(encoding="utf-8").strip()
    if not raw_text:
        return {}

    data = json.loads(raw_text)
    if not isinstance(data, dict):
        raise ValueError("FishMindOS config file must contain a JSON object.")
    return data


def get_config_value(
    section: str,
    key: str,
    env_var: str,
    default: Any = None,
    config_path: str | Path | None = None,
) -> Any:
    env_value = os.getenv(env_var)
    if env_value not in (None, ""):
        return env_value

    data = load_runtime_config(config_path=config_path)
    section_data = data.get(section, {})
    if not isinstance(section_data, dict):
        return default

    value = section_data.get(key, default)
    if value in ("", None):
        return default
    return value


def get_section_config(
    section: str,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    data = load_runtime_config(config_path=config_path)
    section_data = data.get(section, {})
    if not isinstance(section_data, dict):
        return {}
    return dict(section_data)
