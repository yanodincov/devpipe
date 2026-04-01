"""Root Textual application for devpipe.

Manages screen routing, UIState, and services container.
Operator Console visual style: graphite dark, cyan/teal accents.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.design import ColorSystem

from devpipe.app import OrchestratorApp, RunConfig, build_default_app
from devpipe.ui.actions import (
    apply_history_entry,
    begin_stage,
    complete_stage_attempt,
    finish_run,
    load_defaults,
    set_field_value,
    start_run,
    append_run_output,
)
from devpipe.ui.run_session import RunEvent, RunSession
from devpipe.ui.screens.config_screen import ConfigScreen
from devpipe.ui.screens.history_screen import HistoryScreen
from devpipe.ui.screens.run_screen import RunScreen
from devpipe.ui.services import (
    discover_profiles,
    get_dynamic_tag_fields,
    load_default_profile,
    load_profile_defaults,
    load_profile_fields,
    load_profile_stages,
    prepare_initial_state,
    resolve_legacy_form_state,
    _normalize_tag_roles_defaults,
)
from devpipe.ui.state import UIState

# Operator Console color scheme
DEVPIPE_COLORS = {
    "dark": ColorSystem(
        primary="#06b6d4",       # cyan
        secondary="#14b8a6",     # teal
        accent="#22d3ee",        # bright cyan
        warning="#f59e0b",       # amber
        error="#ef4444",         # red
        success="#22c55e",       # green
        background="#1a1a2e",    # deep graphite
        surface="#16213e",       # dark navy
        panel="#0f3460",         # panel blue
    ),
}


class DevpipeTextualApp(App):
    """Devpipe interactive TUI application."""

    TITLE = "devpipe"
    CSS = """
    Screen {
        background: $background;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=True, priority=True),
    ]

    def __init__(self, project_root: Path | None = None, show_prompt: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self._project_root = project_root or Path.cwd()
        self._show_prompt = show_prompt
        self._ui_state = UIState(show_prompt=show_prompt)
        self._result_config: RunConfig | None = None
        self._runtime_app: OrchestratorApp | None = None
        self._run_session: RunSession | None = None
        self._run_thread: threading.Thread | None = None

    def get_default_screen(self) -> ConfigScreen:
        return ConfigScreen(self._ui_state)

    def on_mount(self) -> None:
        """Initialize state and show config screen."""
        self._load_initial_state()
        screen = ConfigScreen(self._ui_state)
        self.push_screen(screen)

    def _load_initial_state(self) -> None:
        """Load profile data and populate UIState."""
        data = prepare_initial_state(self._project_root)
        self._ui_state = load_defaults(
            self._ui_state,
            profile=data["profile"],
            available_profiles=data["available_profiles"],
            available_stages=data["available_stages"],
            fields=data["fields"],
            defaults=data["defaults"],
            available_tags=data.get("available_tags", []),
            profile_errors=data.get("profile_errors", []),
            routing_graph=data.get("routing_graph", {}),
        )

    # ── Screen event handlers ─────────────────────────────────────────────

    def on_config_screen_profile_changed(self, event: ConfigScreen.ProfileChanged) -> None:
        """Reload fields and stages for new profile."""
        from devpipe.ui.services import _build_routing_graph
        from devpipe.profiles.validator import validate_profile, format_validation_errors
        from devpipe.profiles.loader import find_project_root

        profile = event.profile
        profile_errors: list[str] = []
        routing_graph: dict[str, set[str]] = {}
        stages = []
        fields = []
        defaults = {}
        
        # Validate profile first
        project_root = find_project_root()
        profile_dir = project_root / ".devpipe" / "profiles" / profile if project_root else None
        if profile_dir and profile_dir.exists():
            validation_result = validate_profile(profile_dir)
            if not validation_result.valid:
                profile_errors.extend(format_validation_errors(validation_result.errors))
        
        try:
            fields = load_profile_fields(profile, self._project_root)
            stages = load_profile_stages(profile, self._project_root)
            defaults = load_profile_defaults(profile, self._project_root)
            from devpipe.profiles.loader import load_profile
            profile_obj = load_profile(profile, project_root=self._project_root)
            if profile_obj and profile_obj.routing:
                routing_graph = _build_routing_graph(profile_obj.routing)
        except Exception as e:
            import traceback
            traceback.print_exc()
            profile_errors.append(f"Failed to load profile '{profile}': {e}")

        from devpipe.ui.actions import select_profile
        self._ui_state = select_profile(
            self._ui_state,
            profile=profile,
            fields=fields,
            defaults=defaults,
            available_stages=stages,
            profile_errors=profile_errors,
            routing_graph=routing_graph,
        )
        # After profile change, recalc derived fields (e.g., dynamic tag params)
        fake_event = ConfigScreen.DerivedInputsChanged()
        self.on_config_screen_derived_inputs_changed(fake_event)
        
        # Explicitly sync screen state after profile change
        if self.screen_stack:
            screen = self.screen
            if isinstance(screen, ConfigScreen):
                screen._state = self._ui_state
                screen._update_display()

    def on_history_screen_restore_entry(self, event: HistoryScreen.RestoreEntry) -> None:
        """Restore history entry into form state."""
        target_profile = getattr(event.entry, "profile", "") if event.entry is not None else ""
        if target_profile and target_profile != self._ui_state.form.profile:
            self.on_config_screen_profile_changed(ConfigScreen.ProfileChanged(target_profile))

        self._ui_state = apply_history_entry(self._ui_state, event.entry)
        # After restoring, recalc derived fields (e.g., dynamic tag params) if needed
        # This ensures that tag parameters are added to fields based on restored tags
        # We simulate a DerivedInputsChanged event to trigger the same logic
        fake_event = ConfigScreen.DerivedInputsChanged()
        self.on_config_screen_derived_inputs_changed(fake_event)
        # Refresh config screen
        if self.screen_stack:
            screen = self.screen
            if isinstance(screen, ConfigScreen):
                screen._state = self._ui_state
                screen._update_display()

    def on_config_screen_derived_inputs_changed(self, event: ConfigScreen.DerivedInputsChanged) -> None:
        """Recalculate custom fields when tags or stage range changes."""
        self.log(f"[DERIVED] profile={self._ui_state.form.profile}, stages={self._ui_state.form.available_stages}")
        
        selected_item = self._ui_state.selected_nav_item
        selected_key = selected_item.key if selected_item is not None else None
        form = self._ui_state.form

        if not form.available_profiles:
            # Legacy mode: use resolve_legacy_form_state
            data = resolve_legacy_form_state(self._project_root, form.values)
            allowed_custom_keys = {field.key for field in data["fields"]}
            preserved = {}
            for key, value in form.values.items():
                if key in {"profile", "task", "runner", "model", "effort", "first_role", "last_role"}:
                    preserved[key] = value
                elif key in allowed_custom_keys:
                    preserved[key] = value
            defaults = dict(data["defaults"])
            defaults.update(preserved)
            self._ui_state = load_defaults(
                self._ui_state,
                profile=data["profile"],
                available_profiles=data["available_profiles"],
                available_stages=data["available_stages"],
                fields=data["fields"],
                defaults=defaults,
                available_tags=data.get("available_tags", []),
                profile_errors=[],  # Legacy mode has no profile errors
                routing_graph=self._ui_state.form.routing_graph,
            )
        else:
            # Profile-driven mode: recompute fields based on profile inputs + dynamic tag params
            profile_name = form.profile
            if not profile_name:
                # No profile selected, nothing to do
                return
            try:
                from devpipe.profiles.loader import load_profile
                profile_obj = load_profile(profile_name, project_root=self._project_root)
            except Exception:
                return

            # Get base fields from profile inputs (static)
            base_fields = load_profile_fields(profile_obj, self._project_root)
            # Determine selected tags from form.values['tags'] (should be dict)
            tag_roles = form.values.get("tags", {})
            selected_tags = tag_roles if isinstance(tag_roles, dict) else {}
            # Get dynamic tag param fields
            dynamic_fields = get_dynamic_tag_fields(selected_tags, form.values, self._project_root)
            # Combine: base_fields (which includes tags and other inputs) plus dynamic fields
            # Avoid duplicates: if a dynamic field key already exists in base_fields, skip
            existing_keys = {f.key for f in base_fields}
            new_fields = list(base_fields)
            for df in dynamic_fields:
                if df.key not in existing_keys:
                    new_fields.append(df)

            # Recompute stages from the profile's routing
            stages = load_profile_stages(profile_name, self._project_root)

            # Preserve existing values for fields that remain, plus standard keys (but NOT first_role/last_role/tags - they must be reset per profile)
            allowed_keys = {f.key for f in new_fields} | {"profile", "task", "runner", "model", "effort"}
            preserved = {}
            for key, value in form.values.items():
                if key in allowed_keys:
                    preserved[key] = value

            # Build defaults: start with profile defaults and then apply preserved overrides
            try:
                defaults = load_profile_defaults(profile_name, self._project_root)
            except Exception:
                defaults = {}
            # Merge inputs defaults for any fields not in defaults
            for input_key, spec in profile_obj.inputs.items():
                if input_key not in defaults:
                    defaults[input_key] = spec.default
            # Ensure tags dict normalized
            from devpipe.tags import load_available_tags
            available_tags = load_available_tags(self._project_root)
            if 'tags' in defaults:
                defaults['tags'] = _normalize_tag_roles_defaults(defaults['tags'], available_tags)
            else:
                defaults['tags'] = {}
            # Add defaults for dynamic tag params if not already set
            for df in dynamic_fields:
                if df.key not in defaults and df.default:
                    defaults[df.key] = df.default

            defaults.update(preserved)

            # Reload state with new fields, defaults, and updated stages
            self._ui_state = load_defaults(
                self._ui_state,
                profile=form.profile,
                available_profiles=form.available_profiles,
                available_stages=stages,
                fields=new_fields,
                defaults=defaults,
                available_tags=form.available_tags,
                profile_errors=self._ui_state.form.profile_errors,
                routing_graph=self._ui_state.form.routing_graph,
            )

        # Restore nav selection
        if selected_key is not None:
            restored_index = next(
                (index for index, item in enumerate(self._ui_state.nav_items) if item.key == selected_key),
                None,
            )
            if restored_index is not None:
                self._ui_state.selected_nav_index = restored_index

        # Refresh screen if visible
        if self.screen_stack:
            screen = self.screen
            if isinstance(screen, ConfigScreen):
                screen._state = self._ui_state
                screen._update_display()

    @property
    def result_config(self) -> RunConfig | None:
        """Return the RunConfig if user completed the form, else None."""
        return self._result_config

    def build_run_config(self) -> RunConfig:
        """Build a RunConfig from current form state."""
        v = self._ui_state.form.values
        visible_custom_keys = {
            field.key for field in self._ui_state.form.fields if field.section == "custom"
        }
        top_level_custom_keys = {"task_id", "target_branch", "namespace", "service", "tags"}
        extra_params = {
            field.key: v[field.key]
            for field in self._ui_state.form.fields
            if field.section == "custom" and field.key not in top_level_custom_keys and field.key in v
        }
        raw_tags = v.get("tags") or {}
        tags_list = list(raw_tags.keys()) if isinstance(raw_tags, dict) else (raw_tags if isinstance(raw_tags, list) else [])
        tag_roles = raw_tags if isinstance(raw_tags, dict) else {}
        return RunConfig(
            profile=v.get("profile", ""),
            task_id=v.get("task_id") or None,
            task=v.get("task", ""),
            runner=v.get("runner", "auto"),
            model=v.get("model") or None,
            effort=v.get("effort") or None,
            target_branch=v.get("target_branch") if "target_branch" in visible_custom_keys else None,
            namespace=v.get("namespace") if "namespace" in visible_custom_keys else None,
            service=v.get("service") if "service" in visible_custom_keys else None,
            tags=tags_list,
            tag_roles=tag_roles,
            extra_params=extra_params or None,
            first_role=v.get("first_role") or None,
            last_role=v.get("last_role") or None,
        )

    def _selected_run_stages(self) -> list[str]:
        stages = list(self._ui_state.form.available_stages)
        if not stages:
            return []
        first = self._ui_state.form.values.get("first_role") or stages[0]
        last = self._ui_state.form.values.get("last_role") or stages[-1]
        if first in stages and last in stages:
            first_index = stages.index(first)
            last_index = stages.index(last)
            if first_index <= last_index:
                return stages[first_index:last_index + 1]
        return stages

    def _ensure_runtime_app(self) -> OrchestratorApp:
        if self._runtime_app is None:
            bundle_root = Path(__file__).resolve().parents[3]
            self._runtime_app = build_default_app(bundle_root, show_prompt=self._show_prompt)
        return self._runtime_app

    def _launch_run_session(self, config: RunConfig) -> None:
        runtime_app = self._ensure_runtime_app()

        def worker() -> None:
            session = RunSession(runtime_app)
            self._run_session = session

            def on_event(event: RunEvent) -> None:
                self.call_from_thread(self._handle_run_event, event)

            try:
                session.execute(config, on_event)
            except Exception:
                pass
            finally:
                self._run_session = None

        self._run_thread = threading.Thread(target=worker, daemon=False)
        self._run_thread.start()

    def exit(self, result: object | None = None, return_code: int = 0, message: object | None = None) -> None:
        session = self._run_session
        thread = self._run_thread
        if session is not None:
            session.cancel()
        if thread is not None and thread.is_alive() and thread.ident != threading.get_ident():
            thread.join()
        self._run_thread = None
        super().exit(result=result, return_code=return_code, message=message)

    def cancel_active_run_async(self, on_complete: Callable[[], None] | None = None) -> None:
        session = self._run_session
        thread = self._run_thread
        if session is None or thread is None or not thread.is_alive():
            self._run_thread = None
            if on_complete is not None:
                on_complete()
            return

        def worker() -> None:
            session.cancel()
            if thread.ident != threading.get_ident():
                thread.join()
            self._run_thread = None
            if on_complete is not None:
                self.call_from_thread(on_complete)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_run_event(self, event: RunEvent) -> None:
        if event.kind == "stage_started":
            self._ui_state = begin_stage(
                self._ui_state,
                event.stage,
                event.runner,
                event.model,
                event.effort,
            )
        elif event.kind == "stage_completed":
            self._ui_state = complete_stage_attempt(
                self._ui_state,
                event.stage,
                "done",
                summary=event.summary,
                tokens=event.tokens,
            )
        elif event.kind == "output":
            self._ui_state = append_run_output(self._ui_state, event.output_text)
        elif event.kind == "run_finished":
            self._ui_state = finish_run(self._ui_state, event.status, event.run_id)

        try:
            screen = self.screen
        except Exception:
            return
        if isinstance(screen, RunScreen):
            if event.kind == "stage_started":
                screen._state = self._ui_state
                screen.on_stage_started(event.stage, event.runner, event.model, event.effort)
            elif event.kind == "stage_completed":
                screen._state = self._ui_state
                screen.on_stage_completed(event.stage, event.summary, event.structured_output)
            elif event.kind == "output":
                screen._state = self._ui_state
                screen.on_output(event.output_text)
            elif event.kind == "run_finished":
                screen._state = self._ui_state
                screen.on_run_finished(event.status, event.run_id)

    def on_config_screen_run_requested(self, event: ConfigScreen.RunRequested) -> None:
        config = self.build_run_config()
        stages = self._selected_run_stages()
        self._ui_state = start_run(
            self._ui_state,
            run_id="pending",
            stages=stages,
            runner=config.runner,
            model=config.model or "auto",
            effort=config.effort or "auto",
        )
        screen = RunScreen(self._ui_state)
        self.push_screen(screen)
        self._launch_run_session(config)
