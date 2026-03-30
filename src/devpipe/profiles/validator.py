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
    "codex": {"auto", "low", "middle", "medium", "high"},
    "claude": {"auto", "low", "middle", "medium", "high"},
    "auto": {"auto", "low", "middle", "medium", "high"},
}

# Available effort levels
AVAILABLE_EFFORTS = {"auto", "low", "middle", "medium", "high"}


def validate_pipeline_file(path: Path, profile_dir: Path | None = None) -> ValidationResult:
    """Validate a pipeline.yml file and collect all errors.
    
    Args:
        path: Path to pipeline.yml file
        profile_dir: Optional path to profile directory (for validating agent files)
    """
    errors: list[ValidationError] = []
    warnings: list[str] = []
    
    if not path.exists():
        return ValidationResult(
            valid=False,
            errors=[ValidationError(path="", message=f"File not found: {path}")]
        )
    
    # Infer profile_dir if not provided
    if profile_dir is None:
        profile_dir = path.parent
    
    content_raw = path.read_text(encoding="utf-8")
    
    # Check for common YAML syntax issues
    try:
        content = yaml.safe_load(content_raw)
    except yaml.YAMLError as e:
        # Extract line number if possible
        line_num = ""
        if hasattr(e, 'problem_mark') and e.problem_mark:
            line_num = f" at line {e.problem_mark.line + 1}"
        return ValidationResult(
            valid=False,
            errors=[ValidationError(path="", message=f"YAML syntax error{line_num}: {str(e).split('in')[0].strip() if 'in' in str(e) else str(e)}")]
        )
    
    # Check for tabs in YAML (often cause issues)
    lines_with_tabs = []
    for i, line in enumerate(content_raw.split('\n'), 1):
        if '\t' in line and not line.strip().startswith('#'):
            lines_with_tabs.append(i)
    if lines_with_tabs:
        warnings.append(f"YAML contains tab characters on lines {lines_with_tabs[:3]}{'...' if len(lines_with_tabs) > 3 else ''}. Use spaces instead.")
    
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
        stage_errors, stage_warnings = _validate_stages(stages, profile_dir)
        errors.extend(stage_errors)
        warnings.extend(stage_warnings)
    
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


def validate_profile(profile_dir: Path) -> ValidationResult:
    """Validate a complete profile directory including pipeline.yml.
    
    Agent files are validated when referenced in pipeline.yml stages.
    """
    pipeline_path = profile_dir / "pipeline.yml"
    if not pipeline_path.exists():
        pipeline_path = profile_dir / "pipeline.yaml"
    
    result = validate_pipeline_file(pipeline_path, profile_dir)
    
    return result


def validate_all_profiles(project_root: Path) -> dict[str, ValidationResult]:
    """Validate all profiles in a project.
    
    Returns dict mapping profile name to validation result.
    """
    profiles_dir = project_root / ".devpipe" / "profiles"
    if not profiles_dir.exists():
        return {}
    
    results = {}
    for profile_dir in profiles_dir.iterdir():
        if profile_dir.is_dir():
            pipeline_yml = profile_dir / "pipeline.yml"
            pipeline_yaml = profile_dir / "pipeline.yaml"
            if pipeline_yml.exists() or pipeline_yaml.exists():
                profile_name = profile_dir.name
                results[profile_name] = validate_profile(profile_dir)
    
    return results


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


