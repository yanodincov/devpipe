from __future__ import annotations

from devpipe.profiles.agent import TaskEnvelope
from devpipe.runners.base import BaseCliRunner


class ClaudeRunner(BaseCliRunner):
    def __init__(self, command: list[str] | None = None, **kwargs) -> None:
        super().__init__(command=command or ["claude"], **kwargs)

    def _get_command_and_input(self, envelope: TaskEnvelope) -> tuple[list[str], str]:
        command = self.command + [
            "--model", envelope.model_name,
            "--effort", envelope.effort,
        ]
        return command, self.build_prompt(envelope)
