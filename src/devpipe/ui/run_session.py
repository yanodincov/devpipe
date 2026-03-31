"""Bridge between Textual UI and OrchestratorApp.run().

Wraps the runtime execution and converts callbacks into typed UI messages
suitable for the Textual message loop.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from devpipe.app import OrchestratorApp, RunConfig
from devpipe.runtime.state import PipelineState

_ANSI_RE = re.compile(r"\x1b\[[0-9;:<>?=]*[ -/]*[@-~]")
_BLANK_RUN_RE = re.compile(r"\n{3,}")


@dataclass
class RunEvent:
    """Normalized event emitted during a pipeline run."""
    kind: str  # stage_started, stage_completed, stage_failed, output, run_finished
    stage: str = ""
    runner: str = ""
    model: str = ""
    effort: str = ""
    summary: str = ""
    error: str = ""
    output_text: str = ""
    status: str = ""
    run_id: str = ""
    structured_output: dict[str, Any] | None = None
    tokens: int = 0


def sanitize_output_text(text: str) -> str:
    """Convert runner output into clean plain text for the Textual log."""
    plain = _ANSI_RE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    plain = _BLANK_RUN_RE.sub("\n\n", plain)
    return plain.strip("\n")


class RunSession:
    """Wraps OrchestratorApp.run() and emits normalized RunEvents."""

    def __init__(self, app: OrchestratorApp) -> None:
        self._app = app
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        self._app.cancel_active_runs()

    def execute(
        self,
        config: RunConfig,
        on_event: Callable[[RunEvent], None],
    ) -> PipelineState:
        """Run the pipeline synchronously, dispatching RunEvents."""

        def on_stage_start(stage: str, runner: str, model: str, effort: str) -> None:
            on_event(RunEvent(
                kind="stage_started",
                stage=stage,
                runner=runner,
                model=model,
                effort=effort,
            ))

        def on_stage_complete(stage: str, output: dict, tokens: int = 0) -> None:
            on_event(RunEvent(
                kind="stage_completed",
                stage=stage,
                summary=output.get("summary", ""),
                structured_output=output,
                tokens=tokens,
            ))

        # Wire output callback to runners
        def on_output(text: str) -> None:
            if self._cancelled:
                return
            cleaned = sanitize_output_text(text)
            if cleaned:
                on_event(RunEvent(kind="output", output_text=cleaned))

        for runner in self._app.runners.values():
            if hasattr(runner, "output_callback"):
                runner.output_callback = on_output  # type: ignore[union-attr]

        try:
            state = self._app.run(
                config,
                on_stage_start=on_stage_start,
                on_stage_complete=on_stage_complete,
            )
        except Exception as exc:
            on_event(RunEvent(
                kind="run_finished",
                status="failed",
                error=str(exc),
            ))
            raise

        on_event(RunEvent(
            kind="run_finished",
            status=state.status,
            run_id=state.run_id,
        ))
        return state
