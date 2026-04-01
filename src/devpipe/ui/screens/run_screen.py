"""Run screen: timeline + logs + run metadata.

Compatible with Textual 8.x — uses render() and RichLog.
"""
from __future__ import annotations

import json
from time import monotonic
from typing import Any

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.events import Resize
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Static

from devpipe.ui.state import StageAttempt, UIState
from devpipe.ui.widgets.status_bar import RunStatusBar

_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_COLLAPSE_LIMIT = 300
_MESSAGE_TEXT_STYLE = "#f0ede6"


def _humanize_key(key: str) -> str:
    return key.replace("_", " ").strip().title()


def _unwrap_collection_wrapper(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"items"} and isinstance(value.get("items"), list):
        return value["items"]
    return value


def _is_empty_value(value: Any) -> bool:
    return value == [] or value == {} or value == ""


def _append_styled_value(text: Text, value: Any, style: str = _MESSAGE_TEXT_STYLE) -> None:
    if value == "":
        text.append("(empty)", style=style)
        return
    if isinstance(value, bool):
        text.append("true" if value else "false", style=style)
    elif value is None:
        text.append("null", style=style)
    else:
        text.append(str(value), style=style)


def _display_value(value: Any) -> str:
    if value == "":
        return "(empty)"
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return str(value)


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
                continue
            if isinstance(nested, (dict, list)):
                lines.append(f"{prefix}{label}")
                lines.extend(_render_data_lines(nested, indent + 2))
            else:
                lines.append(f"{prefix}{label}: {_display_value(nested)}")
        return lines or [f"{prefix}(empty)"]
    if isinstance(value, list):
        bullet = "•" if indent <= 4 else "-"
        return [f"{prefix}{bullet} {_display_value(item)}" for item in value] or [f"{prefix}(empty)"]
    return [f"{prefix}{_display_value(value)}"]


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
    return _render_block_lines(parsed)


def _message_kind(value: Any) -> tuple[str, Any, dict[str, Any]]:
    if isinstance(value, dict):
        if "final_output" in value:
            primary = value.get("final_output")
            rest = {k: v for k, v in value.items() if k != "final_output"}
            return "final output", primary, rest
        if "status" in value and isinstance(value.get("status"), str):
            rest = {k: v for k, v in value.items() if k != "status"}
            return str(value.get("status") or "status"), None, rest
        for key in ("thinking", "action", "output", "prompt"):
            if key in value:
                primary = value.get(key)
                rest = {k: v for k, v in value.items() if k != key}
                return key, primary, rest
        return "output", None, value
    return "note", value, {}


def _render_block_lines(value: Any) -> str:
    kind, primary, rest = _message_kind(value)
    lines = [f"› {kind}"]
    if primary not in (None, "", [], {}):
        lines.extend(_render_data_lines(primary, indent=2))
    if rest:
        lines.extend(_render_data_lines(rest, indent=2))
    return "\n".join(lines)


def _render_data_text(value: Any, indent: int = 0) -> Text:
    value = _unwrap_collection_wrapper(value)
    text = Text(style=_MESSAGE_TEXT_STYLE)
    prefix = " " * indent
    if isinstance(value, dict):
        items = list(value.items())
        if not items:
            text.append(f"{prefix}(empty)", style="dim")
            return text
        first = True
        for key, nested in items:
            nested = _unwrap_collection_wrapper(nested)
            if _is_empty_value(nested):
                continue
            if not first:
                text.append("\n")
            first = False
            text.append(prefix)
            text.append(_humanize_key(key), style="dim")
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


def _render_block_text(value: Any) -> Text:
    kind, primary, rest = _message_kind(value)
    text = Text(style=_MESSAGE_TEXT_STYLE)
    if kind == "prompt" and isinstance(primary, str):
        prompt_text = primary
        if prompt_text.startswith("Role: "):
            prompt_text = "Agent: " + prompt_text[len("Role: ") :]
        text.append(prompt_text)
    elif primary not in (None, "", [], {}):
        text.append(_render_data_text(primary, indent=2))
    if rest:
        if primary not in (None, "", [], {}):
            text.append("\n")
        text.append(_render_data_text(rest, indent=2))
    return text


