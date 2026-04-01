"""Shared formatting helpers for task snapshots in the TUI."""
from __future__ import annotations

import textwrap
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
    return str(value)


def build_task_snapshot_lines(
    values: dict[str, Any],
    custom_fields: list[tuple[str, str]],
    highlight_key: str | None = None,
    panel_width: int = 80,
) -> list[str]:
    lines: list[str] = []

    # Compute label column width
    all_labels = [label for _, label in STANDARD_FIELDS] + [label for _, label in custom_fields]
    col_w = max((len(l) for l in all_labels), default=10) + 2

    lines.append("[bold #7aa2f7]◆ GENERAL[/bold #7aa2f7]")

    indent = " " * (2 + col_w)
    value_wrap_width = max(30, panel_width - (2 + col_w))

    def _wrap_value(val: str) -> str:
        """Wrap long value with hanging indent aligned to value column."""
        wrapped = textwrap.wrap(val, width=value_wrap_width) or [val]
        return ("\n" + indent).join(wrapped)

    for key, label in STANDARD_FIELDS:
        raw_val = values.get(key, "")
        if key == "profile":
            display_val = f"[#7aa2f7]{raw_val}[/#7aa2f7]" if raw_val else "[dim](empty)[/dim]"
            pad = label.ljust(col_w)
            if key == highlight_key:
                lines.append(f"[bold #7aa2f7]▶ {pad}[/bold #7aa2f7]{display_val}")
            else:
                lines.append(f"  [dim]{pad}[/dim]{display_val}")
            continue
        if key == "task":
            task_str = str(raw_val) if raw_val not in (None, "") else ""
            if len(task_str) > 300:
                task_str = task_str[:300].rstrip() + "…"
            display_val = _wrap_value(task_str) if task_str else "[dim](empty)[/dim]"
        else:
            display_val = format_snapshot_value(raw_val, key=key)
        pad = label.ljust(col_w)
        if key == highlight_key:
            lines.append(f"[bold #7aa2f7]▶ {pad}[/bold #7aa2f7]{display_val}")
        else:
            lines.append(f"  [dim]{pad}[/dim]{display_val}")

    if custom_fields:
        lines.append("")
        lines.append("[bold #9ece6a]◆ CUSTOM[/bold #9ece6a]")
        for key, label in custom_fields:
            display_val = format_snapshot_value(values.get(key, ""), key=key)
            pad = label.ljust(col_w)
            if key == highlight_key:
                lines.append(f"[bold #7aa2f7]▶ {pad}[/bold #7aa2f7]{display_val}")
            else:
                lines.append(f"  [dim]{pad}[/dim]{display_val}")

    return lines


def custom_fields_from_form(fields: list[FieldMeta]) -> list[tuple[str, str]]:
    result = []
    for field in fields:
        if field.section == "custom" and field.key != "tags":
            result.append((field.key, field.label))
    return result


def custom_fields_from_history_entry(entry: dict[str, Any]) -> list[tuple[str, str]]:
    result = [(key, label) for key, label in TOP_LEVEL_CUSTOM_FIELDS if entry.get(key)]
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
