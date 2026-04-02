from __future__ import annotations

from pathlib import Path
from typing import Any

from devpipe.history import load_run_details
from devpipe.run_request import ExecRequest
from devpipe.runtime.state import PipelineState


def build_exec_json_response(
    state: PipelineState,
    request: ExecRequest,
    history_dir: Path,
) -> dict[str, Any]:
    """Build machine-readable exec response."""
    details = load_run_details(history_dir, state.run_id)
    final_output = None
    if details is not None and details.stages:
        final_output = details.stages[-1].output or None
    if final_output is None:
        stage_outputs = state.artifacts.get("stage_outputs", {})
        if isinstance(stage_outputs, dict) and stage_outputs:
            final_output = next(reversed(stage_outputs.values()))

    return {
        "run_id": state.run_id,
        "status": state.status,
        "profile": request.profile,
        "final": final_output,
        "summary": details.summary if details is not None else {},
        "history": {
            "config_path": str(history_dir / f"{state.run_id}.devpipe.yaml"),
            "details_path": str(history_dir / f"{state.run_id}.devpipe.json"),
        },
    }


def build_exec_error_response(error: Exception, run_id: str | None = None) -> dict[str, Any]:
    """Build machine-readable failure payload."""
    payload: dict[str, Any] = {
        "status": "failed",
        "error": {
            "type": error.__class__.__name__,
            "message": str(error),
        },
    }
    if run_id is not None:
        payload["run_id"] = run_id
    return payload
