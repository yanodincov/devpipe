from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BUILTIN_TAGS_DIR = Path(__file__).resolve().parents[2] / "tags"


@dataclass
class TagDefinition:
    """Definition of a tag with rules for each stage."""
    name: str
    stages: list[str]  # stages that have rules.md for this tag


def _load_from_dir(tag_name: str, tag_dir: Path) -> TagDefinition:
    """Load tag definition from directory."""
    stages: list[str] = []
    if tag_dir.exists():
        for stage_dir in tag_dir.iterdir():
            if stage_dir.is_dir() and (stage_dir / "rules.md").exists():
                stages.append(stage_dir.name)
    return TagDefinition(name=tag_name, stages=stages)


def load_tag_definition(tag_name: str, tags_dir: Path) -> TagDefinition:
    """Load a single tag definition."""
    return _load_from_dir(tag_name, tags_dir / tag_name)


def _tag_names_in(tags_dir: Path) -> list[str]:
    """Get list of tag names in a directory."""
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
    """Load specific tag definitions."""
    all_tags = load_available_tags(cwd)
    return {name: all_tags[name] for name in tag_names if name in all_tags}