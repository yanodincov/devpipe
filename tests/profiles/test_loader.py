"""Tests for profile loader."""
from __future__ import annotations

from pathlib import Path
import pytest
import yaml

from devpipe.profiles.loader import ProfileDefinition, load_profile, ProfileLoadError


class TestProfileLoader:
    """Test profile loading from files."""

    def test_load_profile_from_project(self, tmp_path: Path):
        """Test loading a profile from .devpipe/profiles/."""
        project_root = tmp_path / "myproject"
        project_root.mkdir()
        profiles_dir = project_root / ".devpipe" / "profiles" / "myprofile"
        profiles_dir.mkdir(parents=True)

        pipeline_yml = profiles_dir / "pipeline.yml"
        pipeline_yml.write_text(
            """
version: 1
name: myprofile
inputs:
  task:
    type: string
    default: ""
    custom: true
stages:
  developer:
    runner: codex
    model: medium
    effort: middle
    out:
      code:
        type: string
routing:
  start_stage: developer
  by_stage:
    developer:
      next_stages:
        - stage: completed
          default: true
"""
        )

        profile = load_profile("myprofile", project_root=project_root)
        assert profile.name == "myprofile"
        assert "developer" in profile.stages
        assert "task" in profile.inputs

    def test_load_profile_from_yaml_extension(self, tmp_path: Path):
        """Test loading a profile with .yaml extension."""
        project_root = tmp_path / "myproject"
        project_root.mkdir()
        profiles_dir = project_root / ".devpipe" / "profiles" / "yamlprofile"
        profiles_dir.mkdir(parents=True)

        pipeline_yaml = profiles_dir / "pipeline.yaml"
        pipeline_yaml.write_text(
            """
version: 1
name: yamlprofile
inputs:
  message:
    type: string
    default: "test"
    custom: true
stages:
  echo:
    runner: codex
    model: low
    effort: low
    out:
      output:
        type: string
routing:
  start_stage: echo
  by_stage:
    echo:
      next_stages:
        - stage: completed
          default: true
"""
        )

        profile = load_profile("yamlprofile", project_root=project_root)
        assert profile.name == "yamlprofile"
        assert "echo" in profile.stages

    def test_missing_pipeline_yml_raises_error(self, tmp_path: Path):
        """Test error when pipeline file is missing."""
        project_root = tmp_path / "myproject"
        project_root.mkdir()
        profile_dir = project_root / ".devpipe" / "profiles" / "broken"
        profile_dir.mkdir(parents=True)

        with pytest.raises(ProfileLoadError, match="Profile 'broken' not found"):
            load_profile("broken", project_root=project_root)

    def test_profile_requires_stages_and_routing(self, tmp_path: Path):
        """Test profile must have both stages and routing."""
        project_root = tmp_path / "myproject"
        project_root.mkdir()
        profiles_dir = project_root / ".devpipe" / "profiles" / "incomplete"
        profiles_dir.mkdir(parents=True)

        pipeline_yml = profiles_dir / "pipeline.yml"
        pipeline_yml.write_text(
            """
version: 1
name: incomplete
inputs:
  task:
    type: string
    default: ""
    custom: true
stages:
  developer:
    runner: codex
    model: medium
    effort: middle
    out:
      code:
        type: string
"""
        )

        with pytest.raises(ProfileLoadError, match="missing required sections"):
            load_profile("incomplete", project_root=project_root)

    def test_routing_stages_must_match_existing_stages(self, tmp_path: Path):
        """Test routing must only reference defined stages."""
        project_root = tmp_path / "myproject"
        project_root.mkdir()
        profiles_dir = project_root / ".devpipe" / "profiles" / "mismatch"
        profiles_dir.mkdir(parents=True)

        pipeline_yml = profiles_dir / "pipeline.yml"
        pipeline_yml.write_text(
            """
version: 1
name: mismatch
inputs:
  task:
    type: string
    default: ""
    custom: true
stages:
  defined_stage:
    runner: codex
    model: medium
    effort: middle
    out:
      result:
        type: string
routing:
  start_stage: defined_stage
  by_stage:
    defined_stage:
      next_stages:
        - stage: undefined_stage
          default: true
"""
        )

        with pytest.raises(ProfileLoadError, match="references undefined stage"):
            load_profile("mismatch", project_root=project_root)

    def test_profile_definition_integration(self):
        """Test ProfileDefinition connects stages and routing properly."""
        from devpipe.profiles.stages import ProfileStages
        from devpipe.profiles.routing import RoutingSpec

        # Create minimal valid data
        stages = ProfileStages(
            inputs={
                "task": {"type": "string", "default": "", "custom": True},
            },
            stages={
                "dev": {"runner": "codex", "model": "medium", "effort": "middle", "out": {"code": {"type": "string"}}},
            },
        )

        routing = RoutingSpec(
            start_stage="dev",
            by_stage={
                "dev": {"stage": "dev", "next_stages": [{"stage": "completed", "default": True}]},
                "completed": {"stage": "completed", "next_stages": [{"stage": "completed", "default": True}]},
            },
        )

        profile = ProfileDefinition(
            name="test",
            defaults={"runner": "codex"},
            inputs=stages.inputs,
            stages=stages.stages,
            routing=routing,
        )

        assert profile.name == "test"
        assert profile.stages["dev"].name == "dev"
        assert profile.routing.start_stage == "dev"
        # Verify routing stage exists in stages
        assert profile.routing.start_stage in profile.stages
