"""Pure state transitions (actions/reducers) for the UI.

Each function takes UIState (or relevant sub-state) and returns a new state.
No Textual or I/O here.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from devpipe.history import RunHistoryEntry
from devpipe.ui.state import (
    FieldEditorState,
    FieldKind,
    FieldMeta,
    FormState,
    NavSection,
    RunViewState,
    StageAttempt,
    UIState,
    build_nav_items,
    derive_status_bar,
)


def load_defaults(
    state: UIState,
    profile: str,
    available_profiles: list[str],
    available_stages: list[str],
    fields: list[FieldMeta],
    defaults: dict[str, Any],
    available_runners: list[str] | None = None,
    available_tags: list[str] | None = None,
    profile_errors: list[str] | None = None,
    routing_graph: dict[str, set[str]] | None = None,
) -> UIState:
    """Initialize form with profile metadata and default values."""
    new = deepcopy(state)
    new.form.profile = profile
    new.form.available_profiles = available_profiles
    new.form.available_stages = available_stages
    new.form.fields = fields
    new.form.values = dict(defaults)
    if available_runners is not None:
        new.form.available_runners = available_runners
    if available_tags is not None:
        new.form.available_tags = available_tags
    new.form.profile_errors = profile_errors or []
    new.form.routing_graph = routing_graph if routing_graph is not None else {}

    # Ensure standard field defaults
    new.form.values.setdefault("profile", profile)
    new.form.values.setdefault("task", "")
    new.form.values.setdefault("runner", "auto")
    new.form.values.setdefault("model", "auto")
    new.form.values.setdefault("effort", "auto")
    new.form.values.setdefault("first_role", available_stages[0] if available_stages else "")
    new.form.values.setdefault("last_role", "")  # Empty by default

    new.nav_items = build_nav_items(new.form)
    new.status_bar = derive_status_bar(new.form)
    new.selected_nav_index = 0
    new.editor = FieldEditorState()
    return new


def select_nav_item(state: UIState, index: int) -> UIState:
    """Move cursor to a specific nav item."""
    new = deepcopy(state)
    if 0 <= index < len(new.nav_items):
        new.selected_nav_index = index
    return new


def select_profile(
    state: UIState,
    profile: str,
    fields: list[FieldMeta],
    defaults: dict[str, Any],
    available_stages: list[str],
    profile_errors: list[str] | None = None,
    routing_graph: dict[str, set[str]] | None = None,
) -> UIState:
    """Switch profile — completely replace fields and defaults, preserve only compatible values."""
    new = deepcopy(state)
    old_values = new.form.values.copy()

    new.form.profile = profile
    new.form.fields = fields
    new.form.available_stages = available_stages
    new.form.profile_errors = profile_errors or []
    new.form.routing_graph = routing_graph if routing_graph is not None else {}

    # Start with defaults from profile
    new_values = dict(defaults)
    new_values["profile"] = profile

    # Preserve only global preferences (non-custom, profile-agnostic) across profiles
    for key in ("task", "runner", "model", "effort"):
        if key in old_values:
            new_values[key] = old_values[key]

    # Always reset first_role and last_role to bounds of new profile
    if available_stages:
        new_values["first_role"] = available_stages[0]
        new_values["last_role"] = ""  # Empty by default, must be explicitly set
    else:
        new_values["first_role"] = ""
        new_values["last_role"] = ""

    # Validate runner
    if new_values.get("runner") not in new.form.available_runners:
        new_values["runner"] = "auto"

    new.form.values = new_values
    new.nav_items = build_nav_items(new.form)
    new.status_bar = derive_status_bar(new.form)
    new.editor = FieldEditorState()

    # Reset nav selection if needed
    if new.selected_nav_index >= len(new.nav_items):
        new.selected_nav_index = 0

    return new


def set_field_value(state: UIState, key: str, value: Any) -> UIState:
    """Set a form field value."""
    new = deepcopy(state)
    new.form.values[key] = value
    stages = new.form.available_stages
    first = new.form.values.get("first_role")
    last = new.form.values.get("last_role")
    if stages and first in stages and last in stages:
        first_index = stages.index(first)
        last_index = stages.index(last)
        if first_index > last_index:
            if key == "first_role":
                new.form.values["last_role"] = first
            elif key == "last_role":
                new.form.values["first_role"] = last
    new.status_bar = derive_status_bar(new.form)
    return new


def begin_inline_edit(state: UIState, field_key: str) -> UIState:
    """Open inline editor for a field."""
    new = deepcopy(state)
    current_value = new.form.values.get(field_key, "")
    new.editor = FieldEditorState(
        field_key=field_key,
        editing=True,
        draft_value=current_value,
    )
    return new


def cancel_inline_edit(state: UIState) -> UIState:
    """Cancel inline editor without applying."""
    new = deepcopy(state)
    new.editor = FieldEditorState()
    return new


def apply_inline_edit(state: UIState) -> UIState:
    """Apply inline edit value to form."""
    new = deepcopy(state)
    if new.editor.editing and new.editor.field_key:
        new.form.values[new.editor.field_key] = new.editor.draft_value
        new.status_bar = derive_status_bar(new.form)
    new.editor = FieldEditorState()
    return new


def apply_history_entry(state: UIState, entry: RunHistoryEntry | dict) -> UIState:
    """Load values from a history entry into the form."""
    from devpipe.history import RunHistoryEntry
    from devpipe.tags import load_available_tags

    new = deepcopy(state)

    # Extract config dict if entry is RunHistoryEntry, else assume dict-like
    if isinstance(entry, RunHistoryEntry):
        config = entry.config
    else:
        config = entry

    def _infer_kind(value: Any) -> FieldKind:
        if isinstance(value, bool):
            return FieldKind.SELECT
        if isinstance(value, list):
            return FieldKind.ARRAY
        if isinstance(value, dict):
            return FieldKind.OBJECT
        if isinstance(value, int):
            return FieldKind.INT
        return FieldKind.STRING

    field_mapping = {
        "task": "task",
        "task_id": "task_id",
        "runner": "runner",
        "model": "model",
        "effort": "effort",
        "target_branch": "target_branch",
        "service": "service",
        "namespace": "namespace",
        "first_role": "first_role",
        "last_role": "last_role",
    }

    for hist_key, form_key in field_mapping.items():
        if hist_key in config:
            new.form.values[form_key] = config[hist_key]

    # Handle tags: prefer tag_roles dict; if legacy tags list, convert using available tags
    tag_roles = config.get("tag_roles")
    if tag_roles and isinstance(tag_roles, dict):
        new.form.values["tags"] = tag_roles
    else:
        tags_list = config.get("tags", [])
        if tags_list:
            # Convert list to dict with all available stages for each tag
            cwd = Path.cwd()  # FIXME: use project root from state? but we don't have it here
            available_tags = load_available_tags(cwd)
            converted: dict[str, list[str]] = {}
            for tag in tags_list:
                if tag in available_tags:
                    stages = available_tags[tag].stages
                    if stages:
                        converted[tag] = stages
            new.form.values["tags"] = converted
        else:
            new.form.values["tags"] = {}

    # Merge custom params from both modern extra_params and direct config keys.
    existing_keys = {field.key for field in new.form.fields}
    restored_custom = {}
    extra = config.get("extra_params", {})
    if isinstance(extra, dict):
        restored_custom.update(extra)

    known_keys = set(field_mapping) | {"profile", "tags", "tag_roles", "extra_params"}
    for key, value in config.items():
        if key in known_keys:
            continue
        if key in existing_keys or key not in new.form.values:
            restored_custom.setdefault(key, value)

    for k, v in restored_custom.items():
        new.form.values[k] = v
        if k not in existing_keys:
            new.form.fields.append(
                FieldMeta(
                    key=k,
                    label=k.replace("_", " ").title(),
                    kind=_infer_kind(v),
                    section="custom",
                )
            )
            existing_keys.add(k)

    # Validate runner
    if new.form.values.get("runner") not in new.form.available_runners:
        new.form.values["runner"] = "auto"

    # Validate stages
    stages = new.form.available_stages
    if new.form.values.get("first_role") not in stages:
        new.form.values["first_role"] = stages[0] if stages else ""
    # last_role can be empty (means run until completed/failed)
    last_val = new.form.values.get("last_role")
    if last_val and last_val not in stages:
        # Only reset if it's a non-empty invalid value
        new.form.values["last_role"] = ""

    new.nav_items = build_nav_items(new.form)
    new.status_bar = derive_status_bar(new.form)
    new.editor = FieldEditorState()
    return new


def start_run(state: UIState, run_id: str, stages: list[str], runner: str, model: str, effort: str) -> UIState:
    """Transition to run state. Timeline starts empty — stages are added as they are activated."""
    new = deepcopy(state)
    new.active_screen = "run"
    new.run_view = RunViewState(
        run_id=run_id,
        status="running",
        timeline=[],
        runner_name=runner,
        model_name=model,
        effort=effort,
    )
    return new


def append_run_output(state: UIState, text: str) -> UIState:
    """Append output lines to the run log."""
    new = deepcopy(state)
    lines = text.split("\n")
    new.run_view.log_lines.extend(lines)
    return new


def complete_stage_attempt(
    state: UIState,
    stage: str,
    status: str = "done",
    summary: str = "",
    error: str = "",
    tokens: int = 0,
) -> UIState:
    """Mark a stage attempt as done/failed in the timeline."""
    new = deepcopy(state)
    for attempt in new.run_view.timeline:
        if attempt.stage == stage and attempt.status == "active":
            attempt.status = status
            attempt.summary = summary
            attempt.error = error
            attempt.tokens = tokens
            break
    new.run_view.total_tokens += tokens
    return new


def begin_stage(state: UIState, stage: str, runner: str, model: str, effort: str) -> UIState:
    """Mark a stage as active in the timeline."""
    new = deepcopy(state)
    new.run_view.active_stage = stage
    new.run_view.runner_name = runner
    new.run_view.model_name = model
    new.run_view.effort = effort

    for attempt in new.run_view.timeline:
        if attempt.stage == stage and attempt.status == "active":
            return new

    # Find the pending attempt for this stage and activate it
    for attempt in new.run_view.timeline:
        if attempt.stage == stage and attempt.status == "pending":
            attempt.status = "active"
            break
    else:
        # Retry: add a new attempt
        existing = [a for a in new.run_view.timeline if a.stage == stage]
        attempt_num = len(existing) + 1
        new.run_view.timeline.append(
            StageAttempt(stage=stage, attempt_number=attempt_num, status="active")
        )

    return new


def finish_run(state: UIState, status: str, run_id: str) -> UIState:
    """Mark the run as complete."""
    new = deepcopy(state)
    new.run_view.status = status
    new.run_view.run_id = run_id
    return new
