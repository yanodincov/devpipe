"""Service adapters: bridge between UI state layer and project internals.

Reads profiles, history, project config and prepares typed data
for state actions. No Textural imports here.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

from devpipe.project_config import load_project_config
from devpipe.runtime.state import STAGE_ORDER
from devpipe.tags import collect_params, load_available_tags, load_tag_definitions
from devpipe.ui.state import FieldKind, FieldMeta
from devpipe.profiles.loader import ProfileDefinition, _find_pipeline_path
from devpipe.profiles.stages import InputType
from devpipe.profiles.validator import validate_pipeline_file, format_validation_errors


def _git_branch(project_root: Path | None = None) -> str:
    try:
        r = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _task_id_from_branch(branch: str) -> str:
    m = re.match(r"^([A-Z]+-[0-9]+)", branch)
    return m.group(1) if m else ""


def discover_profiles(project_root: Path | None = None) -> list[str]:
    """Find available profile names from .devpipe/profiles/ (local and global)."""
    from devpipe.profiles.loader import find_project_root
    from pathlib import Path

    # Determine starting directory
    start_dir = project_root or Path.cwd()
    # Find actual project root (directory containing .devpipe/)
    root = find_project_root(start_dir) or start_dir

    profiles: set[str] = set()

    # Local project profiles in .devpipe/profiles/
    local_dir = root / ".devpipe" / "profiles"
    if local_dir.exists():
        for p in local_dir.iterdir():
            if p.is_dir() and _has_pipeline_file(p):
                profiles.add(p.name)

    # Global profiles in ~/.devpipe/profiles/
    global_dir = Path.home() / ".devpipe" / "profiles"
    if global_dir.exists() and global_dir != local_dir:
        for p in global_dir.iterdir():
            if p.is_dir() and _has_pipeline_file(p):
                profiles.add(p.name)

    return sorted(profiles)


def _has_pipeline_file(profile_dir: Path) -> bool:
    """Check if profile directory contains pipeline.yaml or pipeline.yml."""
    return (profile_dir / "pipeline.yaml").exists() or (profile_dir / "pipeline.yml").exists()


def load_profile_defaults(profile_name: str, project_root: Path | None = None) -> dict[str, Any]:
    """Load default values from a profile's pipeline.yml."""
    from devpipe.profiles.loader import load_profile, find_project_root

    # Resolve effective project root for builtin/global fallback
    start = project_root if project_root is not None else Path.cwd()
    effective_root = find_project_root(start) or start

    try:
        profile = load_profile(profile_name, project_root=effective_root)
        defaults = dict(profile.defaults)
        defaults.setdefault("runner", "auto")
        return defaults
    except Exception:
        return {}


def load_profile_stages(profile_name: str, project_root: Path | None = None) -> list[str]:
    """Return all stage names from the profile in definition order."""
    from devpipe.profiles.loader import load_profile, find_project_root

    # Resolve effective project root
    start = project_root if project_root is not None else Path.cwd()
    effective_root = find_project_root(start) or start

    try:
        profile = load_profile(profile_name, project_root=effective_root)
        # Return all stage names as defined in the profile (preserve order)
        return list(profile.stages.keys())
    except Exception:
        return []


# Keys managed in the Standard section; exclude from Custom
_STANDARD_KEYS = {"task", "runner", "profile", "first_role", "last_role", "model", "effort"}
# Legacy keys that are handled specially by stage range logic in legacy mode
_LEGACY_TOP_LEVEL_KEYS = _STANDARD_KEYS | {"task_id", "target_branch", "service", "namespace", "tags"}


def _append_field(fields: list[FieldMeta], seen: set[str], field: FieldMeta) -> None:
    if field.key in seen or field.key in _STANDARD_KEYS:
        return
    fields.append(field)
    seen.add(field.key)


def _infer_kind(default: Any, options: list[str] | None = None, multi: bool = False) -> FieldKind:
    if multi:
        return FieldKind.MULTI_SELECT
    if options:
        return FieldKind.SELECT
    if isinstance(default, list):
        return FieldKind.ARRAY
    if isinstance(default, dict):
        return FieldKind.OBJECT
    if isinstance(default, int):
        return FieldKind.INT
    return FieldKind.STRING


