from __future__ import annotations

from types import SimpleNamespace

from rich.panel import Panel

from devpipe.ui.screens.run_screen import LogEntry, LogPanel, RunStagePanel, _format_log_renderable


def test_log_entry_collapses_long_message_and_toggles() -> None:
    toggled: list[int] = []
    text = '{"output":"' + ("x" * 320) + '"}'
    entry = LogEntry(text, entry_id=3, expanded=False, on_toggle=toggled.append)

    rendered = entry.render()

    assert isinstance(rendered, Panel)
    assert "symbols more ..." in rendered.renderable.plain
    assert rendered.subtitle.plain == "[click to expand]"
    assert rendered.subtitle_align == "center"
    entry.on_click(SimpleNamespace())
    assert toggled == [3]


def test_log_entry_expanded_state_shows_collapse_hint() -> None:
    text = '{"output":"' + ("x" * 320) + '"}'
    entry = LogEntry(text, entry_id=1, expanded=True, on_toggle=lambda _id: None)

    rendered = entry.render()

    assert rendered.subtitle.plain == "[click to collapse]"
    assert rendered.subtitle_align == "center"


def test_log_panel_toggle_follow_scrolls_to_bottom() -> None:
    panel = LogPanel()
    calls: list[str] = []
    fake_container = SimpleNamespace(scroll_end=lambda animate=False: calls.append(f"end:{animate}"))
    panel.query_one = lambda *_args, **_kwargs: fake_container  # type: ignore[method-assign]

    panel.pause_follow()
    panel.toggle_follow()

    assert panel._follow_tail is True
    assert calls == ["end:False"]


def test_run_stage_panel_has_smaller_min_width() -> None:
    css = RunStagePanel.DEFAULT_CSS

    assert "min-width: 16;" in css
    assert "width: 20;" in css


def test_format_log_renderable_still_returns_panel_for_prompt() -> None:
    renderable = _format_log_renderable('{"prompt":"Agent: write\\nGoal: demo"}')

    assert isinstance(renderable, Panel)


def test_log_message_body_uses_slightly_lighter_text_color() -> None:
    renderable = _format_log_renderable('{"output":"hello"}')

    assert isinstance(renderable, Panel)
    assert renderable.renderable.spans[0].style == "#f0ede6"
