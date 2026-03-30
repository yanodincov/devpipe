from __future__ import annotations

import json
import time

from devpipe.profiles.agent import TaskEnvelope, TaskResult

_STUBS: dict[str, dict] = {
    "architect": {
        "summary": "[mock] stub architect output",
        "decisions": ["mock decision"],
        "plan": ["mock step 1", "mock step 2"],
        "risks": [],
        "open_questions": [],
    },
    "developer": {
        "summary": "[mock] stub developer output",
        "changed_files": ["mock/file.go"],
        "implementation_notes": ["mock note"],
        "qa_focus": [],
    },
    "test_developer": {
        "summary": "[mock] stub test_developer output",
        "tests": ["mock_test.go"],
        "covered_files": [],
        "verification_commands": [],
    },
    "qa_local": {
        "summary": "[mock] stub qa_local output",
        "verdict": "pass",
        "checks": ["mock check"],
        "acceptance_signals": [],
        "gaps": [],
    },
    "release": {
        "summary": "[mock] stub release output",
        "release_notes": ["mock release"],
        "deploy_branch": "mock-branch",
        "namespace": "mock-ns",
        "pod_name": "mock-pod",
    },
    "qa_stand": {
        "summary": "[mock] stub qa_stand output",
        "verdict": "pass",
        "signals": [],
        "anomalies": [],
    },
}


class MockRunner:
    """Instantly returns stub JSON for each role — for pipeline integration testing."""

    def run(self, envelope: TaskEnvelope) -> TaskResult:
        time.sleep(5)
        stub = _STUBS.get(envelope.role, {"summary": "[mock] unknown role"})
        return TaskResult(
            ok=True,
            summary=stub.get("summary", ""),
            structured_output=stub,
            transcript=json.dumps(stub),
        )
