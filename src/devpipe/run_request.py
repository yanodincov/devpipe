from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from devpipe.app import RunConfig


@dataclass
class ExecRequest:
    """Normalized non-interactive execution request."""
    profile: str = ""
    task: str = ""
    task_id: str | None = None
    runner: str = "auto"
    model: str | None = None
    effort: str | None = None
    tags: list[str] = field(default_factory=list)
    start_agent: str | None = None
    stop_agent: str | None = None
    topic: str | None = None
    extra_params: dict[str, Any] = field(default_factory=dict)
    with_thinking: bool = False

    def to_run_config(self) -> RunConfig:
        extra_params = dict(self.extra_params)
        if self.topic is not None:
            extra_params["topic"] = self.topic
        return RunConfig(
            profile=self.profile,
            task=self.task,
            task_id=self.task_id,
            runner=self.runner,
            model=self.model,
            effort=self.effort,
            tags=self.tags or None,
            extra_params=extra_params or None,
            first_role=self.start_agent,
            last_role=self.stop_agent,
        )


def load_exec_request(pipe_file: str | Path | None, overrides: dict[str, Any]) -> ExecRequest:
    """Load execution request from replay YAML and override with CLI flags."""
    base: dict[str, Any] = {}
    if pipe_file is not None:
        base = _load_pipe_file(Path(pipe_file))

    merged = dict(base)
    for key, value in overrides.items():
        if value is None:
            continue
        if key == "tags" and value == []:
            continue
        merged[key] = value

    tags = merged.get("tags") or []
    if isinstance(tags, str):
        tags = [item.strip() for item in tags.split(",") if item.strip()]

    extra_params = merged.get("extra_params") or {}
    known = {
        "profile",
        "task",
        "task_id",
        "runner",
        "model",
        "effort",
        "tags",
        "start_agent",
        "stop_agent",
        "topic",
        "with_thinking",
    }
    for key, value in merged.items():
        if key not in known and key != "extra_params":
            extra_params[key] = value

    return ExecRequest(
        profile=merged.get("profile", ""),
        task=merged.get("task", ""),
        task_id=merged.get("task_id"),
        runner=merged.get("runner", "auto"),
        model=merged.get("model"),
        effort=merged.get("effort"),
        tags=tags,
        start_agent=merged.get("start_agent"),
        stop_agent=merged.get("stop_agent"),
        topic=merged.get("topic"),
        extra_params=extra_params,
        with_thinking=bool(merged.get("with_thinking", False)),
    )


def _load_pipe_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Pipe file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("Pipe file must be a YAML object")
    return data
