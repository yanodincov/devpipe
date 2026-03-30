from __future__ import annotations

import subprocess

from devpipe.profiles.agent import TaskEnvelope
from devpipe.runners.claude import ClaudeRunner


def test_claude_runner_uses_command_template() -> None:
    calls = []

    def fake_exec(args, **_kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout='{"summary":"ready"}',
            stderr="",
        )

    runner = ClaudeRunner(command=["claude", "--print"], exec_fn=fake_exec)
    result = runner.run(
        TaskEnvelope(
            role="qa_local",
            goal="Validate implementation",
            instructions="Return JSON",
            model_name="sonnet",
            effort="medium",
            context={},
            artifacts={},
            constraints=[],
            output_schema={"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]},
        )
    )

    assert calls[0][:6] == ["claude", "--print", "--model", "sonnet", "--effort", "medium"]
    assert result.summary == "ready"
