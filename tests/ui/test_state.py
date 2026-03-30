"""Tests for UIState model and derived views."""
from __future__ import annotations

import pytest

from devpipe.ui.state import (
    FieldKind,
    FieldMeta,
    FormState,
    NavSection,
    UIState,
    build_nav_items,
    derive_status_bar,
)


def _sample_fields() -> list[FieldMeta]:
    return [
        FieldMeta(key="task", label="Task", kind=FieldKind.STRING, required=True, section="standard"),
        FieldMeta(key="task_id", label="Task Id", kind=FieldKind.STRING, section="custom"),
        FieldMeta(key="target_branch", label="Target Branch", kind=FieldKind.STRING, section="custom"),
        FieldMeta(key="namespace", label="Namespace", kind=FieldKind.STRING, section="custom"),
        FieldMeta(key="service", label="Service", kind=FieldKind.STRING, section="custom"),
        FieldMeta(key="tags", label="Tags", kind=FieldKind.ARRAY, section="custom"),
        FieldMeta(key="extra_params", label="Extra Params", kind=FieldKind.OBJECT, section="custom"),
    ]


def _sample_form() -> FormState:
    return FormState(
        values={"task": "", "runner": "auto", "model": "auto", "effort": "auto", "profile": "test-profile"},
        fields=_sample_fields(),
        profile="test-profile",
        available_profiles=["test-profile", "other-profile"],
        available_stages=["architect", "developer", "qa_local"],
    )


class TestBuildNavItems:
    def test_has_standard_section(self):
        form = _sample_form()
        items = build_nav_items(form)
        standard = [i for i in items if i.section == NavSection.STANDARD]
        labels = [i.label for i in standard]
        assert "Profile" in labels
        assert "Task" in labels
        assert "Runner" in labels
        assert "Model" in labels
        assert "Effort" in labels
        assert "Tags" in labels
        assert "Start Agent" in labels
        assert "Finish Agent" in labels

    def test_has_custom_section_with_profile_inputs(self):
        form = _sample_form()
        items = build_nav_items(form)
        custom = [i for i in items if i.section == NavSection.CUSTOM]
        keys = [i.key for i in custom]
        assert "task_id" in keys
        assert "target_branch" in keys
        assert "namespace" in keys
        assert "tags" not in keys

    def test_task_id_NOT_in_standard_section(self):
        """Task ID must appear only as custom field, not standard."""
        form = _sample_form()
        items = build_nav_items(form)
        standard = [i for i in items if i.section == NavSection.STANDARD]
        standard_keys = [i.key for i in standard]
        assert "task_id" not in standard_keys

    def test_has_actions_section(self):
        form = _sample_form()
        items = build_nav_items(form)
        actions = [i for i in items if i.section == NavSection.ACTIONS]
        labels = [i.label for i in actions]
        assert "History" in labels
        assert "Run Pipeline" in labels

    def test_custom_fields_are_flat_list(self):
        """Profile-driven custom inputs must be a flat list, no stage grouping."""
        form = _sample_form()
        items = build_nav_items(form)
        custom = [i for i in items if i.section == NavSection.CUSTOM]
        # All items at same level, no nested structure
        for item in custom:
            assert isinstance(item.key, str)
            assert item.section == NavSection.CUSTOM


class TestFormState:
    def test_missing_required(self):
        form = _sample_form()
        missing = form.missing_required()
        assert "task" in missing

    def test_is_ready_when_task_set(self):
        form = _sample_form()
        form.values["task"] = "Do something"
        assert form.is_ready

    def test_field_by_key(self):
        form = _sample_form()
        f = form.field_by_key("task")
        assert f is not None
        assert f.label == "Task"

    def test_field_by_key_not_found(self):
        form = _sample_form()
        assert form.field_by_key("nonexistent") is None


class TestDeriveStatusBar:
    def test_not_ready_when_missing_required(self):
        form = _sample_form()
        bar = derive_status_bar(form)
        assert not bar.is_ready
        assert "NOT READY" in bar.right_text
        assert len(bar.validation_errors) > 0
        assert "Tab" not in bar.left_text

    def test_ready_when_all_required_set(self):
        form = _sample_form()
        form.values["task"] = "Do something"
        bar = derive_status_bar(form)
        assert bar.is_ready
        assert "READY" in bar.right_text
        assert "Tab" not in bar.left_text


class TestUIState:
    def test_selected_nav_item(self):
        form = _sample_form()
        state = UIState(form=form)
        state.nav_items = build_nav_items(form)
        state.selected_nav_index = 0
        item = state.selected_nav_item
        assert item is not None
        assert item.key == "profile"

    def test_selected_nav_item_out_of_range(self):
        state = UIState()
        state.nav_items = []
        state.selected_nav_index = 5
        assert state.selected_nav_item is None

    def test_nav_items_by_section(self):
        form = _sample_form()
        state = UIState(form=form)
        state.nav_items = build_nav_items(form)
        standard = state.nav_items_by_section(NavSection.STANDARD)
        assert len(standard) == 8  # Profile, Task, Runner, Model, Effort, Tags, Start Stage, Finish Stage


class TestFieldKind:
    def test_string_kind(self):
        assert FieldKind.STRING == "string"

    def test_int_kind(self):
        assert FieldKind.INT == "int"

    def test_select_kind(self):
        assert FieldKind.SELECT == "select"

    def test_multi_select_kind(self):
        assert FieldKind.MULTI_SELECT == "multi_select"

    def test_array_kind(self):
        assert FieldKind.ARRAY == "array"

    def test_object_kind(self):
        assert FieldKind.OBJECT == "object"
