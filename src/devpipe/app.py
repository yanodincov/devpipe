from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import threading

from devpipe.profiles.agent import build_stage_envelope
from devpipe.profiles.loader import ProfileDefinition, load_profile
from devpipe.profiles.stages import StageType
from devpipe.runtime.engine import PipelineEngine
from devpipe.runtime.events import Event, EventType
from devpipe.runtime.retry import RetryPolicy
from devpipe.runtime.state import PipelineState
from devpipe.engines import (
    discover_available_engines,
    load_runner_runtime_config,
    load_runtime_runner_profiles,
    resolve_engine_choice,
)
from devpipe.runners.claude import ClaudeRunner
from devpipe.runners.command import CommandRunner
from devpipe.runners.codex import CodexRunner
from devpipe.runners.profile_map import RunnerProfiles, resolve_effort, resolve_model
from devpipe.storage.artifact_store import ArtifactStore
from devpipe.storage.run_logger import RunLogger


@dataclass
class RunConfig:
    task: str
    runner: str
    profile: str = ""
    task_id: str | None = None
    model: str | None = None
    effort: str | None = None
    target_branch: str | None = None
    namespace: str | None = None
    service: str | None = None
    tags: list[str] | None = None
    tag_roles: dict[str, list[str]] | None = None  # NEW: per-tag role activation
    extra_params: dict[str, str | list[str]] | None = None
    first_role: str | None = None
    last_role: str | None = None


def _get_nested_value(data: object, path: list[str]) -> object | None:
    current = data
    for part in path:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _resolve_route_field(
    field_path: str,
    *,
    current_output: dict[str, object],
    state: PipelineState,
    config: RunConfig,
) -> object | None:
    if field_path.startswith("out."):
        return _get_nested_value(current_output, field_path.split(".")[1:])
    if field_path.startswith("input."):
        return getattr(config, field_path.split(".", 1)[1], None)
    if field_path.startswith("context."):
        return _get_nested_value(state.shared_context, field_path.split(".")[1:])
    if field_path.startswith("runtime."):
        return _get_nested_value(state.release_context, field_path.split(".")[1:])
    if field_path.startswith("integration."):
        return _get_nested_value(state.shared_context, field_path.split(".")[1:])
    if field_path.startswith("stage."):
        parts = field_path.split(".")
        if len(parts) >= 4 and parts[2] == "out":
            stage_name = parts[1]
            stage_output = state.artifacts.get("stage_outputs", {}).get(stage_name, {})
            return _get_nested_value(stage_output, parts[3:])
    return None


def _matches_condition(actual: object | None, op: str, expected: object) -> bool:
    if op == "eq":
        return actual == expected
    if op == "neq":
        return actual != expected
    if actual is None:
        return False
    if op == "gt":
        return actual > expected
    if op == "gte":
        return actual >= expected
    if op == "lt":
        return actual < expected
    if op == "lte":
        return actual <= expected
    if op == "in":
        return isinstance(expected, list) and actual in expected
    if op == "contains":
        if isinstance(actual, (list, tuple, set, str)):
            return expected in actual
        return False
    return False


def _resolve_next_stage_from_rules(
    profile: ProfileDefinition,
    current_stage: str,
    *,
    current_output: dict[str, object],
    state: PipelineState,
    config: RunConfig,
) -> str:
    stage_routing = profile.routing.by_stage.get(current_stage)
    if stage_routing is None:
        return "completed"

    default_stage: str | None = None
    for rule in stage_routing.next_stages:
        if rule.default:
            default_stage = rule.stage
            continue

        if rule.all and all(
            _matches_condition(
                _resolve_route_field(cond.field, current_output=current_output, state=state, config=config),
                cond.op,
                cond.value,
            )
            for cond in rule.all
        ):
            return rule.stage

        if rule.any and any(
            _matches_condition(
                _resolve_route_field(cond.field, current_output=current_output, state=state, config=config),
                cond.op,
                cond.value,
            )
            for cond in rule.any
        ):
            return rule.stage

    return default_stage or "completed"


