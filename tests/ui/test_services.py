from __future__ import annotations

from devpipe.runtime.state import STAGE_ORDER
from devpipe.ui.services import prepare_initial_state, resolve_legacy_form_state
from devpipe.ui.state import FieldKind


def test_prepare_initial_state_without_profiles_returns_empty(tmp_path):
    """Test that without .devpipe/profiles/, state has no profile or stages."""
    devpipe_dir = tmp_path / ".devpipe"
    devpipe_dir.mkdir()
    # Config may specify a default profile, but if no profiles dir exists, no profile is active
    (devpipe_dir / "config.yaml").write_text(
        "defaults:\n  profile: test-simple",
        encoding="utf-8",
    )

    data = prepare_initial_state(tmp_path)

    # No local profiles dir => no profile active, empty available profiles and stages
    assert data["profile"] == ""
    assert data["available_profiles"] == []
    assert data["available_stages"] == []
    # Defaults should contain standard auto values
    assert data["defaults"]["runner"] == "auto"
    assert data["defaults"]["model"] == "auto"
    assert data["defaults"]["effort"] == "auto"
    # No custom fields from profile
    assert data["fields"] == []


def test_legacy_fields_follow_selected_stage_range(tmp_path):
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

    qa_local_state = resolve_legacy_form_state(
        tmp_path,
        {"tags": ["acquiring-service"], "first_role": "architect", "last_role": "qa_local"},
    )
    qa_stand_state = resolve_legacy_form_state(
        tmp_path,
        {"tags": ["acquiring-service"], "first_role": "architect", "last_role": "qa_stand"},
    )

    qa_local_keys = {field.key for field in qa_local_state["fields"]}
    qa_stand_keys = {field.key for field in qa_stand_state["fields"]}
    assert "dataset" not in qa_local_keys
    assert "dataset" in qa_stand_keys


def test_legacy_fields_follow_selected_stage_range_from_developer_to_qa_local(tmp_path):
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

    state = resolve_legacy_form_state(
        tmp_path,
        {"tags": ["acquiring-service"], "first_role": "developer", "last_role": "qa_local"},
    )

    assert "dataset" not in {field.key for field in state["fields"]}


def test_legacy_fields_before_qa_local_keep_only_task_id(tmp_path):
    devpipe_dir = tmp_path / ".devpipe"
    (devpipe_dir / "tags" / "acquiring-service" / "qa_stand").mkdir(parents=True)
    (devpipe_dir / "config.yaml").write_text(
        """
defaults:
  runner: codex
  service: acquiring
  tags:
    - acquiring-service
available:
  target_branch:
    - release1
  namespace:
    - u1
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

    state = resolve_legacy_form_state(
        tmp_path,
        {"tags": ["acquiring-service"], "first_role": "architect", "last_role": "developer"},
    )

    assert {field.key for field in state["fields"]} == {"task_id"}
