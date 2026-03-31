"""History entry detail widget — matches config screen detail panel style."""
from __future__ import annotations

from pathlib import Path

from devpipe.history import RunHistoryEntry
from devpipe.ui.widgets.task_snapshot import build_task_snapshot_lines, custom_fields_from_profile_history_entry
from rich.text import Text

from textual.widget import Widget


class HistoryPreview(Widget):
    """Detail panel for a history entry, styled like the config detail panel."""

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
        snapshot_values = dict(entry.config)
        extra_params = snapshot_values.get("extra_params", {})
        if isinstance(extra_params, dict):
            snapshot_values.update(extra_params)
        snapshot_values["profile"] = entry.profile

        lines = build_task_snapshot_lines(
            snapshot_values,
            custom_fields_from_profile_history_entry(entry.profile, entry.config, self._project_root),
        )

        # Run metadata
        lines.append("")
        lines.append("[bold #e0af68]◆ RUN INFO[/bold #e0af68]")
        lines.append("")

        ts = entry.timestamp.strftime("%Y-%m-%d  %H:%M:%S")
        lines.append(f"  [dim]{'Started'.ljust(12)}[/dim]{ts}")

        duration_s = entry.summary.get("total_duration_seconds", 0)
        if isinstance(duration_s, (int, float)) and duration_s >= 60:
            dur = f"{int(duration_s // 60)}m {int(duration_s % 60):02d}s"
        else:
            dur = f"{duration_s:.0f}s"
        lines.append(f"  [dim]{'Duration'.ljust(12)}[/dim]{dur}")

        stages_total = entry.summary.get("stages_completed", 0) + entry.summary.get("stages_failed", 0)
        status = entry.summary.get("final_status", "")
        status_color = {"completed": "#9ece6a", "failed": "#f7768e", "cancelled": "#e0af68"}.get(status, "dim")
        status_str = f"[{status_color}]{status}[/{status_color}]"
        if stages_total:
            status_str += f"  [dim]({stages_total} stages)[/dim]"
        lines.append(f"  [dim]{'Status'.ljust(12)}[/dim]{status_str}")

        total_tokens = entry.summary.get("total_tokens", 0)
        if total_tokens:
            lines.append(f"  [dim]{'Tokens'.ljust(12)}[/dim]~{total_tokens:,}")

        self._markup = "\n".join(lines)
        self.refresh()

    def clear(self) -> None:
        self._markup = "[dim]Select an entry[/dim]"
        self.refresh()
