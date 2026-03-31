"""Tests for the run screen state and event bridge."""
from __future__ import annotations

from time import monotonic
from types import SimpleNamespace

import pytest

from devpipe.ui.actions import (
    append_run_output,
    begin_stage,
    complete_stage_attempt,
    finish_run,
    load_defaults,
    start_run,
)
from devpipe.ui.screens.run_screen import (
    LogPanel,
    RunQuestionPanel,
    RunScreen,
    RunStageStrip,
    _format_duration,
    _format_final_result,
    _format_pipeline_completion,
    _format_log_chunk,
    _format_log_renderable,
)
from devpipe.ui.state import FieldKind, FieldMeta, UIState
from devpipe.ui.widgets.status_bar import RunStatusBar


def _make_state() -> UIState:
    fields = [
        FieldMeta(key="task_id", label="Task Id", kind=FieldKind.STRING, section="custom"),
    ]
    state = UIState()
    return load_defaults(
        state,
        profile="current-delivery",
        available_profiles=["current-delivery"],
        available_stages=["architect", "developer", "test_developer", "qa_local", "release", "qa_stand"],
        fields=fields,
        defaults={"task": "Test task", "runner": "auto"},
    )


class TestRunScreen:
    def test_start_run_creates_timeline(self):
        state = _make_state()
        state = start_run(state, "run-1", ["architect", "developer", "qa_local"], "codex", "gpt-5", "medium")
        assert state.active_screen == "run"
        assert len(state.run_view.timeline) == 3
        assert all(a.status == "pending" for a in state.run_view.timeline)

    def test_stage_started_activates_stage(self):
        state = _make_state()
        state = start_run(state, "run-1", ["architect", "developer"], "codex", "gpt-5", "medium")
        state = begin_stage(state, "architect", "codex", "gpt-5", "medium")
        assert state.run_view.active_stage == "architect"
        active = [a for a in state.run_view.timeline if a.status == "active"]
        assert len(active) == 1
        assert active[0].stage == "architect"

    def test_streamed_output(self):
        state = _make_state()
        state = start_run(state, "run-1", ["architect"], "codex", "gpt-5", "medium")
        state = append_run_output(state, "chunk1")
        state = append_run_output(state, "chunk2")
        assert len(state.run_view.log_lines) == 2

    def test_stage_completed(self):
        state = _make_state()
        state = start_run(state, "run-1", ["architect"], "codex", "gpt-5", "medium")
        state = begin_stage(state, "architect", "codex", "gpt-5", "medium")
        state = complete_stage_attempt(state, "architect", "done", summary="Plan ready")
        done = [a for a in state.run_view.timeline if a.status == "done"]
        assert len(done) == 1
        assert done[0].summary == "Plan ready"

    def test_stage_failed(self):
        state = _make_state()
        state = start_run(state, "run-1", ["developer"], "codex", "gpt-5", "medium")
        state = begin_stage(state, "developer", "codex", "gpt-5", "medium")
        state = complete_stage_attempt(state, "developer", "failed", error="Timeout")
        failed = [a for a in state.run_view.timeline if a.status == "failed"]
        assert len(failed) == 1
        assert failed[0].error == "Timeout"

    def test_stage_attempts_in_cycle(self):
        """Test qa_stand -> developer retry cycle produces correct attempt numbers."""
        state = _make_state()
        state = start_run(
            state, "run-1",
            ["developer", "qa_stand"],
            "codex", "gpt-5", "medium",
        )
        # First pass
        state = begin_stage(state, "developer", "codex", "gpt-5", "medium")
        state = complete_stage_attempt(state, "developer", "done", "Code done")
        state = begin_stage(state, "qa_stand", "codex", "gpt-5", "medium")
        state = complete_stage_attempt(state, "qa_stand", "failed", error="Test failed")

        # Retry developer
        state = begin_stage(state, "developer", "codex", "gpt-5", "medium")
        dev_attempts = [a for a in state.run_view.timeline if a.stage == "developer"]
        assert len(dev_attempts) == 2
        assert dev_attempts[0].attempt_number == 1
        assert dev_attempts[1].attempt_number == 2
        assert dev_attempts[0].status == "done"
        assert dev_attempts[1].status == "active"

    def test_run_finished(self):
        state = _make_state()
        state = start_run(state, "run-1", ["architect"], "codex", "gpt-5", "medium")
        state = finish_run(state, "completed", "run-1")
        assert state.run_view.status == "completed"

    def test_run_finished_failed(self):
        state = _make_state()
        state = start_run(state, "run-1", ["architect"], "codex", "gpt-5", "medium")
        state = finish_run(state, "failed", "run-1")
        assert state.run_view.status == "failed"

    def test_return_to_config_after_run(self):
        """After finish_run, active_screen remains run (app handles transition)."""
        state = _make_state()
        state = start_run(state, "run-1", ["architect"], "codex", "gpt-5", "medium")
        state = finish_run(state, "completed", "run-1")
        # The screen is still "run" — app pops it
        assert state.active_screen == "run"


