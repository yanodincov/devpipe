"""Tests for pipeline validator."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from devpipe.profiles.validator import (
    validate_pipeline_file,
    validate_profile,
    ValidationResult,
    ValidationError,
)


def write_pipeline(content: str, tmp_path: Path) -> Path:
    """Write pipeline content to a temp file."""
    pipeline_path = tmp_path / "pipeline.yml"
    pipeline_path.write_text(content, encoding="utf-8")
    return pipeline_path


class TestValidatePipeline:
    """Test pipeline validation."""

    def test_valid_minimal_pipeline(self, tmp_path: Path):
        """Test that a minimal valid pipeline passes."""
        pipeline = """
version: 1
name: test
stages:
  build:
    runner: codex
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path))
        assert result.valid
        assert len(result.errors) == 0

    def test_missing_version(self, tmp_path: Path):
        """Test that missing version fails."""
        pipeline = """
name: test
stages:
  build:
    runner: codex
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path))
        assert not result.valid
        assert any("version" in e.message.lower() for e in result.errors)

    def test_invalid_input_type(self, tmp_path: Path):
        """Test that invalid input type fails."""
        pipeline = """
version: 1
name: test
inputs:
  my_field:
    type: invalid_type
    default: ""
stages:
  build:
    runner: codex
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path))
        assert not result.valid
        assert any("Invalid type" in e.message for e in result.errors)

    def test_multi_without_values_or_custom(self, tmp_path: Path):
        """Test that multi without values or custom fails."""
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
    runner: codex
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path))
        assert not result.valid
        assert any("multi=true requires either 'values' or 'custom=true'" in e.message for e in result.errors)

    def test_reserved_input_name(self, tmp_path: Path):
        """Test that reserved input names fail."""
        pipeline = """
version: 1
name: test
inputs:
  runner:
    type: string
    default: ""
stages:
  build:
    runner: codex
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path))
        assert not result.valid
        assert any("reserved" in e.message.lower() for e in result.errors)

    def test_tags_without_multi(self, tmp_path: Path):
        """Test that tags without multi fails."""
        pipeline = """
version: 1
name: test
inputs:
  tags:
    type: string
    default: ""
stages:
  build:
    runner: codex
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path))
        assert not result.valid
        assert any("tags" in e.message.lower() and "multi" in e.message.lower() for e in result.errors)

    def test_no_path_to_completed(self, tmp_path: Path):
        """Test that no path to completed fails."""
        pipeline = """
version: 1
name: test
stages:
  build:
    runner: codex
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: failed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path))
        assert not result.valid
        assert any("completed" in e.message.lower() for e in result.errors)

    def test_invalid_runner_in_defaults(self, tmp_path: Path):
        """Test that invalid runner in defaults fails."""
        pipeline = """
version: 1
name: test
defaults:
  runner: invalid_runner
stages:
  build:
    runner: codex
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path))
        assert not result.valid
        assert any("runner" in e.message.lower() for e in result.errors)

    def test_invalid_binding_source(self, tmp_path: Path):
        """Test that invalid binding source fails."""
        pipeline = """
version: 1
name: test
stages:
  build:
    runner: codex
    in:
      my_input: invalid.binding
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path))
        assert not result.valid
        assert any("Invalid binding" in e.message or "Unknown binding" in e.message for e in result.errors)

    def test_valid_pipeline_with_inputs(self, tmp_path: Path):
        """Test that a valid pipeline with multiple inputs passes."""
        pipeline = """
version: 1
name: test
inputs:
  my_string:
    type: string
    default: ""
    custom: true
  my_int:
    type: int
    default: 5
    values: [1, 2, 3, 4, 5]
    custom: true
  my_bool:
    type: bool
    default: false
  tags:
    type: string
    multi: true
    default: []
    custom: true
stages:
  build:
    runner: codex
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
"""
        result = validate_pipeline_file(write_pipeline(pipeline, tmp_path))
        assert result.valid, [e.message for e in result.errors]