def _normalize_stage_bounds(first_role: str, last_role: str, stages: list[str]) -> tuple[str, str]:
    if not stages:
        return "", ""
    first = first_role if first_role in stages else stages[0]
    last = last_role if last_role in stages else stages[-1]
    if stages.index(first) > stages.index(last):
        last = first
    return first, last


def _legacy_top_level_fields_enabled(active_roles: set[str]) -> bool:
    qa_local_index = STAGE_ORDER.index("qa_local")
    late_roles = set(STAGE_ORDER[qa_local_index:])
    return bool(active_roles & late_roles)


def _legacy_fields_and_defaults(project_root: Path, current_values: dict[str, Any] | None = None) -> tuple[list[FieldMeta], dict[str, Any], list[str]]:
    project_cfg = load_project_config(project_root)
    current = dict(current_values or {})
    defaults = dict(project_cfg.defaults)
    defaults.update({key: value for key, value in current.items() if value not in (None, "")})
    defaults.setdefault("runner", "auto")
    defaults.setdefault("model", "auto")
    defaults.setdefault("effort", "auto")

    all_tags = load_available_tags(project_root)
    selected_tags = [tag for tag in defaults.get("tags", []) if tag in all_tags]
    defaults["tags"] = selected_tags

    fields: list[FieldMeta] = []
    seen: set[str] = set()

    first_role, last_role = _normalize_stage_bounds(
        str(defaults.get("first_role", "")),
        str(defaults.get("last_role", "")),
        list(STAGE_ORDER),
    )
    defaults["first_role"] = first_role
    defaults["last_role"] = last_role
    first_index = STAGE_ORDER.index(first_role) if first_role in STAGE_ORDER else 0
    last_index = STAGE_ORDER.index(last_role) if last_role in STAGE_ORDER else len(STAGE_ORDER) - 1
    active_roles = set(STAGE_ORDER[first_index:last_index + 1])

    _append_field(fields, seen, FieldMeta(key="task_id", label="Task Id", kind=FieldKind.STRING, section="custom"))
    if _legacy_top_level_fields_enabled(active_roles):
        _append_field(
            fields,
            seen,
            FieldMeta(
                key="target_branch",
                label="Target Branch",
                kind=FieldKind.SELECT if project_cfg.available_list("target_branch") else FieldKind.STRING,
                options=project_cfg.available_list("target_branch"),
                default=defaults.get("target_branch", ""),
                section="custom",
            ),
        )
        _append_field(
            fields,
            seen,
            FieldMeta(key="service", label="Service", kind=FieldKind.STRING, default=defaults.get("service", ""), section="custom"),
        )
        _append_field(
            fields,
            seen,
            FieldMeta(
                key="namespace",
                label="Namespace",
                kind=FieldKind.SELECT if project_cfg.available_list("namespace") else FieldKind.STRING,
                options=project_cfg.available_list("namespace"),
                default=defaults.get("namespace", ""),
                section="custom",
            ),
        )
        _append_field(
            fields,
            seen,
            FieldMeta(
                key="tags",
                label="Tags",
                kind=FieldKind.MULTI_SELECT,
                options=sorted(all_tags),
                default=selected_tags,
                section="custom",
            ),
        )

    tag_defs = load_tag_definitions(selected_tags, project_root)
    for _tag_name, param, available, default in collect_params(tag_defs, project_cfg.tag_params, active_roles):
        project_default = defaults.get(param.key)
        if project_default is None and not param.multi and default:
            defaults[param.key] = default
            project_default = default
        _append_field(
            fields,
            seen,
            FieldMeta(
                key=param.key,
                label=_key_to_label(param.key),
                kind=_infer_kind(project_default, available, multi=param.multi),
                required=param.required,
                options=[str(v) for v in available],
                default=project_default if project_default is not None else ([] if param.multi else ""),
                description=param.description,
                section="custom",
            ),
        )

    dynamic_keys = (set(project_cfg.defaults) | set(project_cfg.available)) - seen - _LEGACY_TOP_LEVEL_KEYS
    for key in sorted(dynamic_keys):
        available = [str(v) for v in project_cfg.available_list(key)]
        default = defaults.get(key, [] if available else "")
        _append_field(
            fields,
            seen,
            FieldMeta(
                key=key,
                label=_key_to_label(key),
                kind=_infer_kind(default, available, multi=isinstance(default, list)),
                options=available,
                default=default,
                section="custom",
            ),
        )

    return fields, defaults, list(STAGE_ORDER)


