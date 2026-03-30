from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Input, Static, TextArea

from devpipe.ui.state import FieldKind, FieldMeta, FormState, NavItem, NavSection
from devpipe.ui.widgets.detail_panel import DetailPanel


def _form() -> FormState:
    return FormState(
        values={
            "profile": "legacy",
            "task": "Ship feature",
            "runner": "codex",
            "model": "auto",
            "effort": "auto",
            "first_role": "architect",
            "last_role": "qa_stand",
            "namespace": "u1-custom",
            "tags": ["go", "custom-tag"],
        },
        fields=[
            FieldMeta(
                key="namespace",
                label="Namespace",
                kind=FieldKind.SELECT,
                options=["u1", "u1-1"],
                description="Release namespace",
                section="custom",
                custom=True,
            ),
            FieldMeta(
                key="tags",
                label="Tags",
                kind=FieldKind.MULTI_SELECT,
                options=["go", "acquiring-service"],
                description="Pipeline tags",
                section="custom",
                custom=True,
            ),
        ],
        profile="legacy",
        available_profiles=["legacy"],
        available_stages=["architect", "developer", "qa_stand"],
    )


def test_custom_field_summary_keeps_full_task_context() -> None:
    panel = DetailPanel()
    item = NavItem(key="namespace", label="Namespace", section=NavSection.CUSTOM)

    panel.show_summary(item, _form())

    rendered = panel.render().plain
    assert "Task: Ship feature" in rendered
    assert "Runner: codex" in rendered
    assert "Model: auto" in rendered
    assert "Effort: auto" in rendered
    assert "Start Agent: architect" in rendered
    assert "Finish Agent: qa_stand" in rendered
    assert "Namespace: u1-custom" in rendered
    assert "Release namespace" in rendered
    assert "Type:" not in rendered
    assert "Options:" not in rendered


def test_standard_field_summary_shows_field_details() -> None:
    panel = DetailPanel()
    item = NavItem(key="runner", label="Runner", section=NavSection.STANDARD)

    panel.show_summary(item, _form())

    rendered = panel.render().plain
    assert "Field Details" not in rendered
    assert "Runner selection mode" in rendered
    assert "Type:" not in rendered
    assert "Options:" not in rendered


def test_tags_is_rendered_as_standard_field() -> None:
    panel = DetailPanel()
    item = NavItem(key="tags", label="Tags", section=NavSection.STANDARD)

    panel.show_summary(item, _form())

    rendered = panel.render().plain
    assert "Tags: go, custom-tag" in rendered
    assert "Pipeline tags" in rendered


def test_text_editor_mode_shows_field_details() -> None:
    panel = DetailPanel()
    item = NavItem(key="task", label="Task", section=NavSection.STANDARD)

    panel.begin_edit(item, _form())

    rendered = panel.render().plain
    assert "Editing:" not in rendered
    assert "Field Details" not in rendered
    assert "Task text passed to the pipeline" not in rendered
    assert "Type:" not in rendered
    assert "Options:" not in rendered
    assert "Current:" not in rendered
    assert "Enter" not in rendered


def test_action_summary_keeps_current_task_context() -> None:
    panel = DetailPanel()
    item = NavItem(key="history", label="History", section=NavSection.ACTIONS, is_action=True)

    panel.show_summary(item, _form())

    rendered = panel.render().plain
    assert "Task: Ship feature" in rendered
    assert "Runner: codex" in rendered
    assert "Model: auto" in rendered
    assert "Press Enter to open history" in rendered


def test_begin_edit_model_uses_single_choice_editor() -> None:
    panel = DetailPanel()
    form = _form()
    item = NavItem(key="model", label="Model", section=NavSection.STANDARD)

    panel.begin_edit(item, form)

    assert panel.editor_mode == "single_choice"
    assert panel.editor_options == ["auto", "low", "middle", "high"]
    assert panel.editor_current_value() == "auto"
    assert "Model level override for all stages" in panel.render().plain
    assert "Type:" not in panel.render().plain
    assert "Options:" not in panel.render().plain


