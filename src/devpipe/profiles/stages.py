"""Stage and input specifications for profile-driven pipelines."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class InputType(str, Enum):
    """Supported input value types."""
    STRING = "string"
    INT = "int"
    BOOL = "bool"
    OBJECT = "object"
    ARRAY = "array"


def _parse_inputs_soft(inputs_data: dict[str, Any]) -> tuple[dict[str, "InputSpec"], list[str]]:
    """Parse inputs with error collection instead of failing.
    
    Returns tuple of (parsed_inputs, error_messages).
    Invalid inputs are skipped, errors are collected.
    """
    from pydantic import ValidationError
    parsed: dict[str, InputSpec] = {}
    errors: list[str] = []
    
    for key, spec_data in inputs_data.items():
        if not isinstance(spec_data, dict):
            errors.append(f"inputs.{key}: specification must be a dictionary")
            continue
        
        # Get type first
        type_val = spec_data.get("type")
        if not type_val:
            errors.append(f"inputs.{key}: type is required")
            continue
        
        # Get multi and default
        multi = spec_data.get("multi", False)
        default = spec_data.get("default")
        
        # Auto-fix default for multi fields
        if multi and not isinstance(default, list):
            # Convert scalar to empty list for multi
            spec_data = dict(spec_data)  # Copy to not modify original
            spec_data["default"] = []
            errors.append(f"inputs.{key}: multi=True requires default to be a list, auto-fixed to []")
        
        if not multi and isinstance(default, list) and spec_data.get("values") is None:
            spec_data = dict(spec_data)
            spec_data["default"] = ""
            errors.append(f"inputs.{key}: multi=False requires scalar default, auto-fixed to empty string")
        
        try:
            parsed[key] = InputSpec(**spec_data)
        except ValidationError as e:
            errors.append(f"inputs.{key}: {e}")
        except Exception as e:
            errors.append(f"inputs.{key}: {e}")
    
    return parsed, errors


class InputSpec(BaseModel):
    """Specification for a profile input."""
    type: InputType
    default: Any
    values: list[Any] | None = None
    multi: bool = False
    custom: bool = False

    @model_validator(mode="after")
    def validate_default_matches_multi(self) -> InputSpec:
        """Validate that default matches multi flag, auto-fix if needed."""
        if self.multi and not isinstance(self.default, list):
            # Auto-fix: convert scalar to list for multi fields
            object.__setattr__(self, 'default', [])
        if not self.multi and isinstance(self.default, list) and self.values is None:
            # Auto-fix: convert list to empty string for non-multi fields without values
            object.__setattr__(self, 'default', '')
        return self

    @field_validator("values")
    @classmethod
    def validate_values_match_type(cls, v: list[Any] | None, info) -> list[Any] | None:
        """Validate that values match the declared type."""
        if v is None:
            return v
        input_type = info.data.get("type")
        if input_type:
            for value in v:
                if not _check_type(value, input_type):
                    raise ValueError(f"values must match type '{input_type.value}'")
        return v

    @model_validator(mode="after")
    def validate_custom_flag(self) -> InputSpec:
        """Validate custom flag constraints."""
        # If no values provided, field is free-form (implicitly custom)
        # Exception: bool type never allows custom values
        if self.values is None and self.type != InputType.BOOL:
            # Auto-set custom=True for free-form fields (no validation needed)
            self.custom = True
        # If values provided, custom can be True or False (default False)
        # For bool, always force custom=False
        if self.type == InputType.BOOL:
            self.custom = False
        return self


class StageInBinding(BaseModel):
    """Input binding specification for a stage."""
    bindings: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _accept_raw_dict(cls, v: Any) -> dict[str, Any]:
        """Allow passing raw dict of bindings without 'bindings' wrapper."""
        if isinstance(v, dict) and "bindings" not in v:
            return {"bindings": v}
        return v

    @field_validator("bindings")
    @classmethod
    def validate_binding_paths(cls, v: dict[str, str]) -> dict[str, str]:
        """Validate binding source paths."""
        allowed_prefixes = ("input.", "context.", "stage.", "runtime.", "integration.")
        for source in v.values():
            if not source.startswith(allowed_prefixes):
                raise ValueError(f"Invalid binding source: {source}. Must start with {', '.join(allowed_prefixes)}")
        return v


class FieldSpec(BaseModel):
    """Specification for an output field."""
    type: InputType
    description: str | None = None


class StageOutField(BaseModel):
    """Output fields specification."""
    fields: dict[str, FieldSpec]


class AgentSpec(BaseModel):
    """Agent specification for a stage.
    
    Either 'folder' or both 'prompt' and 'schema' must be specified.
    - folder: path to directory containing prompt.md and output.schema.json
    - prompt: path to prompt file (relative to profile directory)
    - schema: path to output schema file (relative to profile directory)
    
    After loading, prompt_content and schema_content contain the file contents.
    """
    model_config = ConfigDict(extra='forbid', populate_by_name=True)

    folder: str | None = None
    prompt: str | None = None
    schema_path: str | None = Field(default=None, alias="schema")
    # Loaded content (populated after loading)
    prompt_content: str = ""
    schema_content: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_agent_spec(self) -> AgentSpec:
        """Validate that either folder or (prompt + schema) is specified."""
        if self.folder:
            if self.prompt or self.schema_path:
                raise ValueError("agent: when 'folder' is specified, 'prompt' and 'schema' must not be set")
            return self
        if self.prompt and self.schema_path:
            return self
        raise ValueError("agent: must specify either 'folder' or both 'prompt' and 'schema'")


class StageSpec(BaseModel):
    """Complete specification for a pipeline stage."""
    model_config = ConfigDict(populate_by_name=True)

    name: str
    runner: str = "codex"
    model: str = "middle"
    effort: str = "middle"
    in_: StageInBinding | None = Field(default=None, alias="in")
    out: StageOutField
    retry_limit: int = 1
    tags: list[str] = Field(default_factory=list)
    agent: AgentSpec | None = None

    @field_validator("name")
    @classmethod
    def validate_name_identifier(cls, v: str) -> str:
        """Validate stage name is a valid identifier."""
        if not v.isidentifier():
            raise ValueError("stage name must be a valid Python identifier")
        return v

    @field_validator("runner")
    @classmethod
    def validate_runner(cls, v: str) -> str:
        """Accept any runner value - validation happens in validator module."""
        return v

    @field_validator("model", mode="before")
    @classmethod
    def normalize_model(cls, v: Any) -> str:
        """Accept 'medium' as alias for 'middle'."""
        if v == "medium":
            return "middle"
        return v

    @field_validator("effort", mode="before")
    @classmethod
    def normalize_effort(cls, v: Any) -> str:
        """Accept 'medium' as alias for 'middle'."""
        if v == "medium":
            return "middle"
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        """Validate model level."""
        allowed = {"low", "middle", "high", "auto"}
        if v not in allowed:
            raise ValueError(f"model must be one of: {', '.join(allowed)}")
        return v

    @field_validator("effort")
    @classmethod
    def validate_effort(cls, v: str) -> str:
        """Validate effort level."""
        allowed = {"low", "middle", "high", "auto"}
        if v not in allowed:
            raise ValueError(f"effort must be one of: {', '.join(allowed)}")
        return v

    @model_validator(mode="after")
    def validate_retry_limit(self) -> StageSpec:
        """Validate retry limit is positive."""
        if self.retry_limit < 1:
            raise ValueError("retry_limit must be >= 1")
        return self

    @field_validator("out", mode="before")
    @classmethod
    def _parse_out_dict(cls, v: Any) -> dict[str, Any]:
        """Parse raw out dict into StageOutField structure."""
        if isinstance(v, dict) and "fields" not in v:
            # raw dict of field_name -> field_spec
            fields_dict: dict[str, FieldSpec | dict[str, Any]] = {}
            for field_name, spec in v.items():
                if isinstance(spec, dict):
                    fields_dict[field_name] = spec
                else:
                    # Allow shorthand like "type: string" only? We expect dict.
                    fields_dict[field_name] = {"type": spec}
            return {"fields": fields_dict}
        return v


class ProfileStages(BaseModel):
    """Top-level stages section of a profile."""
    inputs: dict[str, InputSpec] = Field(default_factory=dict)
    stages: dict[str, StageSpec]

    @model_validator(mode="before")
    @classmethod
    def _inject_stage_names(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Inject stage name from dict key if not provided."""
        stages = values.get("stages", {})
        for key, stage_dict in stages.items():
            if isinstance(stage_dict, dict) and "name" not in stage_dict:
                stage_dict["name"] = key
        return values

    @field_validator("stages")
    @classmethod
    def validate_stage_names(cls, v: dict[str, StageSpec]) -> dict[str, StageSpec]:
        """Validate all stage names match their keys."""
        for key, stage in v.items():
            if stage.name != key:
                raise ValueError(f"stage name '{stage.name}' doesn't match dict key '{key}'")
        return v


def _check_type(value: Any, type_name: InputType) -> bool:
    """Check if a value matches the specified type."""
    if type_name == InputType.STRING:
        return isinstance(value, str)
    if type_name == InputType.INT:
        return isinstance(value, int) and not isinstance(value, bool)  # bool is subclass of int
    if type_name == InputType.BOOL:
        return isinstance(value, bool)
    if type_name == InputType.OBJECT:
        return isinstance(value, dict)
    if type_name == InputType.ARRAY:
        return isinstance(value, list)
    return False