def resolve_legacy_form_state(project_root: Path | None = None, current_values: dict[str, Any] | None = None) -> dict[str, Any]:
    root = project_root or Path.cwd()
    fields, defaults, stages = _legacy_fields_and_defaults(root, current_values)
    return {
        "profile": "",
        "available_profiles": [],
        "available_stages": stages,
        "fields": fields,
        "defaults": defaults,
    }


def load_profile_fields(profile: str | ProfileDefinition, project_root: Path | None = None) -> list[FieldMeta]:
    """Build FieldMeta list from profile inputs definition.

    Inputs from pipeline.yml become Custom fields.
    Standard fields (profile, task, runner, first_role, last_role) are excluded.

    Args:
        profile: Profile name or ProfileDefinition object
        project_root: Project root directory
    """
    from devpipe.profiles.loader import ProfileDefinition, load_profile, find_project_root

    if isinstance(profile, ProfileDefinition):
        profile_obj = profile
    else:
        start = project_root if project_root is not None else Path.cwd()
        effective_root = find_project_root(start) or start
        profile_obj = load_profile(profile, project_root=effective_root)

    return _convert_inputs_to_fields(profile_obj.inputs, project_root=project_root, profile=profile_obj)


def _type_to_kind(type_str: str, options: list) -> FieldKind:
    """Map pipeline.yml input type to FieldKind."""
    if options:
        return FieldKind.MULTI_SELECT if len(options) > 1 else FieldKind.SELECT
    mapping = {
        "string": FieldKind.STRING,
        "int": FieldKind.INT,
        "integer": FieldKind.INT,
        "array": FieldKind.ARRAY,
        "object": FieldKind.OBJECT,
        "select": FieldKind.SELECT,
        "multi": FieldKind.MULTI_SELECT,
    }
    return mapping.get(type_str, FieldKind.STRING)


def _key_to_label(key: str) -> str:
    """Convert snake_case key to human-readable label."""
    return key.replace("_", " ").title()


def load_default_profile(project_root: Path | None = None) -> str:
    """Read the default profile from .devpipe/config.yaml (local or global)."""
    from devpipe.profiles.loader import find_project_root

    start = project_root if project_root is not None else Path.cwd()
    effective_root = find_project_root(start) or start
    # Try local config first
    config_path = effective_root / ".devpipe" / "config.yaml"
    if config_path.exists():
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        profile = data.get("defaults", {}).get("profile", "")
        if profile:
            return profile
    # Fallback to global config
    global_config = Path.home() / ".devpipe" / "config.yaml"
    if global_config.exists():
        data = yaml.safe_load(global_config.read_text(encoding="utf-8")) or {}
        return data.get("defaults", {}).get("profile", "")
    return ""


