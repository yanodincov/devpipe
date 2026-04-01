"""Tests for profile loader."""
from __future__ import annotations

from pathlib import Path
import pytest
import yaml

from devpipe.profiles.agent import build_stage_envelope
from devpipe.profiles.loader import ProfileDefinition, load_profile, ProfileLoadError
from devpipe.runtime.state import PipelineState


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

    def test_load_bundled_idea_lab_profile(self):
        """Test the bundled idea-lab profile loads successfully."""
        project_root = Path(__file__).resolve().parents[2]

        profile = load_profile("idea-lab", project_root=project_root)

        assert profile.name == "idea-lab"
        assert list(profile.stages.keys()) == ["intake", "expand", "critique", "refine", "finalize"]
        assert "task" in profile.inputs

    def test_idea_lab_object_outputs_define_nested_properties(self):
        """Test bundled idea-lab agent schemas define nested object properties for Codex strict mode."""
        project_root = Path(__file__).resolve().parents[2]

        profile = load_profile("idea-lab", project_root=project_root)

        for stage_name, stage in profile.stages.items():
            assert stage.agent is not None
            schema = stage.agent.schema_content
            for field_name, field_schema in schema.get("properties", {}).items():
                if field_schema.get("type") != "object":
                    continue
                assert field_schema.get("properties"), (
                    f"{stage_name}.{field_name} must define nested properties "
                    "for Codex structured output"
                )

    def test_build_stage_envelope_uses_loaded_agent_content(self):
        """Test stage envelope uses prompt_content/schema_content loaded into AgentSpec."""
        project_root = Path(__file__).resolve().parents[2]
        profile = load_profile("idea-lab", project_root=project_root)
        stage = profile.stages["intake"]
        state = PipelineState.create(
            task_id="demo-1",
            task_text="Demo task",
            selected_runner="codex",
            run_id="run-1",
        )

        envelope = build_stage_envelope(
            stage,
            state,
            model_name="gpt-test",
            effort="medium",
            project_root=project_root,
        )

        assert "You are the intake stage" in envelope.instructions
        assert envelope.output_schema == stage.agent.schema_content

    def test_build_stage_envelope_replaces_placeholders_from_stage_in_bindings(self):
        """Stage in-bindings must replace matching {{placeholders}} in prompt text."""
        project_root = Path(__file__).resolve().parents[2]
        profile = load_profile("file-demo", project_root=project_root)
        stage = profile.stages["read"]
        state = PipelineState.create(
            task_id="demo-1",
            task_text="Demo task",
            selected_runner="codex",
            run_id="run-1",
        )
        state.release_context["topic"] = "space exploration"
        state.artifacts["stage_outputs"]["write"] = {
            "file_path": "/tmp/demo.txt",
            "lines_written": 5,
            "summary": "done",
        }

        envelope = build_stage_envelope(
            stage,
            state,
            model_name="gpt-test",
            effort="medium",
            extra_context={
                "config": {
                    "task": "Demo task",
                    "extra_params": {"topic": "space exploration"},
                }
            },
            project_root=project_root,
        )

        assert "{{topic}}" not in envelope.instructions
        assert "{{file_path}}" not in envelope.instructions
        assert "{{lines_written}}" not in envelope.instructions
        assert "space exploration" in envelope.instructions
        assert "/tmp/demo.txt" in envelope.instructions
        assert "5 lines" in envelope.instructions

    def test_build_stage_envelope_replaces_idea_lab_input_placeholders(self):
        """Bundled idea-lab prompts should interpolate all declared stage inputs."""
        project_root = Path(__file__).resolve().parents[2]
        profile = load_profile("idea-lab", project_root=project_root)
        stage = profile.stages["intake"]
        state = PipelineState.create(
            task_id="demo-2",
            task_text="Launch a tiny tool for remote writers",
            selected_runner="codex",
            run_id="run-2",
        )
        state.shared_context["shared"] = {
            "created_at": "2026-04-01T00:00:00Z",
            "seed": "demo",
        }

        envelope = build_stage_envelope(
            stage,
            state,
            model_name="gpt-test",
            effort="medium",
            extra_context={
                "config": {
                    "task": "Launch a tiny tool for remote writers",
                    "tone": "playful",
                    "depth": 3,
                    "include_twist": True,
                }
            },
            project_root=project_root,
        )

        assert "{{task}}" not in envelope.instructions
        assert "{{tone}}" not in envelope.instructions
        assert "{{depth}}" not in envelope.instructions
        assert "{{include_twist}}" not in envelope.instructions
        assert "{{shared_context}}" not in envelope.instructions
        assert "Launch a tiny tool for remote writers" in envelope.instructions
        assert "playful" in envelope.instructions
        assert "3" in envelope.instructions
        assert "true" in envelope.instructions
