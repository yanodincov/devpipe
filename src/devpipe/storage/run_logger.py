from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from devpipe.runtime.events import Event
from devpipe.runtime.state import PipelineState


class RunLogger:
    def __init__(self, runs_dir: str | Path, run_id: str) -> None:
        self.run_dir = Path(runs_dir) / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.run_dir / "events.jsonl"
        self.summary_path = self.run_dir / "summary.json"
        self.logs_dir = self.run_dir / "logs"
        self.logs_dir.mkdir(exist_ok=True)

    def log_event(self, event: Event) -> None:
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "event_type": event.event_type.value,
                        "stage": event.stage,
                        "summary": event.summary,
                        "error_message": event.error_message,
                        "payload": event.payload,
                    }
                )
                + "\n"
            )

    def log_stage_transcript(self, stage: str, transcript: str) -> Path:
        path = self.logs_dir / f"{stage}.log"
        path.write_text(transcript, encoding="utf-8")
        return path

    def log_stage_failure(self, stage: str, payload: dict[str, Any]) -> Path:
        path = self.logs_dir / f"{stage}.error.log"
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def write_summary(self, state: PipelineState) -> None:
        self.summary_path.write_text(
            json.dumps(
                {
                    "run_id": state.run_id,
                    "task_id": state.task_id,
                    "status": state.status,
                    "current_stage": state.current_stage,
                    "release_context": state.release_context,
                    "last_error": state.last_error,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
