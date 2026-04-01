"""Config screen: Command Palette + Summary Pane layout.

Left column: Standard / Custom / Actions sections
Right panel: inline-edit and field summary
Bottom: status bar with shortcuts and readiness
"""
from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Input, TextArea

from devpipe.ui.state import (
    FieldKind,
    FormState,
    NavItem,
    NavSection,
    UIState,
    build_nav_items,
    derive_status_bar,
)
from devpipe.ui.widgets.detail_panel import DetailPanel
from devpipe.ui.widgets.nav_list import NavList
from devpipe.ui.widgets.status_bar import StatusBar
from devpipe.ui.actions import set_field_value


class ConfigScreen(Screen):
    """Main config screen with Command Palette + Summary Pane."""

    BINDINGS = [
        Binding("up", "nav_up", "Up", show=False),
        Binding("down", "nav_down", "Down", show=False),
        Binding("enter", "activate", "Edit/Confirm", show=False),
        Binding("space", "toggle_tag", "Toggle tag", show=False),
        Binding("escape", "cancel", "Cancel/Back", show=False),
        Binding("ctrl+h", "open_history", "History", show=True),
        Binding("ctrl+r", "run_pipeline", "Run Pipeline", show=True),
    ]

    DEFAULT_CSS = """
    ConfigScreen {
        layout: vertical;
    }
    ConfigScreen .config-main {
        height: 1fr;
    }
    """

    def __init__(self, ui_state: UIState, **kwargs) -> None:
        super().__init__(**kwargs)
        self._state = ui_state
        self._editing = False
        self._focus_on_nav = True

    def compose(self) -> ComposeResult:
        with Horizontal(classes="config-main"):
            nav = NavList(self._state.nav_items, id="nav-list")
            nav._profile = self._state.form.profile
            yield nav
            yield DetailPanel(id="detail-panel")
        yield StatusBar(show_prompt=self._state.show_prompt, id="status-bar")

    def on_mount(self) -> None:
        self._update_display()

    def _update_display(self) -> None:
        """Refresh all widgets from current state."""
        nav = self.query_one("#nav-list", NavList)
        detail = self.query_one("#detail-panel", DetailPanel)
        status = self.query_one("#status-bar", StatusBar)
        
        nav.set_items(self._state.nav_items, profile=self._state.form.profile)
        nav.selected_index = self._state.selected_nav_index

        item = self._state.selected_nav_item
        if item:
            detail.show_summary(item, self._state.form)

        self._state.status_bar = derive_status_bar(self._state.form)
        status.update_state(self._state.status_bar)

    def _sync_app_state(self) -> None:
        try:
            self.app._ui_state = self._state
        except Exception:
            pass

    # ── Navigation ────────────────────────────────────────────────────────

    def action_nav_up(self) -> None:
        if self._editing:
            detail = self.query_one("#detail-panel", DetailPanel)
            if detail.is_choice_editor_active():
                detail.move_editor_up()
            return
        nav = self.query_one("#nav-list", NavList)
        nav.move_up()
        self._state.selected_nav_index = nav.selected_index
        self._sync_app_state()
        self._show_current_summary()

    def action_nav_down(self) -> None:
        if self._editing:
            detail = self.query_one("#detail-panel", DetailPanel)
            if detail.is_choice_editor_active():
                detail.move_editor_down()
            return
        nav = self.query_one("#nav-list", NavList)
        nav.move_down()
        self._state.selected_nav_index = nav.selected_index
        self._sync_app_state()
        self._show_current_summary()

    def _show_current_summary(self) -> None:
        item = self._state.selected_nav_item
        if item:
            detail = self.query_one("#detail-panel", DetailPanel)
            detail.show_summary(item, self._state.form)
            status = self.query_one("#status-bar", StatusBar)
            self._state.status_bar = derive_status_bar(self._state.form)
            status.update_state(self._state.status_bar)

    # ── Edit lifecycle ────────────────────────────────────────────────────

    def action_activate(self) -> None:
        """Enter pressed — submit for profile/required fields with values, toggle for others."""
        if self._editing:
            detail = self.query_one("#detail-panel", DetailPanel)
            if detail.is_choice_editor_active():
                item = self._state.selected_nav_item
                field_meta = self._state.form.field_by_key(item.key) if item else None
                
                # Check if Enter should submit (profile or required field with values)
                should_submit = (
                    item and item.key == "profile"
                    or field_meta and field_meta.required and field_meta.options
                )
                
                action = detail.editor_activate()
                if action == "confirm":
                    if should_submit:
                        self._confirm_edit()
                elif action == "custom":
                    detail.begin_custom_value_input()
                return
            self._confirm_edit()
            return

        item = self._state.selected_nav_item
        if not item:
            return

        if item.is_action:
            if item.key == "history":
                self.action_open_history()
            elif item.key == "run":
                self.action_run_pipeline()
            return

        # Begin inline edit
        self._editing = True
        detail = self.query_one("#detail-panel", DetailPanel)
        detail.begin_edit(item, self._state.form)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter inside an Input widget during inline editing."""
        if not self._editing:
            return
        detail = self.query_one("#detail-panel", DetailPanel)
        if detail.is_custom_input_active():
            if detail.apply_custom_value(event.value):
                item = self._state.selected_nav_item
                if item and detail.editor_mode == "single_choice":
                    self._confirm_edit()
            return
        self._confirm_edit()

    def _confirm_edit(self) -> None:
        """Confirm inline edit and apply value."""
        detail = self.query_one("#detail-panel", DetailPanel)
        item = self._state.selected_nav_item
        if not item:
            self._editing = False
            return

        value: Any = ""

        if detail.is_choice_editor_active():
            value = detail.editor_current_value()
            self._state = set_field_value(self._state, item.key, value)
            self._sync_app_state()
            self._editing = False
            
            # Profile change needs special handling
            if item.key == "profile":
                self.app.post_message(self.ProfileChanged(str(value)))
                return
            elif item.key in {"first_role", "last_role", "tags"}:
                self.app.post_message(self.DerivedInputsChanged())
            self._update_display()
            return

        try:
            inp = detail.query_one("#inline-input")
            raw_value = inp.text if isinstance(inp, TextArea) else inp.value
            value = self._parse_raw_value(item.key, raw_value)
        except Exception:
            value = ""

        self._state = set_field_value(self._state, item.key, value)
        self._sync_app_state()
        self._editing = False

        # Special: profile change triggers reload - don't update display here,
        # the message handler will update it with the new state
        if item.key == "profile":
            import datetime
            with open('/tmp/devpipe_debug.log', 'a') as f:
                f.write(f"\n[{datetime.datetime.now()}] _confirm_edit posting ProfileChanged\n")
                f.write(f"  new profile={value}\n")
            self.app.post_message(self.ProfileChanged(str(value)))
            return
        elif item.key in {"first_role", "last_role", "tags"}:
            self.app.post_message(self.DerivedInputsChanged())

        self._update_display()

    def _parse_raw_value(self, key: str, raw_value: str) -> Any:
        """Parse raw input value based on field type."""
        field_meta = self._state.form.field_by_key(key)
        if not field_meta:
            return raw_value

        if field_meta.kind in (FieldKind.MULTI_SELECT, FieldKind.ARRAY):
            return [v.strip() for v in raw_value.split(",") if v.strip()]
        elif field_meta.kind == FieldKind.OBJECT:
            result = {}
            for pair in raw_value.split(","):
                pair = pair.strip()
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    result[k.strip()] = v.strip()
            return result
        elif field_meta.kind == FieldKind.INT:
            try:
                return int(raw_value)
            except ValueError:
                return 0
        return raw_value

    def action_cancel(self) -> None:
        if self._editing:
            detail = self.query_one("#detail-panel", DetailPanel)
            # If in tag_roles editor and in edit_roles submode, exit submode first
            if detail.editor_mode == "tag_roles" and detail.editor_submode == "edit_roles":
                detail.cancel_submode()
            else:
                # Apply changes before exiting
                item = self._state.selected_nav_item
                if item:
                    if detail.is_choice_editor_active():
                        value = detail.editor_current_value()
                        self._state = set_field_value(self._state, item.key, value)
                        self._sync_app_state()
                        if item.key == "profile":
                            self.app.post_message(self.ProfileChanged(str(value)))
                        elif item.key in {"first_role", "last_role", "tags"}:
                            self.app.post_message(self.DerivedInputsChanged())
                    else:
                        # Text editor mode - apply the value
                        try:
                            inp = detail.query_one("#inline-input")
                            raw_value = inp.text if isinstance(inp, TextArea) else inp.value
                            value = self._parse_raw_value(item.key, raw_value)
                            self._state = set_field_value(self._state, item.key, value)
                            self._sync_app_state()
                        except Exception:
                            pass
                self._editing = False
                self._update_display()
        else:
            self.app.exit()

    # ── Actions ───────────────────────────────────────────────────────────

    def action_open_history(self) -> None:
        from devpipe.ui.screens.history_screen import HistoryScreen
        self.app.push_screen(HistoryScreen(self._state))

    def action_run_pipeline(self) -> None:
        if not self._state.form.is_ready:
            return
        self.app.post_message(self.RunRequested())

    def action_toggle_tag(self) -> None:
        """Toggle selection of current tag (in main tag list)."""
        if self._editing:
            detail = self.query_one("#detail-panel", DetailPanel)
            if detail.editor_mode == "tag_roles" and detail.editor_submode == "":
                detail.toggle_current_tag()

    # ── Messages ──────────────────────────────────────────────────────────

    class ProfileChanged(Message):
        """Request app to reload profile data."""
        def __init__(self, profile: str) -> None:
            super().__init__()
            self.profile = profile

    class DerivedInputsChanged(Message):
        """Request app to recalculate fields derived from tags and stage range."""
        pass

    class RunRequested(Message):
        """Request app to initialize and start the pipeline run."""
        pass

    def on_detail_panel_action_requested(self, event: DetailPanel.ActionRequested) -> None:
        if event.action == "history":
            self.action_open_history()
        elif event.action == "run":
            self.action_run_pipeline()

    def on_nav_list_item_selected(self, event: NavList.ItemSelected) -> None:
        self._state.selected_nav_index = event.index
        self._sync_app_state()
        self._show_current_summary()

    def on_nav_list_item_activated(self, event: NavList.ItemActivated) -> None:
        self.action_activate()

    @property
    def ui_state(self) -> UIState:
        return self._state
