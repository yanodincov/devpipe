from __future__ import annotations

from pathlib import Path

import devpipe.app as app_module
import devpipe.history as history_module
import pytest
from devpipe.app import OrchestratorApp, RunConfig
from devpipe.profiles.agent import TaskResult


class FakeRunner:
    def __init__(self, outputs: dict[str, dict[str, object]]) -> None:
        self.outputs = outputs
        self.model_name = ""
        self.effort = ""

    def run(self, envelope) -> TaskResult:
        output = self.outputs[envelope.role]
        return TaskResult(
            ok=True,
            summary=f"{envelope.role} ok",
            structured_output=output,
            transcript="",
        )


class FailingRunner:
    def __init__(self) -> None:
        self.model_name = ""
        self.effort = ""

    def run(self, envelope) -> TaskResult:
        raise RuntimeError(f"runner exploded on {envelope.role}")


def _runner_profiles() -> dict[str, dict[str, dict[str, str]]]:
    return {
        "codex": {
            "model": {
                "low": "gpt-test-low",
                "middle": "gpt-test-middle",
                "high": "gpt-test-high",
            },
            "effort": {
                "low": "low",
                "middle": "medium",
                "high": "high",
                "extra": "extra",
            },
        }
    }


def test_orchestrator_uses_conditional_routing_rules(tmp_path: Path, monkeypatch) -> None:
    profile_dir = tmp_path / ".devpipe" / "profiles" / "branchy"
    profile_dir.mkdir(parents=True)
    (tmp_path / ".devpipe" / "runs").mkdir(parents=True)
    monkeypatch.setattr(history_module, "save_run_history", lambda entry, runs_dir: None)

    (profile_dir / "pipeline.yml").write_text(
        """
version: 1
name: branchy
inputs:
  task:
    type: string
    default: ""
    custom: true
stages:
  start:
    runner: codex
    model: low
    effort: low
    out:
      seed:
        type: string
  decide:
    runner: codex
    model: low
    effort: low
    out:
      go_refine:
        type: bool
  refine:
    runner: codex
    model: low
    effort: low
    out:
      refined:
        type: string
  finalize:
    runner: codex
    model: low
    effort: low
    out:
      final:
        type: string
routing:
  start_stage: start
  by_stage:
    start:
      next_stages:
        - stage: decide
          default: true
    decide:
      next_stages:
        - stage: refine
          all:
            - field: out.go_refine
              op: eq
              value: true
        - stage: finalize
          all:
            - field: out.go_refine
              op: eq
              value: false
        - stage: finalize
          default: true
    refine:
      next_stages:
        - stage: finalize
          default: true
    finalize:
      next_stages:
        - stage: completed
          default: true
""".strip(),
        encoding="utf-8",
    )

    runner = FakeRunner(
        {
            "start": {"seed": "idea"},
            "decide": {"go_refine": True},
            "refine": {"refined": "sharper idea"},
            "finalize": {"final": "done"},
        }
    )
    app = OrchestratorApp(
        runners={"codex": runner},
        runs_dir=tmp_path / "runs",
        project_root=tmp_path,
        runner_profiles=_runner_profiles(),
    )

    state = app.run(
        RunConfig(
            profile="branchy",
            task="Test branching",
            runner="codex",
        )
    )

    assert state.status == "completed"
    stage_outputs = state.artifacts["stage_outputs"]
    assert "refine" in stage_outputs
    assert stage_outputs["refine"]["refined"] == "sharper idea"


def test_orchestrator_writes_stage_failure_debug_log(tmp_path: Path, monkeypatch) -> None:
    profile_dir = tmp_path / ".devpipe" / "profiles" / "broken"
    profile_dir.mkdir(parents=True)
    monkeypatch.setattr(history_module, "save_run_history", lambda entry, runs_dir: None)

    (profile_dir / "pipeline.yml").write_text(
        """
version: 1
name: broken
inputs:
  task:
    type: string
    default: ""
    custom: true
stages:
  intake:
    runner: codex
    model: low
    effort: low
    out:
      result:
        type: string
routing:
  start_stage: intake
  by_stage:
    intake:
      next_stages:
        - stage: completed
          default: true
""".strip(),
        encoding="utf-8",
    )

    app = OrchestratorApp(
        runners={"codex": FailingRunner()},
        runs_dir=tmp_path / "runs",
        project_root=tmp_path,
        runner_profiles=_runner_profiles(),
    )

    with pytest.raises(RuntimeError, match="runner exploded on intake"):
        app.run(
            RunConfig(
                profile="broken",
                task="Test failure logging",
                runner="codex",
            )
        )

    run_dirs = sorted((tmp_path / "runs").glob("*"))
    assert run_dirs
    error_log = run_dirs[0] / "logs" / "intake.error.log"
    assert error_log.exists()
    contents = error_log.read_text(encoding="utf-8")
    assert "runner exploded on intake" in contents
    assert '"stage": "intake"' in contents
