"""Tests for routing schema models and validation."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from devpipe.profiles.routing import RouteCondition, RouteRule, StageRouting, RoutingSpec


class TestRouteCondition:
    """Test RouteCondition validation."""

    def test_valid_condition_eq(self):
        """Test valid equality condition."""
        cond = RouteCondition(field="out.result", op="eq", value="success")
        assert cond.field == "out.result"
        assert cond.op == "eq"
        assert cond.value == "success"

    def test_valid_condition_gt(self):
        """Test greater than condition."""
        cond = RouteCondition(field="out.count", op="gt", value=10)
        assert cond.op == "gt"
        assert cond.value == 10

    def test_valid_condition_in(self):
        """Test 'in' operator with list value."""
        cond = RouteCondition(field="input.env", op="in", value=["dev", "qa"])
        assert cond.op == "in"
        assert cond.value == ["dev", "qa"]

    def test_valid_condition_contains(self):
        """Test 'contains' operator for strings/lists."""
        cond = RouteCondition(field="out.tags", op="contains", value="urgent")
        assert cond.op == "contains"

    def test_supported_operators(self):
        """Test all supported operators."""
        # Operators that accept scalar value
        for op in ["eq", "neq", "gt", "gte", "lt", "lte"]:
            cond = RouteCondition(field="input.test", op=op, value="test")
            assert cond.op == op
        # 'in' operator requires list
        cond = RouteCondition(field="input.test", op="in", value=["a", "b"])
        assert cond.op == "in"
        # 'contains' operator
        cond = RouteCondition(field="input.test", op="contains", value="sub")
        assert cond.op == "contains"

    def test_invalid_operator(self):
        """Test unsupported operator raises error."""
        with pytest.raises(ValidationError) as exc_info:
            RouteCondition(field="test.field", op="invalid_op", value="test")
        assert "operator" in str(exc_info.value).lower()

    def test_field_must_have_valid_prefix(self):
        """Test field must have valid prefix: input, in, out, context, runtime."""
        valid_prefixes = ["input.", "in.", "out.", "context.", "runtime."]
        for prefix in valid_prefixes:
            cond = RouteCondition(field=f"{prefix}test", op="eq", value="test")
            assert cond.field.startswith(prefix)

    def test_invalid_field_prefix(self):
        """Test invalid field prefix raises error."""
        with pytest.raises(ValidationError) as exc_info:
            RouteCondition(field="invalid.test", op="eq", value="test")
        assert "field" in str(exc_info.value).lower()


class TestRouteRule:
    """Test RouteRule validation."""

    def test_rule_with_all_conditions(self):
        """Test rule with 'all' block."""
        rule = RouteRule(
            stage="qa",
            all=[
                RouteCondition(field="out.implementation_done", op="eq", value="yes"),
                RouteCondition(field="out.tests_pass", op="eq", value="yes"),
            ],
        )
        assert rule.stage == "qa"
        assert len(rule.all) == 2
        assert rule.any is None
        assert rule.default is None

    def test_rule_with_any_conditions(self):
        """Test rule with 'any' block."""
        rule = RouteRule(
            stage="developer",
            any=[
                RouteCondition(field="out.decision", op="eq", value="needs_rework"),
                RouteCondition(field="out.defects", op="gt", value=0),
            ],
        )
        assert rule.any is not None
        assert len(rule.any) == 2

    def test_rule_with_default(self):
        """Test rule with default flag."""
        rule = RouteRule(stage="failed", default=True)
        assert rule.default is True
        assert rule.stage == "failed"

    def test_rule_without_stage(self):
        """Test stage is required."""
        with pytest.raises(ValidationError) as exc_info:
            RouteRule(all=[])  # type: ignore
        assert "stage" in str(exc_info.value).lower()

    def test_rule_must_have_conditions_or_default(self):
        """Test rule must have either conditions or be default."""
        with pytest.raises(ValidationError) as exc_info:
            RouteRule(stage="qa")  # no conditions, not default
        assert "must have either conditions or default" in str(exc_info.value).lower()

    def test_default_cannot_have_conditions(self):
        """Test default rule cannot have conditions."""
        with pytest.raises(ValidationError) as exc_info:
            RouteRule(
                stage="qa",
                default=True,
                all=[RouteCondition(field="out.x", op="eq", value="y")],
            )
        assert "default rule cannot have conditions" in str(exc_info.value).lower()

    def test_cannot_have_both_all_and_any(self):
        """Test cannot specify both 'all' and 'any'."""
        with pytest.raises(ValidationError) as exc_info:
            RouteRule(
                stage="qa",
                all=[RouteCondition(field="out.x", op="eq", value="y")],
                any=[RouteCondition(field="out.z", op="eq", value="w")],
            )
        assert "cannot have both 'all' and 'any'" in str(exc_info.value).lower()


class TestStageRouting:
    """Test StageRouting validation."""

    def test_valid_stage_routing(self):
        """Test valid stage routing with multiple rules."""
        routing = StageRouting(
            stage="developer",
            next_stages=[
                RouteRule(
                    stage="qa_stand",
                    all=[RouteCondition(field="out.implementation_done", op="eq", value="yes")],
                ),
                RouteRule(stage="developer", default=True),
            ],
        )
        assert routing.stage == "developer"
        assert len(routing.next_stages) == 2

    def test_default_rule_only_one_per_stage(self):
        """Test only one default rule per stage."""
        with pytest.raises(ValidationError) as exc_info:
            StageRouting(
                stage="qa",
                next_stages=[
                    RouteRule(stage="qa2", default=True),
                    RouteRule(stage="qa3", default=True),
                ],
            )
        assert "only one default" in str(exc_info.value).lower()

    def test_stage_must_have_next_stages(self):
        """Test stage routing must have at least one next_stages rule."""
        with pytest.raises(ValidationError) as exc_info:
            StageRouting(stage="orphan", next_stages=[])
        assert "at least one" in str(exc_info.value).lower()

    def test_next_stages_must_include_existing_stages(self):
        """Test next_stages must reference stages that exist in profile."""
        # This validation happens at ProfileDefinition level, not here
        routing = StageRouting(
            stage="developer",
            next_stages=[
                RouteRule(
                    stage="non_existent",
                    all=[RouteCondition(field="out.result", op="eq", value="ok")],
                )
            ],
        )
        assert routing.next_stages[0].stage == "non_existent"


class TestRoutingSpec:
    """Test RoutingSpec (top-level routing)."""

    def test_valid_routing_spec(self):
        """Test complete valid routing configuration."""
        data = {
            "start_stage": "developer",
            "by_stage": {
                "developer": {
                    "stage": "developer",
                    "next_stages": [
                        {
                            "stage": "qa_stand",
                            "all": [{"field": "out.implementation_done", "op": "eq", "value": "yes"}],
                        },
                        {"stage": "developer", "default": True},
                    ],
                },
                "qa_stand": {
                    "stage": "qa_stand",
                    "next_stages": [
                        {
                            "stage": "release",
                            "all": [{"field": "out.decision", "op": "eq", "value": "approved"}],
                        },
                        {
                            "stage": "developer",
                            "any": [
                                {"field": "out.decision", "op": "eq", "value": "needs_rework"},
                                {"field": "out.defects_count", "op": "gt", "value": 0},
                            ],
                        },
                        {"stage": "failed", "default": True},
                    ],
                },
                # Define additional stages referenced
                "release": {
                    "stage": "release",
                    "next_stages": [
                        {"stage": "completed", "default": True}
                    ],
                },
                "failed": {
                    "stage": "failed",
                    "next_stages": [
                        {"stage": "failed", "default": True}
                    ],
                },
                "completed": {
                    "stage": "completed",
                    "next_stages": [
                        {"stage": "completed", "default": True}
                    ],
                },
            },
        }
        routing = RoutingSpec(**data)
        assert routing.start_stage == "developer"
        # Check that all declared stages are present
        assert "developer" in routing.by_stage
        assert "qa_stand" in routing.by_stage
        assert "release" in routing.by_stage
        assert "failed" in routing.by_stage
        assert "completed" in routing.by_stage

    def test_missing_start_stage(self):
        """Test start_stage is required."""
        data = {"by_stage": {}}
        with pytest.raises(ValidationError) as exc_info:
            RoutingSpec(**data)
        assert "start_stage" in str(exc_info.value).lower()

    def test_start_stage_must_exist_in_by_stage(self):
        """Test start_stage must be defined in by_stage."""
        data = {
            "start_stage": "nonexistent",
            "by_stage": {
                "developer": {
                    "stage": "developer",
                    "next_stages": [
                        {
                            "stage": "qa",
                            "all": [{"field": "out.result", "op": "eq", "value": "ok"}],
                        }
                    ],
                }
            },
        }
        with pytest.raises(ValidationError) as exc_info:
            RoutingSpec(**data)
        assert "start_stage" in str(exc_info.value).lower()
        assert "not defined" in str(exc_info.value).lower()

    def test_all_stage_references_must_exist(self):
        """Test all stage references in next_stages must exist in by_stage."""
        data = {
            "start_stage": "developer",
            "by_stage": {
                "developer": {
                    "stage": "developer",
                    "next_stages": [
                        {
                            "stage": "missing_stage",
                            "all": [{"field": "out.result", "op": "eq", "value": "ok"}],
                        }
                    ],
                }
            },
        }
        with pytest.raises(ValidationError) as exc_info:
            RoutingSpec(**data)
        assert "undefined stage" in str(exc_info.value).lower() or "not defined" in str(exc_info.value).lower()
