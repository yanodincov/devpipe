"""Pipeline validation with comprehensive rule checking."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ValidationError:
    """A single validation error."""
    path: str
    message: str
    

@dataclass  
class ValidationResult:
    """Result of validating a pipeline.yml."""
    valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)


# Reserved input names
RESERVED_INPUT_NAMES = {"runner", "profile", "first_role", "last_role", "model", "effort"}

# Valid input types
VALID_INPUT_TYPES = {"string", "int", "bool", "object"}

# Available runners
AVAILABLE_RUNNERS = {"auto", "codex", "claude"}

# Available models per runner
AVAILABLE_MODELS = {
    "codex": {"auto", "low", "middle", "high"},
    "claude": {"auto", "low", "middle", "high"},
    "auto": {"auto", "low", "middle", "high"},
}

# Available effort levels
AVAILABLE_EFFORTS = {"auto", "low", "middle", "high"}


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
    
    # Validate top-level structure
    errors.extend(_validate_top_level(content))
    if errors:
        return ValidationResult(valid=False, errors=errors, warnings=warnings, data=content)
    
    # Validate version
    version = content.get("version")
    if version != 1:
        errors.append(ValidationError(
            path="version",
            message=f"Unsupported version: {version}. Only version 1 is supported."
        ))
    
    # Validate name
    name = content.get("name", "")
    if not name:
        warnings.append("Pipeline name is not specified")
    
    # Validate inputs
    inputs = content.get("inputs", {})
    if not isinstance(inputs, dict):
        errors.append(ValidationError(path="inputs", message="inputs must be a dictionary"))
    else:
        errors.extend(_validate_inputs(inputs))
    
    # Validate stages
    stages = content.get("stages", {})
    if not isinstance(stages, dict):
        errors.append(ValidationError(path="stages", message="stages must be a dictionary"))
    else:
        errors.extend(_validate_stages(stages))
    
    # Validate routing
    routing = content.get("routing", {})
    if not isinstance(routing, dict):
        errors.append(ValidationError(path="routing", message="routing must be a dictionary"))
    else:
        errors.extend(_validate_routing(routing, stages))
    
    # Validate defaults
    defaults = content.get("defaults", {})
    if not isinstance(defaults, dict):
        errors.append(ValidationError(path="defaults", message="defaults must be a dictionary"))
    else:
        errors.extend(_validate_defaults(defaults, inputs, stages))
    
    # Cross-reference validation
    if inputs and stages and routing:
        errors.extend(_validate_cross_references(inputs, stages, routing))
    
    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        data=content
    )


def _validate_top_level(content: dict) -> list[ValidationError]:
    """Validate top-level required fields."""
    errors = []
    
    if "stages" not in content:
        errors.append(ValidationError(path="stages", message="Required field 'stages' is missing"))
    
    if "routing" not in content:
        errors.append(ValidationError(path="routing", message="Required field 'routing' is missing"))
    
    return errors


def _validate_inputs(inputs: dict[str, Any]) -> list[ValidationError]:
    """Validate inputs section."""
    errors = []
    
    for input_name, spec in inputs.items():
        path_prefix = f"inputs.{input_name}"
        
        # Check reserved names
        if input_name in RESERVED_INPUT_NAMES:
            errors.append(ValidationError(
                path=path_prefix,
                message=f"Input '{input_name}' is reserved for system use"
            ))
            continue
        
        # Special handling for tags
        if input_name == "tags":
            if isinstance(spec, dict) and not spec.get("multi", False):
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
        
        # Validate type
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
        
        # Validate multi and custom relationship
        multi = spec.get("multi", False)
        values = spec.get("values")
        custom = spec.get("custom", False)
        
        if multi and values is None and not custom:
            errors.append(ValidationError(
                path=path_prefix,
                message="multi=true requires either 'values' or 'custom=true'"
            ))
        
        # Validate values
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
        
        # Bool-specific warnings
        if type_val == "bool":
            if values is not None:
                warnings.append(f"{path_prefix}.values: bool type ignores 'values' (always true/false)")
            if multi:
                warnings.append(f"{path_prefix}.multi: bool type ignores 'multi' (always single select)")
            if custom:
                warnings.append(f"{path_prefix}.custom: bool type ignores 'custom' (no custom values)")
    
    return errors


def _validate_stages(stages: dict[str, Any]) -> list[ValidationError]:
    """Validate stages section."""
    errors = []
    
    for stage_name, spec in stages.items():
        path_prefix = f"stages.{stage_name}"
        
        # Validate stage name
        if not _is_valid_identifier(stage_name):
            errors.append(ValidationError(
                path=path_prefix,
                message=f"Stage name '{stage_name}' is not a valid identifier"
            ))
        
        if not isinstance(spec, dict):
            errors.append(ValidationError(
                path=path_prefix,
                message="Stage specification must be a dictionary"
            ))
            continue
        
        # Validate runner
        runner = spec.get("runner")
        if not runner:
            errors.append(ValidationError(
                path=f"{path_prefix}.runner",
                message="runner is required"
            ))
        elif not isinstance(runner, str):
            errors.append(ValidationError(
                path=f"{path_prefix}.runner",
                message="runner must be a string"
            ))
        
        # Validate in bindings
        in_bindings = spec.get("in", {})
        if in_bindings and not isinstance(in_bindings, dict):
            errors.append(ValidationError(
                path=f"{path_prefix}.in",
                message="Stage inputs must be a dictionary"
            ))
        elif isinstance(in_bindings, dict):
            errors.extend(_validate_input_bindings(in_bindings, f"{path_prefix}.in"))
        
        # Validate out fields
        out_fields = spec.get("out", {})
        if out_fields and not isinstance(out_fields, dict):
            errors.append(ValidationError(
                path=f"{path_prefix}.out",
                message="Stage outputs must be a dictionary"
            ))
        elif isinstance(out_fields, dict):
            errors.extend(_validate_output_fields(out_fields, f"{path_prefix}.out"))
        
        # Validate agent
        agent = spec.get("agent")
        if agent is not None:
            errors.extend(_validate_agent(agent, f"{path_prefix}.agent"))
    
    return errors


def _validate_input_bindings(bindings: dict[str, str], path_prefix: str) -> list[ValidationError]:
    """Validate input binding sources."""
    errors = []
    allowed_prefixes = ("input.", "context.", "stage.", "runtime.", "integration.")
    
    for binding_name, source in bindings.items():
        if not isinstance(source, str):
            errors.append(ValidationError(
                path=f"{path_prefix}.{binding_name}",
                message=f"Binding source must be a string, got {type(source).__name__}"
            ))
            continue
        
        if not source.startswith(allowed_prefixes):
            errors.append(ValidationError(
                path=f"{path_prefix}.{binding_name}",
                message=f"Invalid binding source '{source}'. Must start with {', '.join(allowed_prefixes)}"
            ))
    
    return errors


def _validate_output_fields(fields: dict[str, Any], path_prefix: str) -> list[ValidationError]:
    """Validate output field specifications."""
    errors = []
    valid_types = {"string", "int", "bool", "object"}
    
    for field_name, field_spec in fields.items():
        if isinstance(field_spec, str):
            # Shorthand: just type
            if field_spec not in valid_types:
                errors.append(ValidationError(
                    path=f"{path_prefix}.{field_name}",
                    message=f"Invalid type '{field_spec}'. Valid types: {', '.join(valid_types)}"
                ))
        elif isinstance(field_spec, dict):
            field_type = field_spec.get("type")
            if not field_type:
                errors.append(ValidationError(
                    path=f"{path_prefix}.{field_name}",
                    message="Output field must have 'type'"
                ))
            elif field_type not in valid_types:
                errors.append(ValidationError(
                    path=f"{path_prefix}.{field_name}",
                    message=f"Invalid type '{field_type}'. Valid types: {', '.join(valid_types)}"
                ))
        else:
            errors.append(ValidationError(
                path=f"{path_prefix}.{field_name}",
                message="Output field specification must be a string or dictionary"
            ))
    
    return errors


def _validate_agent(agent: Any, path_prefix: str) -> list[ValidationError]:
    """Validate agent specification."""
    errors = []
    
    if isinstance(agent, str):
        # Short form: agent name - validated later when checking files
        pass
    elif isinstance(agent, dict):
        prompt = agent.get("prompt")
        schema = agent.get("output_schema")
        
        if prompt is not None and not isinstance(prompt, str):
            errors.append(ValidationError(
                path=f"{path_prefix}.prompt",
                message="prompt must be a string"
            ))
        
        if schema is not None:
            if not isinstance(schema, dict):
                errors.append(ValidationError(
                    path=f"{path_prefix}.output_schema",
                    message="output_schema must be a dictionary"
                ))
    else:
        errors.append(ValidationError(
            path=path_prefix,
            message="Agent must be a string (name) or dictionary"
        ))
    
    return errors


def _validate_routing(routing: dict[str, Any], stages: dict[str, Any]) -> list[ValidationError]:
    """Validate routing section."""
    errors = []
    stage_names = set(stages.keys())
    system_stages = {"completed", "failed"}
    
    # Validate start_stage
    start_stage = routing.get("start_stage")
    if not start_stage:
        errors.append(ValidationError(
            path="routing.start_stage",
            message="start_stage is required"
        ))
    elif start_stage not in stage_names:
        errors.append(ValidationError(
            path="routing.start_stage",
            message=f"start_stage '{start_stage}' is not defined in stages"
        ))
    
    # Validate by_stage
    by_stage = routing.get("by_stage", {})
    if not isinstance(by_stage, dict):
        errors.append(ValidationError(
            path="routing.by_stage",
            message="by_stage must be a dictionary"
        ))
        return errors
    
    for stage_name, stage_routing in by_stage.items():
        path_prefix = f"routing.by_stage.{stage_name}"
        
        if stage_name not in stage_names and stage_name not in system_stages:
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
            elif target_stage not in stage_names and target_stage not in system_stages:
                errors.append(ValidationError(
                    path=f"{path_prefix}.next_stages[{i}].stage",
                    message=f"Target stage '{target_stage}' is not defined"
                ))
    
    # Validate path to completed
    if start_stage and start_stage in stage_names:
        if not _has_path_to_completed(routing, start_stage, stage_names):
            errors.append(ValidationError(
                path="routing",
                message=f"No path from start_stage '{start_stage}' to 'completed'. Pipeline cannot reach completion."
            ))
    
    return errors


def _has_path_to_completed(routing: dict, start: str, stage_names: set) -> bool:
    """Check if there's a path from start to completed."""
    visited = set()
    queue = [start]
    
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        
        if current == "completed":
            return True
        
        stage_routing = routing.get("by_stage", {}).get(current, {})
        next_stages = stage_routing.get("next_stages", [])
        
        for rule in next_stages:
            target = rule.get("stage") if isinstance(rule, dict) else None
            if target and target not in visited:
                queue.append(target)
    
    return False


