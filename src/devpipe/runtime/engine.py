from __future__ import annotations

from copy import deepcopy

from devpipe.runtime.events import Event, EventType
from devpipe.runtime.retry import RetryPolicy
from devpipe.runtime.transitions import first_stage, next_stage, should_retry_stage
from devpipe.runtime.state import PipelineState


class PipelineEngine:
    def __init__(
        self,
        retry_policy: RetryPolicy | None = None,
        get_first_stage: "Callable[[], str] | None" = None,
        get_next_stage: "Callable[[str], str] | None" = None,
    ) -> None:
        self.retry_policy = retry_policy or RetryPolicy.default()
        self.get_first_stage = get_first_stage or (lambda: first_stage())
        self.get_next_stage = get_next_stage or (lambda current: next_stage(current))

    def apply(self, state: PipelineState, event: Event) -> PipelineState:
        new_state = deepcopy(state)
        new_state.artifacts.setdefault("events", []).append(
            {"event_type": event.event_type.value, "stage": event.stage, "summary": event.summary, "error_message": event.error_message}
        )

        if event.event_type == EventType.RUN_STARTED:
            new_state.status = "running"
            new_state.current_stage = self.get_first_stage()
            return new_state

        if event.event_type == EventType.STAGE_COMPLETED:
            if event.stage:
                new_state.artifacts.setdefault("stage_summaries", {})[event.stage] = event.summary
            upcoming = self.get_next_stage(event.stage or new_state.current_stage)
            if upcoming == "completed":
                new_state.status = "completed"
                new_state.current_stage = "completed"
            else:
                new_state.status = "running"
                new_state.current_stage = upcoming
            new_state.last_error = None
            return new_state

        if event.event_type == EventType.STAGE_FAILED:
            stage = event.stage or new_state.current_stage
            attempts = new_state.attempt_counters.get(stage, 0) + 1
            new_state.attempt_counters[stage] = attempts
            new_state.last_error = event.error_message
            if should_retry_stage(stage, attempts - 1, self.retry_policy):
                new_state.status = "retrying"
                new_state.current_stage = stage
            else:
                new_state.status = "failed"
                new_state.current_stage = stage
            return new_state

        return new_state
