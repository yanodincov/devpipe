from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from devpipe.project_config import load_project_config
from devpipe.resource_loader import load_resource_text
from devpipe.runners.profile_map import RunnerProfiles, load_runner_profiles


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_runner_runtime_config(
    project_root: Path | None = None,
    home_dir: Path | None = None,
) -> dict[str, Any]:
    raw = yaml.safe_load(load_resource_text("config/runners.yaml")) or {}
    config = load_project_config(project_root, home_dir=home_dir)
    runners = dict(raw.get("runners", {}))
    for engine_name, overrides in config.engines.items():
        current = runners.get(engine_name, {})
        runners[engine_name] = _deep_merge(current, overrides)
    raw["runners"] = runners
    return raw


def load_runtime_runner_profiles(
    project_root: Path | None = None,
    home_dir: Path | None = None,
) -> RunnerProfiles:
    return load_runner_profiles(load_runner_runtime_config(project_root, home_dir=home_dir))


def discover_available_engines(runner_config: dict[str, Any]) -> list[str]:
    available: list[str] = []
    for engine_name, spec in runner_config.items():
        command = spec.get("command", [])
        if isinstance(command, list) and command:
            binary = str(command[0])
            if shutil.which(binary):
                available.append(engine_name)
    return available


def resolve_engine_choice(
    *,
    requested_runner: str,
    stage_default_engine: str,
    available_engines: list[str],
) -> str:
    if requested_runner != "auto":
        if requested_runner not in available_engines:
            raise ValueError(
                f"Engine '{requested_runner}' is not available. Available engines: {', '.join(available_engines) or 'none'}"
            )
        return requested_runner

    if stage_default_engine in available_engines:
        return stage_default_engine
    if available_engines:
        return available_engines[0]
    raise ValueError("No available AI engines found. Install codex or claude.")