def _validate_defaults(defaults: dict[str, Any], inputs: dict[str, Any], stages: dict[str, Any]) -> list[ValidationError]:
    """Validate defaults section."""
    errors = []
    
    # Validate runner
    runner = defaults.get("runner")
    if runner and runner not in AVAILABLE_RUNNERS:
        errors.append(ValidationError(
            path="defaults.runner",
            message=f"Invalid runner '{runner}'. Available: {', '.join(sorted(AVAILABLE_RUNNERS))}"
        ))
    
    # Validate model
    model = defaults.get("model")
    if model and model not in AVAILABLE_MODELS.get(runner or "auto", set()):
        errors.append(ValidationError(
            path="defaults.model",
            message=f"Invalid model '{model}' for runner '{runner or 'auto'}'"
        ))
    
    # Validate effort
    effort = defaults.get("effort")
    if effort and effort not in AVAILABLE_EFFORTS:
        errors.append(ValidationError(
            path="defaults.effort",
            message=f"Invalid effort '{effort}'. Available: {', '.join(sorted(AVAILABLE_EFFORTS))}"
        ))
    
    # Validate custom defaults reference inputs
    for key in defaults:
        if key in RESERVED_INPUT_NAMES:
            continue
        
        if inputs and key not in inputs:
            errors.append(ValidationError(
                path=f"defaults.{key}",
                message=f"Default '{key}' is not defined in inputs"
            ))
    
    return errors


def _validate_cross_references(inputs: dict, stages: dict, routing: dict) -> list[ValidationError]:
    """Validate cross-references between sections."""
    errors = []
    
    # TODO: Add cross-reference validation for input bindings
    
    return errors


def _is_valid_identifier(name: str) -> bool:
    """Check if a name is a valid identifier."""
    if not name:
        return False
    if name[0].isdigit():
        return False
    return all(c.isalnum() or c in "_-" for c in name)


def _check_value_type(value: Any, type_name: str) -> bool:
    """Check if a value matches the specified type."""
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