class OrchestratorApp:
    def __init__(
        self,
        runners: dict[str, object],
        runs_dir: str | Path,
        jira_adapter=None,
        git_adapter=None,
        github_adapter=None,
        kubernetes_adapter=None,
        retry_policy: RetryPolicy | None = None,
        project_root: str | Path | None = None,
        runner_profiles: RunnerProfiles | None = None,
    ) -> None:
        self.runners = runners
        self.runs_dir = Path(runs_dir)
        self.jira_adapter = jira_adapter
        self.git_adapter = git_adapter
        self.github_adapter = github_adapter
        self.kubernetes_adapter = kubernetes_adapter
        self.base_retry_policy = retry_policy or RetryPolicy.default()
        self.project_root = Path(project_root) if project_root is not None else None
        self.runner_profiles = runner_profiles or {}
        self._cancel_requested = threading.Event()
        self.command_runner = CommandRunner()

    def run(
        self,
        config: RunConfig,
        on_stage_start: "Callable[[str, str, str, str], None] | None" = None,
        on_stage_complete: "Callable[[str, dict], None] | None" = None,
    ) -> PipelineState:
        from datetime import datetime, timezone
        from devpipe.history import RunDetailsEntry, RunReplayConfig, StageRun, save_run_details, save_run_replay_config
        from devpipe.profiles.loader import get_stage_order_from_routing

        self._cancel_requested.clear()

        # Generate ISO timestamp run_id
        run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S.%f")

        # Load profile - if not specified, use default from project config
        if not config.profile:
            from devpipe.project_config import load_project_config
            proj_cfg = load_project_config(self.project_root)
            default_profile = proj_cfg.default("profile")
            if not default_profile:
                raise ValueError("No profile specified and no default profile configured")
            config.profile = default_profile
        profile = load_profile(config.profile, project_root=self.project_root)

        # Determine stage ordering and transitions from routing
        stage_order = get_stage_order_from_routing(profile.routing, profile.stages)
        if not stage_order:
            raise ValueError(f"Profile '{config.profile}' has no stages in routing")

        # Build next_stage mapping from default rules
        next_stage_map: dict[str, str] = {}
        for stage_name, stage_routing in profile.routing.by_stage.items():
            for rule in stage_routing.next_stages:
                if rule.default:
                    next_stage_map[stage_name] = rule.stage
                    break
            if stage_name not in next_stage_map and stage_routing.next_stages:
                next_stage_map[stage_name] = stage_routing.next_stages[0].stage

        # Determine first and last stages
        first_stage = config.first_role if config.first_role else profile.routing.start_stage
        last_stage = config.last_role if config.last_role else None

        if first_stage not in profile.stages:
            raise ValueError(f"Unknown first_role: {first_stage}")
        if last_stage is not None and last_stage not in profile.stages:
            raise ValueError(f"Unknown last_role: {last_stage}")

        # Compute engine's first_stage and get_next_stage functions
        def get_first() -> str:
            return first_stage

        def get_next(current: str) -> str:
            if last_stage is not None and current == last_stage:
                return "completed"
            return next_stage_map.get(current, "completed")

        # Prepare retry policy with stage-specific limits from profile
        stage_limits = {name: spec.retry_limit for name, spec in profile.stages.items()}
        # Combine with base policy's stage_limits (overlay)
        combined_limits = {**self.base_retry_policy.stage_limits, **stage_limits}
        retry_policy = RetryPolicy(
            default_limit=self.base_retry_policy.default_limit,
            stage_limits=combined_limits,
        )
        engine = PipelineEngine(
            retry_policy=retry_policy,
            get_first_stage=get_first,
            get_next_stage=get_next,
        )

        task_id = config.task_id or "no-id"
        state = PipelineState.create(
            task_id=task_id,
            task_text=config.task,
            selected_runner=config.runner,
            run_id=run_id,
        )
        state.release_context.update({**(config.extra_params or {})})

        if self.jira_adapter is not None and config.task_id:
            state.shared_context["jira"] = self.jira_adapter.fetch_issue(config.task_id)

        # History tracking
        run_start_time = datetime.now(timezone.utc)
        stage_runs: dict[str, dict] = {}
        total_tokens: int = 0

        logger = RunLogger(self.runs_dir, state.run_id)
        artifacts = ArtifactStore(logger.run_dir)

        event = Event(EventType.RUN_STARTED, payload={"task_id": task_id})
        logger.log_event(event)
        state = engine.apply(state, event)

        try:
            while state.status not in {"completed", "failed", "cancelled"}:
                if self._cancel_requested.is_set():
                    state.status = "cancelled"
                    break

                # Get stage specification
                if state.current_stage not in profile.stages:
                    raise ValueError(f"Stage '{state.current_stage}' not found in profile '{config.profile}'")
                stage_spec = profile.stages[state.current_stage]

                # Initialize stage tracking if this is first time entering this stage
                stage_name = state.current_stage
                if stage_name not in stage_runs:
                    stage_runs[stage_name] = {
                        "name": stage_name,
                        "started_at": datetime.now(timezone.utc),
                        "completed_at": None,
                        "status": "running",
                        "attempts": []
                    }
                stage_entry = stage_runs[stage_name]

                # Build context
                stage_context: dict[str, object] = {"config": config.__dict__}
                if state.current_stage == "release":
                    if not config.target_branch:
                        raise ValueError("target_branch must be provided for release stage")
                    if not config.namespace:
                        raise ValueError("namespace must be provided for release stage")
                    if not config.service:
                        raise ValueError("service must be provided for release stage")
                    current_branch = getattr(self.git_adapter, "current_branch", lambda: None)() if self.git_adapter is not None else None
                    stage_context["release_inputs"] = {
                        "branch": current_branch,
                        "target_branch": config.target_branch,
                        "namespace": config.namespace,
                        "service": config.service,
                        **(config.extra_params or {}),
                    }

                # Filter user tags by tag_roles for this stage
                stage_name = stage_spec.name
                user_tags_for_stage: list[str] = []
                if config.tags:
                    if config.tag_roles:
                        for tag in config.tags:
                            roles = config.tag_roles.get(tag, [])
                            if stage_name in roles:
                                user_tags_for_stage.append(tag)
                    else:
                        user_tags_for_stage = list(config.tags)

                if stage_spec.type == StageType.AI:
                    actual_runner_name = resolve_engine_choice(
                        requested_runner=config.runner,
                        stage_default_engine=stage_spec.default_engine or "",
                        available_engines=list(self.runners.keys()),
                    )
                    runner = self.runners[actual_runner_name]
                    state.selected_runner = actual_runner_name
                    model_level = stage_spec.model if config.model in {None, "", "auto"} else config.model
                    effort_level = stage_spec.effort if config.effort in {None, "", "auto"} else config.effort
                    resolved_model = resolve_model(self.runner_profiles, actual_runner_name, model_level)
                    resolved_effort = resolve_effort(self.runner_profiles, actual_runner_name, effort_level)
                    runner.model_name = resolved_model
                    runner.effort = resolved_effort
                    envelope = build_stage_envelope(
                        stage_spec,
                        state,
                        model_name=resolved_model,
                        effort=resolved_effort,
                        extra_context=stage_context,
                        project_root=self.project_root,
                        tags=user_tags_for_stage,  # only user tags filtered by roles; stage_spec.tags handled inside
                    )
                else:
                    actual_runner_name = "cmd"
                    runner = self.command_runner
                    state.selected_runner = actual_runner_name
                    resolved_model = ""
                    resolved_effort = ""
                    envelope = None

                if on_stage_start is not None:
                    on_stage_start(state.current_stage, actual_runner_name, resolved_model, resolved_effort)

                attempt_start = datetime.now(timezone.utc)
                try:
                    if stage_spec.type == StageType.AI:
                        result = runner.run(envelope)
                    else:
                        result = runner.run(stage_spec, project_root=self.project_root)
                except Exception as exc:
                    attempt_end = datetime.now(timezone.utc)
                    stage_entry["attempts"].append({
                        "started_at": attempt_start,
                        "completed_at": attempt_end,
                        "status": "failed",
                        "error_message": str(exc)
                    })
                    logger.log_stage_failure(
                        stage_spec.name,
                        {
                            "stage": stage_spec.name,
                            "runner": actual_runner_name,
                            "model": resolved_model,
                            "effort": resolved_effort,
                            "error": str(exc),
                            "config": config.__dict__,
                            "context": stage_context,
                            "output_schema": envelope.output_schema if envelope is not None else {},
                        },
                    )
                    if self._cancel_requested.is_set():
                        state.status = "cancelled"
                        logger.write_summary(state)
                        break
                    failure = Event(EventType.STAGE_FAILED, stage=state.current_stage, error_message=str(exc))
                    logger.log_event(failure)
                    state = engine.apply(state, failure)
                    logger.write_summary(state)
                    if state.status == "failed":
                        stage_entry["completed_at"] = attempt_end
                        stage_entry["status"] = "failed"
                        raise
                    continue

                if self._cancel_requested.is_set():
                    state.status = "cancelled"
                    logger.write_summary(state)
                    break

                # Record successful attempt and mark stage complete
                attempt_end = datetime.now(timezone.utc)
                total_tokens += result.tokens
                stage_entry["attempts"].append({
                    "started_at": attempt_start,
                    "completed_at": attempt_end,
                    "status": "completed",
                    "output": result.structured_output,
                    "tokens": result.tokens,
                })
                stage_entry["output"] = result.structured_output
                stage_entry["completed_at"] = attempt_end
                stage_entry["status"] = "completed"

                state.artifacts.setdefault("stage_outputs", {})[stage_spec.name] = result.structured_output
                transcript_path = logger.log_stage_transcript(stage_spec.name, result.transcript)
                artifacts.write_stage_artifacts(stage_spec.name, result.structured_output)
                state.shared_context[f"{stage_spec.name}_log"] = str(transcript_path)

                if on_stage_complete is not None:
                    on_stage_complete(stage_spec.name, result.structured_output, tokens=result.tokens)

                if last_stage is not None and stage_spec.name == last_stage:
                    next_stage = "completed"
                else:
                    next_stage = _resolve_next_stage_from_rules(
                        profile,
                        stage_spec.name,
                        current_output=result.structured_output,
                        state=state,
                        config=config,
                    )

                success = Event(
                    EventType.STAGE_COMPLETED,
                    stage=stage_spec.name,
                    summary=result.summary,
                    payload={"next_stage": next_stage},
                )
                logger.log_event(success)
                state = engine.apply(state, success)
                logger.write_summary(state)

                if last_stage is not None and stage_spec.name == last_stage and state.status not in {"completed", "failed"}:
                    state.status = "completed"
                    state.current_stage = "completed"
                    logger.write_summary(state)

                if stage_spec.name == "release" and self.github_adapter is not None:
                    self.github_adapter.ensure_workflow_success(state.run_id)
        finally:
            logger.write_summary(state)
            # Finalize any running stages with current status
            run_end_time = datetime.now(timezone.utc)
            for entry in stage_runs.values():
                if entry["status"] == "running":
                    entry["completed_at"] = run_end_time
                    entry["status"] = state.status  # cancelled, failed, or maybe completed from outside?

            # Build summary
            total_duration = (run_end_time - run_start_time).total_seconds()
            stages_completed = sum(1 for e in stage_runs.values() if e["status"] == "completed")
            stages_failed = sum(1 for e in stage_runs.values() if e["status"] == "failed")
            summary = {
                "total_duration_seconds": round(total_duration, 3),
                "stages_completed": stages_completed,
                "stages_failed": stages_failed,
                "final_status": state.status,
                "total_tokens": total_tokens,
            }

            # Convert stage_runs dict to ordered list of StageRun objects
            ordered_stage_dicts = [stage_runs[name] for name in stage_order if name in stage_runs]
            stage_run_objects = [
                StageRun(
                    name=s["name"],
                    started_at=s["started_at"],
                    completed_at=s["completed_at"],
                    status=s["status"],
                    output=s.get("output", {}),
                    attempts=s["attempts"],
                )
                for s in ordered_stage_dicts
            ]

            replay_entry = RunReplayConfig(
                profile=config.profile,
                config=config.__dict__,
            )
            details_entry = RunDetailsEntry(
                run_id=run_id,
                timestamp=run_start_time,
                stages=stage_run_objects,
                summary=summary,
            )
            history_dir = self.project_root / ".devpipe" / "history"
            save_run_replay_config(run_id, replay_entry, history_dir)
            save_run_details(details_entry, history_dir)

        return state

    def cancel_active_runs(self) -> None:
        self._cancel_requested.set()
        for runner in self.runners.values():
            cancel = getattr(runner, "cancel", None)
            if callable(cancel):
                cancel()


def build_default_app(base_dir: str | Path, show_prompt: bool = False) -> OrchestratorApp:
    del base_dir
    project_root = Path.cwd()
    raw_config = load_runner_runtime_config(project_root=project_root)
    runner_config = raw_config.get("runners", {})
    runner_profiles = load_runtime_runner_profiles(project_root=project_root)
    available_engines = discover_available_engines(runner_config)
    runners: dict[str, object] = {}

    codex_config = runner_config.get("codex", {})
    if "codex" in available_engines:
        runners["codex"] = CodexRunner(
            command=codex_config.get("command", ["codex"]),
            timeout=int(codex_config.get("timeout", 300)),
            show_prompt=show_prompt,
        )
    claude_config = runner_config.get("claude", {})
    if "claude" in available_engines:
        runners["claude"] = ClaudeRunner(
            command=claude_config.get("command", ["claude"]),
            timeout=int(claude_config.get("timeout", 300)),
            show_prompt=show_prompt,
        )

    return OrchestratorApp(
        runners=runners,
        runs_dir=project_root / ".devpipe" / "runs",
        project_root=project_root,
        runner_profiles=runner_profiles,
    )
