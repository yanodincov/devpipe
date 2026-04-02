"""Run history persistence with replay YAML and execution-details JSON."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from devpipe.app import RunConfig

ISO_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


@dataclass
class StageRun:
    """Record of a single stage execution, including attempts."""
    name: str
    started_at: datetime
    completed_at: datetime | None
    status: str
    output: dict = field(default_factory=dict)
    attempts: list[dict] = field(default_factory=list)


@dataclass
class RunReplayConfig:
    """Replayable launch input stored in .devpipe.yaml."""
    profile: str
    config: dict[str, Any]

    def to_yaml_dict(self) -> dict[str, Any]:
        data = dict(self.config)
        data["profile"] = self.profile
        return data


@dataclass
class RunDetailsEntry:
    """Execution details stored in .devpipe.json."""
    run_id: str
    timestamp: datetime
    summary: dict[str, Any]
    stages: list[StageRun]

    def to_json_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp.strftime(ISO_DATETIME_FORMAT)
        for stage in data.get("stages", []):
            if isinstance(stage.get("started_at"), datetime):
                stage["started_at"] = stage["started_at"].strftime(ISO_DATETIME_FORMAT)
            if isinstance(stage.get("completed_at"), datetime):
                stage["completed_at"] = stage["completed_at"].strftime(ISO_DATETIME_FORMAT)
            for attempt in stage.get("attempts", []):
                if isinstance(attempt.get("started_at"), datetime):
                    attempt["started_at"] = attempt["started_at"].strftime(ISO_DATETIME_FORMAT)
                if isinstance(attempt.get("completed_at"), datetime):
                    attempt["completed_at"] = attempt["completed_at"].strftime(ISO_DATETIME_FORMAT)
        return data

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> RunDetailsEntry:
        stages: list[StageRun] = []
        for stage_data in data.get("stages", []):
            started_at = datetime.strptime(stage_data["started_at"], ISO_DATETIME_FORMAT)
            completed_at = stage_data.get("completed_at")
            if completed_at is not None:
                completed_at = datetime.strptime(completed_at, ISO_DATETIME_FORMAT)
            attempts = []
            for attempt in stage_data.get("attempts", []):
                parsed_attempt = dict(attempt)
                if parsed_attempt.get("started_at") is not None:
                    parsed_attempt["started_at"] = datetime.strptime(parsed_attempt["started_at"], ISO_DATETIME_FORMAT)
                if parsed_attempt.get("completed_at") is not None:
                    parsed_attempt["completed_at"] = datetime.strptime(parsed_attempt["completed_at"], ISO_DATETIME_FORMAT)
                attempts.append(parsed_attempt)
            stages.append(
                StageRun(
                    name=stage_data["name"],
                    started_at=started_at,
                    completed_at=completed_at,
                    status=stage_data["status"],
                    output=stage_data.get("output", {}),
                    attempts=attempts,
                )
            )
        return cls(
            run_id=data["run_id"],
            timestamp=datetime.strptime(data["timestamp"], ISO_DATETIME_FORMAT),
            summary=data.get("summary", {}),
            stages=stages,
        )


@dataclass
class RunHistoryEntry:
    """Combined view used by UI and history screens."""
    run_id: str
    timestamp: datetime
    profile: str
    config: dict[str, Any]
    stages: list[StageRun]
    summary: dict[str, Any]


def save_run_replay_config(run_id: str, entry: RunReplayConfig, history_dir: Path) -> None:
    """Save replayable launch input to YAML."""
    history_dir.mkdir(parents=True, exist_ok=True)
    file_path = history_dir / f"{run_id}.devpipe.yaml"
    file_path.write_text(
        yaml.dump(entry.to_yaml_dict(), default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def save_run_details(entry: RunDetailsEntry, history_dir: Path) -> None:
    """Save execution details to JSON."""
    history_dir.mkdir(parents=True, exist_ok=True)
    file_path = history_dir / f"{entry.run_id}.devpipe.json"
    file_path.write_text(
        json.dumps(entry.to_json_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_run_details(history_dir: Path, run_id: str) -> RunDetailsEntry | None:
    """Load JSON execution details for a run."""
    file_path = history_dir / f"{run_id}.devpipe.json"
    if not file_path.exists():
        return None
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return RunDetailsEntry.from_json_dict(data)


def load_run_history(history_dir: Path) -> list[RunHistoryEntry]:
    """Load replay YAML files and combine them with adjacent JSON details."""
    entries: list[RunHistoryEntry] = []
    if not history_dir.exists():
        return entries

    for yaml_file in sorted(history_dir.glob("*.devpipe.yaml")):
        try:
            config_data = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
            if not isinstance(config_data, dict):
                continue
            run_id = yaml_file.name.removesuffix(".devpipe.yaml")
            details = load_run_details(history_dir, run_id)
            profile = str(config_data.get("profile", ""))
            config = {k: v for k, v in config_data.items() if k != "profile"}
            timestamp = details.timestamp if details is not None else datetime.fromtimestamp(yaml_file.stat().st_mtime, tz=timezone.utc)
            summary = details.summary if details is not None else {}
            stages = details.stages if details is not None else []
            entries.append(
                RunHistoryEntry(
                    run_id=run_id,
                    timestamp=timestamp,
                    profile=profile,
                    config=config,
                    stages=stages,
                    summary=summary,
                )
            )
        except Exception:
            continue

    entries.sort(key=lambda e: e.timestamp, reverse=True)
    return entries


# --- Legacy format (global history for tui) ---

HISTORY_PATH = Path.home() / ".devpipecfg" / "history.yaml"
MAX_ENTRIES = 50


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def save_run(config: "RunConfig") -> None:
    """Legacy: save run start to global history."""
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    if HISTORY_PATH.exists():
        entries = yaml.safe_load(HISTORY_PATH.read_text(encoding="utf-8")) or []

    extra = config.extra_params or {}
    tag_roles = config.tag_roles or {}
    tags_union = sorted(set(tag_roles.keys()))
    entry: dict[str, Any] = {
        "date": _now_iso(),
        "task": config.task or "",
        "task_id": config.task_id or "",
        "runner": config.runner or "codex",
        "model": config.model or "auto",
        "effort": config.effort or "auto",
        "target_branch": config.target_branch or "",
        "service": config.service or "",
        "namespace": config.namespace or "",
        "tags": tags_union,
        "tag_roles": dict(tag_roles),
        "extra_params": dict(extra),
        "first_role": config.first_role or "",
        "last_role": config.last_role or "",
    }
    entries.insert(0, entry)
    HISTORY_PATH.write_text(
        yaml.dump(entries[:MAX_ENTRIES], allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def finish_run(config: "RunConfig") -> None:
    """Legacy: mark run as finished in global history."""
    if not HISTORY_PATH.exists():
        return

    entries = yaml.safe_load(HISTORY_PATH.read_text(encoding="utf-8")) or []
    for entry in entries:
        if entry.get("finished_at"):
            continue
        if entry.get("task", "") != (config.task or ""):
            continue
        if entry.get("task_id", "") != (config.task_id or ""):
            continue
        entry["finished_at"] = _now_iso()
        break

    HISTORY_PATH.write_text(
        yaml.dump(entries[:MAX_ENTRIES], allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def load_history() -> list[dict]:
    """Legacy: load global history entries."""
    if not HISTORY_PATH.exists():
        return []
    return yaml.safe_load(HISTORY_PATH.read_text(encoding="utf-8")) or []
