"""Pure UI state models for the Textual Command Palette + Summary Pane layout.

No Textual/terminal I/O here — only typed dataclasses and derived views.
State is driven by profile metadata, not by old roles/STAGE_ORDER.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FieldKind(str, Enum):
    """Kind of input field in the config form."""
    STRING = "string"
    INT = "int"
    SELECT = "select"
    MULTI_SELECT = "multi_select"
    ARRAY = "array"
    OBJECT = "object"
    TAG_ROLES = "tag_roles"  # special field for managing tags with per-role activation


@dataclass
class FieldMeta:
    """Metadata for a single editable field."""
    key: str
    label: str
    kind: FieldKind = FieldKind.STRING
    required: bool = False
    options: list[str] = field(default_factory=list)
    default: Any = ""
    description: str = ""
    section: str = "custom"  # "standard" or "custom"
    custom: bool = False  # Allow custom values for SELECT/MULTI_SELECT
    # Extra metadata for special field kinds (e.g., tag_roles: {tag_name: [available_roles]})
    extra: dict[str, Any] = field(default_factory=dict)


class NavSection(str, Enum):
    STANDARD = "Standard"
    CUSTOM = "Custom"
    ACTIONS = "Actions"


@dataclass
class NavItem:
    """One entry in the left navigation column."""
    key: str
    label: str
    section: NavSection
    is_action: bool = False
    badge: str = ""


@dataclass
class FieldEditorState:
    """State of the inline editor in the detail pane."""
    field_key: str | None = None
    editing: bool = False
    draft_value: Any = None
    error: str = ""


@dataclass
class FormState:
    """All form values + field metadata for the config screen."""
    values: dict[str, Any] = field(default_factory=dict)
    fields: list[FieldMeta] = field(default_factory=list)
    profile: str = ""
    available_profiles: list[str] = field(default_factory=list)
    available_runners: list[str] = field(default_factory=lambda: ["auto"])
    available_models: list[str] = field(default_factory=lambda: ["auto", "low", "middle", "high"])
    available_efforts: list[str] = field(default_factory=lambda: ["auto", "low", "middle", "high", "extra"])
    available_stages: list[str] = field(default_factory=list)
    available_tags: list[str] = field(default_factory=list)
    profile_errors: list[str] = field(default_factory=list)  # Validation/loading errors from profile
    routing_graph: dict[str, set[str]] = field(default_factory=dict)  # stage -> possible next stages

    def field_by_key(self, key: str) -> FieldMeta | None:
        for f in self.fields:
            if f.key == key:
                return f
        return None

    def missing_required(self) -> list[str]:
        missing = []
        # 'task' is always required (standard field)
        if not self.values.get("task"):
            missing.append("task")
        # Check custom fields
        for f in self.fields:
            if f.required:
                val = self.values.get(f.key)
                if not val:
                    missing.append(f.key)
        return missing

    @property
    def is_ready(self) -> bool:
        return len(self.missing_required()) == 0 and len(self.profile_errors) == 0


@dataclass
class StatusBarState:
    """Bottom status bar state."""
    left_text: str = ""
    center_text: str = ""
    right_text: str = ""
    is_ready: bool = False
    validation_errors: list[str] = field(default_factory=list)


@dataclass
class StageAttempt:
    """One stage execution attempt on the run screen."""
    stage: str
    attempt_number: int
    status: str = "pending"  # pending, active, done, failed, skipped
    summary: str = ""
    error: str = ""
    elapsed_seconds: float = 0.0
    tokens: int = 0


@dataclass
class RunViewState:
    """State for the run screen."""
    run_id: str = ""
    status: str = "idle"  # idle, running, completed, failed
    timeline: list[StageAttempt] = field(default_factory=list)
    active_stage: str = ""
    active_attempt: int = 0
    log_lines: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    runner_name: str = ""
    model_name: str = ""
    effort: str = ""
    total_tokens: int = 0


@dataclass
class UIState:
    """Top-level UI state container."""
    form: FormState = field(default_factory=FormState)
    editor: FieldEditorState = field(default_factory=FieldEditorState)
    status_bar: StatusBarState = field(default_factory=StatusBarState)
    run_view: RunViewState = field(default_factory=RunViewState)

    nav_items: list[NavItem] = field(default_factory=list)
    selected_nav_index: int = 0
    active_screen: str = "config"  # config, history, run
    show_prompt: bool = False

    @property
    def selected_nav_item(self) -> NavItem | None:
        if 0 <= self.selected_nav_index < len(self.nav_items):
            return self.nav_items[self.selected_nav_index]
        return None

    def nav_items_by_section(self, section: NavSection) -> list[NavItem]:
        return [item for item in self.nav_items if item.section == section]


def build_nav_items(form: FormState) -> list[NavItem]:
    """Build the left-column navigation from current form state.

    Structure:
      Standard: Profile, Task, Runner, Start Stage, Finish Stage, (optional Tags)
      Custom: all profile-driven inputs as flat list
      Actions: History, Run Pipeline
    """
    items: list[NavItem] = []

    # Determine if tags field is present
    has_tags_field = any(f.key == "tags" for f in form.fields)

    # Standard section
    standard_fields = [
        ("profile", "Profile"),
        ("task", "Task"),
        ("runner", "Runner"),
        ("model", "Model"),
        ("effort", "Effort"),
    ]
    if has_tags_field:
        standard_fields.append(("tags", "Tags"))
    standard_fields += [
        ("first_role", "Start Agent"),
        ("last_role", "Finish Agent"),
    ]
    for key, label in standard_fields:
        items.append(NavItem(key=key, label=label, section=NavSection.STANDARD))

    # Custom section — profile-driven inputs, flat list
    for f in form.fields:
        if f.section == "custom" and f.key != "tags":
            items.append(NavItem(key=f.key, label=f.label, section=NavSection.CUSTOM))

    # Actions section
    items.append(NavItem(key="history", label="History", section=NavSection.ACTIONS, is_action=True))
    items.append(NavItem(key="run", label="Run Pipeline", section=NavSection.ACTIONS, is_action=True))

    return items


def derive_status_bar(form: FormState) -> StatusBarState:
    """Derive status bar state from current form."""
    # Profile errors take precedence - can't run with invalid config
    if form.profile_errors:
        return StatusBarState(
            left_text="↑↓ navigate  Enter edit",
            center_text=f"{len(form.profile_errors)} error(s)",
            right_text="ERROR",
            is_ready=False,
            validation_errors=form.profile_errors,
        )
    
    missing = form.missing_required()
    if missing:
        errors = [f"{k} is required" for k in missing]
        return StatusBarState(
            left_text="↑↓ navigate  Enter edit",
            center_text=f"{len(errors)} error(s)",
            right_text="NOT READY",
            is_ready=False,
            validation_errors=errors,
        )
    
    return StatusBarState(
        left_text="↑↓ navigate  Enter edit",
        center_text="All fields set",
        right_text="READY",
        is_ready=True,
    )