def _validate_stages(stages: dict[str, Any], profile_dir: Path) -> tuple[list[ValidationError], list[str]]:
    """Validate stages section.
    
    Returns tuple of (errors, warnings).
    """
    errors = []
    warnings = []
    
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
        elif runner not in AVAILABLE_RUNNERS:
            errors.append(ValidationError(
                path=f"{path_prefix}.runner",
                message=f"Invalid runner '{runner}'. Available runners: {', '.join(sorted(AVAILABLE_RUNNERS))}"
            ))
        
        # Validate model if present
        model = spec.get("model")
        if model is not None:
            if not isinstance(model, str):
                errors.append(ValidationError(
                    path=f"{path_prefix}.model",
                    message="model must be a string"
                ))
            elif model not in AVAILABLE_MODELS.get("auto", set()):
                # Model availability depends on runner, but we validate against common set
                all_models = set().union(*AVAILABLE_MODELS.values())
                if model not in all_models:
                    errors.append(ValidationError(
                        path=f"{path_prefix}.model",
                        message=f"Invalid model '{model}'. Available models: {', '.join(sorted(all_models))}"
                    ))
        
        # Validate effort if present
        effort = spec.get("effort")
        if effort is not None:
            if not isinstance(effort, str):
                errors.append(ValidationError(
                    path=f"{path_prefix}.effort",
                    message="effort must be a string"
                ))
            elif effort not in AVAILABLE_EFFORTS:
                errors.append(ValidationError(
                    path=f"{path_prefix}.effort",
                    message=f"Invalid effort '{effort}'. Available efforts: {', '.join(sorted(AVAILABLE_EFFORTS))}"
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
            out_errors, out_warnings = _validate_output_fields(out_fields, f"{path_prefix}.out")
            errors.extend(out_errors)
            warnings.extend(out_warnings)
        
        # Validate agent
        agent = spec.get("agent")
        if agent is not None:
            errors.extend(_validate_agent(agent, f"{path_prefix}.agent", profile_dir))
    
    return errors, warnings


def _validate_input_bindings(bindings: dict[str, str], path_prefix: str) -> list[ValidationError]:
    """Validate input binding sources.
    
    Valid binding formats:
    - input.field_name
    - context.field_name  
    - runtime.field_name
    - integration.service_name
    - stage.stage_name.field_name
    - stage.stage_name.out.field_name
    - stage_name.result.jsonpath (references output from another stage)
    """
    errors = []
    
    for binding_name, source in bindings.items():
        if not isinstance(source, str):
            errors.append(ValidationError(
                path=f"{path_prefix}.{binding_name}",
                message=f"Binding source must be a string, got {type(source).__name__}"
            ))
            continue
        
        # Check for complex expressions (with 'if'/'else') - skip validation
        if ' if ' in source or ' else ' in source:
            continue
        
        # Parse binding source
        dot_count = source.count('.')
        if dot_count < 1:
            errors.append(ValidationError(
                path=f"{path_prefix}.{binding_name}",
                message=f"Invalid binding source '{source}'. Must contain at least one dot separator"
            ))
            continue
        
        parts = source.split('.', 1)
        prefix = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        
        # Valid prefixes (lowercase)
        valid_prefixes = {"input", "context", "runtime", "integration", "stage"}
        
        # Validate known prefixes
        if prefix in valid_prefixes:
            if prefix == "stage":
                # stage.stage_name.field_name or stage.stage_name.out.field_name
                if dot_count < 2:
                    errors.append(ValidationError(
                        path=f"{path_prefix}.{binding_name}",
                        message=f"Invalid stage binding '{source}'. Expected 'stage.stage_name.field_name' or 'stage.stage_name.out.field_name'"
                    ))
        else:
            # Unknown prefix - could be a stage reference like developer.result.data
            # But we still want to catch obvious typos
            # Accept if it looks like a reference (has at least 2 dots after prefix)
            if dot_count < 2:
                # Could be typo like "invalid.binding" (only 1 dot, unknown prefix)
                errors.append(ValidationError(
                    path=f"{path_prefix}.{binding_name}",
                    message=f"Unknown binding prefix '{prefix}'. Must start with input., context., runtime., integration., stage., or be a stage reference"
                ))
    
    return errors


def _validate_output_fields(fields: dict[str, Any], path_prefix: str) -> tuple[list[ValidationError], list[str]]:
    """Validate output field specifications.
    
    Output fields should use JSON Schema format with type and optionally properties.
    Simple type strings like 'string', 'object' are also accepted for backwards compatibility.
    
    Returns tuple of (errors, warnings).
    """
    errors = []
    warnings = []
    valid_types = {"string", "int", "bool", "object"}
    
    for field_name, field_spec in fields.items():
        if isinstance(field_spec, str):
            # Shorthand: just type (deprecated but accepted)
            warnings.append(f"{path_prefix}.{field_name}: Consider using JSON Schema format instead of shorthand type")
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
            
            # For object type, recommend properties
            if field_type == "object":
                if "properties" not in field_spec:
                    warnings.append(f"{path_prefix}.{field_name}: object type should define 'properties'")
        else:
            errors.append(ValidationError(
                path=f"{path_prefix}.{field_name}",
                message="Output field specification must be a string or dictionary"
            ))
    
    return errors, warnings


def _validate_agent(agent: Any, path_prefix: str, profile_dir: Path) -> list[ValidationError]:
    """Validate agent specification.
    
    Agent must be a dict with either:
    - folder: name of folder in agents/ directory (must contain prompt.md and output.schema.json)
    - prompt + schema: paths to prompt and schema files (relative to profile directory)
    """
    errors = []
    
    if not isinstance(agent, dict):
        errors.append(ValidationError(
            path=path_prefix,
            message="Agent must be an object with 'folder' or both 'prompt' and 'schema'"
        ))
        return errors
    
    folder = agent.get("folder")
    prompt = agent.get("prompt")
    schema = agent.get("schema")
    
    # Check for unknown fields
    known_fields = {"folder", "prompt", "schema"}
    unknown = set(agent.keys()) - known_fields
    if unknown:
        errors.append(ValidationError(
            path=path_prefix,
            message=f"Unknown agent fields: {', '.join(sorted(unknown))}"
        ))
    
    if folder is not None:
        # folder mode
        if not isinstance(folder, str):
            errors.append(ValidationError(
                path=f"{path_prefix}.folder",
                message="folder must be a string"
            ))
            return errors
        
        if prompt is not None or schema is not None:
            errors.append(ValidationError(
                path=path_prefix,
                message="When 'folder' is specified, 'prompt' and 'schema' must not be set"
            ))
            return errors
        
        # Validate folder exists and has required files
        agent_dir = profile_dir / "agents" / folder
        if not agent_dir.exists():
            errors.append(ValidationError(
                path=f"{path_prefix}.folder",
                message=f"Agent folder 'agents/{folder}' not found"
            ))
        else:
            prompt_file = agent_dir / "prompt.md"
            schema_file = agent_dir / "output.schema.json"
            
            if not prompt_file.exists():
                errors.append(ValidationError(
                    path=f"{path_prefix}.folder",
                    message=f"Agent folder 'agents/{folder}' missing prompt.md"
                ))
            if not schema_file.exists():
                errors.append(ValidationError(
                    path=f"{path_prefix}.folder",
                    message=f"Agent folder 'agents/{folder}' missing output.schema.json"
                ))
            elif schema_file.exists():
                # Validate schema file is valid JSON
                errors.extend(_validate_output_schema(schema_file, f"{path_prefix}.folder"))
    
    elif prompt is not None or schema is not None:
        # prompt + schema mode
        if prompt is None:
            errors.append(ValidationError(
                path=f"{path_prefix}.prompt",
                message="'prompt' is required when 'schema' is specified"
            ))
        if schema is None:
            errors.append(ValidationError(
                path=f"{path_prefix}.schema",
                message="'schema' is required when 'prompt' is specified"
            ))
        
        if prompt is not None:
            if not isinstance(prompt, str):
                errors.append(ValidationError(
                    path=f"{path_prefix}.prompt",
                    message="prompt must be a string (file path)"
                ))
            else:
                prompt_file = profile_dir / prompt
                if not prompt_file.exists():
                    errors.append(ValidationError(
                        path=f"{path_prefix}.prompt",
                        message=f"Prompt file not found: {prompt}"
                    ))
        
        if schema is not None:
            if not isinstance(schema, str):
                errors.append(ValidationError(
                    path=f"{path_prefix}.schema",
                    message="schema must be a string (file path)"
                ))
            else:
                schema_file = profile_dir / schema
                if not schema_file.exists():
                    errors.append(ValidationError(
                        path=f"{path_prefix}.schema",
                        message=f"Schema file not found: {schema}"
                    ))
                else:
                    errors.extend(_validate_output_schema(schema_file, f"{path_prefix}.schema"))
    
    else:
        errors.append(ValidationError(
            path=path_prefix,
            message="Agent must specify either 'folder' or both 'prompt' and 'schema'"
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
    stage_names = set(stages.keys())
    
    # Build output field registry
    stage_outputs: dict[str, set[str]] = {}
    for stage_name, stage_spec in stages.items():
        if isinstance(stage_spec, dict):
            out = stage_spec.get("out", {})
            if isinstance(out, dict):
                stage_outputs[stage_name] = set(out.keys())
            else:
                stage_outputs[stage_name] = set()
    
    # Validate input bindings in each stage
    for stage_name, stage_spec in stages.items():
        if not isinstance(stage_spec, dict):
            continue
        
        in_bindings = stage_spec.get("in", {})
        if not isinstance(in_bindings, dict):
            continue
        
        for binding_name, source in in_bindings.items():
            if not isinstance(source, str):
                continue
            
            # Skip complex expressions (contain 'if', 'else', operators)
            if ' if ' in source or ' else ' in source or any(op in source for op in ['+', '-', '*', '/', '==', '!=', '<', '>', 'and', 'or']):
                # Complex expression - skip validation
                continue
            
            errors.extend(_validate_binding_source(
                source, 
                inputs, 
                stage_outputs, 
                stage_names,
                f"stages.{stage_name}.in.{binding_name}"
            ))
    
    return errors


def _validate_binding_source(
    source: str, 
    inputs: dict, 
    stage_outputs: dict[str, set[str]],
    stage_names: set[str],
    path: str
) -> list[ValidationError]:
    """Validate a single binding source reference."""
    errors = []
    
    parts = source.split(".", 1)
    if len(parts) < 2:
        errors.append(ValidationError(
            path=path,
            message=f"Invalid binding source '{source}'. Must be in format 'prefix.field'"
        ))
        return errors
    
    prefix = parts[0]
    field = parts[1] if len(parts) > 1 else ""
    
    if prefix == "input":
        # input.field_name
        if field not in inputs:
            errors.append(ValidationError(
                path=path,
                message=f"Input '{field}' referenced in binding not found in inputs section"
            ))
    
    elif prefix == "stage":
        # stage.stage_name.field_name or stage.stage_name.out.field_name
        stage_parts = field.split(".", 1)
        if len(stage_parts) < 2:
            errors.append(ValidationError(
                path=path,
                message=f"Invalid stage binding '{source}'. Must be 'stage.stage_name.field_name'"
            ))
        else:
            ref_stage = stage_parts[0]
            ref_field = stage_parts[1]
            
            # Handle 'out.' prefix
            if ref_field.startswith("out."):
                ref_field = ref_field[4:]  # Remove 'out.' prefix
            
            if ref_stage not in stage_names:
                errors.append(ValidationError(
                    path=path,
                    message=f"Stage '{ref_stage}' referenced in binding not found in stages section"
                ))
            elif ref_stage in stage_outputs and ref_field not in stage_outputs[ref_stage]:
                errors.append(ValidationError(
                    path=path,
                    message=f"Output field '{ref_field}' not found in stage '{ref_stage}'"
                ))
    
    elif prefix == "context":
        # context.field_name - runtime context, always valid
        pass
    
    elif prefix == "runtime":
        # runtime.field_name - runtime values, always valid
        pass
    
    elif prefix == "integration":
        # integration.field_name - integration values, always valid
        pass
    
    else:
        errors.append(ValidationError(
            path=path,
            message=f"Unknown binding prefix '{prefix}'. Must be input, context, stage, runtime, or integration"
        ))
    
    return errors


def _validate_output_schema(schema_path: Path, path_prefix: str) -> list[ValidationError]:
    """Validate output.schema.json structure."""
    errors = []
    
    try:
        import json
        content = json.loads(schema_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [ValidationError(
            path=f"{path_prefix}.output.schema.json",
            message=f"Invalid JSON: {e}"
        )]
    except FileNotFoundError:
        return []
    
    if not isinstance(content, dict):
        errors.append(ValidationError(
            path=f"{path_prefix}.output.schema.json",
            message="Schema must be a JSON object"
        ))
        return errors
    
    schema_type = content.get("type")
    if schema_type and schema_type != "object":
        errors.append(ValidationError(
            path=f"{path_prefix}.output.schema.json",
            message=f"Root type should be 'object', got '{schema_type}'"
        ))
    
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