def test_stage_strip_shows_only_completed_and_active_steps() -> None:
    strip = RunStageStrip()
    state = _make_state()
    state = start_run(state, "run-1", ["architect", "developer", "qa_local"], "codex", "gpt-5", "medium")
    state = begin_stage(state, "architect", "codex", "gpt-5", "medium")
    state.run_view.timeline[0].elapsed_seconds = 12
    state = complete_stage_attempt(state, "architect", "done", summary="done")
    state = begin_stage(state, "developer", "codex", "gpt-5", "medium")
    state.run_view.timeline[1].elapsed_seconds = 8
    strip.set_timeline(state.run_view.timeline)
    strip.set_spinner_frame("⠋")

    rendered = strip.render().plain

    assert "architect" in rendered
    assert "developer" in rendered
    assert "qa_local" not in rendered
    assert "⠋" in rendered
    assert "12s" in rendered
    assert "8s" in rendered


def test_format_duration_keeps_fraction_for_short_steps() -> None:
    assert _format_duration(0.8) == "0.8s"
    assert _format_duration(9.4) == "9.4s"


def test_stage_strip_shows_current_pending_step_before_first_start() -> None:
    strip = RunStageStrip()
    state = _make_state()
    state = start_run(state, "run-1", ["architect", "developer"], "codex", "gpt-5", "medium")
    strip.set_timeline(state.run_view.timeline)

    rendered = strip.render().plain

    assert "architect" in rendered
    assert "developer" not in rendered
    assert "No active steps yet" not in rendered


def test_run_status_bar_shows_model_effort_and_total_time() -> None:
    bar = RunStatusBar()

    bar.update_run_state(status="running", elapsed="1m 24s", model="gpt-5", effort="high")

    rendered = bar.render().plain

    assert "running" in rendered
    assert "model gpt-5" in rendered
    assert "effort high" in rendered
    assert "1m 24s" in rendered
    assert "current step" not in rendered


def test_run_status_bar_shows_cancel_confirmation_alert() -> None:
    bar = RunStatusBar()

    bar.show_alert("Stop pipeline? Y — confirm  N — stay")

    rendered = bar.render().plain

    assert "Stop pipeline?" in rendered
    assert "model" not in rendered


def test_run_status_bar_alert_css_is_red() -> None:
    css = RunStatusBar.DEFAULT_CSS

    assert "RunStatusBar.-alert" in css
    assert "$error" in css


def test_question_panel_has_placeholder() -> None:
    panel = RunQuestionPanel()
    widgets = list(panel.compose())

    assert widgets[0].render().plain == "Question"
    assert "No active question yet" in widgets[1].render().plain


def test_log_panel_title_matches_screen_style() -> None:
    panel = LogPanel()
    title = next(panel.compose())

    assert "Output" == title.render().plain


def test_format_log_chunk_pretty_prints_json_objects() -> None:
    formatted = _format_log_chunk('{"risks":{"items":["too slow","too noisy"]},"needs_refinement":false}')

    assert "Risks" in formatted
    assert "too slow" in formatted
    assert "Items" not in formatted
    assert "\nNeeds Refinement:" in formatted


def test_format_log_chunk_keeps_command_block_compact() -> None:
    formatted = _format_log_chunk("⟫ pwd\n/Users/test/project\n\n")

    assert formatted.startswith("⟫ pwd")
    assert "/Users/test/project" in formatted


def test_stage_strip_css_adds_vertical_padding() -> None:
    css = RunStageStrip.DEFAULT_CSS

    assert "padding: 0 2;" in css
    assert "height: 3;" in css
    assert "$panel" in css


def test_stage_strip_render_shows_only_steps_row() -> None:
    strip = RunStageStrip()
    state = _make_state()
    state = start_run(state, "run-1", ["architect", "developer"], "codex", "gpt-5", "medium")
    state = begin_stage(state, "architect", "codex", "gpt-5", "medium")
    state.run_view.timeline[0].elapsed_seconds = 3.2
    strip.set_timeline(state.run_view.timeline)
    strip.set_spinner_frame("⠋")

    rendered = strip.render().plain

    assert "architect" in rendered
    assert "active" not in rendered
    assert rendered.count("\n") == 0


