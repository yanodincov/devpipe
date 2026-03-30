"""Pipeline validation with graceful error collection."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ValidationError:
    """A single validation error."""
    path: str  # Dot-notation path like "inputs.task.type" or "stages.architect.agent"
    message: str
    

@dataclass  
class ValidationResult:
    """Result of validating a pipeline.yml."""
    valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)


# Reserved names that should NOT be used as input names
# These are system-controlled fields that cannot be overridden by user inputs
# Note: 'task' is allowed as it's the primary task input
RESERVED_INPUT_NAMES = {"runner", "profile", "first_role", "last_role", "model", "effort"}

# Special names that have specific handling requirements
SPECIAL_INPUT_NAMES = {
    "tags": "tags must have 'multi: true' to be used as a tag selector",
}

# Valid input types for pipeline inputs
VALID_INPUT_TYPES = {"string", "int", "bool", "object"}


def validate_pipeline_file(path: Path) -> ValidationResult:
    """Validate a pipeline.yml file and collect all errors."""
    errors: list[ValidationError] = []
    warnings: list[str] = []
    
    if not path.exists():
        return ValidationResult(
            valid=False,
            errors=[ValidationError(path="", message=f"File not found: {path}")]
        )
    
    try:
        content = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return ValidationResult(
            valid=False,
            errors=[ValidationError(path="", message=f"YAML parse error: {e}")]
        )
    
    if not isinstance(content, dict):
        return ValidationResult(
            valid=False,
            errors=[ValidationError(path="", message="Pipeline must be a YAML dictionary")]
        )
    
    version = content.get("version")
    if version != 1:
        errors.append(ValidationError(path="version", message=f"Unsupported version: {version}. Only version 1 is supported."))
    
    name = content.get("name", "")
    if not name:
        warnings.append("Profile name is not specified")
    
    inputs = content.get("inputs", {})
    if not isinstance(inputs, dict):
        errors.append(ValidationError(path="inputs", message="inputs must be a dictionary"))
        inputs = {}
    
    stages = content.get("stages", {})
    if not isinstance(stages, dict):
        errors.append(ValidationError(path="stages", message="stages must be a dictionary"))
        stages = {}
    
    routing = content.get("routing", {})
    if not isinstance(routing, dict):
        errors.append(ValidationError(path="routing", message="routing must be a dictionary"))
        routing = {}
    
    errors.extend(_validate_inputs(inputs))
    errors.extend(_validate_stages(stages))
    errors.extend(_validate_routing(routing, stages))
    
    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        data=content
    )


def _validate_inputs(inputs: dict[str, Any]) -> list[ValidationError]:
    """Validate inputs section."""
    errors: list[ValidationError] = []
    
    for input_name, spec in inputs.items():
        path_prefix = f"inputs.{input_name}"
        
        if input_name in RESERVED_INPUT_NAMES:
            errors.append(ValidationError(
                path=path_prefix,
                message=f"Input '{input_name}' is reserved for system use"
            ))
            continue
        
        # Special handling for tags
        if input_name == "tags":
            multi = spec.get("multi", False) if isinstance(spec, dict) else False
            if not multi:
                errors.append(ValidationError(
                    path=path_prefix,
                    message="tags input must have 'multi: true'"
                ))
        
        if not isinstance(spec, dict):
            errors.append(ValidationError(
                path=path_prefix,
                message="Input specification must be a dictionary"
            ))
            continue
        
        type_val = spec.get("type")
        if not type_val:
            errors.append(ValidationError(
                path=f"{path_prefix}.type",
                message="Input type is required"
            ))
        elif type_val not in VALID_INPUT_TYPES:
            errors.append(ValidationError(
                path=f"{path_prefix}.type",
                message=f"Invalid type '{type_val}'. Valid types: {', '.join(sorted(VALID_INPUT_TYPES))}"
            ))
        
        default = spec.get("default")
        multi = spec.get("multi", False)
        values = spec.get("values")
        
        # Note: multi/non-multi default type mismatches are auto-fixed in InputSpec
        
        if values is not None:
            if not isinstance(values, list):
                errors.append(ValidationError(
                    path=f"{path_prefix}.values",
                    message="values must be a list"
                ))
            elif type_val and type_val in VALID_INPUT_TYPES:
                for i, val in enumerate(values):
                    if not _check_value_type(val, type_val):
                        errors.append(ValidationError(
                            path=f"{path_prefix}.values[{i}]",
                            message=f"Value '{val}' does not match type '{type_val}'"
                        ))
        
        # Bool-specific validation: ignore/validate extra flags
        if type_val == "bool":
            if values is not None:
                warnings.append(f"{path_prefix}.values: bool type ignores 'values' (always true/false)")
            if multi:
                warnings.append(f"{path_prefix}.multi: bool type ignores 'multi' (always single select)")
            if spec.get("custom"):
                warnings.append(f"{path_prefix}.custom: bool type ignores 'custom' (no custom values allowed)")
            if spec.get("required"):
                warnings.append(f"{path_prefix}.required: bool type ignores 'required' (always optional with default)")
        
        # Validate custom flag for int type
        if type_val == "int" and values is not None:
            # int with values can have custom: true to allow custom int values
            pass
    
    return errors


def _validate_stages(stages: dict[str, Any]) -> list[ValidationError]:
    """Validate stages section."""
    errors: list[ValidationError] = []
    
    for stage_name, spec in stages.items():
        path_prefix = f"stages.{stage_name}"
        
        if not isinstance(spec, dict):
            errors.append(ValidationError(
                path=path_prefix,
                message="Stage specification must be a dictionary"
            ))
            continue
        
        agent = spec.get("agent")
        if agent is not None:
            if isinstance(agent, str):
                pass
            elif isinstance(agent, dict):
                prompt = agent.get("prompt")
                if prompt and not isinstance(prompt, str):
                    errors.append(ValidationError(
                        path=f"{path_prefix}.agent.prompt",
                        message="Agent prompt must be a string"
                    ))
            else:
                errors.append(ValidationError(
                    path=f"{path_prefix}.agent",
                    message="Agent must be a string (name) or dictionary"
                ))
        
        in_bindings = spec.get("in", {})
        if in_bindings and not isinstance(in_bindings, dict):
            errors.append(ValidationError(
                path=f"{path_prefix}.in",
                message="Stage inputs must be a dictionary"
            ))
        
        out_fields = spec.get("out", {})
        if out_fields and not isinstance(out_fields, dict):
            errors.append(ValidationError(
                path=f"{path_prefix}.out",
                message="Stage outputs must be a dictionary"
            ))
    
    return errors


def _validate_routing(routing: dict[str, Any], stages: dict[str, Any]) -> list[ValidationError]:
    """Validate routing section."""
    errors: list[ValidationError] = []
    
    start_stage = routing.get("start_stage")
    if not start_stage:
        errors.append(ValidationError(
            path="routing.start_stage",
            message="start_stage is required"
        ))
    elif start_stage not in stages:
        errors.append(ValidationError(
            path="routing.start_stage",
            message=f"start_stage '{start_stage}' is not defined in stages"
        ))
    
    by_stage = routing.get("by_stage", {})
    if not isinstance(by_stage, dict):
        errors.append(ValidationError(
            path="routing.by_stage",
            message="by_stage must be a dictionary"
        ))
        return errors
    
    stage_names = set(stages.keys())
    
    for stage_name, stage_routing in by_stage.items():
        path_prefix = f"routing.by_stage.{stage_name}"
        
        if stage_name not in stage_names:
            errors.append(ValidationError(
                path=path_prefix,
                message=f"Stage '{stage_name}' is not defined in stages section"
            ))
        
        if not isinstance(stage_routing, dict):
            errors.append(ValidationError(
                path=path_prefix,
                message="Stage routing must be a dictionary"
            ))
            continue
        
        next_stages = stage_routing.get("next_stages", [])
        if not isinstance(next_stages, list):
            errors.append(ValidationError(
                path=f"{path_prefix}.next_stages",
                message="next_stages must be a list"
            ))
            continue
        
        for i, rule in enumerate(next_stages):
            if not isinstance(rule, dict):
                errors.append(ValidationError(
                    path=f"{path_prefix}.next_stages[{i}]",
                    message="Rule must be a dictionary"
                ))
                continue
            
            target_stage = rule.get("stage")
            if not target_stage:
                errors.append(ValidationError(
                    path=f"{path_prefix}.next_stages[{i}].stage",
                    message="Rule must specify 'stage'"
                ))
            elif target_stage not in stage_names and target_stage not in {"completed", "failed"}:
                errors.append(ValidationError(
                    path=f"{path_prefix}.next_stages[{i}].stage",
                    message=f"Target stage '{target_stage}' is not defined in stages"
                ))
    
    return errors


def _check_value_type(value: Any, type_name: str) -> bool:
    """Check if value matches the declared type."""
    if type_name == "string":
        return isinstance(value, str)
    elif type_name == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    elif type_name == "bool":
        return isinstance(value, bool)
    elif type_name == "object":
        return isinstance(value, dict)
    return True


def format_validation_errors(errors: list[ValidationError]) -> list[str]:
    """Format validation errors for display."""
    return [f"{e.path}: {e.message}" if e.path else e.message for e in errors]