def prepare_initial_state(project_root: Path | None = None) -> dict[str, Any]:
    """Prepare all data needed for the initial load_defaults action.

    Returns a dict with keys: profile, available_profiles, available_stages,
    fields, defaults, profile_errors.
    """
    from devpipe.profiles.loader import find_project_root, load_profile, _find_pipeline_path

    start = project_root if project_root is not None else Path.cwd()
    root = find_project_root(start) or start

    profiles = discover_profiles(root)
    default_profile = load_default_profile(root)

    # If default profile is not in available list, adjust:
    # - if there are available profiles, pick the first one
    # - if no profiles available, clear default_profile (ignore config)
    if default_profile not in profiles:
        if profiles:
            default_profile = profiles[0]
        else:
            default_profile = ""

    profile_errors: list[str] = []
    profile_warnings: list[str] = []
    profile_obj = None
    base_fields = []
    stages = []
    defaults = {}

    if default_profile:
        # Validate pipeline.yml first
        pipeline_path = _find_pipeline_path(default_profile, root)
        if pipeline_path:
            validation_result = validate_pipeline_file(pipeline_path)
            if not validation_result.valid:
                profile_errors.extend(format_validation_errors(validation_result.errors))
            profile_warnings.extend(validation_result.warnings)
        
        try:
            profile_obj = load_profile(default_profile, project_root=root)
            base_fields = load_profile_fields(profile_obj, root)
            stages = load_profile_stages(default_profile, root)
            defaults = load_profile_defaults(default_profile, root)
        except Exception as e:
            error_msg = str(e)
            # Extract meaningful error message
            if "Unsupported profile version" in error_msg:
                profile_errors.append(f"Unsupported profile version in '{default_profile}'")
            elif "routing section must specify start_stage" in error_msg:
                profile_errors.append(f"Profile '{default_profile}' missing start_stage in routing")
            elif "Invalid" in error_msg:
                profile_errors.append(f"Invalid configuration in '{default_profile}': {error_msg}")
            else:
                profile_errors.append(f"Failed to load profile '{default_profile}': {error_msg}")
            profile_obj = None
            base_fields = []
            stages = []
            defaults = {}

        # If profile loaded successfully, merge defaults and add dynamic tag fields
        if profile_obj:
            # Normalize bool defaults from profile.defaults section
            for key, spec in profile_obj.inputs.items():
                if key in defaults and spec.type.value == "bool":
                    if isinstance(defaults[key], bool):
                        defaults[key] = "true" if defaults[key] else "false"
            
            # Merge defaults from profile.inputs (where not already set)
            for key, spec in profile_obj.inputs.items():
                if key not in defaults:
                    # Convert default based on type
                    if key == "tags" and spec.multi:
                        # Normalize tags list to dict with all roles
                        available_tags = load_available_tags(root)
                        defaults[key] = _normalize_tag_roles_defaults(spec.default, available_tags)
                    elif spec.type.value == "bool":
                        # Normalize bool to lowercase string
                        defaults[key] = "true" if spec.default else "false"
                    else:
                        defaults[key] = spec.default
            # Ensure tags is dict if present (normalize from profile.defaults as well)
            if 'tags' in defaults:
                available_tags = load_available_tags(root)
                defaults['tags'] = _normalize_tag_roles_defaults(defaults['tags'], available_tags)
            else:
                # Ensure tags exists as empty dict for consistency
                defaults['tags'] = {}

            # Add dynamic tag parameter fields based on selected tags
            selected_tags = defaults.get('tags', {})
            if selected_tags and profile_obj:
                dynamic_fields = get_dynamic_tag_fields(selected_tags, defaults, root)
                # Avoid duplicates with base_fields
                existing_keys = {f.key for f in base_fields}
                fields = list(base_fields)
                for df in dynamic_fields:
                    if df.key not in existing_keys:
                        fields.append(df)
                        # Ensure default is in defaults dict
                        if df.key not in defaults:
                            defaults[df.key] = df.default
                    else:
                        # Update default if needed?
                        pass
            else:
                fields = base_fields
        else:
            fields = base_fields
    else:
        fields = []
        stages = []
        defaults = {}

    # Ensure standard defaults for runner/model/effort
    defaults.setdefault("runner", "auto")
    defaults.setdefault("model", "auto")
    defaults.setdefault("effort", "auto")

    # Auto-populate task_id from git branch
    branch = _git_branch(root)
    if branch:
        task_id = _task_id_from_branch(branch)
        if task_id:
            defaults.setdefault("task_id", task_id)

    # Load available tags for UI consumption
    available_tags_dict = load_available_tags(root)
    available_tags_list = sorted(available_tags_dict.keys())

    # Compute routing graph if profile loaded
    routing_graph: dict[str, set[str]] = {}
    if profile_obj and profile_obj.routing:
        routing_graph = _build_routing_graph(profile_obj.routing)
        # Validate: there must be a path from start_stage to completed
        start_stage = profile_obj.routing.start_stage
        reachable = _get_reachable_stages(routing_graph, start_stage)
        if "completed" not in reachable:
            profile_errors.append(
                f"No path from start_stage '{start_stage}' to 'completed' in routing. "
                "Pipeline cannot reach completion."
            )

    return {
        "profile": default_profile,
        "available_profiles": profiles,
        "available_stages": stages,
        "fields": fields,
        "defaults": defaults,
        "available_tags": available_tags_list,
        "routing_graph": routing_graph,
        "profile_errors": profile_errors,
    }


# Helper functions for new-format (routing) profiles

def _build_routing_graph(routing) -> dict[str, set[str]]:
    """Build adjacency list from routing spec.

    Returns dict mapping stage -> set of possible next stages (including 'completed' and 'failed').
    """
    graph: dict[str, set[str]] = {}
    for stage_name, stage_routing in routing.by_stage.items():
        next_stages = set()
        for rule in stage_routing.next_stages:
            next_stages.add(rule.stage)
        graph[stage_name] = next_stages
    return graph


