"""Tests for pipeline validator."""
from __future__ import annotations

from pathlib import Path

from devpipe.profiles.validator import validate_pipeline_file


def write_pipeline(content: str, tmp_path: Path) -> Path:
    """Write pipeline content to a temp file."""
    pipeline_path = tmp_path / "pipeline.yml"
    pipeline_path.write_text(content, encoding="utf-8")
    return pipeline_path


def write_agent(tmp_path: Path, name: str, output_field: str = "result") -> None:
    """Create a minimal agent folder for validator tests."""
    agent_dir = tmp_path / "agents" / name
    agent_dir.mkdir(parents=True)
    (agent_dir / "prompt.md").write_text(f"{name} prompt", encoding="utf-8")
    (agent_dir / "output.schema.json").write_text(
        (
            '{"type":"object","properties":{"%s":{"type":"string"}},'
            '"required":["%s"]}'
        )
        % (output_field, output_field),
        encoding="utf-8",
    )


class TestValidatePipeline:
    """Test pipeline validation."""

    def test_valid_minimal_ai_pipeline(self, tmp_path: Path):
        """Test that a minimal valid AI pipeline passes."""
        write_agent(tmp_path, "build")
        pipeline = """
version: 1
name: test
stages:
  build:
    type: ai
    default_engine: codex
    agent:
      folder: build
    out:
      result:
        type: string
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path), tmp_path)
        assert result.valid
        assert len(result.errors) == 0

    def test_valid_cmd_pipeline(self, tmp_path: Path):
        """Test that a valid command pipeline passes."""
        pipeline = """
version: 1
name: test
stages:
  build:
    type: cmd
    command:
      exec: ["echo", "ok"]
      parse: text
      result:
        mode: raw
        source: stdout
    out:
      summary:
        type: string
      stdout:
        type: string
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path), tmp_path)
        assert result.valid
        assert len(result.errors) == 0

    def test_missing_version(self, tmp_path: Path):
        """Test that missing version fails."""
        write_agent(tmp_path, "build")
        pipeline = """
name: test
stages:
  build:
    type: ai
    default_engine: codex
    agent:
      folder: build
    out:
      result:
        type: string
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path), tmp_path)
        assert not result.valid
        assert any("version" in e.message.lower() for e in result.errors)

    def test_invalid_input_type(self, tmp_path: Path):
        """Test that invalid input type fails."""
        write_agent(tmp_path, "build")
        pipeline = """
version: 1
name: test
inputs:
  my_field:
    type: invalid_type
    default: ""
stages:
  build:
    type: ai
    default_engine: codex
    agent:
      folder: build
    out:
      result:
        type: string
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path), tmp_path)
        assert not result.valid
        assert any("Invalid type" in e.message for e in result.errors)

    def test_multi_without_values_or_custom(self, tmp_path: Path):
        """Test that multi without values or custom fails."""
        write_agent(tmp_path, "build")
        pipeline = """
version: 1
name: test
inputs:
  my_field:
    type: string
    multi: true
    default: []
stages:
  build:
    type: ai
    default_engine: codex
    agent:
      folder: build
    out:
      result:
        type: string
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path), tmp_path)
        assert not result.valid
        assert any("multi=true requires either 'values' or 'custom=true'" in e.message for e in result.errors)

    def test_reserved_input_name(self, tmp_path: Path):
        """Test that reserved input names fail."""
        write_agent(tmp_path, "build")
        pipeline = """
version: 1
name: test
inputs:
  runner:
    type: string
    default: ""
stages:
  build:
    type: ai
    default_engine: codex
    agent:
      folder: build
    out:
      result:
        type: string
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path), tmp_path)
        assert not result.valid
        assert any("reserved" in e.message.lower() for e in result.errors)

    def test_tags_without_multi(self, tmp_path: Path):
        """Test that tags without multi fails."""
        write_agent(tmp_path, "build")
        pipeline = """
version: 1
name: test
inputs:
  tags:
    type: string
    default: ""
stages:
  build:
    type: ai
    default_engine: codex
    agent:
      folder: build
    out:
      result:
        type: string
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path), tmp_path)
        assert not result.valid
        assert any("tags" in e.message.lower() and "multi" in e.message.lower() for e in result.errors)

    def test_no_path_to_completed(self, tmp_path: Path):
        """Test that no path to completed fails."""
        write_agent(tmp_path, "build")
        pipeline = """
version: 1
name: test
stages:
  build:
    type: ai
    default_engine: codex
    agent:
      folder: build
    out:
      result:
        type: string
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: failed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path), tmp_path)
        assert not result.valid
        assert any("completed" in e.message.lower() for e in result.errors)

    def test_invalid_runner_in_defaults(self, tmp_path: Path):
        """Test that invalid run-level runner in defaults fails."""
        write_agent(tmp_path, "build")
        pipeline = """
version: 1
name: test
defaults:
  runner: invalid_runner
stages:
  build:
    type: ai
    default_engine: codex
    agent:
      folder: build
    out:
      result:
        type: string
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path), tmp_path)
        assert not result.valid
        assert any("runner" in e.message.lower() for e in result.errors)

    def test_invalid_binding_source(self, tmp_path: Path):
        """Test that invalid binding source fails."""
        write_agent(tmp_path, "build")
        pipeline = """
