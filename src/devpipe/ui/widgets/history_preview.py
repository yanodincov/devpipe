"""History entry preview widget.

Uses render() for Textual 8.x compatibility.
"""
from __future__ import annotations

from devpipe.history import RunHistoryEntry
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

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._markup: str = "[dim]Select an entry[/dim]"

    def render(self) -> Text:
        return Text.from_markup(self._markup)

    def show_entry(self, entry: RunHistoryEntry) -> None:
        """Render a history entry preview."""
        cfg = entry.config
        lines = [f"[bold cyan]╸ {entry.profile}[/bold cyan]\n"]
        lines.append(f"Task: {cfg.get('task', '') or '(no description)'}")
        lines.append(f"Task ID: {cfg.get('task_id', '')}")
        lines.append(f"Runner: {cfg.get('runner', 'auto')}  Model: {cfg.get('model', 'auto')}  Effort: {cfg.get('effort', 'auto')}")
        tags = cfg.get("tags", [])
        if tags:
            lines.append(f"Tags: {', '.join(tags)}")
        lines.append("")
        lines.append("[dim]── Stages ──[/dim]")
        for stage in entry.stages:
            icon = "✓" if stage.status == "completed" else "✗" if stage.status == "failed" else "⏸"
            lines.append(f"{icon} {stage.name}: {stage.status}")
            if stage.output:
                # Show a brief glimpse of output keys
                keys = list(stage.output.keys())
                if keys:
                    lines.append(f"   outputs: {', '.join(keys)}")
        lines.append("")
        lines.append(f"[dim]Started: {entry.timestamp.strftime('%Y-%m-%d %H:%M:%S')}[/dim]")
        lines.append(f"[dim]Duration: {entry.summary.get('total_duration_seconds', 0):.1f}s  Status: {entry.summary.get('final_status')}[/dim]")

        self._markup = "\n".join(lines)
        self.refresh()

    def clear(self) -> None:
        self._markup = "[dim]Select an entry[/dim]"
        self.refresh()