def _get_reachable_stages(graph: dict[str, set[str]], start: str) -> set[str]:
    """Get all stages reachable from start using DFS."""
    reachable: set[str] = set()
    stack = [start]
    while stack:
        current = stack.pop()
        if current in reachable or current in {"completed", "failed"}:
            continue
        reachable.add(current)
        if current in graph:
            for next_stage in graph[current]:
                if next_stage not in reachable and next_stage not in {"completed", "failed"}:
                    stack.append(next_stage)
    return reachable


def _stages_that_can_reach_completed(graph: dict[str, set[str]], completed_stages: set[str]) -> set[str]:
    """Find all stages that can eventually lead to 'completed'.

    Uses reverse graph traversal from 'completed' stage.
    """
    can_reach: set[str] = set()
    stack = list(completed_stages)
    reverse_graph: dict[str, set[str]] = {}
    for stage, next_stages in graph.items():
        for next_s in next_stages:
            if next_s not in reverse_graph:
                reverse_graph[next_s] = set()
            reverse_graph[next_s].add(stage)
    while stack:
        current = stack.pop()
        if current in can_reach:
            continue
        can_reach.add(current)
        if current in reverse_graph:
            for prev in reverse_graph[current]:
                if prev not in can_reach and prev not in {"completed", "failed"}:
                    stack.append(prev)
    return can_reach


def _get_start_options_for_profile(profile) -> list[str]:
    """Get valid start agent options for a profile.

    Returns list of stages that can be used as start (first_role).
    All profile stages are valid starts since any stage could be an entry point.
    """
    return sorted(profile.stages.keys())


def _get_finish_options_for_start(
    graph: dict[str, set[str]],
    start: str,
    profile_stage_names: list[str],
) -> list[str]:
    """Get valid finish agent options given a start stage.

    Rules:
    - Only profile stages (real agents) can be selected as finish
    - Stage must be reachable from start
    - Stage must be able to lead to 'completed' (not stuck in a cycle)

    Returns list of valid finish stages (no completed/failed - they are system agents).
    """
    reachable_from_start = _get_reachable_stages(graph, start)
    can_reach_completed = _stages_that_can_reach_completed(graph, {"completed"})
    valid_finishes: list[str] = []

    for stage in profile_stage_names:
        if stage in reachable_from_start and stage in can_reach_completed:
            valid_finishes.append(stage)

    valid_finishes.sort(key=lambda s: profile_stage_names.index(s))
    return valid_finishes


def _get_stage_order_from_routing(routing, stages) -> list[str]:
    """Extract a linear ordered list of stages from routing spec by following default transitions."""
    start = routing.start_stage
    by_stage = routing.by_stage
    ordered: list[str] = []
    visited: set[str] = set()
    current = start
    while current and current not in {"completed", "failed"} and current not in visited:
        visited.add(current)
        ordered.append(current)
        stage_routing = by_stage.get(current)
        if not stage_routing:
            break
        # Find default rule
        default_rule = None
        for rule in stage_routing.next_stages:
            if rule.default:
                default_rule = rule
                break
        if default_rule is None:
            # No default rule; pick first rule if any
            if stage_routing.next_stages:
                default_rule = stage_routing.next_stages[0]
            else:
                break
        current = default_rule.stage
    return ordered


def _normalize_tag_roles_defaults(tags_value: Any, available_tags: dict[str, Any]) -> dict[str, list[str]]:
    """Normalize tags default value to dict format: {tag: [roles]}."""
    if isinstance(tags_value, dict):
        return {k: list(v) for k, v in tags_value.items() if k in available_tags}
    elif isinstance(tags_value, list):
        result = {}
        for tag in tags_value:
            if tag in available_tags:
                roles = sorted(available_tags[tag].params_by_role.keys())
                result[tag] = roles
        return result
    return {}


