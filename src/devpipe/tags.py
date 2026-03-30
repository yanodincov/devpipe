from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

BUILTIN_TAGS_DIR = Path(__file__).resolve().parents[2] / "tags"


@dataclass
class TagParam:
    key: str
    description: str = ""
    required: bool = False
    available: list[str] = field(default_factory=list)
    multi: bool = False


@dataclass
class TagDefinition:
    name: str
    params_by_role: dict[str, list[TagParam]] = field(default_factory=dict)

    @property
    def all_params(self) -> list[TagParam]:
        seen: set[str] = set()
        result = []
        for params in self.params_by_role.values():
            for p in params:
                if p.key not in seen:
                    seen.add(p.key)
                    result.append(p)
        return result


def _load_params_file(path: Path) -> list[TagParam]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [
        TagParam(
            key=p["key"],
            description=p.get("description", ""),
            required=p.get("required", False),
            available=[str(v) for v in p.get("available", [])],
            multi=bool(p.get("multi", False)),
        )
        for p in data.get("params", [])
    ]


def _load_from_dir(tag_name: str, tag_dir: Path) -> TagDefinition:
    params_by_role: dict[str, list[TagParam]] = {}
    if tag_dir.exists():
        for role_dir in tag_dir.iterdir():
            if role_dir.is_dir():
                params = _load_params_file(role_dir / "params.yaml")
                if params:
                    params_by_role[role_dir.name] = params
    return TagDefinition(name=tag_name, params_by_role=params_by_role)


def load_tag_definition(tag_name: str, tags_dir: Path) -> TagDefinition:
    return _load_from_dir(tag_name, tags_dir / tag_name)


def _tag_names_in(tags_dir: Path) -> list[str]:
    if not tags_dir.exists():
        return []
    return sorted(p.name for p in tags_dir.iterdir() if p.is_dir())


def load_available_tags(cwd: Path | None = None) -> dict[str, TagDefinition]:
    """Load all available tags: custom (.devpipe/tags/) first, then builtin (tags/)."""
    cwd = cwd or Path.cwd()
    custom_dir = cwd / ".devpipe" / "tags"
    result: dict[str, TagDefinition] = {}

    for name in _tag_names_in(custom_dir):
        result[name] = _load_from_dir(name, custom_dir / name)

    for name in _tag_names_in(BUILTIN_TAGS_DIR):
        if name not in result:
            result[name] = _load_from_dir(name, BUILTIN_TAGS_DIR / name)

    return result


def load_tag_definitions(
    tag_names: list[str],
    cwd: Path | None = None,
) -> dict[str, TagDefinition]:
    all_tags = load_available_tags(cwd)
    return {name: all_tags[name] for name in tag_names if name in all_tags}


def collect_params(
    tag_definitions: dict[str, TagDefinition],
    project_tag_params: dict[str, dict],
    tag_roles: dict[str, set[str]] | set[str] | None = None,
) -> list[tuple[str, TagParam, list[str], str]]:
    """Returns list of (tag_name, param, available_values, default_value).

    If tag_roles is given, only params defined under roles that are active for each tag are included.
    tag_roles can be:
    - None: all roles for each tag are active.
    - dict[tag, set[role]]: per-tag active roles.
    - set[role]: legacy active_roles applied to all tags.
    """
    seen: set[str] = set()
    result = []
    for tag_name, defn in tag_definitions.items():
        overrides = project_tag_params.get(tag_name, {})
        # Determine which roles are active for this tag
        if tag_roles is None:
            active_roles_for_tag = set(defn.params_by_role.keys())
        else:
            if isinstance(tag_roles, dict):
                active_roles_for_tag = tag_roles.get(tag_name, set())
            else:
                # Assume it's a set of roles (legacy active_roles)
                active_roles_for_tag = tag_roles
        for role, params in defn.params_by_role.items():
            if role not in active_roles_for_tag:
                continue
            for param in params:
                if param.key in seen:
                    continue
                seen.add(param.key)
                available = overrides.get("available", {}).get(param.key, param.available)
                default = str(overrides.get("defaults", {}).get(param.key, available[0] if available else ""))
                result.append((tag_name, param, available, default))
    return result
