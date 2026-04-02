"""Tests for the history screen state."""
from __future__ import annotations

from datetime import datetime, timezone
import pytest

from devpipe.history import RunHistoryEntry
from devpipe.ui.screens.history_screen import HistoryList
from devpipe.ui.actions import apply_history_entry, load_defaults
from devpipe.ui.state import FieldKind, FieldMeta, UIState
from devpipe.ui.widgets.history_preview import HistoryPreview
from devpipe.ui.widgets.task_snapshot import build_task_snapshot_lines, custom_fields_from_history_entry


def _make_entry(**overrides) -> RunHistoryEntry:
    """Create a minimal RunHistoryEntry for tests."""
    default_config = {
        "task": "",
        "runner": "auto",
        "model": "auto",
        "effort": "auto",
        "tags": [],
        "first_role": "",
        "last_role": "",
        "task_id": "",
        "target_branch": "",
        "service": "",
        "namespace": "",
        "extra_params": {},
    }
    default_config.update(overrides.get("config", {}))
    return RunHistoryEntry(
        run_id=overrides.get("run_id", "test-run"),
        timestamp=overrides.get("timestamp", datetime.now(timezone.utc)),
        profile=overrides.get("profile", "current-delivery"),
        config=default_config,
        stages=overrides.get("stages", []),
        summary=overrides.get("summary", {
            "total_duration_seconds": 0,
            "stages_completed": 0,
            "stages_failed": 0,
            "final_status": "pending",
        }),
    )


def _make_state() -> UIState:
    fields = [
        FieldMeta(key="task_id", label="Task Id", kind=FieldKind.STRING, section="custom"),
        FieldMeta(key="target_branch", label="Target Branch", kind=FieldKind.STRING, section="custom"),
    ]
    state = UIState()
    return load_defaults(
        state,
        profile="current-delivery",
        available_profiles=["current-delivery"],
        available_stages=["architect", "developer", "qa_local"],
        fields=fields,
        defaults={"task": "", "runner": "auto"},
        available_runners=["auto", "codex", "claude"],
    )


class TestHistoryRestore:
    def test_restore_populates_form(self):
        state = _make_state()
        entry = {
            "date": "2026-03-27 12:00:00",
            "task": "Build feature X",
            "task_id": "MRC-456",
            "runner": "codex",
            "target_branch": "main",
            "service": "acquiring",
            "namespace": "prod",
            "tags": ["go"],
            "extra_params": {"dataset": "full"},
            "first_role": "architect",
            "last_role": "qa_local",
        }
        new = apply_history_entry(state, entry)
        assert new.form.values["task"] == "Build feature X"
        assert new.form.values["task_id"] == "MRC-456"
        assert new.form.values["runner"] == "codex"
        assert new.form.values["target_branch"] == "main"
        assert new.form.values["dataset"] == "full"
        assert new.form.values["first_role"] == "architect"
        assert new.form.values["last_role"] == "qa_local"

    def test_restore_validates_runner(self):
        state = _make_state()
        entry = {"runner": "nonexistent"}
        new = apply_history_entry(state, entry)
        assert new.form.values["runner"] == "auto"

    def test_restore_validates_stages(self):
        state = _make_state()
        entry = {"first_role": "unknown", "last_role": "unknown"}
        new = apply_history_entry(state, entry)
        assert new.form.values["first_role"] == "architect"
        assert new.form.values["last_role"] == ""  # Empty by default for invalid

    def test_restore_with_multiple_stage_attempts(self):
        """History entry with stage data should be correctly processed."""
        state = _make_state()
        entry = {
            "task": "Retry test",
            "runner": "auto",
            "first_role": "developer",
            "last_role": "qa_local",
        }
        new = apply_history_entry(state, entry)
        assert new.form.values["first_role"] == "developer"
        assert new.form.values["last_role"] == "qa_local"


def test_history_list_hides_date_and_truncates_multiline_title() -> None:
    hist_list = HistoryList()
    entry = _make_entry(
        config={"task": "First line of task\nSecond line should be hidden because title must stay single-line"},
        timestamp=datetime(2026, 3, 27, 12, 0, 0, tzinfo=timezone.utc),
    )
    hist_list.set_entries([entry])

    rendered = hist_list.render().plain

    assert "2026-03-27" not in rendered
    assert "First line of task" in rendered
    assert "Second line should be hidden" not in rendered


