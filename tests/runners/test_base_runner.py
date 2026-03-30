from __future__ import annotations

import os
import subprocess

from devpipe.profiles.agent import TaskEnvelope
from devpipe.runners.base import BaseCliRunner


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


def test_base_runner_starts_process_in_new_session(monkeypatch) -> None:
    runner = BaseCliRunner(command=["runner"], use_pty=False)
    popen_kwargs: dict[str, object] = {}

    class FakeProc:
        returncode = 0

        def communicate(self, prompt: str, timeout: int) -> tuple[str, str]:
            assert prompt
            assert timeout == runner.timeout
            return ('{"summary":"done"}', "")

    def fake_popen(*_args, **kwargs):
        popen_kwargs.update(kwargs)
        return FakeProc()

    monkeypatch.setattr("subprocess.Popen", fake_popen)

    result = runner.run(_envelope())

    assert result.structured_output["summary"] == "done"
    assert popen_kwargs["start_new_session"] is True


def test_base_runner_non_pty_uses_exec_fn_override() -> None:
    calls: list[list[str]] = []

    def fake_exec(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        assert kwargs["input"]
        assert kwargs["timeout"] == 300
        return subprocess.CompletedProcess(args=args, returncode=0, stdout='{"summary":"done"}', stderr="")

    runner = BaseCliRunner(command=["runner"], use_pty=False, exec_fn=fake_exec)

    result = runner.run(_envelope())

    assert calls == [["runner"]]
    assert result.structured_output["summary"] == "done"


def test_base_runner_cancel_kills_process_group(monkeypatch) -> None:
    runner = BaseCliRunner(command=["runner"])
    calls: list[tuple[str, int, int] | tuple[str, int]] = []

    class FakeProc:
        pid = 4321

        def poll(self) -> None:
            return None

    runner._set_active_process(FakeProc())

    monkeypatch.setattr(os, "getpgid", lambda pid: calls.append(("getpgid", pid)) or 9876)
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: calls.append(("killpg", pgid, sig)))

    runner.cancel()

    assert ("getpgid", 4321) in calls
    assert any(call[0] == "killpg" and call[1] == 9876 for call in calls)