def _render_message_panel(value: Any) -> Panel:
    kind, _, _ = _message_kind(value)
    title = Text(kind, style="#6b7280")
    body = _render_block_text(value)
    return Panel(
        body,
        title=title,
        title_align="left",
        border_style="#2a2e39",
        box=box.ROUNDED,
        padding=0,
        expand=True,
    )


def _render_collapsed_message_panel(value: Any, limit: int = _COLLAPSE_LIMIT) -> Panel:
    kind, _, _ = _message_kind(value)
    title = Text(kind, style="#6b7280")
    plain = _render_block_text(value).plain
    collapsed = plain[:limit].rstrip()
    if len(plain) > limit:
        collapsed += f" {len(plain) - len(collapsed)} symbols more ..."
    return Panel(
        Text(collapsed, style=_MESSAGE_TEXT_STYLE),
        title=title,
        title_align="left",
        subtitle=Text("[click to expand]", style="dim"),
        subtitle_align="center",
        border_style="#2a2e39",
        box=box.ROUNDED,
        padding=0,
        expand=True,
    )


def _format_log_renderable(text: str) -> str | Panel:
    parsed = _parse_log_value(text)
    if isinstance(parsed, str):
        return parsed
    return _render_message_panel(parsed)


def _parse_log_value(text: str) -> str | dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        return ""
    if stripped.startswith("⟫ "):
        return {"action": stripped[2:].strip()}
    if stripped.startswith("▶ Started:"):
        return {"status": "started", "stage": stripped.split(":", 1)[1].strip()}
    if stripped.startswith("✓ Completed:"):
        return {"status": "completed", "stage": stripped.split(":", 1)[1].strip()}
    if stripped.startswith("✗ Failed:"):
        parts = stripped.split("\n", 1)
        payload: dict[str, Any] = {"status": "failed", "stage": parts[0].split(":", 1)[1].strip()}
        if len(parts) > 1 and parts[1].strip():
            payload["error"] = parts[1].strip()
        return payload
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return {"note": stripped}
    return parsed


def _format_final_result(output: dict[str, Any]) -> str:
    return json.dumps({"final_output": output}, ensure_ascii=False)


def _format_pipeline_completion(run_id: str, elapsed: str, final_output: dict[str, Any] | None = None, total_tokens: int = 0) -> str:
    payload: dict[str, Any] = {"status": "completed", "run": run_id}
    if elapsed:
        payload["duration"] = elapsed
    if total_tokens > 0:
        payload["tokens"] = f"~{total_tokens}"
    if isinstance(final_output, dict) and final_output:
        payload["output_captured"] = True
    return json.dumps(payload, ensure_ascii=False)


