"""History screen: list of past runs with preview and restore.

Compatible with Textual 8.x.
"""
from __future__ import annotations

from pathlib import Path
from rich.text import Text

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.screen import Screen
from textual.widget import Widget

from devpipe.history import load_run_history, RunHistoryEntry
from devpipe.ui.state import UIState
from devpipe.ui.widgets.history_preview import HistoryPreview
from devpipe.ui.widgets.task_snapshot import compact_history_title


class HistoryList(Widget, can_focus=True):
    """Vertical list of history entries."""

    DEFAULT_CSS = """
    HistoryList {
        width: 1fr;
        min-width: 28;
        max-width: 40;
        background: $surface;
        border-right: solid $primary-darken-3;
        padding: 1 0;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._entries: list[RunHistoryEntry] = []
        self._selected: int = 0

    def render(self) -> Text:
        text = Text()
        text.append("╸ History\n\n", style="bold dim")
        available_width = max(12, (self.size.width or 28) - 2)
        for i, entry in enumerate(self._entries):
            task = compact_history_title(entry.config.get("task", "") or "", max_len=available_width)
            if i == self._selected:
                text.append(f"» {task}\n", style="bold cyan")
            else:
                text.append(f"{task}\n", style="dim")
        if not self._entries:
            text.append("No history entries\n", style="dim")
        return text

    def set_entries(self, entries: list[RunHistoryEntry]) -> None:
        self._entries = entries
        self._selected = 0
        self.refresh()

    def move_up(self) -> None:
        if self._selected > 0:
            self._selected -= 1
            self.refresh()

    def move_down(self) -> None:
        if self._selected < len(self._entries) - 1:
            self._selected += 1
            self.refresh()

    @property
    def current_entry(self) -> RunHistoryEntry | None:
        if self._entries and 0 <= self._selected < len(self._entries):
            return self._entries[self._selected]
        return None


class HistoryStatusBar(Widget):
    """Status bar for history screen."""

    DEFAULT_CSS = """
    HistoryStatusBar {
        height: 1;
        dock: bottom;
        background: $primary-darken-3;
        color: $text;
    }
    """

    def render(self) -> Text:
        return Text.from_markup(" [dim]Enter — restore  ·  Esc — back[/dim]")


class HistoryScreen(Screen):
    """Screen showing history entries with preview and restore."""

    BINDINGS = [
        Binding("up", "nav_up", "Up", show=False),
        Binding("down", "nav_down", "Down", show=False),
        Binding("enter", "restore", "Restore", show=True),
        Binding("escape", "back", "Back", show=True),
    ]

    DEFAULT_CSS = """
    HistoryScreen {
        layout: vertical;
    }
    HistoryScreen .history-main {
        height: 1fr;
    }
    """

    class RestoreEntry(Message):
        """Request to restore a history entry into form."""
        def __init__(self, entry: RunHistoryEntry) -> None:
            super().__init__()
            self.entry = entry

    def __init__(self, ui_state: UIState, project_root: Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._state = ui_state
        self.project_root = project_root or Path.cwd()

    def compose(self) -> ComposeResult:
        with Horizontal(classes="history-main"):
            yield HistoryList(id="history-list")
            yield HistoryPreview(id="history-preview")
        yield HistoryStatusBar()

    def on_mount(self) -> None:
        history_runs_dir = self.project_root / ".devpipe" / "runs"
        entries = load_run_history(history_runs_dir)[:20]
        hist_list = self.query_one("#history-list", HistoryList)
        hist_list.set_entries(entries)
        if entries:
            preview = self.query_one("#history-preview", HistoryPreview)
            preview.show_entry(entries[0])

    def action_nav_up(self) -> None:
        hist_list = self.query_one("#history-list", HistoryList)
        hist_list.move_up()
        self._show_preview()

    def action_nav_down(self) -> None:
        hist_list = self.query_one("#history-list", HistoryList)
        hist_list.move_down()
        self._show_preview()

    def _show_preview(self) -> None:
        hist_list = self.query_one("#history-list", HistoryList)
        entry = hist_list.current_entry
        if entry:
            preview = self.query_one("#history-preview", HistoryPreview)
            preview.show_entry(entry)

    def action_restore(self) -> None:
        hist_list = self.query_one("#history-list", HistoryList)
        entry = hist_list.current_entry
        if entry:
            self.post_message(self.RestoreEntry(entry))
            self.app.pop_screen()

    def action_back(self) -> None:
        self.app.pop_screen()