def get_dynamic_tag_fields(
    selected_tags: dict[str, list[str]],
    existing_values: dict[str, Any],
    project_root: Path,
) -> list[FieldMeta]:
    """Build custom fields for tag parameters based on selected tags.

    Args:
        selected_tags: Dict of tag -> list of roles (stages) where tag is active
        existing_values: Current form values (to preserve defaults/overrides)
        project_root: Project root directory

    Returns:
        List of FieldMeta for tag parameters that should be included.
    """
    from devpipe.project_config import load_project_config

    if not selected_tags:
        return []

    # Load tag definitions for selected tags
    tag_defs = load_tag_definitions(list(selected_tags.keys()), project_root)
    if not tag_defs:
        return []

    project_cfg = load_project_config(project_root)
    # Convert tag_roles dict to sets for collect_params
    tag_roles_sets = {tag: set(roles) for tag, roles in selected_tags.items()}
    dynamic_fields: list[FieldMeta] = []

    for _tag_name, param, available, default in collect_params(tag_defs, project_cfg.tag_params, tag_roles_sets):
        # Skip if this field key is already in existing_values? We include all.
        # Determine current value: use existing if present, else default
        current_value = existing_values.get(param.key)
        if current_value is None and not param.multi and default:
            current_value = default
        # Infer kind based on current_value and available, multi
        kind = _infer_kind(current_value, available, multi=param.multi)
        # Build field meta
        field_meta = FieldMeta(
            key=param.key,
            label=_key_to_label(param.key),
            kind=kind,
            required=param.required,
            options=[str(v) for v in available],
            default=current_value if current_value is not None else ([] if param.multi else ""),
            description=param.description,
            section="custom",
        )
        dynamic_fields.append(field_meta)

    return dynamic_fields


def _convert_inputs_to_fields(inputs: dict[str, Any], project_root: Path | None = None, profile: Any = None) -> list[FieldMeta]:
    """Convert InputSpec objects (from loader) to FieldMeta list for UI.

    Args:
        inputs: Dict of InputSpec objects
        project_root: Project root for loading available tags if needed
        profile: Optional ProfileDefinition for accessing defaults and extra metadata
    """
    from devpipe.tags import load_available_tags
    from devpipe.profiles.loader import ProfileDefinition

    fields: list[FieldMeta] = []
    available_tags = None

    for key, spec in inputs.items():
        if key in _STANDARD_KEYS:
            continue

        type_str = spec.type.value
        default = spec.default
        values = spec.values
        multi = spec.multi
        custom = getattr(spec, 'custom', False)

        # Special handling for tags: create TAG_ROLES field
        if key == "tags" and multi:
            if available_tags is None:
                available_tags = load_available_tags(project_root)
            profile_stages = list(profile.stages.keys()) if profile is not None else []
            tag_roles_extra: dict[str, list[str]] = {}
            for tag_name in available_tags:
                tag_def = available_tags.get(tag_name)
                if tag_def and tag_def.params_by_role:
                    tag_roles_extra[tag_name] = sorted(tag_def.params_by_role.keys())
                else:
                    tag_roles_extra[tag_name] = profile_stages
            default_tag_roles = _normalize_tag_roles_defaults(default, available_tags)
            fields.append(FieldMeta(
                key=key,
                label=_key_to_label(key),
                kind=FieldKind.TAG_ROLES,
                required=False,
                options=sorted(available_tags.keys()),
                default=default_tag_roles,
                extra=tag_roles_extra,
                section="standard",
            ))
            continue

        # Determine field kind based on type and options
        options: list[str] = []
        
        if type_str == "bool":
            # Boolean is always a SELECT with true/false, no custom values allowed
            kind = FieldKind.SELECT
            options = ["true", "false"]
            custom = False
            multi = False
            # Convert bool default to lowercase string
            default = "true" if default else "false"
        elif multi:
            # Multi-select for arrays
            kind = FieldKind.MULTI_SELECT
            if values:
                options = [str(v) for v in values]
            # If no values but multi=True, custom is auto-set by InputSpec validator
        elif values:
            # Has predefined values - SELECT
            kind = FieldKind.SELECT
            options = [str(v) for v in values]
        else:
            # Free-form input based on type
            type_kind_map = {
                "string": FieldKind.STRING,
                "int": FieldKind.INT,
                "object": FieldKind.OBJECT,
            }
            kind = type_kind_map.get(type_str, FieldKind.STRING)

        fields.append(FieldMeta(
            key=key,
            label=_key_to_label(key),
            kind=kind,
            required=False,
            options=options,
            default=default,
            description="",
            section="custom",
            custom=custom if type_str != "bool" else False,
        ))
    return fields
