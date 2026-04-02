from __future__ import annotations

from devpipe.runtime.state import STAGE_ORDER
from devpipe.ui.services import prepare_initial_state, resolve_legacy_form_state
from devpipe.ui.state import FieldKind


def write_agent(profile_dir, name: str) -> None:
    agent_dir = profile_dir / "agents" / name
    agent_dir.mkdir(parents=True)
    (agent_dir / "prompt.md").write_text(f"{name} prompt", encoding="utf-8")
    (agent_dir / "output.schema.json").write_text(
        '{"type":"object","properties":{"response":{"type":"string"},"result":{"type":"string"}},"required":["result"]}',
        encoding="utf-8",
    )


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
    # Tag params via params.yaml are deprecated - fields come from pipeline.yml only
    assert "tags" in qa_local_keys
    assert "tags" in qa_stand_keys


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

    state = resolve_legacy_form_state(
        tmp_path,
        {"tags": ["acquiring-service"], "first_role": "developer", "last_role": "qa_local"},
    )

    # Tag params via params.yaml are deprecated - fields come from pipeline.yml only
    assert "tags" in {field.key for field in state["fields"]}


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


def test_profile_with_reserved_input_name_shows_error(tmp_path):
    """Test that profile with reserved input name shows error but is still selectable."""
    devpipe_dir = tmp_path / ".devpipe"
    profiles_dir = devpipe_dir / "profiles" / "bad-profile"
    profiles_dir.mkdir(parents=True)
    write_agent(profiles_dir, "echo")
    
    # Profile with reserved input name 'runner' - need valid stages
    (profiles_dir / "pipeline.yml").write_text(
        """
version: 1
name: bad-profile
inputs:
  runner:
    type: string
    default: ""
stages:
  echo:
    type: ai
    default_engine: codex
    agent:
      folder: echo
    in:
      msg: input.runner
    out:
      response:
        type: string
routing:
  start_stage: echo
  by_stage:
    echo:
      next_stages:
        - stage: completed
          default: true
""".strip(),
        encoding="utf-8",
    )
    
    (devpipe_dir / "config.yaml").write_text(
        "defaults:\n  profile: bad-profile",
        encoding="utf-8",
    )
    
    data = prepare_initial_state(tmp_path)
    
    # Profile should still be selectable
    assert data["profile"] == "bad-profile"
    # profile_errors should contain the conflict error
    assert len(data["profile_errors"]) >= 1
    assert any("reserved" in err.lower() for err in data["profile_errors"])


def test_profile_with_invalid_yaml_shows_error(tmp_path):
    """Test that profile with loading error shows error and falls back to empty."""
    devpipe_dir = tmp_path / ".devpipe"
    profiles_dir = devpipe_dir / "profiles" / "broken-profile"
    profiles_dir.mkdir(parents=True)
    
    # Valid YAML structure but invalid stage definition (missing required field)
    (profiles_dir / "pipeline.yml").write_text(
        """
version: 1
name: broken-profile
inputs:
  message:
    type: string
stages:
  echo:
    type: ai
    default_engine: codex
    # Missing required 'out' field
routing:
  start_stage: echo
  by_stage:
    echo:
      next_stages:
        - stage: completed
          default: true
""".strip(),
        encoding="utf-8",
    )
    
    (devpipe_dir / "config.yaml").write_text(
        "defaults:\n  profile: broken-profile",
        encoding="utf-8",
    )
    
    data = prepare_initial_state(tmp_path)
    
    # Should have profile_errors due to validation failure
    assert len(data["profile_errors"]) >= 1
    # Error message should mention the validation issue
    assert any("Invalid" in err or "Failed" in err for err in data["profile_errors"])


def test_profile_missing_routing_shows_error(tmp_path):
    """Test that profile missing routing shows error."""
    devpipe_dir = tmp_path / ".devpipe"
    profiles_dir = devpipe_dir / "profiles" / "incomplete-profile"
    profiles_dir.mkdir(parents=True)
    write_agent(profiles_dir, "echo")
    
    # Missing routing section
    (profiles_dir / "pipeline.yml").write_text(
        """
version: 1
name: incomplete-profile
inputs:
  message:
    type: string
stages:
  echo:
    type: ai
    default_engine: codex
    agent:
      folder: echo
    in:
      msg: input.message
    out:
      response:
        type: string
# Missing routing section
""".strip(),
        encoding="utf-8",
    )
    
    (devpipe_dir / "config.yaml").write_text(
        "defaults:\n  profile: incomplete-profile",
        encoding="utf-8",
    )
    
    data = prepare_initial_state(tmp_path)
    
    # Should have error about missing routing
    assert len(data["profile_errors"]) >= 1
    # Error message should mention routing or start_stage
    assert any("routing" in err.lower() or "start_stage" in err.lower() or "failed" in err.lower() for err in data["profile_errors"])


def test_profile_without_declared_tags_gets_standard_tags_field(tmp_path):
    devpipe_dir = tmp_path / ".devpipe"
    profiles_dir = devpipe_dir / "profiles" / "plain-profile"
    profiles_dir.mkdir(parents=True)
    (devpipe_dir / "tags" / "go" / "review").mkdir(parents=True)
    write_agent(profiles_dir, "review")

    (profiles_dir / "pipeline.yml").write_text(
        """
version: 1
name: plain-profile
defaults:
  runner: auto
inputs:
  message:
    type: string
    default: ""
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
    (devpipe_dir / "config.yaml").write_text(
        "defaults:\n  profile: plain-profile",
        encoding="utf-8",
    )

    data = prepare_initial_state(tmp_path)

    tags_field = next((field for field in data["fields"] if field.key == "tags"), None)
    assert tags_field is not None
    assert tags_field.kind == FieldKind.TAG_ROLES
    assert tags_field.section == "standard"
    assert data["defaults"]["tags"] == {}


def test_profile_without_declared_tags_keeps_profile_inputs_as_custom(tmp_path):
    devpipe_dir = tmp_path / ".devpipe"
    profiles_dir = devpipe_dir / "profiles" / "plain-profile"
    profiles_dir.mkdir(parents=True)
    (devpipe_dir / "tags" / "go" / "review").mkdir(parents=True)
    write_agent(profiles_dir, "review")

    (profiles_dir / "pipeline.yml").write_text(
        """
version: 1
name: plain-profile
defaults:
  runner: auto
inputs:
  message:
    type: string
    default: ""
    custom: true
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
    (devpipe_dir / "config.yaml").write_text(
        "defaults:\n  profile: plain-profile",
        encoding="utf-8",
    )

    data = prepare_initial_state(tmp_path)

    keys = {field.key: field.section for field in data["fields"]}
    assert keys["message"] == "custom"
    assert keys["tags"] == "standard"
