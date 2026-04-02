from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from devpipe.profiles.agent import TaskResult
from devpipe.profiles.stages import CommandResultMode, CommandSpec, StageSpec
from devpipe.runners.base import CommandFailedError, InvalidRunnerOutputError


class CommandRunner:
    """Runner for command-only stages."""

    def run(self, stage: StageSpec, *, project_root: str | Path | None = None) -> TaskResult:
        if stage.command is None:
            raise ValueError("cmd stage requires command configuration")

        command = stage.command
        completed = subprocess.run(
            command.exec,
            capture_output=True,
            text=True,
            cwd=self._resolve_cwd(command, project_root),
            env=self._resolve_env(command),
            timeout=command.timeout,
            check=False,
        )

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        transcript = self._build_transcript(command, completed.returncode, stdout, stderr)

        if completed.returncode != 0:
            raise CommandFailedError(stderr.strip() or stdout.strip() or f"command exited with code {completed.returncode}")

        structured_output = self._build_output(command, completed.returncode, stdout, stderr)
        summary = str(structured_output.get("summary", "")).strip() or f"{stage.name} ok"
        return TaskResult(
            ok=True,
            summary=summary,
            structured_output=structured_output,
            transcript=transcript,
            tokens=0,
        )

    @staticmethod
    def _resolve_env(command: CommandSpec) -> dict[str, str]:
        env = os.environ.copy()
        env.update(command.env)
        return env

    @staticmethod
    def _resolve_cwd(command: CommandSpec, project_root: str | Path | None) -> str | None:
        if command.cwd is None:
            return None
        if command.cwd == "project_root":
            return str(project_root) if project_root is not None else None
        if project_root is None:
            return command.cwd
        return str((Path(project_root) / command.cwd).resolve())

    @staticmethod
    def _build_transcript(command: CommandSpec, exit_code: int, stdout: str, stderr: str) -> str:
        return (
            f"Command: {command.exec}\n"
            f"Exit code: {exit_code}\n"
            f"Stdout:\n{stdout}\n"
            f"Stderr:\n{stderr}\n"
        )

    @staticmethod
    def _pick_source(command: CommandSpec, stdout: str, stderr: str) -> str:
        return stdout if command.result.source == "stdout" else stderr

    def _build_output(self, command: CommandSpec, exit_code: int, stdout: str, stderr: str) -> dict[str, object]:
        source_text = self._pick_source(command, stdout, stderr)
        if command.result.mode == CommandResultMode.SCHEMA:
            if command.parse.value != "json":
                raise InvalidRunnerOutputError("schema mode requires parse=json")
            try:
                payload = json.loads(source_text or "{}")
            except json.JSONDecodeError as exc:
                raise InvalidRunnerOutputError(f"invalid JSON command output: {exc}") from exc
            if not isinstance(payload, dict):
                raise InvalidRunnerOutputError("structured command output must be a JSON object")
            return payload

        summary = source_text.strip() or stdout.strip() or stderr.strip() or "command completed"
        return {
            "summary": summary,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
        }