def test_single_choice_has_correct_option_marked() -> None:
    panel = DetailPanel()
    form = _form()
    item = NavItem(key="model", label="Model", section=NavSection.STANDARD)

    panel.begin_edit(item, form)
    
    # Initial state: auto is committed, cursor on auto
    rendered = panel.render().plain
    assert "● auto" in rendered
    
    # Move cursor down twice
    panel.move_editor_down()
    panel.move_editor_down()
    
    # Now cursor is on middle, but committed is still auto
    rendered = panel.render().plain
    assert "▸ ○ middle" in rendered
    assert "● auto" in rendered
    
    # Press Enter to select middle
    panel.editor_activate()
    
    # Now middle is committed
    rendered = panel.render().plain
    assert "● middle" in rendered
    assert "○ auto" in rendered


def test_single_choice_activate_updates_committed_value() -> None:
    panel = DetailPanel()
    form = _form()
    item = NavItem(key="first_role", label="Start Stage", section=NavSection.STANDARD)

    panel.begin_edit(item, form)
    panel.move_editor_down()
    assert panel.editor_activate() == "confirm"

    assert panel.editor_current_value() == "developer"


def test_single_choice_deselect_on_non_required_field() -> None:
    """Non-required fields can be deselected by pressing Enter on selected option."""
    panel = DetailPanel()
    form = FormState(
        values={"severity": "high"},
        fields=[
            FieldMeta(
                key="severity",
                label="Severity",
                kind=FieldKind.SELECT,
                options=["low", "middle", "high"],
                required=False,
                section="custom",
            ),
        ],
    )
    item = NavItem(key="severity", label="Severity", section=NavSection.CUSTOM)

    panel.begin_edit(item, form)
    
    # Initial: high is selected
    rendered = panel.render().plain
    assert "● high" in rendered
    
    # Move to the selected option and press Enter
    panel.move_editor_down()
    panel.move_editor_down()
    assert panel.editor_activate() == "toggle"
    
    # Now nothing is selected (empty string)
    assert panel.editor_current_value() == ""
    rendered = panel.render().plain
    assert "○ high" in rendered


def test_single_choice_cannot_deselect_required_field() -> None:
    """Required fields cannot be deselected."""
    panel = DetailPanel()
    form = FormState(
        values={"severity": "high"},
        fields=[
            FieldMeta(
                key="severity",
                label="Severity",
                kind=FieldKind.SELECT,
                options=["low", "middle", "high"],
                required=True,
                section="custom",
            ),
        ],
    )
    item = NavItem(key="severity", label="Severity", section=NavSection.CUSTOM)

    panel.begin_edit(item, form)
    
    # Initial: high is selected
    rendered = panel.render().plain
    assert "● high" in rendered
    
    # Move to the selected option and press Enter
    panel.move_editor_down()
    panel.move_editor_down()
    assert panel.editor_activate() == "confirm"
    
    # Still selected (required field cannot be deselected)
    assert panel.editor_current_value() == "high"
    rendered = panel.render().plain
    assert "● high" in rendered


def test_begin_edit_namespace_uses_single_choice_editor_with_custom_values() -> None:
    panel = DetailPanel()
    form = _form()
    item = NavItem(key="namespace", label="Namespace", section=NavSection.CUSTOM)

    panel.begin_edit(item, form)

    assert panel.editor_mode == "single_choice"
    assert panel.editor_allows_custom is True
    assert "u1-custom" in panel.editor_options
    assert "Release namespace" in panel.render().plain
    assert "Type:" not in panel.render().plain
    assert "Options:" not in panel.render().plain


def test_role_editor_options_respect_current_bounds() -> None:
    panel = DetailPanel()
    form = _form()
    form.values["first_role"] = "developer"
    form.values["last_role"] = "developer"

    panel.begin_edit(NavItem(key="first_role", label="Start Stage", section=NavSection.STANDARD), form)
    assert panel.editor_options == ["architect", "developer"]

    panel.begin_edit(NavItem(key="last_role", label="Finish Stage", section=NavSection.STANDARD), form)
    assert panel.editor_options == ["developer", "qa_stand"]