def test_run_screen_stage_started_does_not_duplicate_existing_active_attempt() -> None:
    state = _make_state()
    state = start_run(state, "run-1", ["architect", "developer"], "codex", "gpt-5", "medium")
    state = begin_stage(state, "architect", "codex", "gpt-5", "medium")
    screen = RunScreen(state)
    screen.query_one = lambda *_args, **_kwargs: SimpleNamespace(  # type: ignore[method-assign]
        set_timeline=lambda *_a, **_k: None,
        set_spinner_frame=lambda *_a, **_k: None,
        update_run_state=lambda *_a, **_k: None,
        set_mode=lambda *_a, **_k: None,
        append=lambda *_a, **_k: None,
        show_alert=lambda *_a, **_k: None,
        clear_alert=lambda *_a, **_k: None,
    )

    screen.on_stage_started("architect", "codex", "gpt-5", "medium")

    architect_attempts = [attempt for attempt in screen._state.run_view.timeline if attempt.stage == "architect"]
    assert len(architect_attempts) == 1
    assert architect_attempts[0].status == "active"


def test_run_screen_stage_started_sets_clock_for_existing_active_attempt() -> None:
    state = _make_state()
    state = start_run(state, "run-1", ["architect", "developer"], "codex", "gpt-5", "medium")
    state = begin_stage(state, "architect", "codex", "gpt-5", "medium")
    screen = RunScreen(state)
    screen.query_one = lambda *_args, **_kwargs: SimpleNamespace(  # type: ignore[method-assign]
        set_timeline=lambda *_a, **_k: None,
        set_spinner_frame=lambda *_a, **_k: None,
        update_run_state=lambda *_a, **_k: None,
        set_mode=lambda *_a, **_k: None,
        append=lambda *_a, **_k: None,
        show_alert=lambda *_a, **_k: None,
        clear_alert=lambda *_a, **_k: None,
    )

    screen.on_stage_started("architect", "codex", "gpt-5", "medium")

    assert screen._active_stage_started_at is not None


def test_log_panel_append_respects_follow_tail_state() -> None:
    panel = LogPanel()
    writes: list[bool | None] = []
    fake_log = SimpleNamespace(
        write=lambda _text, **kwargs: writes.append(kwargs.get("scroll_end")),
    )
    panel.query_one = lambda *_args, **_kwargs: fake_log  # type: ignore[method-assign]

    panel.append("first")
    panel.pause_follow()
    panel.append("second")

    assert writes == [True, False]


def test_run_screen_stage_markers_use_readable_status_messages() -> None:
    state = _make_state()
    screen = RunScreen(state)
    messages: list[str] = []
    screen.query_one = lambda *_args, **_kwargs: SimpleNamespace(  # type: ignore[method-assign]
        set_timeline=lambda *_a, **_k: None,
        set_spinner_frame=lambda *_a, **_k: None,
        update_run_state=lambda *_a, **_k: None,
        set_mode=lambda *_a, **_k: None,
        append=lambda text, *_a, **_k: messages.append(text),
        show_alert=lambda *_a, **_k: None,
        clear_alert=lambda *_a, **_k: None,
    )

    screen.on_stage_started("architect", "codex", "gpt-5", "medium")
    screen.on_stage_completed("architect", "done")

    assert any("Started: architect" in text for text in messages)
    assert any("Completed: architect" in text for text in messages)
    assert any(text.startswith("\n") for text in messages)


def test_run_screen_stage_completed_preserves_elapsed_when_attempt_already_done() -> None:
    state = _make_state()
    screen = RunScreen(state)
    screen.query_one = lambda *_args, **_kwargs: SimpleNamespace(  # type: ignore[method-assign]
        set_timeline=lambda *_a, **_k: None,
        set_spinner_frame=lambda *_a, **_k: None,
        update_run_state=lambda *_a, **_k: None,
        set_mode=lambda *_a, **_k: None,
        append=lambda *_a, **_k: None,
        show_alert=lambda *_a, **_k: None,
        clear_alert=lambda *_a, **_k: None,
    )
    screen._state.run_view.timeline = [
        SimpleNamespace(stage="architect", status="done", elapsed_seconds=0.0, summary="", error="")
    ]
    screen._active_stage_started_at = monotonic() - 2.4

    screen.on_stage_completed("architect", "done")

    assert screen._state.run_view.timeline[0].elapsed_seconds >= 2.0


