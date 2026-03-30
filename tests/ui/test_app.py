from __future__ import annotations

from types import SimpleNamespace

from textual.app import App

from devpipe.ui.actions import load_defaults, set_field_value
from devpipe.ui.app import DevpipeTextualApp
from devpipe.ui.screens.config_screen import ConfigScreen
from devpipe.ui.run_session import sanitize_output_text
from devpipe.ui.state import FieldKind, FieldMeta, UIState


def test_build_run_config_collects_custom_fields_and_overrides(tmp_path):
    app = DevpipeTextualApp(project_root=tmp_path)
    state = load_defaults(
        UIState(),
        profile="",
        available_profiles=[],
        available_stages=["architect", "developer", "qa_local"],
        fields=[
            FieldMeta(key="task_id", label="Task ID", kind=FieldKind.STRING, section="custom"),
            FieldMeta(key="dataset", label="Dataset", kind=FieldKind.MULTI_SELECT, section="custom"),
        ],
        defaults={
            "task": "Ship it",
            "task_id": "MRC-123",
            "runner": "codex",
            "model": "high",
            "effort": "extra",
            "target_branch": "release1",
            "namespace": "u1",
            "service": "acquiring",
            "tags": ["go"],
            "dataset": ["s4-3ds"],
        },
    )
    app._ui_state = state

    config = app.build_run_config()

    assert config.task_id == "MRC-123"
    assert config.model == "high"
    assert config.effort == "extra"
    assert config.extra_params == {"dataset": ["s4-3ds"]}


def test_derived_inputs_refresh_preserves_selected_nav_item(tmp_path):
    devpipe_dir = tmp_path / ".devpipe"
    (devpipe_dir / "tags" / "acquiring-service" / "qa_stand").mkdir(parents=True)
    (devpipe_dir / "config.yaml").write_text(
        """
defaults:
  runner: codex
  service: acquiring
  tags:
    - acquiring-service
""".strip(),
        encoding="utf-8",
    )
    (devpipe_dir / "tags" / "acquiring-service" / "qa_stand" / "params.yaml").write_text(
        """
params:
  - key: dataset
    description: Test dataset
    required: true
    multi: true
    available:
      - s4-3ds
""".strip(),
        encoding="utf-8",
    )

    app = DevpipeTextualApp(project_root=tmp_path)
    app._load_initial_state()
    app._ui_state.selected_nav_index = next(
        index for index, item in enumerate(app._ui_state.nav_items) if item.key == "last_role"
    )
    app._ui_state = set_field_value(app._ui_state, "last_role", "qa_local")

    app.on_config_screen_derived_inputs_changed(ConfigScreen.DerivedInputsChanged())

    assert app._ui_state.selected_nav_item is not None
    assert app._ui_state.selected_nav_item.key == "last_role"


def test_build_run_config_ignores_hidden_legacy_top_level_fields(tmp_path):
    app = DevpipeTextualApp(project_root=tmp_path)
    state = load_defaults(
        UIState(),
        profile="",
        available_profiles=[],
        available_stages=["architect", "developer", "qa_local", "release", "qa_stand"],
        fields=[
            FieldMeta(key="task_id", label="Task ID", kind=FieldKind.STRING, section="custom"),
        ],
        defaults={
            "task": "Ship it",
            "task_id": "MRC-123",
            "runner": "codex",
            "service": "acquiring",
            "namespace": "u1",
            "tags": ["acquiring-service"],
            "target_branch": "release1",
            "first_role": "architect",
            "last_role": "developer",
        },
    )
    app._ui_state = state

    config = app.build_run_config()

    assert config.task_id == "MRC-123"
    assert config.service is None
    assert config.namespace is None
    assert config.target_branch is None
    assert config.tags == ["acquiring-service"]


def test_run_requested_seeds_timeline_before_screen_is_shown(tmp_path):
    app = DevpipeTextualApp(project_root=tmp_path)
    state = load_defaults(
        UIState(),
        profile="",
        available_profiles=[],
        available_stages=["architect", "developer", "qa_local", "release"],
        fields=[],
        defaults={
            "task": "Ship it",
            "runner": "codex",
            "model": "high",
            "effort": "extra",
            "first_role": "developer",
            "last_role": "release",
        },
    )
    app._ui_state = state

    pushed: list[object] = []
    app.push_screen = lambda screen: pushed.append(screen)  # type: ignore[method-assign]
    app._launch_run_session = lambda config: None  # type: ignore[method-assign]

    app.on_config_screen_run_requested(ConfigScreen.RunRequested())

    assert [attempt.stage for attempt in app._ui_state.run_view.timeline] == ["developer", "qa_local", "release"]
    assert app._ui_state.run_view.status == "running"
    assert pushed


def test_handle_run_event_updates_run_state(tmp_path):
    app = DevpipeTextualApp(project_root=tmp_path)
    state = load_defaults(
        UIState(),
        profile="",
        available_profiles=[],
        available_stages=["architect", "developer"],
        fields=[],
        defaults={"task": "Ship it", "runner": "codex"},
    )
    state = app._ui_state = load_defaults(
        state,
        profile="",
        available_profiles=[],
        available_stages=["architect", "developer"],
        fields=[],
        defaults={"task": "Ship it", "runner": "codex"},
    )
    app._ui_state = state
    app._ui_state.run_view.timeline = []
    app._ui_state.run_view.status = "running"
    app._handle_run_event(SimpleNamespace(kind="stage_started", stage="architect", runner="codex", model="gpt-5", effort="medium"))

    assert app._ui_state.run_view.active_stage == "architect"
    assert app._ui_state.run_view.timeline[0].stage == "architect"


def test_ensure_runtime_app_uses_devpipe_bundle_when_project_has_no_runner_config(tmp_path):
    app = DevpipeTextualApp(project_root=tmp_path)

    runtime_app = app._ensure_runtime_app()

    assert "codex" in runtime_app.runners
    assert "claude" in runtime_app.runners


def test_exit_cancels_active_run_and_waits_for_worker(tmp_path, monkeypatch):
    app = DevpipeTextualApp(project_root=tmp_path)
    calls: list[str] = []

    class FakeSession:
        def cancel(self) -> None:
            calls.append("cancel")

    class FakeThread:
        def __init__(self) -> None:
            self.ident = 123

        def is_alive(self) -> bool:
            return True

        def join(self) -> None:
            calls.append("join")

    monkeypatch.setattr(App, "exit", lambda self, *args, **kwargs: calls.append("super-exit"))
    app._run_session = FakeSession()
    app._run_thread = FakeThread()

    app.exit()

    assert calls == ["cancel", "join", "super-exit"]


def test_sanitize_output_text_strips_ansi_and_collapses_blank_lines() -> None:
    raw = "\x1b[97mHello\x1b[0m\n\n\nworld\n\x1b[2m\x1b[0m"

    cleaned = sanitize_output_text(raw)

    assert cleaned == "Hello\n\nworld"


def test_cancel_active_run_async_cancels_session_and_joins_worker(tmp_path) -> None:
    app = DevpipeTextualApp(project_root=tmp_path)
    calls: list[str] = []

    class FakeSession:
        def cancel(self) -> None:
            calls.append("cancel")

    class FakeThread:
        ident = 123

        def is_alive(self) -> bool:
            return True

        def join(self, timeout: float | None = None) -> None:
            calls.append(f"join:{timeout}")

    app._run_session = FakeSession()
    app._run_thread = FakeThread()
    app.call_from_thread = lambda callback: callback()  # type: ignore[method-assign]

    app.cancel_active_run_async(lambda: calls.append("done"))

    assert calls == ["cancel", "join:None", "done"]
