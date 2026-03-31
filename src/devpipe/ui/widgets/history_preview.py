"""History entry preview widget.

Uses render() for Textual 8.x compatibility.
"""
from __future__ import annotations

from pathlib import Path

from devpipe.history import RunHistoryEntry
from devpipe.ui.widgets.task_snapshot import build_task_snapshot_lines, custom_fields_from_profile_history_entry
from rich.text import Text

from textual.widget import Widget


class HistoryPreview(Widget):
    """Preview panel for a history entry."""

    DEFAULT_CSS = """
    HistoryPreview {
        width: 2fr;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, project_root: Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._project_root = project_root or Path.cwd()
        self._markup: str = "[dim]Select an entry[/dim]"

    def render(self) -> Text:
        return Text.from_markup(self._markup)

    def show_entry(self, entry: RunHistoryEntry) -> None:
        """Render a history entry preview."""
        snapshot_values = dict(entry.config)
        extra_params = snapshot_values.get("extra_params", {})
        if isinstance(extra_params, dict):
            snapshot_values.update(extra_params)
        snapshot_values["profile"] = entry.profile
        lines = build_task_snapshot_lines(
            snapshot_values,
            custom_fields_from_profile_history_entry(entry.profile, entry.config, self._project_root),
        )
        lines.append("")
        lines.append(f"[dim]Started: {entry.timestamp.strftime('%Y-%m-%d %H:%M:%S')}[/dim]")
        lines.append(f"[dim]Duration: {entry.summary.get('total_duration_seconds', 0):.1f}s[/dim]")

        self._markup = "\n".join(lines)
        self.refresh()

    def clear(self) -> None:
        self._markup = "[dim]Select an entry[/dim]"
        self.refresh()