def test_history_list_truncates_to_single_line_with_ellipsis() -> None:
    hist_list = HistoryList()
    entry = _make_entry(
        config={"task": "Очень длинное название задачи которое обязательно должно быть обрезано в списке истории"}
    )
    hist_list.set_entries([entry])

    rendered_lines = hist_list.render().plain.splitlines()

    assert rendered_lines[2].endswith("…")
    assert "\n" not in rendered_lines[2]


def test_history_list_removes_large_left_indent() -> None:
    hist_list = HistoryList()
    entry = _make_entry(config={"task": "Build feature X"})
    hist_list.set_entries([entry])

    rendered_lines = hist_list.render().plain.splitlines()

    assert rendered_lines[2] == "▶ Build feature X"


def test_history_preview_matches_form_snapshot_layout() -> None:
    preview = HistoryPreview()
    entry = _make_entry(
        config={
            "task": "Build feature X",
            "task_id": "MRC-456",
            "runner": "codex",
            "model": "high",
            "effort": "extra",
            "target_branch": "main",
            "service": "acquiring",
            "namespace": "prod",
            "tags": ["go"],
            "extra_params": {"dataset": ["full"]},
            "first_role": "architect",
            "last_role": "qa_local",
        },
        timestamp=datetime(2026, 3, 27, 12, 0, 0, tzinfo=timezone.utc),
        summary={"total_duration_seconds": 240, "stages_completed": 1, "stages_failed": 0, "final_status": "completed"},
    )
    preview.show_entry(entry)

    rendered = preview.render().plain
    snapshot_values = dict(entry.config)
    snapshot_values.update(entry.config.get("extra_params", {}))
    snapshot_values["profile"] = entry.profile
    expected_lines = build_task_snapshot_lines(
        snapshot_values,
        custom_fields_from_history_entry(entry.config),
    )

    assert "Build feature X" in rendered
    assert "codex" in rendered
    assert "high" in rendered
    assert "extra" in rendered
    assert "architect" in rendered
    assert "qa_local" in rendered
    assert "MRC-456" in rendered
    assert "2026-03-27" in rendered
    assert "4m 00s" in rendered
    assert "── Stages ──" not in rendered
    assert "Dataset" in rendered
    assert "full" in rendered


def test_history_preview_shows_empty_custom_fields_from_profile(tmp_path) -> None:
    profile_dir = tmp_path / ".devpipe" / "profiles" / "idea-lab"
    profile_dir.mkdir(parents=True)
    write_agent(profile_dir, "review")
    (profile_dir / "pipeline.yml").write_text(
        """
version: 1
name: idea-lab
defaults:
  runner: auto
inputs:
  component:
    type: string
    default: ""
  dataset:
    type: array
    default: []
stages:
  review:
    type: ai
    default_engine: codex
    agent:
      folder: review
    out:
      result:
        type: string
routing:
  start_stage: review
  by_stage:
    review:
      next_stages:
        - stage: completed
          default: true
""".strip(),
        encoding="utf-8",
    )

    preview = HistoryPreview(project_root=tmp_path)
    entry = _make_entry(
        profile="idea-lab",
        config={
            "task": "Build feature X",
            "runner": "codex",
            "model": "",
            "effort": "",
            "tags": {},
            "first_role": "",
            "last_role": "",
        },
    )

    preview.show_entry(entry)

    rendered = preview.render().plain

    assert "Component" in rendered
    assert "Dataset" in rendered
    assert "(empty)" in rendered


def test_history_screen_reads_entries_from_history_dir(tmp_path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_load_run_history(path):
        captured["path"] = path
        return []

    monkeypatch.setattr("devpipe.ui.screens.history_screen.load_run_history", fake_load_run_history)

    from devpipe.ui.screens.history_screen import HistoryScreen
    from devpipe.ui.state import UIState

    screen = HistoryScreen(UIState(), project_root=tmp_path)
    screen.query_one = lambda *args, **kwargs: HistoryList()  # type: ignore[method-assign]
    screen.on_mount()

    assert captured["path"] == tmp_path / ".devpipe" / "history"
def write_agent(profile_dir: Path, name: str) -> None:
    agent_dir = profile_dir / "agents" / name
    agent_dir.mkdir(parents=True)
    (agent_dir / "prompt.md").write_text(f"{name} prompt", encoding="utf-8")
    (agent_dir / "output.schema.json").write_text(
        '{"type":"object","properties":{"result":{"type":"string"}},"required":["result"]}',
        encoding="utf-8",
    )