def test_last_role_options_hide_earlier_stages_than_selected_first_role() -> None:
    panel = DetailPanel()
    form = _form()
    form.values["first_role"] = "developer"
    form.values["last_role"] = "qa_stand"

    panel.begin_edit(NavItem(key="last_role", label="Finish Stage", section=NavSection.STANDARD), form)

    assert "architect" not in panel.editor_options
    assert panel.editor_options == ["developer", "qa_stand"]


def test_start_role_options_end_at_selected_last_role() -> None:
    panel = DetailPanel()
    form = _form()
    form.available_stages = ["architect", "developer", "test_developer", "qa_local", "release", "qa_stand"]
    form.values["first_role"] = "release"
    form.values["last_role"] = "qa_stand"

    panel.begin_edit(NavItem(key="last_role", label="Finish Stage", section=NavSection.STANDARD), form)

    assert panel.editor_options == ["release", "qa_stand"]


def test_finish_role_developer_limits_start_role_options() -> None:
    panel = DetailPanel()
    form = _form()
    form.available_stages = ["architect", "developer", "test_developer", "qa_local", "release", "qa_stand"]
    form.values["first_role"] = "architect"
    form.values["last_role"] = "developer"

    panel.begin_edit(NavItem(key="first_role", label="Start Stage", section=NavSection.STANDARD), form)

    assert panel.editor_options == ["architect", "developer"]


def test_begin_edit_tags_uses_multi_choice_editor() -> None:
    panel = DetailPanel()
    form = _form()
    item = NavItem(key="tags", label="Tags", section=NavSection.CUSTOM)

    panel.begin_edit(item, form)

    assert panel.editor_mode == "multi_choice"
    assert panel.editor_allows_custom is True
    assert "custom-tag" in panel.editor_options
    assert panel.editor_current_value() == ["go", "custom-tag"]
    rendered = panel.render().plain
    assert "● go" in rendered
    assert "● custom-tag" in rendered
    assert all(span.style != "x" for span in panel.render().spans)
    assert "Pipeline tags" in panel.render().plain
    assert "Type:" not in panel.render().plain
    assert "Options:" not in panel.render().plain


def test_single_choice_accepts_custom_value_and_selects_it() -> None:
    panel = DetailPanel()
    form = _form()
    item = NavItem(key="namespace", label="Namespace", section=NavSection.CUSTOM)

    panel.begin_edit(item, form)
    panel.begin_custom_value_input()
    assert panel.apply_custom_value("u2-special") is True

    assert "u2-special" in panel.editor_options
    assert panel.editor_current_value() == "u2-special"


def test_multi_choice_removes_custom_value_when_unchecked() -> None:
    panel = DetailPanel()
    form = _form()
    item = NavItem(key="tags", label="Tags", section=NavSection.CUSTOM)

    panel.begin_edit(item, form)
    panel.move_editor_selection_to("custom-tag")
    panel.toggle_editor_option()

    assert "custom-tag" not in panel.editor_current_value()
    assert "custom-tag" not in panel.editor_options


def test_inline_input_css_adds_vertical_spacing_and_removes_blue_focus_border() -> None:
    css = DetailPanel.DEFAULT_CSS

    assert "DetailPanel #inline-input {" in css
    assert "layout: vertical;" in css
    assert "DetailPanel .editor-copy--top {" in css
    assert "margin-bottom: 1;" in css
    assert "DetailPanel .editor-copy--bottom {" in css
    assert "margin-top: 1;" in css
    assert "border: none;" in css
    assert "DetailPanel #inline-input:focus {" in css
    assert "border: tall #6b7280;" in css


def test_attached_text_editor_mounts_input_only() -> None:
    class DetailPanelApp(App[None]):
        def compose(self) -> ComposeResult:
            yield DetailPanel(id="panel")

    async def run() -> None:
        app = DetailPanelApp()
        async with app.run_test() as pilot:
            panel = app.query_one(DetailPanel)
            panel.begin_edit(NavItem(key="task", label="Task", section=NavSection.STANDARD), _form())
            await pilot.pause()

            children = list(panel.children)
            assert len(children) == 1
            assert isinstance(children[0], TextArea)

    asyncio.run(run())
