"""Tests for UI actions (state transitions)."""
from __future__ import annotations

import pytest

from devpipe.ui.actions import (
    apply_history_entry,
    apply_inline_edit,
    begin_inline_edit,
    begin_stage,
    cancel_inline_edit,
    complete_stage_attempt,
    finish_run,
    load_defaults,
    select_nav_item,
    select_profile,
    set_field_value,
    start_run,
    append_run_output,
)
from devpipe.ui.state import (
    FieldKind,
    FieldMeta,
    NavSection,
    UIState,
)


def _sample_fields() -> list[FieldMeta]:
    return [
        FieldMeta(key="task_id", label="Task Id", kind=FieldKind.STRING, section="custom"),
        FieldMeta(key="target_branch", label="Target Branch", kind=FieldKind.STRING, section="custom"),
        FieldMeta(key="namespace", label="Namespace", kind=FieldKind.STRING, section="custom"),
        FieldMeta(key="service", label="Service", kind=FieldKind.STRING, section="custom"),
        FieldMeta(key="tags", label="Tags", kind=FieldKind.ARRAY, section="custom"),
    ]


def _loaded_state() -> UIState:
    state = UIState()
    return load_defaults(
        state,
        profile="test-profile",
        available_profiles=["test-profile", "other"],
        available_stages=["architect", "developer", "qa_local"],
        fields=_sample_fields(),
        defaults={"task": "Do something", "runner": "auto"},
        available_runners=["auto", "codex", "claude"],
    )


class TestLoadDefaults:
    def test_sets_profile(self):
        state = _loaded_state()
        assert state.form.profile == "test-profile"

    def test_sets_default_values(self):
        state = _loaded_state()
        assert state.form.values["task"] == "Do something"
        assert state.form.values["runner"] == "auto"

    def test_sets_standard_defaults(self):
        state = _loaded_state()
        assert state.form.values["model"] == "auto"
        assert state.form.values["effort"] == "auto"
        assert state.form.values["first_role"] == "architect"
        assert state.form.values["last_role"] == ""  # Empty by default

    def test_builds_nav_items(self):
        state = _loaded_state()
        assert len(state.nav_items) > 0
        sections = {i.section for i in state.nav_items}
        assert NavSection.STANDARD in sections
        assert NavSection.CUSTOM in sections
        assert NavSection.ACTIONS in sections

    def test_status_bar_is_derived(self):
        state = _loaded_state()
        assert state.status_bar.is_ready  # task is set


class TestSelectNavItem:
    def test_moves_cursor(self):
        state = _loaded_state()
        new = select_nav_item(state, 3)
        assert new.selected_nav_index == 3

    def test_ignores_out_of_range(self):
        state = _loaded_state()
        new = select_nav_item(state, 999)
        assert new.selected_nav_index == 0  # unchanged


class TestSelectProfile:
    def test_switches_profile(self):
        state = _loaded_state()
        new_fields = [
            FieldMeta(key="new_field", label="New Field", kind=FieldKind.STRING, section="custom"),
        ]
        new = select_profile(
            state,
            profile="other",
            fields=new_fields,
            defaults={"runner": "codex"},
            available_stages=["dev", "test"],
        )
        assert new.form.profile == "other"
        # Standard values preserved
        assert new.form.values["task"] == "Do something"
        # Custom fields replaced
        custom = [f for f in new.form.fields if f.section == "custom"]
        assert len(custom) == 1
        assert custom[0].key == "new_field"

    def test_resets_invalid_first_role(self):
        state = _loaded_state()
        state = set_field_value(state, "first_role", "invalid_stage")
        new = select_profile(
            state,
            profile="other",
            fields=[],
            defaults={},
            available_stages=["dev", "test"],
        )
        assert new.form.values["first_role"] == "dev"


class TestSetFieldValue:
    def test_sets_value(self):
        state = _loaded_state()
        new = set_field_value(state, "task_id", "MRC-123")
        assert new.form.values["task_id"] == "MRC-123"

    def test_updates_status_bar(self):
        state = UIState()
        fields = [FieldMeta(key="task", label="Task", required=True, section="standard")]
        state = load_defaults(state, "p", ["p"], ["a"], fields, {"task": ""})
        assert not state.status_bar.is_ready
        state = set_field_value(state, "task", "something")
        assert state.status_bar.is_ready

    def test_normalizes_stage_range_when_first_role_moves_past_last_role(self):
        state = _loaded_state()
        state = set_field_value(state, "last_role", "architect")
        state = set_field_value(state, "first_role", "developer")
        assert state.form.values["first_role"] == "developer"
        assert state.form.values["last_role"] == "developer"

    def test_normalizes_stage_range_when_last_role_moves_before_first_role(self):
        state = _loaded_state()
        state = set_field_value(state, "first_role", "developer")
        state = set_field_value(state, "last_role", "architect")
        assert state.form.values["first_role"] == "architect"
        assert state.form.values["last_role"] == "architect"


