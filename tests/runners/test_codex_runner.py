from __future__ import annotations

import json
import subprocess

import pytest

from devpipe.profiles.agent import TaskEnvelope
from devpipe.runners.codex import CodexRunner
from devpipe.runners.base import InvalidRunnerOutputError, RunnerTimeoutError


def _envelope() -> TaskEnvelope:
    return TaskEnvelope(
        role="architect",
        goal="Create a plan",
        instructions="Return JSON",
        model_name="gpt-5.4",
        effort="high",
        context={"task": "Implement feature"},
        artifacts={},
        constraints=[],
        output_schema={"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]},
    )


def test_codex_runner_returns_structured_output() -> None:
    runner = CodexRunner()

    def fake_run_pty(envelope: TaskEnvelope):
        command, _ = runner._get_command_and_input(envelope)
        assert "-m" in command
        assert "gpt-5.4" in command
        assert '-c' in command
        assert 'model_reasoning_effort="high"' in command
        assert runner._output_file is not None
        with open(runner._output_file, "w", encoding="utf-8") as f:
            json.dump({"summary": "done"}, f)
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

    runner._run_pty = fake_run_pty  # type: ignore[method-assign]
    result = runner.run(_envelope())

    assert result.ok is True
    assert result.structured_output["summary"] == "done"


def test_codex_runner_raises_timeout() -> None:
    runner = CodexRunner()
    runner._run_pty = lambda _envelope: (_ for _ in ()).throw(RunnerTimeoutError("timed out"))  # type: ignore[method-assign]

    with pytest.raises(RunnerTimeoutError):
        runner.run(_envelope())


def test_codex_runner_rejects_invalid_output() -> None:
    runner = CodexRunner()

    def fake_run_pty(envelope: TaskEnvelope):
        command, _ = runner._get_command_and_input(envelope)
        assert runner._output_file is not None
        with open(runner._output_file, "w", encoding="utf-8") as f:
            f.write('{"bad":true}')
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

    runner._run_pty = fake_run_pty  # type: ignore[method-assign]

    with pytest.raises(InvalidRunnerOutputError):
        runner.run(_envelope())


def test_codex_runner_hides_boring_successful_command_output() -> None:
    event = {
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "command": "cat /tmp/noise.txt",
            "exit_code": 0,
            "aggregated_output": "line1\nline2\nline3",
        },
    }

    formatted = CodexRunner._format_event(event)

    assert formatted is None


def test_codex_runner_run_pty_registers_process_callback(monkeypatch) -> None:
    runner = CodexRunner()
    seen: dict[str, object] = {}

    def fake_run_with_pty(*_args, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(args=["codex"], returncode=0, stdout="", stderr="")

    monkeypatch.setattr("devpipe.runners.base._run_with_pty", fake_run_with_pty)

    runner._run_pty(_envelope())

    assert seen["process_callback"] == runner._set_active_process
