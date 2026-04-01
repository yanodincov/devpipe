from __future__ import annotations

import json
import os

from devpipe.profiles.agent import TaskEnvelope, TaskResult
from devpipe.parser_legacy import OutputParseError, OutputParser
from devpipe.runners.base import (
    BaseCliRunner,
    CommandFailedError,
    InvalidRunnerOutputError,
)


class CodexRunner(BaseCliRunner):
    """Runner for the OpenAI Codex CLI.

    Uses `codex exec --json` so the process exits cleanly after the task.
    PTY is kept on stdout so codex uses line-buffered I/O and JSONL events
    stream in real-time instead of arriving all at once when the process exits.
    JSONL events are intercepted, formatted, and forwarded to output_callback.
    Final structured output is read from --output-last-message (clean JSON).
    Uses --output-schema for API-level JSON schema validation; schema is
    transformed to add additionalProperties:false recursively (OpenAI requirement).
    """

    def __init__(self, command: list[str] | None = None, **kwargs) -> None:
        kwargs.setdefault("use_pty", True)
        kwargs.setdefault("forward_to_tty", False)
        super().__init__(command=command or ["codex"], **kwargs)
        self._jsonl_buf = ""
        self._real_output_callback = None
        self._output_file: str | None = None
        self._last_agent_message = ""  # fallback if --output-last-message is empty
        self._tokens: int = 0

    # ── schema transformation ─────────────────────────────────────────────────

    @staticmethod
    def _make_strict_schema(schema: dict) -> dict:
        """Transform schema to comply with OpenAI structured output requirements.

        - additionalProperties: false on every object
        - all properties listed in required (strict mode mandates it)
        Applied recursively to nested objects and array items.
        """
        if not isinstance(schema, dict):
            return schema
        result = dict(schema)
        if result.get("type") == "object":
            result["additionalProperties"] = False
            if "properties" in result:
                result["properties"] = {
                    k: CodexRunner._make_strict_schema(v)
                    for k, v in result["properties"].items()
                }
                # all property keys must appear in required
                all_keys = list(result["properties"].keys())
                existing = list(result.get("required", []))
                result["required"] = existing + [k for k in all_keys if k not in existing]
        if "items" in result:
            result["items"] = CodexRunner._make_strict_schema(result["items"])
        for key in ("anyOf", "oneOf", "allOf"):
            if key in result:
                result[key] = [CodexRunner._make_strict_schema(s) for s in result[key]]
        return result

    # ── JSONL event formatting ────────────────────────────────────────────────

    # Commands that are pure file-reading noise from codex context loading
    _BORING_CMD_PREFIXES = (
        "printf ", "echo ", "sed ", "awk ", "for f in ", "for file in ",
        "while ", "true", "false", "read ", "cat ", "head ", "tail ",
        "ls ", "find ", "wc ", "sort ",
    )

    @classmethod
    def _is_boring_cmd(cls, cmd: str) -> bool:
        c = cmd.strip()
        return any(c.startswith(p) for p in cls._BORING_CMD_PREFIXES) or c in ("true", "false")

    @classmethod
    def _format_agent_message(cls, text: str) -> str:
        """Format an agent_message as a structured UI payload."""
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return json.dumps({"thinking": text}, ensure_ascii=False)

        summary = data.get("summary")
        if summary:
            return json.dumps({"thinking": summary}, ensure_ascii=False)
        # No summary — show raw text as thinking
        return json.dumps({"thinking": text}, ensure_ascii=False)

    def _format_event(self, event: dict) -> str | None:
        etype = event.get("type", "")
        item = event.get("item", {})
        itype = item.get("type", "")

        if etype == "item.completed" and itype == "agent_message":
            text = item.get("text", "").strip()
            return self._format_agent_message(text) if text else None

        # skip item.started for commands — we show everything on item.completed
        if etype == "item.started" and itype == "command_execution":
            return None

        if etype == "item.completed" and itype == "command_execution":
            cmd = item.get("command", "")
            for prefix in ("/bin/zsh -lc ", "/bin/bash -lc ", "bash -c "):
                if cmd.startswith(prefix):
                    cmd = cmd[len(prefix):].strip("\"'")
                    break

            exit_code = item.get("exit_code")
            is_printf = cmd.lstrip().startswith("printf ")
            is_boring = self._is_boring_cmd(cmd)

            if exit_code is not None and exit_code != 0:
                payload: dict[str, object] = {"action": cmd[:80] + ("…" if len(cmd) > 80 else "")}
                payload["status"] = "failed"
                payload["exit_code"] = exit_code
            else:
                payload = {"action": cmd}

            output = item.get("aggregated_output", "").rstrip("\n")
            if is_boring and exit_code in (None, 0) and not is_printf:
                return None
            if not output:
                return json.dumps(payload, ensure_ascii=False)

            if is_printf:
                return json.dumps({"output": output}, ensure_ascii=False)

            # skip trivially boring commands with no interesting output
            if cmd.strip() in ("true", "false", "") and not output:
                return None
            if cmd.strip() in ("true", "false"):
                return None

            out_lines = output.splitlines()
            payload["result"] = out_lines if len(out_lines) > 1 else out_lines[0]
            return json.dumps(payload, ensure_ascii=False)

        if etype == "turn.completed":
            usage = event.get("usage", {})
            if isinstance(usage, dict):
                self._tokens += (
                    usage.get("input_tokens", 0)
                    + usage.get("output_tokens", 0)
                    + usage.get("cached_input_tokens", 0)
                )
            return None

        return None  # skip other events

    # ── output_callback wrapper ───────────────────────────────────────────────

    def _on_raw_output(self, text: str) -> None:
        """Intercept raw PTY output, parse JSONL lines, forward formatted text."""
        # heartbeat (empty string) — just forward to keep spinner alive
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
                if isinstance(event, dict) and "prompt" in event:
                    if self._real_output_callback:
                        self._real_output_callback(json.dumps(event, ensure_ascii=False) + "\n")
                    continue
                # log all events for debugging (useful when --output-schema changes event types)
                with open("/tmp/devpipe_events.jsonl", "a", errors="replace") as _ef:
                    _ef.write(line + "\n")
                # capture text from any completed item as transcript fallback;
                # with --output-schema the final answer may not be an agent_message
                if event.get("type") == "item.completed":
                    item = event.get("item", {})
                    txt = item.get("text", "") or item.get("content", "") or item.get("output", "")
                    if txt:
                        self._last_agent_message = txt
                formatted = self._format_event(event)
                if formatted and self._real_output_callback:
                    self._real_output_callback(formatted + "\n")
            except json.JSONDecodeError:
                # not a JSON line — output as-is (shouldn't happen with --json)
                if self._real_output_callback:
                    self._real_output_callback(line + "\n")

    # ── run ───────────────────────────────────────────────────────────────────

    def _get_command_and_input(self, envelope: TaskEnvelope) -> tuple[list[str], str]:
        prompt = self.build_prompt(envelope)
        self._output_file = f"/tmp/devpipe_output_{envelope.role}.txt"
        schema_file = f"/tmp/devpipe_schema_{envelope.role}.json"

        for path in (self._output_file, schema_file):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

        strict_schema = self._make_strict_schema(envelope.output_schema)
        with open(schema_file, "w") as f:
            json.dump(strict_schema, f)

        command = self.command + [
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "-m", envelope.model_name,
            "-c", f'model_reasoning_effort="{envelope.effort}"',
            "--output-last-message", self._output_file,
            "--output-schema", schema_file,
            "--json",
            prompt,
        ]
        return command, ""  # empty stdin — exec mode doesn't need it

    def run(self, envelope: TaskEnvelope) -> TaskResult:
        # Wrap output_callback to parse JSONL before displaying
        self._jsonl_buf = ""
        self._last_agent_message = ""
        self._tokens = 0
        self._real_output_callback = self.output_callback
        self.output_callback = self._on_raw_output
        self._emit_prompt(self.build_prompt(envelope))
        # clear event log for this stage
        try:
            os.remove("/tmp/devpipe_events.jsonl")
        except FileNotFoundError:
            pass

        try:
            completed = self._run_pty(envelope)
        finally:
            self.output_callback = self._real_output_callback

        # Non-zero exit is fatal only if stderr is not just a codex warning
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            _warnings = ("no last agent message", "wrote empty content", "no agent message")
            is_warning = any(w in stderr for w in _warnings)
            if not is_warning:
                raise CommandFailedError(stderr or f"codex exited with code {completed.returncode}")

        # Priority: --output-last-message file → last agent_message from stream → raw stdout
        transcript = ""
        if self._output_file and os.path.exists(self._output_file):
            with open(self._output_file, errors="replace") as f:
                transcript = f.read().strip()
        if not transcript:
            transcript = self._last_agent_message
        if not transcript:
            transcript = completed.stdout

        with open("/tmp/devpipe_transcript.txt", "w", errors="replace") as f:
            f.write(transcript)

        parser = OutputParser(envelope.output_schema)
        try:
            structured_output = parser.parse(transcript)
        except OutputParseError as exc:
            with open("/tmp/devpipe_parse_error.txt", "w", errors="replace") as f:
                f.write(
                    f"role: {envelope.role}\nerror: {exc}\n\n"
                    f"--- transcript ---\n{transcript}\n\n"
                    f"--- raw stdout (last 200 lines) ---\n"
                    + "\n".join(completed.stdout.splitlines()[-200:])
                )
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

    def _run_pty(self, envelope: TaskEnvelope):
        """Delegate to BaseCliRunner.run() using PTY."""
        from devpipe.runners.base import _run_with_pty
        import subprocess
        import time

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
        except subprocess.TimeoutExpired as exc:
            from devpipe.runners.base import RunnerTimeoutError
            raise RunnerTimeoutError(str(exc)) from exc