class TestInlineEdit:
    def test_begin_edit(self):
        state = _loaded_state()
        new = begin_inline_edit(state, "task")
        assert new.editor.editing
        assert new.editor.field_key == "task"
        assert new.editor.draft_value == "Do something"

    def test_cancel_edit(self):
        state = _loaded_state()
        state = begin_inline_edit(state, "task")
        state = cancel_inline_edit(state)
        assert not state.editor.editing

    def test_apply_edit(self):
        state = _loaded_state()
        state = begin_inline_edit(state, "task")
        state.editor.draft_value = "New task"
        state = apply_inline_edit(state)
        assert state.form.values["task"] == "New task"
        assert not state.editor.editing


class TestApplyHistoryEntry:
    def test_loads_history_values(self):
        state = _loaded_state()
        entry = {
            "task": "Old task",
            "task_id": "MRC-999",
            "runner": "codex",
            "target_branch": "main",
            "extra_params": {"dataset": "s4"},
        }
        new = apply_history_entry(state, entry)
        assert new.form.values["task"] == "Old task"
        assert new.form.values["task_id"] == "MRC-999"
        assert new.form.values["runner"] == "codex"
        assert new.form.values["dataset"] == "s4"
        assert new.form.field_by_key("dataset") is not None

    def test_adds_missing_custom_fields_from_extra_params(self):
        state = _loaded_state()
        entry = {
            "extra_params": {
                "dataset": ["s4"],
                "retry_count": 3,
            },
        }

        new = apply_history_entry(state, entry)

        dataset = new.form.field_by_key("dataset")
        retry_count = new.form.field_by_key("retry_count")
        assert dataset is not None
        assert retry_count is not None
        assert dataset.kind == FieldKind.ARRAY
        assert retry_count.kind == FieldKind.INT

    def test_resets_invalid_runner(self):
        state = _loaded_state()
        entry = {"runner": "invalid_runner"}
        new = apply_history_entry(state, entry)
        assert new.form.values["runner"] == "auto"

    def test_resets_invalid_stage(self):
        state = _loaded_state()
        entry = {"first_role": "unknown_stage"}
        new = apply_history_entry(state, entry)
        assert new.form.values["first_role"] == "architect"


class TestRunActions:
    def test_start_run(self):
        state = _loaded_state()
        new = start_run(state, "run-123", ["architect", "developer"], "codex", "gpt-5", "medium")
        assert new.active_screen == "run"
        assert new.run_view.status == "running"
        assert new.run_view.run_id == "run-123"
        # Timeline starts empty — stages are added as they are activated
        assert new.run_view.timeline == []

    def test_begin_stage(self):
        state = _loaded_state()
        state = start_run(state, "run-123", ["architect", "developer"], "codex", "gpt-5", "medium")
        state = begin_stage(state, "architect", "codex", "gpt-5", "medium")
        assert state.run_view.active_stage == "architect"
        active = [a for a in state.run_view.timeline if a.status == "active"]
        assert len(active) == 1
        assert active[0].stage == "architect"

    def test_complete_stage(self):
        state = _loaded_state()
        state = start_run(state, "run-123", ["architect"], "codex", "gpt-5", "medium")
        state = begin_stage(state, "architect", "codex", "gpt-5", "medium")
        state = complete_stage_attempt(state, "architect", "done", "Completed successfully")
        done = [a for a in state.run_view.timeline if a.status == "done"]
        assert len(done) == 1

    def test_retry_adds_new_attempt(self):
        """When a stage is retried, a new attempt should appear in timeline."""
        state = _loaded_state()
        state = start_run(state, "run-123", ["developer"], "codex", "gpt-5", "medium")
        state = begin_stage(state, "developer", "codex", "gpt-5", "medium")
        state = complete_stage_attempt(state, "developer", "failed", error="Timeout")
        # Retry: begin_stage again
        state = begin_stage(state, "developer", "codex", "gpt-5", "medium")
        dev_attempts = [a for a in state.run_view.timeline if a.stage == "developer"]
        assert len(dev_attempts) == 2
        assert dev_attempts[1].attempt_number == 2

    def test_begin_stage_ignores_duplicate_start_for_active_attempt(self):
        state = _loaded_state()
        state = start_run(state, "run-123", ["architect", "developer"], "codex", "gpt-5", "medium")
        state = begin_stage(state, "architect", "codex", "gpt-5", "medium")

        state = begin_stage(state, "architect", "codex", "gpt-5", "medium")

        architect_attempts = [a for a in state.run_view.timeline if a.stage == "architect"]
        assert len(architect_attempts) == 1
        assert architect_attempts[0].status == "active"

    def test_append_run_output(self):
        state = _loaded_state()
        state = start_run(state, "run-123", ["architect"], "codex", "gpt-5", "medium")
        state = append_run_output(state, "line1\nline2")
        assert len(state.run_view.log_lines) == 2

    def test_finish_run(self):
        state = _loaded_state()
        state = start_run(state, "run-123", ["architect"], "codex", "gpt-5", "medium")
        state = finish_run(state, "completed", "run-123")
        assert state.run_view.status == "completed"
