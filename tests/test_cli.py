from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from devpipe import cli
from devpipe.history import RunDetailsEntry, StageRun, save_run_details
from devpipe.runtime.state import PipelineState


class FakeRunner:
    def __init__(self) -> None:
        self.output_callback = None


class FakeApp:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.runners = {"codex": FakeRunner()}
        self.seen_config = None

    def run(self, config, on_stage_start=None, on_stage_complete=None):
        self.seen_config = config
        if on_stage_start is not None:
            on_stage_start("write", "codex", "gpt-5.4-mini", "low")
        runner = self.runners["codex"]
        if runner.output_callback is not None:
            runner.output_callback('{"type":"action","action":"pwd","result":"/tmp"}\n')
            runner.output_callback('{"type":"thinking","text":"step by step"}\n')
        if on_stage_complete is not None:
            on_stage_complete("write", {"summary": "done"}, tokens=123)

        state = PipelineState.create(
            task_id=config.task_id or "no-id",
            task_text=config.task,
            selected_runner=config.runner,
            run_id="run-123",
        )
        state.status = "completed"
        state.current_stage = "completed"
        state.artifacts["stage_outputs"]["finalize"] = {"final": "done"}
        save_run_details(
            RunDetailsEntry(
                run_id="run-123",
                timestamp=datetime(2026, 4, 2, 10, 11, 12, tzinfo=timezone.utc),
                summary={"final_status": "completed", "total_duration_seconds": 2.5},
                stages=[
                    StageRun(
                        name="finalize",
                        started_at=datetime(2026, 4, 2, 10, 11, 12, tzinfo=timezone.utc),
                        completed_at=datetime(2026, 4, 2, 10, 11, 14, tzinfo=timezone.utc),
                        status="completed",
                        output={"final": "done"},
                        attempts=[],
                    )
                ],
            ),
            self.project_root / ".devpipe" / "history",
        )
        return state


def test_exec_command_merges_pipe_file_with_flag_overrides_and_returns_final_json(tmp_path, monkeypatch, capsys):
    pipe_file = tmp_path / "release.devpipe.yaml"
    pipe_file.write_text(
        """
profile: delivery
task: from file
runner: auto
model: low
effort: low
tags:
  - file-tag
start_agent: intake
stop_agent: finalize
topic: from-file
""".strip(),
        encoding="utf-8",
    )

    fake_app = FakeApp(tmp_path)
    monkeypatch.setattr(cli, "find_project_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "build_default_app", lambda *args, **kwargs: fake_app)

    code = cli.main(
        [
            "exec",
            f"--pipe-file={pipe_file}",
            "--task=override task",
            "--runner=codex",
            "--tags=one,two",
            "--start-agent=expand",
            "--stop-agent=finalize",
            "--topic=override-topic",
        ]
    )

    assert code == 0
    assert fake_app.seen_config.profile == "delivery"
    assert fake_app.seen_config.task == "override task"
    assert fake_app.seen_config.runner == "codex"
    assert fake_app.seen_config.tags == ["one", "two"]
    assert fake_app.seen_config.first_role == "expand"
    assert fake_app.seen_config.last_role == "finalize"
    assert fake_app.seen_config.extra_params["topic"] == "override-topic"

    payload = json.loads(capsys.readouterr().out)
    assert payload["type"] == "final"
    assert payload["status"] == "completed"
    assert payload["final"]["final"] == "done"
    assert payload["profile"] == "delivery"


def test_exec_command_with_thinking_streams_jsonl_and_final_event(tmp_path, monkeypatch, capsys):
    fake_app = FakeApp(tmp_path)
    monkeypatch.setattr(cli, "find_project_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "build_default_app", lambda *args, **kwargs: fake_app)

    code = cli.main(
        [
            "exec",
            "--profile=delivery",
            "--task=hello",
            "--runner=codex",
            "--with-thinking",
        ]
    )

    assert code == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert lines[0]["type"] == "stage_started"
    assert lines[1]["type"] == "action"
    assert lines[2]["type"] == "thinking"
    assert lines[3]["type"] == "stage_completed"
    assert lines[-1]["type"] == "final"
    assert lines[-1]["final"]["final"] == "done"


def test_doctor_command_returns_non_zero_when_no_engines(monkeypatch, capsys):
    monkeypatch.setattr(cli, "find_project_root", lambda: Path.cwd())
    monkeypatch.setattr(cli, "discover_available_engines", lambda *_args, **_kwargs: [])

    code = cli.main(["doctor"])

    assert code == 1
    assert "No available AI engines found" in capsys.readouterr().out