def test_run_screen_formats_finalize_output_as_result_block() -> None:
    state = _make_state()
    screen = RunScreen(state)
    messages: list[str] = []
    screen.query_one = lambda *_args, **_kwargs: SimpleNamespace(  # type: ignore[method-assign]
        set_timeline=lambda *_a, **_k: None,
        set_spinner_frame=lambda *_a, **_k: None,
        update_run_state=lambda *_a, **_k: None,
        set_mode=lambda *_a, **_k: None,
        append=lambda text, *_a, **_k: messages.append(text),
        show_alert=lambda *_a, **_k: None,
        clear_alert=lambda *_a, **_k: None,
    )

    screen._state.run_view.timeline = [SimpleNamespace(stage="review", status="active", elapsed_seconds=0, summary="", error="")]
    screen.on_stage_completed(
        "review",
        "done",
        {
            "headline": "ClearPR",
            "summary": "Turns sharp PR comments into clear, respectful feedback.",
            "actions": ["Build MVP", "Run pilot"],
        },
    )
    screen.on_run_finished("completed", "run-1")

    rendered = "\n".join(messages)
    assert "Final Output" in rendered
    assert "ClearPR" in rendered
    assert "Build MVP" in rendered


def test_format_final_result_uses_card_style_sections() -> None:
    formatted = _format_final_result(
        {
            "headline": "ClearPR",
            "summary": "Cleaner PR communication.",
            "details": {
                "positioning": "Layer above GitHub reviews.",
                "best_angle": "Less friction per merge.",
            },
            "actions": ["Pilot", "Measure"],
        }
    )

    assert formatted.startswith("◆ Final Output")
    assert "\nHeadline: ClearPR" in formatted
    assert "\nDetails\n" in formatted
    assert "• Pilot" in formatted
    assert "• Measure" in formatted


def test_format_log_chunk_formats_top_level_sections_with_spacing() -> None:
    formatted = _format_log_chunk(
        '{"summary":"Cleaner PR communication.","details":{"positioning":"Layer above GitHub reviews."},"actions":["Pilot","Measure"]}'
    )

    assert "Summary: Cleaner PR communication." in formatted
    assert "\nDetails\n" in formatted
    assert "• Pilot" in formatted


def test_format_log_chunk_renders_empty_items_wrapper_as_empty_value() -> None:
    formatted = _format_log_chunk('{"risks":{"items":[]}}')

    assert "Risks: (empty)" in formatted
    assert "Items" not in formatted


def test_format_log_chunk_renders_empty_strings_as_empty_placeholders() -> None:
    formatted = _format_log_chunk('{"top_name":"","pitch":"","final_card":{"positioning":""}}')

    assert "Top Name: (empty)" in formatted
    assert "Pitch: (empty)" in formatted
    assert "Positioning: (empty)" in formatted


def test_run_status_bar_uses_panel_palette() -> None:
    css = RunStatusBar.DEFAULT_CSS

    assert "$panel" in css
    assert "$error" in css


def test_run_status_bar_dims_labels_but_keeps_values_bright() -> None:
    bar = RunStatusBar()
    bar.update_run_state(
        status="running",
        elapsed="11s",
        model="gpt-5.3-codex",
        effort="medium",
    )

    rendered = bar.render()
    plain = rendered.plain

    def style_at(fragment: str) -> str | None:
        offset = plain.index(fragment)
        for span in rendered.spans:
            if span.start <= offset < span.end:
                return str(span.style)
        return None

    assert style_at("model") == "dim"
    assert style_at("effort") == "dim"
    assert style_at("gpt-5.3-codex") in {"white", None}
    assert style_at("medium") in {"white", None}


def test_format_log_renderable_dims_only_property_names() -> None:
    renderable = _format_log_renderable('{"top_name":"ClearPR","pitch":"Friendly reviews"}')
    assert hasattr(renderable, "spans")

    plain = renderable.plain

    def style_at(fragment: str) -> str | None:
        offset = plain.index(fragment)
        for span in renderable.spans:
            if span.start <= offset < span.end:
                return str(span.style)
        return None

    assert style_at("Top Name") == "dim"
    assert style_at("Pitch") == "dim"
    assert style_at("ClearPR") in {"white", None}
    assert style_at("Friendly reviews") in {"white", None}


def test_format_pipeline_completion_includes_duration_and_name() -> None:
    formatted = _format_pipeline_completion(
        run_id="run-1",
        elapsed="4m 19s",
        final_output={"headline": "ClearPR", "summary": "Cleaner PR communication."},
    )

    assert "Pipeline completed" in formatted
    assert "Duration: 4m 19s" in formatted
    assert "Output captured" in formatted


