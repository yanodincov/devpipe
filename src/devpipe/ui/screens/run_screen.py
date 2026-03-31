"""Run screen: timeline + logs + run metadata.

Compatible with Textual 8.x — uses render() and RichLog.
"""
from __future__ import annotations

import json
from time import monotonic
from typing import Any

from rich.text import Text

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import RichLog, Static

from devpipe.ui.state import StageAttempt, UIState
from devpipe.ui.widgets.status_bar import RunStatusBar

_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


def _humanize_key(key: str) -> str:
    return key.replace("_", " ").strip().title()


def _unwrap_collection_wrapper(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"items"} and isinstance(value.get("items"), list):
        return value["items"]
    return value


def _is_empty_value(value: Any) -> bool:
    return value == [] or value == {} or value == ""


def _append_styled_value(text: Text, value: Any, style: str = "white") -> None:
    if value == "":
        text.append("(empty)", style=style)
        return
    if isinstance(value, bool):
        text.append("true" if value else "false", style=style)
    elif value is None:
        text.append("null", style=style)
    else:
        text.append(str(value), style=style)


def _format_duration(seconds: float) -> str:
    if seconds < 10:
        short = f"{max(0.0, seconds):.1f}".rstrip("0").rstrip(".")
        return f"{short}s"
    total_seconds = max(0, int(seconds))
    minutes, secs = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _render_data_lines(value: Any, indent: int = 0) -> list[str]:
    value = _unwrap_collection_wrapper(value)
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, nested in value.items():
            label = _humanize_key(key)
            nested = _unwrap_collection_wrapper(nested)
            if _is_empty_value(nested):
                lines.append(f"{prefix}{label}: (empty)")
                continue
            if isinstance(nested, (dict, list)):
                lines.append(f"{prefix}{label}")
                lines.extend(_render_data_lines(nested, indent + 2))
            else:
                lines.append(f"{prefix}{label}: {nested}")
        return lines or [f"{prefix}(empty)"]
    if isinstance(value, list):
        bullet = "•" if indent <= 4 else "-"
        return [f"{prefix}{bullet} {item}" for item in value] or [f"{prefix}(empty)"]
    return [f"{prefix}{value}"]


