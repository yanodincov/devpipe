"""Routing specifications for profile-driven pipelines."""
from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RouteCondition(BaseModel):
    """A condition for routing decisions."""
    field: str
    op: str
    value: Any

    SUPPORTED_OPERATORS: ClassVar[set[str]] = {"eq", "neq", "gt", "gte", "lt", "lte", "in", "contains"}
    VALID_FIELD_PREFIXES: ClassVar[set[str]] = {"input.", "in.", "stage.", "out.", "context.", "runtime.", "integration."}

    @field_validator("op")
    @classmethod
    def validate_operator(cls, v: str) -> str:
        """Validate operator is supported."""
        if v not in cls.SUPPORTED_OPERATORS:
            raise ValueError(f"Unsupported operator '{v}'. Supported: {', '.join(sorted(cls.SUPPORTED_OPERATORS))}")
        return v

    @field_validator("field")
    @classmethod
    def validate_field_prefix(cls, v: str) -> str:
        """Validate field has a valid prefix."""
        if not any(v.startswith(prefix) for prefix in cls.VALID_FIELD_PREFIXES):
            raise ValueError(f"Invalid field prefix in '{v}'. Must start with one of: {', '.join(sorted(cls.VALID_FIELD_PREFIXES))}")
        return v

    @field_validator("value")
    @classmethod
    def validate_value_for_in_operator(cls, v: Any, info) -> Any:
        """Validate that 'in' operator has a list value."""
        op = info.data.get("op")
        if op == "in" and not isinstance(v, list):
            raise ValueError("'in' operator requires a list value")
        return v


class RouteRule(BaseModel):
    """A routing rule that decides the next stage."""
    stage: str
    all: list[RouteCondition] | None = None
    any: list[RouteCondition] | None = None
    default: Literal[None, True] = None  # type: ignore

    @model_validator(mode="after")
    def validate_rule_structure(self) -> RouteRule:
        """Validate rule has either conditions or is a default."""
        has_conditions = (self.all is not None and len(self.all) > 0) or (self.any is not None and len(self.any) > 0)
        if not has_conditions and self.default is None:
            raise ValueError("rule must have either conditions or default")
        if self.default and has_conditions:
            raise ValueError("default rule cannot have conditions")
        if self.all is not None and self.any is not None:
            raise ValueError("cannot have both 'all' and 'any' conditions")
        return self

    @field_validator("all", "any")
    @classmethod
    def validate_conditions_not_empty(cls, v: list[RouteCondition] | None) -> list[RouteCondition] | None:
        """Validate condition lists are non-empty if provided."""
        if v is not None and len(v) == 0:
            raise ValueError("condition lists cannot be empty")
        return v


class StageRouting(BaseModel):
    """Routing configuration for a single stage."""
    stage: str
    next_stages: list[RouteRule]

    @field_validator("next_stages")
    @classmethod
    def validate_next_stages_not_empty(cls, v: list[RouteRule]) -> list[RouteRule]:
        """Validate at least one next_stages rule exists."""
        if not v:
            raise ValueError("next_stages must contain at least one rule")
        return v

    @model_validator(mode="after")
    def validate_single_default(self) -> StageRouting:
        """Validate only one default rule per stage."""
        defaults = [rule for rule in self.next_stages if rule.default]
        if len(defaults) > 1:
            raise ValueError(f"Only one default rule allowed per stage, found {len(defaults)}")
        return self


class RoutingSpec(BaseModel):
    """Complete routing specification."""
    start_stage: str
    by_stage: dict[str, StageRouting]

    @model_validator(mode="after")
    def validate_start_stage_exists(self) -> RoutingSpec:
        """Validate start_stage is defined in by_stage."""
        if self.start_stage not in self.by_stage:
            raise ValueError(f"start_stage '{self.start_stage}' is not defined in by_stage")
        return self

    @model_validator(mode="after")
    def validate_stage_references(self) -> RoutingSpec:
        """Validate all stage references in next_stages exist (except special terminal stages)."""
        available_stages = set(self.by_stage.keys())
        special_stages = {"completed", "failed"}
        for stage_name, routing in self.by_stage.items():
            for rule in routing.next_stages:
                if rule.stage not in available_stages and rule.stage not in special_stages:
                    raise ValueError(f"Stage '{stage_name}' references undefined stage '{rule.stage}'")
        return self
