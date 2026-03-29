"""Service adapters: bridge between UI state layer and project internals.

Reads profiles, history, project config and prepares typed data
for state actions. No Textual imports here.
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
    """Extract ordered stage list from profile's routing spec."""
    from devpipe.profiles.loader import load_profile, find_project_root

    # Resolve effective project root
    start = project_root if project_root is not None else Path.cwd()
    effective_root = find_project_root(start) or start

    try:
        profile = load_profile(profile_name, project_root=effective_root)
        return _get_stage_order_from_routing(profile.routing, profile.stages)
    except Exception:
        return []


# Keys managed in the Standard section; exclude from Custom
_STANDARD_KEYS = {"task", "runner", "profile", "first_role", "last_role"}
_LEGACY_TOP_LEVEL_KEYS = _STANDARD_KEYS | {"task_id", "target_branch", "service", "namespace", "tags", "model", "effort"}


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


def load_profile_fields(profile_name: str, project_root: Path | None = None) -> list[FieldMeta]:
    """Build FieldMeta list from profile inputs definition.

    Inputs from pipeline.yml become Custom fields.
    Standard fields (profile, task, runner, first_role, last_role) are excluded.
    """
    from devpipe.profiles.loader import load_profile, find_project_root

    # Resolve effective project root
    start = project_root if project_root is not None else Path.cwd()
    effective_root = find_project_root(start) or start

    try:
        profile = load_profile(profile_name, project_root=effective_root)
        return _convert_inputs_to_fields(profile.inputs)
    except Exception:
        return []


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
    """Read the default profile from .devpipe/config.yaml."""
    from devpipe.profiles.loader import find_project_root

    start = project_root if project_root is not None else Path.cwd()
    effective_root = find_project_root(start) or start
    config_path = effective_root / ".devpipe" / "config.yaml"
    if not config_path.exists():
        return ""
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return data.get("defaults", {}).get("profile", "")


def prepare_initial_state(project_root: Path | None = None) -> dict[str, Any]:
    """Prepare all data needed for the initial load_defaults action.

    Returns a dict with keys: profile, available_profiles, available_stages,
    fields, defaults.
    """
    from devpipe.profiles.loader import find_project_root

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

    if default_profile:
        fields = load_profile_fields(default_profile, root)
        stages = load_profile_stages(default_profile, root)
        defaults = load_profile_defaults(default_profile, root)
    else:
        # No profile configured and no profiles available
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

    return {
        "profile": default_profile,
        "available_profiles": profiles,
        "available_stages": stages,
        "fields": fields,
        "defaults": defaults,
    }


# Helper functions for new-format (routing) profiles

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


def _convert_inputs_to_fields(inputs: dict[str, Any]) -> list[FieldMeta]:
    """Convert InputSpec objects (from loader) to FieldMeta list for UI."""
    fields: list[FieldMeta] = []
    for key, spec in inputs.items():
        if key in _STANDARD_KEYS:
            continue
        # spec is InputSpec; extract attributes
        type_str = spec.type.value
        default = spec.default
        values = spec.values
        options = values or []
        multi = spec.multi
        # InputSpec doesn't have 'required' or 'description'
        required = False
        description = ""

        # Determine kind
        if multi:
            kind = FieldKind.MULTI_SELECT
        elif options:
            kind = FieldKind.SELECT
        else:
            type_map = {
                "string": FieldKind.STRING,
                "int": FieldKind.INT,
                "bool": FieldKind.STRING,  # Boolean as string toggle
                "array": FieldKind.ARRAY,
                "object": FieldKind.OBJECT,
            }
            kind = type_map.get(type_str, FieldKind.STRING)

        fields.append(FieldMeta(
            key=key,
            label=_key_to_label(key),
            kind=kind,
            required=required,
            options=[str(o) for o in options],
            default=default,
            description=description,
            section="custom",
        ))
    return fields