class RunStagePanel(Widget):
    """Left panel with vertical list of stage attempts."""

    DEFAULT_CSS = """
    RunStagePanel {
        width: 20;
        min-width: 16;
        background: #1e1e1e;
        border-right: solid $primary-darken-3;
        padding: 1 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._timeline: list[StageAttempt] = []
        self._spinner_frame = _SPINNER_FRAMES[0]

    def on_mount(self) -> None:
        self.styles.background = "#1e1e1e"

    def render(self) -> Text:
        text = Text()
        text.append("◆ STAGES\n\n", style="bold #7aa2f7")

        if not self._timeline:
            text.append("  No active steps yet\n", style="dim")
            return text

        for attempt in self._timeline:
            label = attempt.stage if attempt.attempt_number == 1 else f"{attempt.stage} #{attempt.attempt_number}"

            if attempt.status == "active":
                text.append("▶ ", style="bold #7aa2f7")
                text.append(f"{label}", style="bold #7aa2f7")
                if attempt.elapsed_seconds > 0:
                    text.append(f"  {_format_duration(attempt.elapsed_seconds)}", style="bold #7aa2f7")
                text.append("\n")
            elif attempt.status == "done":
                text.append("· ", style="dim")
                text.append(f"{label}", style="dim")
                if attempt.elapsed_seconds > 0:
                    text.append(f"  {_format_duration(attempt.elapsed_seconds)}", style="dim")
                if attempt.tokens > 0:
                    text.append(f"  ~{attempt.tokens}t", style="dim #484f58")
                text.append("\n")
            elif attempt.status == "failed":
                text.append("✗ ", style="bold #f7768e")
                text.append(f"{label}", style="#f7768e")
                if attempt.elapsed_seconds > 0:
                    text.append(f"  {_format_duration(attempt.elapsed_seconds)}", style="dim")
                text.append("\n")
            else:
                text.append(f"  {label}\n", style="dim #484f58")

        return text

    def _icon_and_styles(self, attempt: StageAttempt) -> tuple[str, str, str]:
        if attempt.status == "done":
            return "·", "dim", "dim"
        if attempt.status == "failed":
            return "✗", "#f7768e", "dim"
        if attempt.status == "active":
            return self._spinner_frame, "bold #7aa2f7", "bold #7aa2f7"
        return " ", "dim #484f58", "dim"

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
        background: $panel;
        border-right: solid $primary-darken-3;
        padding: 1 1 0 1;
    }
    RunQuestionPanel .question-title {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        background: #161922;
        border: round #2a2e39;
        content-align: left middle;
    }
    RunQuestionPanel .question-body {
        margin-top: 1;
        padding: 1 2;
        border: round #2a2e39;
        background: #12141b;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._body_markup = ""
        self.set_mode("idle")

    def compose(self) -> ComposeResult:
        yield Static("Questions", classes="question-title")
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


class LogEntry(Widget, can_focus=False):
    """Single clickable log entry that can collapse and expand."""

    DEFAULT_CSS = """
    LogEntry {
        width: 1fr;
        height: auto;
        margin-bottom: 1;
    }
    """

    def __init__(
        self,
        text: str,
        entry_id: int,
        expanded: bool = False,
        on_toggle: callable | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._text = text
        self._entry_id = entry_id
        self._expanded = expanded
        self._on_toggle = on_toggle
        self._value = _parse_log_value(text)
        self._plain = _render_block_text(self._value).plain

    @property
    def is_collapsible(self) -> bool:
        return len(self._plain) > _COLLAPSE_LIMIT

    def render(self) -> Panel:
        if self.is_collapsible and not self._expanded:
            return _render_collapsed_message_panel(self._value)
        panel = _render_message_panel(self._value)
        if self.is_collapsible:
            return Panel(
                Text(panel.renderable.plain, style=_MESSAGE_TEXT_STYLE),
                title=panel.title,
                title_align=panel.title_align,
                subtitle=Text("[click to collapse]", style="dim"),
                subtitle_align="center",
                border_style=panel.border_style,
                box=panel.box,
                padding=panel.padding,
                expand=True,
            )
        return panel

    def on_click(self, event: events.Click) -> None:
        if self.is_collapsible and self._on_toggle is not None:
            self._on_toggle(self._entry_id)


class LogScroll(VerticalScroll, can_focus=False):
    """Scrollable container that updates follow-tail state while scrolling."""

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        if self.parent is not None:
            self.parent.pause_follow()  # type: ignore[union-attr]
        super().on_mouse_scroll_up(event)

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        super().on_mouse_scroll_down(event)
        if self.parent is not None:
            if self.is_vertical_scroll_end:
                self.parent.resume_follow()  # type: ignore[union-attr]
            else:
                self.parent.pause_follow()  # type: ignore[union-attr]


class LogPanel(Widget, can_focus=False):
    """Log viewer using RichLog."""

    DEFAULT_CSS = """
    LogPanel {
        width: 1fr;
        background: #1e1e1e;
        padding: 0;
        min-width: 0;
    }
    LogPanel LogScroll {
        width: 1fr;
        height: 1fr;
        padding: 0;
        background: #1e1e1e;
        min-width: 0;
        scrollbar-size: 0 0;
    }
    LogPanel LogScroll:focus {
        background: #1e1e1e;
        border: none;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._follow_tail: bool = True
        self._entries: list[str] = []
        self._expanded_entries: set[int] = set()

    def compose(self) -> ComposeResult:
        yield LogScroll(id="log-output")

    def append(self, text: str) -> None:
        entry_id = len(self._entries)
        self._entries.append(text)
        try:
            container = self.query_one("#log-output", LogScroll)
            container.mount(
                LogEntry(
                    text,
                    entry_id=entry_id,
                    expanded=entry_id in self._expanded_entries,
                    on_toggle=self.toggle_entry,
                )
            )
            if self._follow_tail:
                container.scroll_end(animate=False)
        except Exception:
            pass

    def clear(self) -> None:
        try:
            container = self.query_one("#log-output", LogScroll)
            for child in list(container.children):
                child.remove()
            self._entries = []
            self._expanded_entries = set()
        except Exception:
            pass

    def on_resize(self, event: Resize) -> None:
        self._rerender_entries()

    def _rerender_entries(self) -> None:
        try:
            container = self.query_one("#log-output", LogScroll)
            for child in list(container.children):
                child.remove()
            for entry_id, entry in enumerate(self._entries):
                container.mount(
                    LogEntry(
                        entry,
                        entry_id=entry_id,
                        expanded=entry_id in self._expanded_entries,
                        on_toggle=self.toggle_entry,
                    )
                )
            if self._follow_tail:
                container.scroll_end(animate=False)
        except Exception:
            pass

    def toggle_follow(self) -> None:
        self.resume_follow()
        try:
            container = self.query_one("#log-output", LogScroll)
            container.scroll_end(animate=False)
        except Exception:
            pass

    def pause_follow(self) -> None:
        self._follow_tail = False

    def resume_follow(self) -> None:
        self._follow_tail = True

    def toggle_entry(self, entry_id: int) -> None:
        if entry_id in self._expanded_entries:
            self._expanded_entries.remove(entry_id)
        else:
            self._expanded_entries.add(entry_id)
        self._rerender_entries()

    def scroll_up(self) -> None:
        self.pause_follow()
        log = self.query_one("#log-output", LogScroll)
        log.scroll_up(animate=False, immediate=True)

    def scroll_down(self) -> None:
        log = self.query_one("#log-output", LogScroll)
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
    RunScreen .run-main {
        height: 1fr;
        width: 1fr;
        background: #1e1e1e;
    }
    RunScreen #log-output {
        background: #1e1e1e;
        tint: transparent;
        min-width: 0;
    }
    RunScreen #log-output:focus {
        background: #1e1e1e;
        background-tint: transparent 0%;
        tint: transparent;
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
        with Horizontal(classes="run-main"):
            yield RunStagePanel(id="run-stage-strip")
            yield LogPanel(id="log-panel")
        yield RunStatusBar(show_prompt=self._state.show_prompt, id="run-status")

    def on_mount(self) -> None:
        if self._state.run_view.status == "running":
            self._run_started_at = monotonic()
        self.set_interval(0.2, self._tick_run_clock)
        self._update_run_display()

    def _update_run_display(self) -> None:
        rv = self._state.run_view
        stage_strip = self.query_one("#run-stage-strip", RunStagePanel)
        stage_strip.set_timeline(rv.timeline)
        stage_strip.set_spinner_frame(_SPINNER_FRAMES[self._spinner_index % len(_SPINNER_FRAMES)])

        status = self.query_one("#run-status", RunStatusBar)
        status.update_run_state(
            status=rv.status,
            elapsed=_format_duration(rv.elapsed_seconds),
            runner=rv.runner_name,
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
                    total_tokens=self._state.run_view.total_tokens,
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
