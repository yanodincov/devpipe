"""Shared formatting helpers for task snapshots in the TUI."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from devpipe.ui.state import FieldMeta

STANDARD_FIELDS: list[tuple[str, str]] = [
    ("profile", "Profile"),
    ("task", "Task"),
    ("runner", "Runner"),
    ("model", "Model"),
    ("effort", "Effort"),
    ("tags", "Tags"),
    ("first_role", "Start Agent"),
    ("last_role", "Finish Agent"),
]

TOP_LEVEL_CUSTOM_FIELDS: list[tuple[str, str]] = [
    ("task_id", "Task Id"),
    ("target_branch", "Target Branch"),
    ("service", "Service"),
    ("namespace", "Namespace"),
]

HISTORY_TITLE_MAX_LEN = 40


def format_snapshot_value(value: Any, key: str = "") -> str:
    if value is None or value == "":
        return "[dim](empty)[/dim]"
    # Normalize bool to lowercase string
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) if value else "[dim](empty)[/dim]"
    if isinstance(value, dict):
        if not value:
            return "[dim](empty)[/dim]"
        if key == "tags":
            # tag_roles: {tag: [roles]}
            return ", ".join(f"{k} ({', '.join(v)})" for k, v in value.items())
        return ", ".join(f"{k}={v}" for k, v in value.items())
    str_value = str(value)
    if key == "task":
        lines = str_value.splitlines()
        if len(lines) > 3:
            return "\n".join(lines[:3]) + "\n..."
        return str_value
    return str_value


def build_task_snapshot_lines(
    values: dict[str, Any],
    custom_fields: list[tuple[str, str]],
    highlight_key: str | None = None,
) -> list[str]:
    lines: list[str] = []

    for key, label in STANDARD_FIELDS:
        display_val = format_snapshot_value(values.get(key, ""), key=key)
        if key == highlight_key:
            lines.append(f" [bold]▸ {label}:[/bold] {display_val}")
        else:
            lines.append(f"   {label}: {display_val}")

    if custom_fields:
        lines.append("\n[dim]── Custom ──[/dim]")
        for key, label in custom_fields:
            display_val = format_snapshot_value(values.get(key, ""), key=key)
            if key == highlight_key:
                lines.append(f" [bold]▸ {label}:[/bold] {display_val}")
            else:
                lines.append(f"   {label}: {display_val}")

    return lines


def custom_fields_from_form(fields: list[FieldMeta]) -> list[tuple[str, str]]:
    result = []
    for field in fields:
        if field.section == "custom" and field.key != "tags":
            result.append((field.key, field.label))
    return result


def custom_fields_from_history_entry(entry: dict[str, Any]) -> list[tuple[str, str]]:
    result = [(key, label) for key, label in TOP_LEVEL_CUSTOM_FIELDS if key in entry]
    extra = entry.get("extra_params", {})
    if isinstance(extra, dict):
        for key in extra:
            result.append((key, key.replace("_", " ").title()))
    return result


def custom_fields_from_profile_history_entry(
    profile: str,
    entry: dict[str, Any],
    project_root: Path | None = None,
) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _append(key: str, label: str) -> None:
        if key == "tags" or key in seen:
            return
        result.append((key, label))
        seen.add(key)

    try:
        from devpipe.ui.services import load_profile_fields

        for field in load_profile_fields(profile, project_root):
            if field.section == "custom":
                _append(field.key, field.label)
    except Exception:
        pass

    for key, label in custom_fields_from_history_entry(entry):
        _append(key, label)

    return result


def compact_history_title(task: str, max_len: int = HISTORY_TITLE_MAX_LEN) -> str:
    first_line = (task or "").splitlines()[0].strip()
    if not first_line:
        return "(empty)"
    if len(first_line) <= max_len:
        return first_line
    return f"{first_line[: max_len - 1].rstrip()}…"
