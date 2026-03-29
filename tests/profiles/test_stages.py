"""Tests for stage schema models and validation."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from devpipe.profiles.stages import InputSpec, StageSpec, ProfileStages


class TestInputSpec:
    """Test InputSpec validation."""

    def test_valid_string_input(self):
        """Test valid string input with all optional fields."""
        spec = InputSpec(type="string", default="test", values=["a", "b"], multi=False, custom=True)
        assert spec.type == "string"
        assert spec.default == "test"
        assert spec.values == ["a", "b"]
        assert spec.multi is False
        assert spec.custom is True

    def test_valid_int_input(self):
        """Test valid int input."""
        spec = InputSpec(type="int", default=42, values=[1, 2, 3], multi=False, custom=False)
        assert spec.type == "int"
        assert spec.default == 42
        assert spec.values == [1, 2, 3]

    def test_multi_string_with_list_default(self):
        """Test multi=true requires list default for string type."""
        spec = InputSpec(type="string", default=["a", "b"], multi=True, custom=True)
        assert spec.multi is True
        assert isinstance(spec.default, list)

    def test_multi_int_with_list_default(self):
        """Test multi=true requires list default for int type."""
        spec = InputSpec(type="int", default=[1, 2], values=[1, 2, 3], multi=True, custom=False)
        assert spec.multi is True
        assert isinstance(spec.default, list)

    def test_single_multi_false_requires_scalar_default(self):
        """Test multi=false requires scalar default."""
        with pytest.raises(ValidationError) as exc_info:
            InputSpec(type="string", default=["a", "b"], multi=False, custom=True)
        assert "multi=False requires scalar default" in str(exc_info.value)

    def test_custom_false_requires_value_in_values(self):
        """Test custom=false requires runtime value from values list."""
        spec = InputSpec(type="string", default="allowed", values=["allowed", "another"], custom=False)
        assert spec.custom is False
        # This should be valid because default is in values

    def test_custom_true_allows_any_value_of_type(self):
        """Test custom=true allows any valid type value."""
        spec = InputSpec(type="string", default="any_value", values=["allowed"], custom=True)
        assert spec.custom is True
        # Should allow default even if not in values

    def test_values_type_mismatch(self):
        """Test values must match the declared type."""
        with pytest.raises(ValidationError) as exc_info:
            InputSpec(type="int", values=["not_int", "also_not_int"], custom=False)
        assert "values must match type" in str(exc_info.value).lower()

    def test_required_type_field(self):
        """Test type field is required."""
        with pytest.raises(ValidationError) as exc_info:
            InputSpec(default="test")  # type: ignore
        assert "type" in str(exc_info.value).lower()


class TestStageSpec:
    """Test StageSpec validation."""

    def test_valid_stage_with_inputs_and_outputs(self):
        """Test valid stage with in/out bindings."""
        stage_data = {
            "name": "test_stage",
            "runner": "codex",
            "model": "medium",
            "effort": "middle",
            "in": {"task": "input.task", "context": "context.shared"},
            "out": {"result": {"type": "string"}, "count": {"type": "int"}},
        }
        stage = StageSpec(**stage_data)
        assert stage.name == "test_stage"
        assert stage.runner == "codex"
        assert stage.in_.bindings == {"task": "input.task", "context": "context.shared"}
        assert len(stage.out.fields) == 2

    def test_stage_without_in(self):
        """Test stage can have no input bindings."""
        stage = StageSpec(name="simple", runner="codex", model="medium", effort="middle", out={"result": {"type": "string"}})
        assert stage.in_ is None or stage.in_.bindings == {}

    def test_stage_without_out(self):
        """Test stage must have out fields."""
        with pytest.raises(ValidationError) as exc_info:
            StageSpec(name="bad", runner="codex", model="medium", effort="middle", **{"in": {"x": "input.y"}})  # type: ignore
        assert "out" in str(exc_info.value).lower()

    def test_out_field_requires_type(self):
        """Test out fields require type specification."""
        with pytest.raises(ValidationError):
            StageSpec(name="bad", runner="codex", model="medium", effort="middle", **{"out": {"field": {}}})  # type: ignore

    def test_valid_out_field_types(self):
        """Test valid out field type values."""
        stage = StageSpec(
            name="test",
            runner="codex",
            model="medium",
            effort="middle",
            out={
                "string_field": {"type": "string"},
                "int_field": {"type": "int"},
                "bool_field": {"type": "bool"},
                "object_field": {"type": "object"},
            },
        )
        assert len(stage.out.fields) == 4


class TestProfileStages:
    """Test ProfileStages (the full stages section)."""

    def test_valid_profile_stages(self):
        """Test loading valid profile stages."""
        data = {
            "inputs": {
                "task": {"type": "string", "default": "", "custom": True},
                "count": {"type": "int", "default": 0, "custom": False, "values": [1, 2, 3]},
            },
            "stages": {
                "developer": {
                    "runner": "codex",
                    "model": "medium",
                    "effort": "middle",
                    "in": {"task": "input.task"},
                    "out": {"code": {"type": "string"}},
                },
                "qa": {
                    "runner": "claude",
                    "model": "high",
                    "effort": "low",
                    "out": {"approved": {"type": "bool"}},
                },
            },
        }
        stages = ProfileStages(**data)
        assert len(stages.inputs) == 2
        assert len(stages.stages) == 2
        assert "developer" in stages.stages
        assert "qa" in stages.stages

    def test_missing_inputs_default_to_empty(self):
        """Test that inputs can be omitted."""
        data = {
            "stages": {
                "dev": {"runner": "codex", "model": "medium", "effort": "middle", "out": {"x": {"type": "string"}}},
            },
        }
        stages = ProfileStages(**data)
        assert stages.inputs == {}

    def test_stage_name_must_be_valid_identifier(self):
        """Test stage names are valid identifiers."""
        data = {
            "stages": {
                "invalid-stage-name": {"runner": "codex", "model": "medium", "effort": "middle", "out": {"x": {"type": "string"}}},
            },
        }
        with pytest.raises(ValidationError):
            ProfileStages(**data)
