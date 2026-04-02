from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ProjectConfig:
    defaults: dict = field(default_factory=dict)
    available: dict = field(default_factory=dict)
    tag_params: dict = field(default_factory=dict)  # {tag_name: {defaults: {}, available: {}}}
    engines: dict = field(default_factory=dict)

    def default(self, key: str, fallback=None):
        return self.defaults.get(key, fallback)

    def available_list(self, key: str) -> list[str]:
        return self.available.get(key, [])


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def load_project_config(cwd: Path | None = None, *, home_dir: Path | None = None) -> ProjectConfig:
    root = cwd or Path.cwd()
    global_path = (home_dir or Path.home()) / ".devpipe" / "config.yaml"
    local_path = root / ".devpipe" / "config.yaml"

    global_data = _load_yaml(global_path)
    local_data = _load_yaml(local_path)
    data = _deep_merge(global_data, local_data)

    return ProjectConfig(
        defaults=data.get("defaults", {}),
        available=data.get("available", {}),
        tag_params=data.get("tag_params", {}),
        engines=data.get("engines", {}),
    )
