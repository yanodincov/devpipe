"""Right-side detail/summary panel with inline editing support."""
from __future__ import annotations

from typing import Any

from rich.text import Text

from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input, Static

from devpipe.ui.state import FieldKind, FieldMeta, FormState, NavItem, NavSection
from devpipe.ui.widgets.task_snapshot import (
    build_task_snapshot_lines,
    custom_fields_from_form,
    format_snapshot_value,
)


class DetailPanel(Widget):
    """Right panel: summary/inline-edit for the currently selected nav item."""

    DEFAULT_CSS = """
    DetailPanel {
        width: 2fr;
        layout: vertical;
        background: $surface;
        padding: 1 2;
        overflow-y: auto;
    }
    DetailPanel .editor-copy {
        width: 1fr;
        height: auto;
    }
    DetailPanel .editor-copy--top {
        margin-bottom: 1;
    }
    DetailPanel .editor-copy--bottom {
        margin-top: 1;
    }
    DetailPanel #inline-input {
        width: 1fr;
        margin: 0;
        border: none;
        padding: 0 1;
        background: $panel;
        color: $text;
    }
    DetailPanel #inline-input:focus {
        border: tall #6b7280;
    }
    """

    class FieldValueChanged(Message):
        """Emitted when user changes a field value via inline edit."""
        def __init__(self, key: str, value: Any) -> None:
            super().__init__()
            self.key = key
            self.value = value

    class ActionRequested(Message):
        """Emitted when user activates a nav action (History, Run)."""
        def __init__(self, action: str) -> None:
            super().__init__()
            self.action = action

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._current_item: NavItem | None = None
        self._form: FormState = FormState()
        self._editing: bool = False
        self._edit_field: str = ""
        self._summary_text: str = "Select an item"
        self._editor_mode: str = "none"
        self._editor_options: list[str] = []
        self._editor_selected_index: int = 0
        self._editor_selected_values: list[str] = []
        self._editor_committed_value: Any = ""
        self._editor_allows_custom: bool = False
        self._editor_custom_prompt: bool = False
        # Tag roles editor state
        self._editor_tag_roles: dict[str, list[str]] = {}
        self._editor_selected_tag: str | None = None
        self._editor_roles_options: list[str] = []
        self._editor_submode: str = ""
        self._editor_saved_options: list[str] = []
        self._editor_saved_index: int = 0  # "" or "edit_roles"

    def render(self) -> Text:
        """Render the detail panel as Rich Text."""
        return Text.from_markup(self._summary_text)

    def show_summary(self, item: NavItem, form: FormState) -> None:
        """Display current values for the selected nav item."""
        self._current_item = item
        self._form = form
        self._editing = False
        self._editor_mode = "none"
        self._editor_options = []
        self._editor_selected_index = 0
        self._editor_selected_values = []
        self._editor_committed_value = ""
        self._editor_allows_custom = False
        self._editor_custom_prompt = False
        self._editor_tag_roles = {}
        self._editor_selected_tag = None
        self._editor_roles_options = []
        self._editor_submode = ""
        self._editor_saved_options = []
        self._editor_saved_index = 0

        # Remove any mounted edit widgets
        for child in list(self.children):
            child.remove()

        lines: list[str] = []

        # If profile has errors, show only errors (no task snapshot)
        if form.profile_errors:
            lines.append("")
            lines.append("[bold white on red]  PROFILE ERRORS  [/bold white on red]")
            lines.append("")
            for error in form.profile_errors:
                # Escape brackets to prevent Textual markup parsing
                safe_error = error.replace("[", "\\[").replace("]", "\\]")
                lines.append(f"  [bold red]![/bold red] [dim]{safe_error}[/dim]")
            lines.append("")
            self._summary_text = "\n".join(lines)
            self.refresh()
            return

        if item.is_action:
            lines.extend(build_task_snapshot_lines(form.values, custom_fields_from_form(form.fields)))
            lines.append("")
            if item.key == "run":
                missing = form.missing_required()
                if missing:
                    lines.append(f"[bold red]Cannot run:[/bold red] Missing: {', '.join(missing)}")
                else:
                    lines.append("[bold green]Ready to run pipeline[/bold green]")
                    lines.append("\n[dim]Press Enter to start the pipeline[/dim]")
            elif item.key == "history":
                lines.append("[dim]Press Enter to open history[/dim]")
            self._summary_text = "\n".join(lines)
            self.refresh()
            return

        value = form.values.get(item.key, "")
        field_meta = form.field_by_key(item.key)

        lines.extend(build_task_snapshot_lines(form.values, custom_fields_from_form(form.fields), item.key))
        self._add_field_detail(lines, item.key, value, field_meta, form)

        self._summary_text = "\n".join(lines)
        self.refresh()

    def _add_field_detail(self, lines: list[str], key: str, value: Any, field_meta: FieldMeta | None, form: FormState) -> None:
        """Add detail view for a custom field."""
        if field_meta:
            if field_meta.description:
                lines.append(f"\n  [dim]{field_meta.description}[/dim]")
            if field_meta.required:
                lines.append("  [yellow]Required[/yellow]")
            return

        description, _type_name, _options = self._standard_field_details(key, form)
        if description:
            lines.append(f"\n  [dim]{description}[/dim]")

    def _standard_field_details(self, key: str, form: FormState) -> tuple[str, str, list[str]]:
        if key == "profile":
            return ("Active project profile", "select", list(form.available_profiles))
        if key == "runner":
            return ("Runner selection mode", "select", list(form.available_runners))
        if key == "model":
            return ("Model level override for all stages", "select", list(form.available_models))
        if key == "effort":
            return ("Reasoning effort override for all stages", "select", list(form.available_efforts))
        if key == "tags":
            field_meta = form.field_by_key("tags")
            if field_meta and field_meta.kind == FieldKind.TAG_ROLES:
                return ("Assign tags to agents (stages)", "tag_roles", list(field_meta.options) if field_meta else [])
            return ("Pipeline tags (list)", "multi_select", list(field_meta.options) if field_meta else [])
        if key == "first_role":
            return ("Start agent in the pipeline", "select", self._bounded_stage_options(form, key))
        if key == "last_role":
            return ("Finish agent in the pipeline", "select", self._bounded_stage_options(form, key))
        return ("Task text passed to the pipeline", "text", [])

    @staticmethod
    def _bounded_stage_options(form: FormState, key: str) -> list[str]:
        stages = list(form.available_stages)
        if not stages:
            return []
        first = form.values.get("first_role")
        last = form.values.get("last_role")
        routing_graph = form.routing_graph

        if not routing_graph:
            if key == "first_role" and last in stages:
                return stages[: stages.index(last) + 1]
            if key == "last_role" and first in stages:
                return stages[stages.index(first):]
            return stages

        from devpipe.ui.services import _get_finish_options_for_start

        profile_stage_names = stages
        if key == "first_role":
            return list(profile_stage_names)
        if key == "last_role":
            if first not in profile_stage_names:
                first = profile_stage_names[0] if profile_stage_names else ""
            if first:
                return _get_finish_options_for_start(routing_graph, first, profile_stage_names)
            return list(profile_stage_names) + ["failed"]
        return stages

    def begin_edit(self, item: NavItem, form: FormState) -> None:
        """Switch to inline-edit mode for the current field."""
        if item.is_action:
            self.post_message(self.ActionRequested(item.key))
            return

        self._editing = True
        self._current_item = item
        self._edit_field = item.key
        self._form = form
        self._editor_mode = "none"
        self._editor_options = []
        self._editor_selected_index = 0
        self._editor_selected_values = []
        self._editor_committed_value = ""
        self._editor_allows_custom = False
        self._editor_custom_prompt = False

        # Remove any children first
        for child in list(self.children):
            child.remove()

        value = form.values.get(item.key, "")
        field_meta = form.field_by_key(item.key)
        kind = field_meta.kind if field_meta else FieldKind.STRING

        if item.key == "profile":
            self._setup_single_choice_editor(item.label, value, form.available_profiles)
        elif item.key == "runner":
            self._setup_single_choice_editor(item.label, value, form.available_runners)
        elif item.key == "model":
            self._setup_single_choice_editor(item.label, value, form.available_models)
        elif item.key == "effort":
            self._setup_single_choice_editor(item.label, value, form.available_efforts)
        elif item.key in ("first_role", "last_role"):
            self._setup_single_choice_editor(item.label, value, self._bounded_stage_options(form, item.key))
        elif item.key == "tags" and field_meta and field_meta.kind == FieldKind.TAG_ROLES:
            self._setup_tag_roles_editor(item.label, value, field_meta)
        elif kind == FieldKind.SELECT and field_meta and field_meta.options:
            self._setup_single_choice_editor(item.label, value, field_meta.options, allow_custom=field_meta.custom)
        elif kind == FieldKind.MULTI_SELECT and field_meta:
            self._setup_multi_choice_editor(item.label, value, field_meta.options, allow_custom=field_meta.custom)
        elif kind == FieldKind.ARRAY:
            self._mount_text_editor(item.key, ", ".join(value) if isinstance(value, list) else str(value))
        elif kind == FieldKind.OBJECT:
            if isinstance(value, dict):
                text = ", ".join(f"{k}={v}" for k, v in value.items())
            else:
                text = str(value) if value else ""
            self._mount_text_editor(item.key, text)
        else:
            self._mount_text_editor(item.key, str(value) if value else "")

        self.refresh()

    def _setup_single_choice_editor(self, label: str, current: Any, options: list[str], allow_custom: bool = False) -> None:
        self._editing = True
        self._editor_mode = "single_choice"
        self._editor_allows_custom = allow_custom
        self._editor_options = self._normalize_options(options, current)
        # Normalize bool to lowercase string for matching
        if isinstance(current, bool):
            current_str = "true" if current else "false"
        else:
            current_str = str(current) if current not in (None, "") else ""
        self._editor_selected_index = self._editor_options.index(current_str) if current_str in self._editor_options else 0
        self._editor_committed_value = current_str
        self._summary_text = self._render_choice_editor(label, multi=False)

    def _setup_multi_choice_editor(self, label: str, current: Any, options: list[str], allow_custom: bool = False) -> None:
        self._editing = True
        self._editor_mode = "multi_choice"
        self._editor_allows_custom = allow_custom
        current_values = [str(v) for v in current] if isinstance(current, list) else ([str(current)] if current else [])
        self._editor_selected_values = current_values
        self._editor_committed_value = list(current_values)
        self._editor_options = self._normalize_options(options, current_values)
        self._editor_selected_index = 0
        self._summary_text = self._render_choice_editor(label, multi=True)

    def _setup_tag_roles_editor(self, label: str, current: Any, field_meta: Any) -> None:
        """Setup editor for managing tags with per-role activation.

        Current value is dict[tag_name, list[roles]].
        """
        self._editing = True
        self._editor_mode = "tag_roles"
        # Copy current tag_roles dict
        self._editor_tag_roles = dict(current) if isinstance(current, dict) else {}
        # Ensure all selected tags have a roles entry
        for tag in list(self._editor_tag_roles.keys()):
            if not isinstance(self._editor_tag_roles[tag], list):
                self._editor_tag_roles[tag] = []
        # Options: all available tags
        self._editor_options = list(field_meta.options)
        # Start with first tag selected if any, else none
        self._editor_selected_index = 0 if self._editor_options else -1
        self._editor_selected_tag = self._editor_options[0] if self._editor_options else None
        self._editor_submode = ""  # main list
        self._editor_roles_options = []
        self._editor_saved_options = []
        self._editor_saved_index = 0
        self._summary_text = self._render_tag_roles_editor(label, field_meta)

    def _render_tag_roles_editor(self, label: str, field_meta: Any) -> str:
        lines = []

        if self._editor_submode == "edit_roles" and self._editor_selected_tag:
            lines.append(f"  Agents for [bold]{self._editor_selected_tag}[/bold]:")
            lines.append("")
            current_agents = set(self._editor_tag_roles.get(self._editor_selected_tag, []))
            for i, agent in enumerate(self._editor_options):
                cursor = "▸" if i == self._editor_selected_index else " "
                mark = "●" if agent in current_agents else "○"
                lines.append(f" {cursor} {mark} {agent}")
        else:
            for i, tag in enumerate(self._editor_options):
                cursor = "▸" if i == self._editor_selected_index else " "
                agents = self._editor_tag_roles.get(tag, [])
                marks = f"({', '.join(agents) if agents else '...'})"
                mark = "●" if tag in self._editor_tag_roles else "○"
                lines.append(f" {cursor} {mark} {tag} {marks}")

        return "\n".join(lines)

    @staticmethod
    def _normalize_options(options: list[str], current: Any) -> list[str]:
        result = [str(option) for option in options]
        current_values = current if isinstance(current, list) else [current]
        for value in current_values:
            if value in (None, ""):
                continue
            # Normalize bool to lowercase string
            if isinstance(value, bool):
                string_value = "true" if value else "false"
            else:
                string_value = str(value)
            if string_value not in result:
                result.append(string_value)
        return result

    def _mount_text_editor(self, key: str, value: str) -> None:
        self._summary_text = ""
        if not self.is_attached:
            self.refresh()
            return
        self._mount_inline_input(
            title_markup="",
            input_value=value,
            placeholder=f"Enter {key}",
        )

    def _mount_custom_value_input(self) -> None:
        self._editor_custom_prompt = True
        self._summary_text = ""
        if not self.is_attached:
            self.refresh()
            return
        self._mount_inline_input(
            title_markup="",
            input_value="",
            placeholder="Custom value",
        )
        self.refresh()

    def _mount_inline_input(
        self,
        title_markup: str,
        input_value: str,
        placeholder: str,
    ) -> None:
        self._summary_text = ""
        if title_markup:
            top = Static(title_markup, classes="editor-copy editor-copy--top")
            self.mount(top)
        inp = Input(value=input_value, placeholder=placeholder, id="inline-input")
        self.mount(inp)
        inp.focus()

    def _render_choice_editor(self, label: str, multi: bool) -> str:
        lines = []
        description, _type_name, _options = self._standard_field_details(self._edit_field, self._form)
        field_meta = self._form.field_by_key(self._edit_field)
        if field_meta is not None:
            description = field_meta.description or description
        if description:
            lines.append(f"  [dim]{description}[/dim]")
            lines.append("")
        for index, option in enumerate(self._editor_options):
            cursor = "▸" if index == self._editor_selected_index else " "
            if multi:
                mark = "●" if option in self._editor_selected_values else "○"
                lines.append(f" {cursor} {mark} {option}")
            else:
                mark = "●" if index == self._editor_selected_index else "○"
                lines.append(f" {cursor} {mark} {option}")
        if self._editor_allows_custom:
            cursor = "▸" if self._editor_selected_index == len(self._editor_options) else " "
            lines.append(f" {cursor} + Add custom value")
        return "\n".join(lines)

    def is_choice_editor_active(self) -> bool:
        return self._editing and self._editor_mode in {"single_choice", "multi_choice", "tag_roles"}

    def is_custom_input_active(self) -> bool:
        return self._editing and self._editor_custom_prompt

    @property
    def editor_mode(self) -> str:
        return self._editor_mode

    @property
    def editor_submode(self) -> str:
        return getattr(self, "_editor_submode", "")

    @property
    def editor_options(self) -> list[str]:
        return list(self._editor_options)

    @property
    def editor_allows_custom(self) -> bool:
        return self._editor_allows_custom

    def editor_current_value(self) -> Any:
        if self._editor_mode == "single_choice":
            if not self._editor_options:
                return ""
            return self._editor_options[self._editor_selected_index]
        if self._editor_mode == "multi_choice":
            return list(self._editor_selected_values)
        if self._editor_mode == "tag_roles":
            # Return only tags that have at least one role selected
            result = {tag: roles for tag, roles in self._editor_tag_roles.items() if roles}
            return result
        return ""

    def move_editor_up(self) -> None:
        if not self.is_choice_editor_active():
            return
        if self._editor_selected_index > 0:
            self._editor_selected_index -= 1
            self._refresh_editor_text()

    def move_editor_down(self) -> None:
        if not self.is_choice_editor_active():
            return
        max_index = len(self._editor_options) - 1 + (1 if self._editor_allows_custom else 0)
        if self._editor_selected_index < max_index:
            self._editor_selected_index += 1
            self._refresh_editor_text()

    def move_editor_selection_to(self, option: str) -> None:
        if option in self._editor_options:
            self._editor_selected_index = self._editor_options.index(option)
            self._refresh_editor_text()

    def toggle_editor_option(self) -> bool:
        if self._editor_mode != "multi_choice":
            return False
        if self._editor_selected_index >= len(self._editor_options):
            return False
        option = self._editor_options[self._editor_selected_index]
        if option in self._editor_selected_values:
            self._editor_selected_values.remove(option)
            if option not in self._form.field_by_key(self._edit_field).options:  # type: ignore[union-attr]
                self._editor_options.remove(option)
                self._editor_selected_index = min(self._editor_selected_index, max(0, len(self._editor_options) - 1))
        else:
            self._editor_selected_values.append(option)
        self._editor_committed_value = list(self._editor_selected_values)
        self._refresh_editor_text()
        return True

    def editor_activate(self) -> str:
        if self._editor_mode == "single_choice":
            if self._editor_selected_index < len(self._editor_options):
                self._editor_committed_value = self._editor_options[self._editor_selected_index]
                self._refresh_editor_text()
                return "confirm"
            return "custom"
        if self._editor_mode == "multi_choice":
            if self._editor_selected_index < len(self._editor_options):
                self.toggle_editor_option()
                return "toggle"
            return "custom"
        if self._editor_mode == "tag_roles":
            if not self._editor_options:
                return "none"
            if self._editor_submode == "edit_roles":
                tag = self._editor_selected_tag
                if not tag:
                    return "none"
                available_roles = self._editor_roles_options
                if self._editor_selected_index < len(available_roles):
                    role = available_roles[self._editor_selected_index]
                    current = set(self._editor_tag_roles.get(tag, []))
                    if role in current:
                        current.remove(role)
                        # Remove tag entirely if no agents left
                        if not current:
                            if tag in self._editor_tag_roles:
                                del self._editor_tag_roles[tag]
                        else:
                            self._editor_tag_roles[tag] = sorted(current)
                    else:
                        current.add(role)
                        self._editor_tag_roles[tag] = sorted(current)
                    self._refresh_editor_text()
                    return "toggle"
                return "none"
            else:
                # Main mode: add tag with empty roles, then enter edit_roles
                tag = self._editor_options[self._editor_selected_index]
                if tag not in self._editor_tag_roles:
                    # Add tag with empty roles (user must select agents explicitly)
                    self._editor_tag_roles[tag] = []
                self._editor_selected_tag = tag
                # Save current main list state before switching
                self._editor_saved_options = list(self._editor_options)
                self._editor_saved_index = self._editor_selected_index
                self._editor_submode = "edit_roles"
                # Switch to roles list for this tag (sorted)
                field_meta = self._form.field_by_key(self._edit_field)
                self._editor_roles_options = sorted(field_meta.extra.get(tag, [])) if field_meta else []
                self._editor_options = self._editor_roles_options
                self._editor_selected_index = 0
                self._refresh_editor_text()
                return "edit_roles"  # don't close editor, just switch submode
        return "none"

    def begin_custom_value_input(self) -> None:
        if not self._editor_allows_custom:
            return
        self._mount_custom_value_input()

    def apply_custom_value(self, raw_value: str) -> bool:
        value = raw_value.strip()
        if not value:
            return False
        # Validate int fields - check if all options are integers
        if self._edit_field:
            field_meta = self._form.field_by_key(self._edit_field)
            if field_meta and field_meta.kind in (FieldKind.INT, FieldKind.SELECT):
                # Check if all predefined options are integers
                all_int = field_meta.kind == FieldKind.INT or all(
                    self._is_int(opt) for opt in field_meta.options
                )
                if all_int:
                    try:
                        int(value)
                    except ValueError:
                        return False
        if value not in self._editor_options:
            self._editor_options.append(value)
        if self._editor_mode == "single_choice":
            self._editor_selected_index = self._editor_options.index(value)
            self._editor_committed_value = value
        elif self._editor_mode == "multi_choice" and value not in self._editor_selected_values:
            self._editor_selected_values.append(value)
            self._editor_selected_index = self._editor_options.index(value)
            self._editor_committed_value = list(self._editor_selected_values)
        self._editor_custom_prompt = False
        for child in list(self.children):
            child.remove()
        self._refresh_editor_text()
        return True

    @staticmethod
    def _is_int(s: str) -> bool:
        try:
            int(s)
            return True
        except ValueError:
            return False

    def _refresh_editor_text(self) -> None:
        if not self._current_item:
            return
        if self._editor_mode == "tag_roles":
            field_meta = self._form.field_by_key(self._edit_field)
            self._summary_text = self._render_tag_roles_editor(
                self._current_item.label,
                field_meta,
            )
        else:
            self._summary_text = self._render_choice_editor(
                self._current_item.label,
                multi=self._editor_mode == "multi_choice",
            )
        self.refresh()

    def cancel_submode(self) -> None:
        """Exit from tag_roles edit_roles submode back to main tag list."""
        if self._editor_mode == "tag_roles" and self._editor_submode == "edit_roles":
            # Restore main list options and index
            self._editor_options = self._editor_saved_options
            self._editor_selected_index = self._editor_saved_index
            self._editor_submode = ""
            self._refresh_editor_text()

    def toggle_current_tag(self) -> None:
        """Toggle the current tag in the main list (add/remove with empty roles if adding)."""
        if self._editor_mode != "tag_roles" or self._editor_submode:
            return
        if not self._editor_options or self._editor_selected_index >= len(self._editor_options):
            return
        tag = self._editor_options[self._editor_selected_index]
        if tag in self._editor_tag_roles:
            # Remove tag
            del self._editor_tag_roles[tag]
        else:
            # Add tag with empty roles (user must select agents explicitly)
            self._editor_tag_roles[tag] = []
        self._refresh_editor_text()