def _format_log_chunk(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    if stripped.startswith("⟫ "):
        return text.rstrip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return text
    return "\n".join(_render_data_lines(parsed))


def _render_data_text(value: Any, indent: int = 0) -> Text:
    value = _unwrap_collection_wrapper(value)
    text = Text()
    prefix = " " * indent
    if isinstance(value, dict):
        items = list(value.items())
        if not items:
            text.append(f"{prefix}(empty)", style="dim")
            return text
        for index, (key, nested) in enumerate(items):
            if index:
                text.append("\n")
            text.append(prefix)
            text.append(_humanize_key(key), style="dim")
            nested = _unwrap_collection_wrapper(nested)
            if _is_empty_value(nested):
                text.append(": ", style="dim")
                text.append("(empty)", style="dim")
                continue
            if isinstance(nested, (dict, list)):
                text.append("\n")
                text.append(_render_data_text(nested, indent + 2))
            else:
                text.append(": ", style="dim")
                _append_styled_value(text, nested)
        return text
    if isinstance(value, list):
        if not value:
            text.append(f"{prefix}(empty)", style="dim")
            return text
        for index, item in enumerate(value):
            if index:
                text.append("\n")
            text.append(f"{prefix}• ", style="dim")
            if isinstance(item, (dict, list)):
                nested = _render_data_text(item, indent + 2)
                if nested.plain.startswith(" " * (indent + 2)):
                    nested = Text(nested.plain[indent + 2 :], style=nested.style)
                text.append(nested)
            else:
                _append_styled_value(text, item)
        return text
    text.append(prefix)
    _append_styled_value(text, value)
    return text


def _format_log_renderable(text: str) -> str | Text:
    stripped = text.strip()
    if not stripped:
        return ""
    if stripped.startswith("⟫ "):
        return text.rstrip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return text
    renderable = _render_data_text(parsed)
    renderable.append("\n")
    return renderable


def _format_final_result(output: dict[str, Any]) -> str:
    lines = ["◆ Final Output", ""]
    lines.extend(_render_data_lines(output))
    return "\n".join(lines)


def _format_pipeline_completion(run_id: str, elapsed: str, final_output: dict[str, Any] | None = None) -> str:
    lines = ["✓ Pipeline completed", f"  Run: {run_id}"]
    if elapsed:
        lines.append(f"  Duration: {elapsed}")
    if isinstance(final_output, dict) and final_output:
        lines.append("  Output captured")
    return "\n".join(lines)


class RunStageStrip(Widget):
    """Top strip with completed and active stage attempts."""

    DEFAULT_CSS = """
    RunStageStrip {
        height: 3;
        padding: 0 2;
        background: $panel;
        border-bottom: solid $primary-darken-3;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._timeline: list[StageAttempt] = []
        self._spinner_frame = _SPINNER_FRAMES[0]

    def render(self) -> Text:
        visible_attempts = [attempt for attempt in self._timeline if attempt.status != "pending"]
        if not visible_attempts and self._timeline:
            visible_attempts = [self._timeline[0]]
        if not visible_attempts:
            return Text.from_markup("[dim]No active steps yet[/dim]")

        cards = []
        for attempt in visible_attempts:
            icon, style = self._icon_and_style(attempt)
            label = attempt.stage if attempt.attempt_number == 1 else f"{attempt.stage} #{attempt.attempt_number}"
            cards.append((f"{icon} {label}", _format_duration(attempt.elapsed_seconds), style, attempt.status))

        width = max(16, min(26, max(len(title) for title, _, _, _ in cards) + 6))
        line = Text()
        for index, (title, duration, style, status) in enumerate(cards):
            if index:
                line.append("  ", style="dim")
            line.append(title[:width], style=style)
            line.append(" ", style="dim")
            duration_style = "bold #7aa2f7" if status == "active" else "dim"
            line.append(duration, style=duration_style)
        return line

    def _icon_and_style(self, attempt: StageAttempt) -> tuple[str, str]:
        if attempt.status == "done":
            return "✓", "bold #9ece6a"
        if attempt.status == "failed":
            return "✗", "bold #f7768e"
        return self._spinner_frame, "bold #7dcfff"

    def set_timeline(self, timeline: list[StageAttempt]) -> None:
        self._timeline = timeline
        self.refresh()

    def set_spinner_frame(self, frame: str) -> None:
        self._spinner_frame = frame
        self.refresh()


class RunQuestionPanel(Widget):
    """Reserved area for questions and answer options."""

    DEFAULT_CSS = """
    RunQuestionPanel {
        width: 28;
        min-width: 24;
        background: $surface;
        border-right: solid $primary-darken-3;
        padding: 0;
    }
    RunQuestionPanel .question-title {
        height: 1;
        padding: 0 2;
        color: $text-muted;
        background: $surface;
    }
    RunQuestionPanel .question-body {
        padding: 1 2;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._body_markup = ""
        self.set_mode("idle")

    def compose(self) -> ComposeResult:
        yield Static("Question", classes="question-title")
        yield Static(self._body_markup, classes="question-body", id="question-body")

    def set_mode(self, mode: str) -> None:
        if mode == "confirm_cancel":
            self._body_markup = (
                "[dim]Stop pipeline and return to config?[/dim]\n\n"
                "[dim]Press Y to confirm or N to stay here.[/dim]"
            )
        elif mode == "cancelling":
            self._body_markup = "[dim]Cancelling pipeline...[/dim]"
        else:
            self._body_markup = (
                "[dim]No active question yet[/dim]\n\n"
                "[dim]Options will appear here when a stage asks for input.[/dim]"
            )
        try:
            self.query_one("#question-body", Static).update(Text.from_markup(self._body_markup))
        except Exception:
            pass


class RunLogOutput(RichLog):
    """RichLog that disables follow-tail while the operator scrolls away."""

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        self.parent.pause_follow()  # type: ignore[union-attr]
        super()._on_mouse_scroll_up(event)

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        super()._on_mouse_scroll_down(event)
        if self.is_vertical_scroll_end:
            self.parent.resume_follow()  # type: ignore[union-attr]
        else:
            self.parent.pause_follow()  # type: ignore[union-attr]


class LogPanel(Widget, can_focus=True):
    """Log viewer using RichLog."""

    DEFAULT_CSS = """
    LogPanel {
        width: 1fr;
        background: $panel;
        padding: 0;
    }
    LogPanel .log-title {
        height: 1;
        padding: 0 2;
        color: $text-muted;
        background: $surface;
    }
    LogPanel RichLog {
        height: 1fr;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._follow_tail: bool = True

    def compose(self) -> ComposeResult:
        yield Static("Output", classes="log-title")
        yield RunLogOutput(highlight=True, markup=False, wrap=True, id="log-output")

    def append(self, text: str) -> None:
        try:
            log = self.query_one("#log-output", RichLog)
            payload = _format_log_renderable(text)
            if isinstance(payload, str):
                if payload and not payload.endswith("\n"):
                    payload += "\n"
                log.write(payload, scroll_end=self._follow_tail, animate=False)
            elif payload:
                log.write(payload, scroll_end=self._follow_tail, animate=False)
        except Exception:
            pass

    def clear(self) -> None:
        try:
            log = self.query_one("#log-output", RichLog)
            log.clear()
        except Exception:
            pass

    def toggle_follow(self) -> None:
        self._follow_tail = not self._follow_tail

    def pause_follow(self) -> None:
        self._follow_tail = False

    def resume_follow(self) -> None:
        self._follow_tail = True

    def scroll_up(self) -> None:
        self.pause_follow()
        log = self.query_one("#log-output", RichLog)
        log.scroll_up(animate=False, immediate=True)

    def scroll_down(self) -> None:
        log = self.query_one("#log-output", RichLog)
        log.scroll_down(animate=False, immediate=True)
        if log.is_vertical_scroll_end:
            self.resume_follow()
        else:
            self.pause_follow()


class RunScreen(Screen):
    """Pipeline execution screen with timeline and logs."""

    BINDINGS = [
        Binding("up", "nav_up", "Up", show=False),
        Binding("down", "nav_down", "Down", show=False),
        Binding("escape", "back", "Back", show=True),
        Binding("y", "confirm_cancel", "Confirm Cancel", show=False),
        Binding("n", "dismiss_cancel", "Dismiss Cancel", show=False),
        Binding("f", "toggle_follow", "Follow Tail", show=True),
    ]

    DEFAULT_CSS = """
    RunScreen {
        layout: vertical;
    }
    RunScreen .run-body {
        height: 1fr;
    }
    RunScreen .run-main {
        height: 1fr;
    }
    """

    def __init__(self, ui_state: UIState, **kwargs) -> None:
        super().__init__(**kwargs)
        self._state = ui_state
        self._run_started_at: float | None = None
        self._active_stage_started_at: float | None = None
        self._spinner_index = 0
        self._confirm_cancel = False
        self._cancelling = False
        self._last_stage_output: dict[str, Any] | None = None

    def compose(self) -> ComposeResult:
        yield RunStageStrip(id="run-stage-strip")
        with Horizontal(classes="run-body"):
            yield RunQuestionPanel(id="run-question-panel")
            yield LogPanel(id="log-panel")
        yield RunStatusBar(id="run-status")

    def on_mount(self) -> None:
        if self._state.run_view.status == "running":
            self._run_started_at = monotonic()
        self.set_interval(0.2, self._tick_run_clock)
        self._update_run_display()

    def _update_run_display(self) -> None:
        rv = self._state.run_view
        stage_strip = self.query_one("#run-stage-strip", RunStageStrip)
        stage_strip.set_timeline(rv.timeline)
        stage_strip.set_spinner_frame(_SPINNER_FRAMES[self._spinner_index % len(_SPINNER_FRAMES)])
        question = self.query_one("#run-question-panel", RunQuestionPanel)
        question.set_mode("idle")

        status = self.query_one("#run-status", RunStatusBar)
        status.update_run_state(
            status=rv.status,
            elapsed=_format_duration(rv.elapsed_seconds),
            model=rv.model_name,
            effort=rv.effort,
        )
        if self._cancelling:
            status.show_alert("Cancelling pipeline...")
        elif self._confirm_cancel:
            status.show_alert("Stop pipeline? Y — confirm  N — stay")
        else:
            status.clear_alert()

    def _tick_run_clock(self) -> None:
        if self._state.run_view.status != "running":
            return
        now = monotonic()
        if self._run_started_at is not None:
            self._state.run_view.elapsed_seconds = now - self._run_started_at
        if self._active_stage_started_at is not None:
            for attempt in self._state.run_view.timeline:
                if attempt.status == "active":
                    attempt.elapsed_seconds = now - self._active_stage_started_at
                    break
        self._spinner_index += 1
        self._update_run_display()

    # ── Run event handlers (called from app) ──────────────────────────────

    def on_stage_started(self, stage: str, runner: str, model: str, effort: str) -> None:
        if any(attempt.stage == stage and attempt.status == "active" for attempt in self._state.run_view.timeline):
            now = monotonic()
            if self._run_started_at is None:
                self._run_started_at = now
            if self._active_stage_started_at is None or self._state.run_view.active_stage != stage:
                self._active_stage_started_at = now
            self._state.run_view.active_stage = stage
            self._state.run_view.runner_name = runner
            self._state.run_view.model_name = model
            self._state.run_view.effort = effort
            self._update_run_display()
            return

        now = monotonic()
        if self._run_started_at is None:
            self._run_started_at = now
        self._active_stage_started_at = now
        self._state.run_view.active_stage = stage
        self._state.run_view.runner_name = runner
        self._state.run_view.model_name = model
        self._state.run_view.effort = effort

        self._update_run_display()
        log_panel = self.query_one("#log-panel", LogPanel)
        log_panel.append(f"\n▶ Started: {stage}\n\n")

    def on_stage_completed(
        self,
        stage: str,
        summary: str = "",
        structured_output: dict[str, Any] | None = None,
    ) -> None:
        now = monotonic()
        matched_attempt: StageAttempt | Any | None = None
        for attempt in self._state.run_view.timeline:
            if attempt.stage == stage and attempt.status == "active":
                matched_attempt = attempt
                break
        if matched_attempt is None:
            for attempt in reversed(self._state.run_view.timeline):
                if attempt.stage == stage:
                    matched_attempt = attempt
                    break
        if matched_attempt is not None:
            matched_attempt.status = "done"
            matched_attempt.summary = summary
            if self._active_stage_started_at is not None:
                matched_attempt.elapsed_seconds = now - self._active_stage_started_at
        self._active_stage_started_at = None
        if structured_output:
            self._last_stage_output = structured_output
        self._update_run_display()
        log_panel = self.query_one("#log-panel", LogPanel)
        log_panel.append(f"\n✓ Completed: {stage}\n\n")

    def on_stage_failed(self, stage: str, error: str = "") -> None:
        now = monotonic()
        for attempt in self._state.run_view.timeline:
            if attempt.stage == stage and attempt.status == "active":
                attempt.status = "failed"
                attempt.error = error
                if self._active_stage_started_at is not None:
                    attempt.elapsed_seconds = now - self._active_stage_started_at
                break
        self._active_stage_started_at = None
        self._update_run_display()
        log_panel = self.query_one("#log-panel", LogPanel)
        log_panel.append(f"\n✗ Failed: {stage}\n{error}\n\n" if error else f"\n✗ Failed: {stage}\n\n")

    def on_output(self, text: str) -> None:
        log_panel = self.query_one("#log-panel", LogPanel)
        log_panel.append(text)

    def on_run_finished(self, status: str, run_id: str) -> None:
        now = monotonic()
        self._confirm_cancel = False
        self._cancelling = False
        self._state.run_view.status = status
        self._state.run_view.run_id = run_id
        if self._run_started_at is not None:
            self._state.run_view.elapsed_seconds = now - self._run_started_at
        self._active_stage_started_at = None
        self._update_run_display()
        log_panel = self.query_one("#log-panel", LogPanel)
        if status == "completed":
            if self._last_stage_output:
                log_panel.append("\n" + _format_final_result(self._last_stage_output) + "\n\n")
            log_panel.append(
                "\n"
                + _format_pipeline_completion(
                    run_id=run_id,
                    elapsed=_format_duration(self._state.run_view.elapsed_seconds),
                    final_output=self._last_stage_output,
                )
                + "\n\n"
            )
        elif status == "cancelled":
            log_panel.append(f"\n■ Pipeline cancelled  {run_id}\n\n")
        else:
            log_panel.append(f"\n✗ Pipeline failed  {run_id}\n\n")

    # ── Navigation ────────────────────────────────────────────────────────

    def action_nav_up(self) -> None:
        log_panel = self.query_one("#log-panel", LogPanel)
        log_panel.scroll_up()

    def action_nav_down(self) -> None:
        log_panel = self.query_one("#log-panel", LogPanel)
        log_panel.scroll_down()

    def action_back(self) -> None:
        if self._state.run_view.status == "running":
            if self._cancelling:
                return
            self._confirm_cancel = not self._confirm_cancel
            self._update_run_display()
            return
        self.app.pop_screen()

    def action_confirm_cancel(self) -> None:
        if not self._confirm_cancel or self._cancelling:
            return
        self._confirm_cancel = False
        self._cancelling = True
        self._update_run_display()
        self._begin_cancel_return()

    def action_dismiss_cancel(self) -> None:
        if not self._confirm_cancel or self._cancelling:
            return
        self._confirm_cancel = False
        self._update_run_display()

    def action_toggle_follow(self) -> None:
        log_panel = self.query_one("#log-panel", LogPanel)
        log_panel.toggle_follow()

    def _finish_cancel_return(self) -> None:
        self._confirm_cancel = False
        self._cancelling = False
        self.app.pop_screen()

    def _begin_cancel_return(self) -> None:
        self.app.cancel_active_run_async(self._finish_cancel_return)
