from __future__ import annotations

import json
from typing import Any

from devpipe.profiles.agent import TaskEnvelope, TaskResult
from devpipe.parser_legacy import OutputParseError, OutputParser
from devpipe.runners.base import (
    BaseCliRunner,
    CommandFailedError,
    InvalidRunnerOutputError,
    RunnerTimeoutError,
    _run_with_pty,
)


class ClaudeRunner(BaseCliRunner):
    def __init__(self, command: list[str] | None = None, **kwargs) -> None:
        kwargs.setdefault("use_pty", True)
        kwargs.setdefault("forward_to_tty", False)
        super().__init__(command=command or ["claude"], **kwargs)
        self._jsonl_buf = ""
        self._real_output_callback = None
        self._thinking_buffer = ""
        self._result_structured_output: dict[str, Any] | None = None
        self._tokens: int = 0

    @staticmethod
    def _append_flag(command: list[str], flag: str, *values: str) -> list[str]:
        if flag in command:
            return command
        command.extend([flag, *values])
        return command

    def _get_command_and_input(self, envelope: TaskEnvelope) -> tuple[list[str], str]:
        schema = json.dumps(envelope.output_schema, separators=(",", ":"))
        prompt = self.build_prompt(envelope)
        command = list(self.command)
        self._append_flag(command, "--print")
        self._append_flag(command, "--verbose")
        self._append_flag(command, "--output-format", "stream-json")
        self._append_flag(command, "--include-partial-messages")
        self._append_flag(command, "--no-session-persistence")
        command.extend([
            "--model", envelope.model_name,
            "--effort", envelope.effort,
            "--json-schema", schema,
            prompt,
        ])
        return command, ""

    def _emit(self, payload: dict[str, str]) -> None:
        if self._real_output_callback:
            self._real_output_callback(json.dumps(payload, ensure_ascii=False) + "\n")

    def _flush_thinking(self) -> None:
        thinking = self._thinking_buffer.strip()
        if not thinking:
            return
        self._emit({"thinking": thinking})
        self._thinking_buffer = ""

    def _capture_structured_output(self, event: dict[str, Any]) -> None:
        if event.get("type") == "result":
            if isinstance(event.get("structured_output"), dict):
                self._result_structured_output = event["structured_output"]
            usage = event.get("usage", {})
            if isinstance(usage, dict):
                self._tokens = (
                    usage.get("input_tokens", 0)
                    + usage.get("output_tokens", 0)
                    + usage.get("cache_creation_input_tokens", 0)
                    + usage.get("cache_read_input_tokens", 0)
                )
            return

        if event.get("type") != "assistant":
            return
        message = event.get("message", {})
        for block in message.get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == "StructuredOutput":
                structured = block.get("input")
                if isinstance(structured, dict):
                    self._result_structured_output = structured
                    return

    def _capture_structured_output_from_stdout(self, stdout: str) -> None:
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._capture_structured_output(event)
            if self._result_structured_output is not None:
                return

    def _handle_stream_event(self, stream_event: dict[str, Any]) -> None:
        etype = stream_event.get("type")
        if etype == "content_block_start":
            block = stream_event.get("content_block", {})
            block_type = block.get("type")
            if block_type == "thinking":
                self._thinking_buffer = ""
            elif block_type == "tool_use":
                name = block.get("name")
                if name:
                    self._emit({"action": name})
            return

        if etype == "content_block_delta":
            delta = stream_event.get("delta", {})
            if delta.get("type") == "thinking_delta":
                self._thinking_buffer += delta.get("thinking", "")
            return

        if etype == "content_block_stop":
            self._flush_thinking()

    def _on_raw_output(self, text: str) -> None:
        if not text:
            if self._real_output_callback:
                self._real_output_callback("")
            return

        self._jsonl_buf += text
        while "\n" in self._jsonl_buf:
            line, self._jsonl_buf = self._jsonl_buf.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                if self._real_output_callback:
                    self._real_output_callback(line + "\n")
                continue

            self._capture_structured_output(event)

            if event.get("type") == "stream_event":
                self._handle_stream_event(event.get("event", {}))

    def _run_pty(self, envelope: TaskEnvelope):
        command, prompt = self._get_command_and_input(envelope)
        try:
            return _run_with_pty(
                command,
                input=prompt,
                timeout=self.timeout,
                env=self.env or None,
                output_callback=self.output_callback,
                forward_to_tty=self.forward_to_tty,
                stdin_callback=self.stdin_callback,
                process_callback=self._set_active_process,
            )
        except TimeoutError as exc:  # pragma: no cover - defensive
            raise RunnerTimeoutError(str(exc)) from exc
        except Exception as exc:
            if exc.__class__.__name__ == "TimeoutExpired":
                raise RunnerTimeoutError(str(exc)) from exc
            raise

    def run(self, envelope: TaskEnvelope) -> TaskResult:
        self._jsonl_buf = ""
        self._thinking_buffer = ""
        self._result_structured_output = None
        self._tokens = 0
        self._real_output_callback = self.output_callback
        self.output_callback = self._on_raw_output

        try:
            completed = self._run_pty(envelope)
        finally:
            self.output_callback = self._real_output_callback

        if completed.returncode != 0:
            raise CommandFailedError(completed.stderr or f"claude exited with code {completed.returncode}")

        structured_output = self._result_structured_output
        if structured_output is None:
            self._capture_structured_output_from_stdout(completed.stdout)
            structured_output = self._result_structured_output
        transcript = json.dumps(structured_output or {}, ensure_ascii=False)
        if structured_output is None:
            parser = OutputParser(envelope.output_schema)
            try:
                structured_output = parser.parse(completed.stdout)
                transcript = completed.stdout
            except OutputParseError as exc:
                raise InvalidRunnerOutputError(str(exc)) from exc

        return TaskResult(
            ok=True,
            summary=str(structured_output.get("summary", "")),
            structured_output=structured_output,
            artifacts={},
            next_hints=[],
            error_type=None,
            error_message=None,
            transcript=transcript,
            tokens=self._tokens,
        )