def test_run_screen_shows_cancelled_pipeline_message() -> None:
    state = _make_state()
    screen = RunScreen(state)
    messages: list[str] = []
    screen.query_one = lambda *_args, **_kwargs: SimpleNamespace(  # type: ignore[method-assign]
        set_timeline=lambda *_a, **_k: None,
        set_spinner_frame=lambda *_a, **_k: None,
        update_run_state=lambda *_a, **_k: None,
        set_mode=lambda *_a, **_k: None,
        append=lambda text, *_a, **_k: messages.append(text),
        show_alert=lambda *_a, **_k: None,
        clear_alert=lambda *_a, **_k: None,
    )

    screen.on_run_finished("cancelled", "run-1")

    assert any("Pipeline cancelled" in text for text in messages)


def test_run_screen_back_while_running_enters_cancel_confirmation() -> None:
    state = _make_state()
    state.run_view.status = "running"
    screen = RunScreen(state)
    status = SimpleNamespace(
        update_run_state=lambda *_a, **_k: None,
        show_alert=lambda *_a, **_k: None,
        clear_alert=lambda *_a, **_k: None,
    )
    question = SimpleNamespace(set_mode=lambda *_a, **_k: None)
    stage_strip = SimpleNamespace(set_timeline=lambda *_a, **_k: None, set_spinner_frame=lambda *_a, **_k: None)
    mapping = {
        "#run-stage-strip": stage_strip,
        "#run-question-panel": question,
        "#run-status": status,
    }
    screen.query_one = lambda selector, *_args, **_kwargs: mapping[selector]  # type: ignore[method-assign]

    screen.action_back()

    assert screen._confirm_cancel is True


def test_run_screen_back_shows_cancel_confirmation_in_status_bar() -> None:
    state = _make_state()
    state.run_view.status = "running"
    screen = RunScreen(state)
    calls: list[str] = []
    status = SimpleNamespace(
        update_run_state=lambda *_a, **_k: None,
        show_alert=lambda message: calls.append(message),
        clear_alert=lambda: calls.append("clear"),
    )
    question = SimpleNamespace(set_mode=lambda *_a, **_k: None)
    stage_strip = SimpleNamespace(set_timeline=lambda *_a, **_k: None, set_spinner_frame=lambda *_a, **_k: None)
    mapping = {
        "#run-stage-strip": stage_strip,
        "#run-question-panel": question,
        "#run-status": status,
    }
    screen.query_one = lambda selector, *_args, **_kwargs: mapping[selector]  # type: ignore[method-assign]

    screen.action_back()

    assert any("Stop pipeline?" in call for call in calls)


def test_run_screen_confirm_cancel_uses_app_async_cancel() -> None:
    state = _make_state()
    state.run_view.status = "running"
    screen = RunScreen(state)
    calls: list[str] = []

    screen._confirm_cancel = True
    screen._begin_cancel_return = lambda: calls.append("cancel")  # type: ignore[method-assign]
    status = SimpleNamespace(
        update_run_state=lambda *_a, **_k: None,
        show_alert=lambda *_a, **_k: None,
        clear_alert=lambda: None,
    )
    question = SimpleNamespace(set_mode=lambda *_a, **_k: None)
    stage_strip = SimpleNamespace(set_timeline=lambda *_a, **_k: None, set_spinner_frame=lambda *_a, **_k: None)
    mapping = {
        "#run-stage-strip": stage_strip,
        "#run-question-panel": question,
        "#run-status": status,
    }
    screen.query_one = lambda selector, *_args, **_kwargs: mapping[selector]  # type: ignore[method-assign]

    screen.action_confirm_cancel()

    assert calls == ["cancel"]
    assert screen._cancelling is True


def test_run_screen_dismiss_cancel_restores_status_bar() -> None:
    state = _make_state()
    state.run_view.status = "running"
    screen = RunScreen(state)
    calls: list[str] = []
    screen._confirm_cancel = True
    status = SimpleNamespace(
        update_run_state=lambda *_a, **_k: None,
        show_alert=lambda message: calls.append(message),
        clear_alert=lambda: calls.append("clear"),
    )
    question = SimpleNamespace(set_mode=lambda *_a, **_k: None)
    stage_strip = SimpleNamespace(set_timeline=lambda *_a, **_k: None, set_spinner_frame=lambda *_a, **_k: None)
    mapping = {
        "#run-stage-strip": stage_strip,
        "#run-question-panel": question,
        "#run-status": status,
    }
    screen.query_one = lambda selector, *_args, **_kwargs: mapping[selector]  # type: ignore[method-assign]

    screen.action_dismiss_cancel()

    assert screen._confirm_cancel is False
    assert "clear" in calls
