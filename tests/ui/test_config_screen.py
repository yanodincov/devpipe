"""Tests for the config screen (Textual)."""
from __future__ import annotations

import pytest

from devpipe.ui.state import (
    FieldKind,
    FieldMeta,
    NavSection,
    UIState,
    build_nav_items,
)
from devpipe.ui.actions import load_defaults
from devpipe.ui.screens.config_screen import ConfigScreen


def _make_state() -> UIState:
    """Create a UIState loaded with test data."""
    fields = [
        FieldMeta(key="task_id", label="Task Id", kind=FieldKind.STRING, section="custom"),
        FieldMeta(key="target_branch", label="Target Branch", kind=FieldKind.STRING, section="custom"),
        FieldMeta(key="namespace", label="Namespace", kind=FieldKind.STRING, section="custom"),
        FieldMeta(key="service", label="Service", kind=FieldKind.STRING, section="custom"),
        FieldMeta(key="tags", label="Tags", kind=FieldKind.ARRAY, section="custom"),
        FieldMeta(key="extra_params", label="Extra Params", kind=FieldKind.OBJECT, section="custom"),
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


class TestConfigScreenState:
    """Test the config screen state structure without Textual."""

    def test_has_no_tab_binding(self):
        keys = {binding.key for binding in ConfigScreen.BINDINGS}
        assert "tab" not in keys

    def test_standard_section_has_five_fields(self):
        state = _make_state()
        standard = [i for i in state.nav_items if i.section == NavSection.STANDARD]
        assert len(standard) == 8
        labels = [i.label for i in standard]
        assert labels == ["Profile", "Task", "Runner", "Model", "Effort", "Tags", "Start Agent", "Finish Agent"]

    def test_custom_section_has_profile_inputs(self):
        state = _make_state()
        custom = [i for i in state.nav_items if i.section == NavSection.CUSTOM]
        keys = [i.key for i in custom]
        assert "task_id" in keys
        assert "target_branch" in keys

    def test_task_id_not_in_standard(self):
        state = _make_state()
        standard = [i for i in state.nav_items if i.section == NavSection.STANDARD]
        keys = [i.key for i in standard]
        assert "task_id" not in keys

    def test_actions_section(self):
        state = _make_state()
        actions = [i for i in state.nav_items if i.section == NavSection.ACTIONS]
        labels = [i.label for i in actions]
        assert "History" in labels
        assert "Run Pipeline" in labels

    def test_status_bar_ready_when_task_set(self):
        state = _make_state()
        assert state.status_bar.is_ready  # task is "Test task"

    def test_status_bar_not_ready_when_task_empty(self):
        fields = [
            FieldMeta(key="task_id", label="Task Id", kind=FieldKind.STRING, section="custom"),
        ]
        state = UIState()
        state = load_defaults(state, "p", ["p"], ["a"], fields, {"task": ""})
        # task is required by default in standard fields - but we need to add it as custom field
        # Actually task is a standard field, so it's checked via form.fields
        # We need to add a required field to test
        fields_with_req = [
            FieldMeta(key="req_field", label="Required", kind=FieldKind.STRING, required=True, section="custom"),
        ]
        state = load_defaults(state, "p", ["p"], ["a"], fields_with_req, {"req_field": ""})
        assert not state.status_bar.is_ready

    def test_run_pipeline_disabled_when_not_ready(self):
        """Run Pipeline should not be actionable when required fields missing."""
        fields = [
            FieldMeta(key="task", label="Task", kind=FieldKind.STRING, required=True, section="custom"),
        ]
        state = UIState()
        state = load_defaults(state, "p", ["p"], ["a"], fields, {"task": ""})
        assert not state.form.is_ready

    def test_different_field_kinds(self):
        """Test that different input types are properly represented."""
        fields = [
            FieldMeta(key="name", label="Name", kind=FieldKind.STRING, section="custom"),
            FieldMeta(key="count", label="Count", kind=FieldKind.INT, section="custom"),
            FieldMeta(key="env", label="Environment", kind=FieldKind.SELECT,
                      options=["dev", "staging", "prod"], section="custom"),
            FieldMeta(key="tags", label="Tags", kind=FieldKind.MULTI_SELECT,
                      options=["go", "python", "rust"], section="custom"),
            FieldMeta(key="items", label="Items", kind=FieldKind.ARRAY, section="custom"),
            FieldMeta(key="params", label="Params", kind=FieldKind.OBJECT, section="custom"),
        ]
        state = UIState()
        state = load_defaults(state, "p", ["p"], ["a"], fields, {})

        custom = [i for i in state.nav_items if i.section == NavSection.CUSTOM]
        assert len(custom) == 5

        # Verify field metadata
        for f in fields:
            meta = state.form.field_by_key(f.key)
            assert meta is not None
            assert meta.kind == f.kind

    def test_inline_edit_current_data_shown(self):
        """Detail pane must show current task data."""
        state = _make_state()
        # Verify current values are in form
        assert state.form.values.get("task") == "Test task"
        assert state.form.values.get("runner") == "auto"
        assert state.form.values.get("model") == "auto"
        assert state.form.values.get("effort") == "auto"
        assert state.form.values.get("first_role") == "architect"
        assert state.form.values.get("last_role") == ""  # Empty by default
