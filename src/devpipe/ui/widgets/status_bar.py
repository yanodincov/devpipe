"""Bottom status bar widgets.

Uses render() for Textual 8.x compatibility.
"""
from __future__ import annotations

from rich.text import Text

from textual.widget import Widget

from devpipe.ui.state import StatusBarState


class StatusBar(Widget):
    """Bottom status bar: shortcuts, help, readiness."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        dock: bottom;
        background: $primary-darken-3;
        color: $text;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._left = ""
        self._center = ""
        self._right = ""
        self._is_ready = False
        self._is_error = False

    def render(self) -> Text:
        text = Text()
        text.append(f" {self._left}", style="dim")
        if self._center:
            text.append("    ")
            text.append(self._center, style="dim")
        if self._right:
            text.append("    ")
            if self._is_error:
                text.append(self._right, style="bold #f7768e")
            else:
                style = "bold #9ece6a" if self._is_ready else "bold #e0af68"
                text.append(self._right, style=style)
        return text

    def update_state(self, state: StatusBarState) -> None:
        """Update the status bar from state."""
        self._left = state.left_text
        self._center = state.center_text
        self._right = state.right_text
        self._is_ready = state.is_ready
        self._is_error = state.right_text == "ERROR"
        self.refresh()


class RunStatusBar(Widget):
    """Bottom status bar for run mode."""

    DEFAULT_CSS = """
    RunStatusBar {
        height: 1;
        dock: bottom;
        background: $primary-darken-3;
        color: $text;
    }
    RunStatusBar.-alert {
        background: $error;
        color: $text;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._status = ""
        self._runner = ""
        self._model = ""
        self._effort = ""
        self._elapsed = ""
        self._alert_message = ""
        self._alert_active = False

    def render(self) -> Text:
        if self._alert_active:
            return Text(f" {self._alert_message}", style="bold")

        text = Text()
        text.append(" esc back", style="dim")
        text.append("  f follow", style="dim")
        text.append("    ")
        if self._runner:
            text.append("runner ", style="dim")
            text.append(self._runner, style="white")
            text.append("  ")
        if self._model:
            text.append("model ", style="dim")
            text.append(self._model, style="white")
            text.append("  ")
        if self._effort:
            text.append("effort ", style="dim")
            text.append(self._effort, style="white")
            text.append("  ")
        if self._status:
            status = self._status
            if status == "running":
                text.append(f"running", style="bold #7aa2f7")
            elif status == "completed":
                text.append("completed", style="bold #9ece6a")
            elif status in ("failed", "cancelled"):
                text.append(status, style="bold #f7768e")
            else:
                text.append(status, style="dim")
            if self._elapsed:
                text.append(f"  {self._elapsed}", style="dim")
        return text

    def update_run_state(
        self,
        status: str = "",
        elapsed: str = "",
        runner: str = "",
        model: str = "",
        effort: str = "",
    ) -> None:
        self._status = status
        self._elapsed = elapsed
        self._runner = runner
        self._model = model
        self._effort = effort
        self.refresh()

    def show_alert(self, message: str) -> None:
        self._alert_message = message
        self._alert_active = True
        self.add_class("-alert")
        self.refresh()

    def clear_alert(self) -> None:
        self._alert_message = ""
        self._alert_active = False
        self.remove_class("-alert")
        self.refresh()
