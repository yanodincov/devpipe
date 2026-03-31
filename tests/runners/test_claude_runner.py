from __future__ import annotations

import json
import subprocess

import pytest

from devpipe.profiles.agent import TaskEnvelope
from devpipe.runners.claude import ClaudeRunner


def test_claude_runner_uses_command_template() -> None:
    envelope = TaskEnvelope(
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

    runner = ClaudeRunner(command=["claude"])
    command, prompt = runner._get_command_and_input(envelope)

    assert command[:12] == [
        "claude",
        "--print",
        "--verbose",
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--no-session-persistence",
        "--model",
        "sonnet",
        "--effort",
        "medium",
        "--json-schema",
    ]
    assert command[12] == '{"type":"object","properties":{"summary":{"type":"string"}},"required":["summary"]}'
    assert command[13].startswith("Role: qa_local")
    assert prompt == ""


def test_claude_runner_forwards_stdout_to_output_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    runner = ClaudeRunner(command=["claude"], output_callback=seen.append)
    stream = "\n".join(
        [
            json.dumps({"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "thinking"}}}),
            json.dumps({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "Considering one route."}}}),
            json.dumps({"type": "stream_event", "event": {"type": "content_block_stop"}}),
            json.dumps({"type": "result", "subtype": "success", "structured_output": {"summary": "ready"}}),
        ]
    )
    monkeypatch.setattr(
        ClaudeRunner,
        "_run_pty",
        lambda self, envelope: (
            self.output_callback(stream + "\n"),
            subprocess.CompletedProcess(args=["claude"], returncode=0, stdout=stream, stderr=""),
        )[1],
    )
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

    assert result.summary == "ready"
    assert any('"thinking": "Considering one route."' in item for item in seen)


def test_claude_runner_formats_thinking_and_actions_from_stream_json() -> None:
    seen: list[str] = []
    runner = ClaudeRunner(command=["claude"])
    runner._real_output_callback = seen.append

    runner._on_raw_output(
        "\n".join(
            [
                json.dumps({"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "thinking"}}}),
                json.dumps({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "First part. "}}}),
                json.dumps({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "Second part."}}}),
                json.dumps({"type": "stream_event", "event": {"type": "content_block_stop"}}),
                json.dumps({"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "tool_use", "name": "StructuredOutput"}}}),
            ]
        )
        + "\n"
    )

    assert any('"thinking": "First part. Second part."' in item for item in seen)
    assert any('"action": "StructuredOutput"' in item for item in seen)


def test_claude_runner_uses_result_structured_output_from_stream_json(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = "\n".join(
        [
            json.dumps(
                {
                    "type": "stream_event",
                    "event": {
                        "type": "content_block_start",
                        "content_block": {"type": "thinking"},
                    },
                }
            ),
            json.dumps(
                {
                    "type": "stream_event",
                    "event": {
                        "type": "content_block_delta",
                        "delta": {"type": "thinking_delta", "thinking": "Considering two angles."},
                    },
                }
            ),
            json.dumps({"type": "stream_event", "event": {"type": "content_block_stop"}}),
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "structured_output": {"summary": "ready"},
                }
            ),
        ]
    )

    monkeypatch.setattr(
        ClaudeRunner,
        "_run_pty",
        lambda self, envelope: subprocess.CompletedProcess(
            args=["claude"],
            returncode=0,
            stdout=stream,
            stderr="",
        ),
    )

    runner = ClaudeRunner(command=["claude"])
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

    assert result.summary == "ready"
    assert result.structured_output == {"summary": "ready"}