version: 1
name: test
stages:
  build:
    type: ai
    default_engine: codex
    in:
      my_input: invalid.binding
    agent:
      folder: build
    out:
      result:
        type: string
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path), tmp_path)
        assert not result.valid
        assert any("Invalid binding" in e.message or "Unknown binding" in e.message for e in result.errors)

    def test_stage_requires_explicit_type(self, tmp_path: Path):
        """Test that old pipelines without stage type fail."""
        write_agent(tmp_path, "build")
        pipeline = """
version: 1
name: test
stages:
  build:
    default_engine: codex
    agent:
      folder: build
    out:
      result:
        type: string
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path), tmp_path)
        assert not result.valid
        assert any(e.path == "stages.build.type" for e in result.errors)

    def test_stage_rejects_legacy_runner_field(self, tmp_path: Path):
        """Test that old runner field is rejected."""
        write_agent(tmp_path, "build")
        pipeline = """
version: 1
name: test
stages:
  build:
    type: ai
    runner: codex
    agent:
      folder: build
    out:
      result:
        type: string
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path), tmp_path)
        assert not result.valid
        assert any(e.path == "stages.build.runner" for e in result.errors)

    def test_default_not_in_values(self, tmp_path: Path):
        """Test that default must be in values when custom is false."""
        write_agent(tmp_path, "build")
        pipeline = """
version: 1
name: test
inputs:
  my_field:
    type: string
    default: "value3"
    values: ["value1", "value2"]
stages:
  build:
    type: ai
    default_engine: codex
    agent:
      folder: build
    out:
      result:
        type: string
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path), tmp_path)
        assert not result.valid
        assert any("not in values" in e.message for e in result.errors)

    def test_default_list_without_multi(self, tmp_path: Path):
        """Test that default cannot be a list when multi is false."""
        write_agent(tmp_path, "build")
        pipeline = """
version: 1
name: test
inputs:
  my_field:
    type: string
    default: ["value1"]
    values: ["value1", "value2"]
stages:
  build:
    type: ai
    default_engine: codex
    agent:
      folder: build
    out:
      result:
        type: string
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path), tmp_path)
        assert not result.valid
        assert any("scalar" in e.message.lower() and "list" in e.message.lower() for e in result.errors)

    def test_default_list_with_multi_valid(self, tmp_path: Path):
        """Test that default can be a list when multi is true."""
        write_agent(tmp_path, "build")
        pipeline = """
version: 1
name: test
inputs:
  my_field:
    type: string
    multi: true
    default: ["value1"]
    values: ["value1", "value2"]
stages:
  build:
    type: ai
    default_engine: codex
    agent:
      folder: build
    out:
      result:
        type: string
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path), tmp_path)
        assert result.valid, [e.message for e in result.errors]

    def test_default_list_with_multi_not_in_values(self, tmp_path: Path):
        """Test that multi default values must all be in values."""
        write_agent(tmp_path, "build")
        pipeline = """
version: 1
name: test
inputs:
  my_field:
    type: string
    multi: true
    default: ["value1", "value3"]
    values: ["value1", "value2"]
stages:
  build:
    type: ai
    default_engine: codex
    agent:
      folder: build
    out:
      result:
        type: string
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path), tmp_path)
        assert not result.valid
        assert any("not in values" in e.message for e in result.errors)

    def test_retry_limit_negative(self, tmp_path: Path):
        """Test that negative retry_limit fails."""
        write_agent(tmp_path, "build")
        pipeline = """
version: 1
name: test
stages:
  build:
    type: ai
    default_engine: codex
    retry_limit: -1
    agent:
      folder: build
    out:
      result:
        type: string
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path), tmp_path)
        assert not result.valid
        assert any("retry_limit" in e.message and "non-negative" in e.message for e in result.errors)

    def test_retry_limit_float(self, tmp_path: Path):
        """Test that float retry_limit fails."""
        write_agent(tmp_path, "build")
        pipeline = """
version: 1
name: test
stages:
  build:
    type: ai
    default_engine: codex
    retry_limit: 1.5
    agent:
      folder: build
    out:
      result:
        type: string
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path), tmp_path)
        assert not result.valid
        assert any("retry_limit" in e.message and "integer" in e.message for e in result.errors)

    def test_retry_limit_valid(self, tmp_path: Path):
        """Test that valid retry_limit passes."""
        write_agent(tmp_path, "build")
        pipeline = """
version: 1
name: test
stages:
  build:
    type: ai
    default_engine: codex
    retry_limit: 3
    agent:
      folder: build
    out:
      result:
        type: string
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path), tmp_path)
        assert result.valid, [e.message for e in result.errors]

    def test_retry_limit_zero_passes_validation(self, tmp_path: Path):
        """Test that retry_limit zero passes validator checks."""
        write_agent(tmp_path, "build")
        pipeline = """
version: 1
name: test
stages:
  build:
    type: ai
    default_engine: codex
    retry_limit: 0
    agent:
      folder: build
    out:
      result:
        type: string
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path), tmp_path)
        assert result.valid, [e.message for e in result.errors]
