"""Agent envelope building for profile-driven stages."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

BUILTIN_TAGS_DIR = Path(__file__).resolve().parents[3] / "tags"


@dataclass
class TaskEnvelope:
    """Task envelope for runner execution."""
    role: str
    goal: str
    instructions: str
    model_name: str
    effort: str
    context: dict[str, object]
    artifacts: dict[str, object]
    constraints: list[str]
    output_schema: dict[str, object]


@dataclass
class TaskResult:
    """Result from runner execution."""
    ok: bool
    summary: str
    structured_output: dict[str, object]
    artifacts: dict[str, object] = field(default_factory=dict)
    next_hints: list[str] = field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None
    transcript: str = ""


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def compose_stage_instructions(
    base_prompt: str,
    stage_name: str,
    project_root: str | Path | None = None,
    tags: list[str] | None = None,
) -> str:
    """Compose instructions for a stage by adding tag rules."""
    instructions = base_prompt.strip()
    if project_root is None:
        return instructions

    root = Path(project_root)
    sections: list[str] = []

    # Project-specific rules: .devpipe/<STAGE_NAME>_RULES.md
    project_rules = _read(root / ".devpipe" / f"{stage_name.upper()}_RULES.md")
    if project_rules:
        sections.append(f"## Project-Specific Rules\n\n{project_rules}")

    # Tag rules from custom and builtin tags
    for tag in tags or []:
        # Custom tag rules: .devpipe/tags/<tag>/<stage>/rules.md
        custom_path = root / ".devpipe" / "tags" / tag / stage_name / "rules.md"
        custom = _read(custom_path)
        if custom:
            sections.append(f"## Tag Rules: {tag}\n\n{custom}")
            continue
        # Builtin tag rules: tags/<tag>/<stage>/rules.md
        builtin = _read(BUILTIN_TAGS_DIR / tag / stage_name / "rules.md")
        if builtin:
            sections.append(f"## Tag Rules: {tag}\n\n{builtin}")

    if not sections:
        return instructions
    return f"{instructions}\n\n" + "\n\n".join(sections)


def build_stage_envelope(
    stage_spec,
    state,
    model_name: str,
    effort: str,
    extra_context: dict[str, object] | None = None,
    project_root: str | Path | None = None,
    tags: list[str] | None = None,
) -> TaskEnvelope:
    """Build TaskEnvelope from stage specification and runtime state."""
    context = {
        "task_id": state.task_id,
        "task_text": state.task_text,
        "run_id": state.run_id,
        "current_stage": state.current_stage,
        "shared_context": state.shared_context,
        "release_context": state.release_context,
    }
    if extra_context:
        context.update(extra_context)

    # Determine prompt and output_schema from agent
    prompt = ""
    output_schema = {}
    if stage_spec.agent:
        prompt = stage_spec.agent.prompt_content
        output_schema = stage_spec.agent.schema_content

    # Merge stage-specific tags (from profile) with user-provided tags (from config)
    stage_tags = set(stage_spec.tags or [])
    user_tags = set(tags or [])
    merged_tags = list(stage_tags | user_tags)

    # Compose instructions with tag rules
    instructions = compose_stage_instructions(
        prompt,
        stage_spec.name,
        project_root=project_root,
        tags=merged_tags,
    )

    return TaskEnvelope(
        role=stage_spec.name,
        goal=f"Execute stage {stage_spec.name} for task {state.task_id}",
        instructions=instructions,
        model_name=model_name,
        effort=effort,
        context=context,
        artifacts=state.artifacts,
        constraints=["Return machine-readable JSON matching output_schema."],
        output_schema=output_schema,
    )
