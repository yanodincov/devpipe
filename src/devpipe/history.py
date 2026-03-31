"""Run history persistence: store run summaries as YAML files in .devpipe/history/."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import yaml
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from devpipe.app import RunConfig

ISO_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


# --- New format (per-project YAML runs) ---

@dataclass
class StageRun:
    """Record of a single stage execution, including attempts."""
    name: str
    started_at: datetime
    completed_at: datetime | None
    status: str  # "completed", "failed", "cancelled"
    output: dict = field(default_factory=dict)
    attempts: list[dict] = field(default_factory=list)


@dataclass
class RunHistoryEntry:
    """Complete record of a pipeline run."""
    run_id: str
    timestamp: datetime
    profile: str
    config: dict
    stages: list[StageRun]
    summary: dict

    def to_yaml_dict(self) -> dict:
        """Convert to a dict suitable for YAML serialization."""
        data = asdict(self)
        # Convert datetime to ISO string
        data["timestamp"] = self.timestamp.strftime(ISO_DATETIME_FORMAT)
        for stage in data.get("stages", []):
            if isinstance(stage.get("started_at"), datetime):
                stage["started_at"] = stage["started_at"].strftime(ISO_DATETIME_FORMAT)
            if isinstance(stage.get("completed_at"), datetime):
                if stage["completed_at"] is not None:
                    stage["completed_at"] = stage["completed_at"].strftime(ISO_DATETIME_FORMAT)
            # attempts contain datetimes too
            for attempt in stage.get("attempts", []):
                if isinstance(attempt.get("started_at"), datetime):
                    attempt["started_at"] = attempt["started_at"].strftime(ISO_DATETIME_FORMAT)
                if isinstance(attempt.get("completed_at"), datetime):
                    if attempt["completed_at"] is not None:
                        attempt["completed_at"] = attempt["completed_at"].strftime(ISO_DATETIME_FORMAT)
        return data

    @classmethod
    def from_yaml_dict(cls, data: dict) -> RunHistoryEntry:
        """Parse from a dict loaded from YAML."""
        # Parse timestamps
        data["timestamp"] = datetime.strptime(data["timestamp"], ISO_DATETIME_FORMAT)
        stages = []
        for stage_data in data.get("stages", []):
            stage_data["started_at"] = datetime.strptime(stage_data["started_at"], ISO_DATETIME_FORMAT)
            comp = stage_data.get("completed_at")
            if comp is not None:
                stage_data["completed_at"] = datetime.strptime(comp, ISO_DATETIME_FORMAT)
            # parse attempts
            attempts = []
            for att in stage_data.get("attempts", []):
                att["started_at"] = datetime.strptime(att["started_at"], ISO_DATETIME_FORMAT)
                comp_att = att.get("completed_at")
                if comp_att is not None:
                    att["completed_at"] = datetime.strptime(comp_att, ISO_DATETIME_FORMAT)
                attempts.append(att)
            stage_data["attempts"] = attempts
            stages.append(StageRun(**stage_data))
        data["stages"] = stages
        return cls(**data)


def save_run_history(entry: RunHistoryEntry, history_dir: Path) -> None:
    """Save a run history entry to a YAML file in history_dir."""
    history_dir.mkdir(parents=True, exist_ok=True)
    file_path = history_dir / f"{entry.run_id}.devpipe.yml"
    file_path.write_text(
        yaml.dump(entry.to_yaml_dict(), default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def load_run_history(history_dir: Path) -> list[RunHistoryEntry]:
    """Load all run history entries from history_dir, sorted by timestamp descending."""
    entries: list[RunHistoryEntry] = []
    if not history_dir.exists():
        return entries
    for yaml_file in sorted(history_dir.glob("*.devpipe.yml")):
        try:
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
            if data:
                entries.append(RunHistoryEntry.from_yaml_dict(data))
        except Exception:
            # Skip corrupted files
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
    from devpipe.tags import load_available_tags
    from pathlib import Path

    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    if HISTORY_PATH.exists():
        entries = yaml.safe_load(HISTORY_PATH.read_text(encoding="utf-8")) or []

    extra = config.extra_params or {}
    # Convert tag_roles to legacy tags list if needed, or keep both
    tag_roles = config.tag_roles or {}
    # For backward compatibility, also store tags as list (union of all tags from tag_roles)
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
