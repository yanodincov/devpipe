"""Profile loading and validation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

import yaml
from pydantic import ValidationError

from devpipe.profiles.stages import ProfileStages, StageSpec, StageInBinding, StageOutField, FieldSpec
from devpipe.profiles.routing import RoutingSpec, StageRouting, RouteRule


def find_project_root(start_dir: Path | None = None) -> Path | None:
    """Find the project root by searching upward for a directory containing .devpipe/.

    Args:
        start_dir: Directory to start searching from (defaults to current working directory)

    Returns:
        Path to project root if found, None otherwise.
    """
    start = (start_dir or Path.cwd()).resolve()
    current = start

    # Walk up the directory tree
    while True:
        if (current / ".devpipe").is_dir():
            return current
        if current.parent == current:
            # Reached filesystem root
            break
        current = current.parent

    return None


class ProfileLoadError(Exception):
    """Error loading a profile."""
    pass


@dataclass
class ProfileDefinition:
    """Complete loaded profile definition."""
    name: str
    defaults: dict[str, Any]
    inputs: dict[str, Any]  # InputSpec instances actually
    stages: dict[str, StageSpec]
    routing: RoutingSpec

    def get_stage(self, name: str) -> StageSpec:
        """Get stage by name."""
        return self.stages[name]

    def get_available_stages(self) -> list[str]:
        """Get list of all stage names."""
        return sorted(self.stages.keys())


def _load_yaml_file(path: Path) -> dict[str, Any]:
    """Load YAML file and return dict."""
    if not path.exists():
        raise ProfileLoadError(f"File not found: {path}")
    try:
        content = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(content, dict):
            raise ProfileLoadError(f"Invalid YAML structure in {path}, expected dict")
        return content
    except yaml.YAMLError as e:
        raise ProfileLoadError(f"YAML parse error in {path}: {e}") from e


def load_profile(
    profile_name: str,
    *,
    project_root: Path | None = None,
) -> ProfileDefinition:
    """
    Load a profile by name.

    Search order:
    1. Project profiles: <project_root>/.devpipe/profiles/<profile_name>/pipeline.yaml or pipeline.yml
    2. Global profiles: ~/.devpipe/profiles/<profile_name>/pipeline.yaml or pipeline.yml

    Args:
        profile_name: Name of the profile to load
        project_root: Project root directory (defaults to auto-detected from CWD)

    Returns:
        ProfileDefinition with validated stages and routing

    Raises:
        ProfileLoadError: If profile cannot be found or is invalid
    """
    if project_root is None:
        detected_root = find_project_root()
        if detected_root is None:
            raise ProfileLoadError(
                "Could not find project root (directory containing .devpipe/) "
                "from current working directory. Specify project_root explicitly."
            )
        project_root = detected_root

    # Search locations:
    # 1. Project local: <project_root>/.devpipe/profiles/<profile_name>/pipeline.yaml or pipeline.yml
    # 2. Global: ~/.devpipe/profiles/<profile_name>/pipeline.yaml or pipeline.yml
    search_dirs = [
        project_root / ".devpipe" / "profiles" / profile_name,
        Path.home() / ".devpipe" / "profiles" / profile_name,
    ]

    for profile_dir in search_dirs:
        if not profile_dir.exists():
            continue
        # Try .yaml first, then .yml
        yaml_path = profile_dir / "pipeline.yaml"
        yml_path = profile_dir / "pipeline.yml"
        pipeline_path = None
        if yaml_path.exists():
            pipeline_path = yaml_path
        elif yml_path.exists():
            pipeline_path = yml_path
        if pipeline_path:
            raw_data = _load_yaml_file(pipeline_path)
            base_dir = profile_dir
            return _build_profile_definition(profile_name, raw_data, base_dir)

    # Construct error message with all checked paths
    checked = []
    for d in search_dirs:
        checked.append(str(d / "pipeline.yaml"))
    raise ProfileLoadError(
        f"Profile '{profile_name}' not found. Checked: {', '.join(checked)}"
    )


def _build_profile_definition(
    profile_name: str,
    raw_data: dict[str, Any],
    base_dir: Path,
) -> ProfileDefinition:
    """
    Build ProfileDefinition from raw YAML data.

    Args:
        profile_name: Profile name
        raw_data: Parsed YAML dict
        base_dir: Directory containing pipeline.yml (for resolving relative paths)

    Returns:
        ProfileDefinition instance
    """
    # Extract version and metadata
    version = raw_data.get("version")
    if version != 1:
        raise ProfileLoadError(f"Unsupported profile version: {version}")

    name = raw_data.get("name", profile_name)

    # Parse stages (inputs + stage definitions)
    stages_section = raw_data.get("stages", {})
    inputs_section = raw_data.get("inputs", {})

    # Build ProfileStages
    try:
        profile_stages = _parse_profile_stages(inputs_section, stages_section, base_dir)
    except ValidationError as e:
        raise ProfileLoadError(f"Invalid stages configuration: {e}") from e

    # Parse routing
    routing_section = raw_data.get("routing")
    if not routing_section:
        raise ProfileLoadError("Profile missing required sections: routing")

    try:
        routing = _parse_routing(routing_section, profile_stages)
    except ValidationError as e:
        raise ProfileLoadError(f"Invalid routing configuration: {e}") from e

    # Build final profile definition
    profile = ProfileDefinition(
        name=name,
        defaults=raw_data.get("defaults", {}),
        inputs=profile_stages.inputs,
        stages=profile_stages.stages,
        routing=routing,
    )

    return profile


def _parse_profile_stages(
    inputs_data: dict[str, Any],
    stages_data: dict[str, Any],
    base_dir: Path,
) -> ProfileStages:
    """Parse stages and inputs from raw YAML."""
    # Parse inputs first
    inputs: dict[str, Any] = {}
    for key, spec_data in inputs_data.items():
        inputs[key] = spec_data  # Will be validated via InputSpec later

    # Parse each stage
    stages: dict[str, StageSpec] = {}
    for stage_key, stage_data in stages_data.items():
        # Add stage name if not present (key is authoritative)
        if "name" not in stage_data:
            stage_data["name"] = stage_key

        # Handle in bindings
        in_binding = None
        if "in" in stage_data:
            in_binding = StageInBinding(bindings=stage_data["in"])
            stage_data = {k: v for k, v in stage_data.items() if k != "in"}
            stage_data["in"] = in_binding

        # Handle out fields
        if "out" in stage_data:
            out_fields = {}
            for field_name, field_spec in stage_data["out"].items():
                if isinstance(field_spec, dict):
                    out_fields[field_name] = FieldSpec(**field_spec)
                else:
                    # Allow shorthand if field_spec is just type string
                    out_fields[field_name] = FieldSpec(type=field_spec)
            stage_data["out"] = StageOutField(fields=out_fields)

        # Create StageSpec
        stage = StageSpec(**stage_data)
        stages[stage_key] = stage

    return ProfileStages(inputs=inputs, stages=stages)


def _parse_routing(
    routing_data: dict[str, Any],
    profile_stages: ProfileStages,
) -> RoutingSpec:
    """Parse routing section and validate stage references."""
    # Parse by_stage
    by_stage: dict[str, StageRouting] = {}
    stage_names = set(profile_stages.stages.keys())

    for stage_name, stage_routing_data in routing_data.get("by_stage", {}).items():
        # Ensure referenced stage exists
        if stage_name not in stage_names:
            raise ProfileLoadError(
                f"Routing references stage '{stage_name}' which is not defined in stages section"
            )

        # Parse next_stages
        next_stages_list = stage_routing_data.get("next_stages", [])
        rules: list[RouteRule] = []
        for rule_data in next_stages_list:
            # Convert dict to RouteRule
            rule = RouteRule(**rule_data)
            rules.append(rule)

        routing = StageRouting(stage=stage_name, next_stages=rules)
        by_stage[stage_name] = routing

    # Create RoutingSpec
    start_stage = routing_data.get("start_stage")
    if not start_stage:
        raise ProfileLoadError("routing section must specify start_stage")

    routing_spec = RoutingSpec(start_stage=start_stage, by_stage=by_stage)
    return routing_spec
