from __future__ import annotations

from datetime import datetime, timezone
import json

import yaml

from devpipe import history


def test_save_run_replay_config_writes_yaml_without_runtime_metadata(tmp_path) -> None:
    entry = history.RunReplayConfig(
        profile="idea-lab",
        config={
            "task": "test",
            "runner": "codex",
            "topic": "demo",
        },
    )

    history_dir = tmp_path / ".devpipe" / "history"
    history.save_run_replay_config("run-123", entry, history_dir)

    saved_file = history_dir / "run-123.devpipe.yaml"
    assert saved_file.exists()

    data = yaml.safe_load(saved_file.read_text(encoding="utf-8"))
    assert data == {
        "profile": "idea-lab",
        "task": "test",
        "runner": "codex",
        "topic": "demo",
    }
    assert "run_id" not in data
    assert "timestamp" not in data


def test_save_run_details_writes_json_with_runtime_metadata(tmp_path) -> None:
    entry = history.RunDetailsEntry(
        run_id="run-123",
        timestamp=datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc),
        summary={"final_status": "completed"},
        stages=[],
    )

    history_dir = tmp_path / ".devpipe" / "history"
    history.save_run_details(entry, history_dir)

    saved_file = history_dir / "run-123.devpipe.json"
    assert saved_file.exists()

    data = json.loads(saved_file.read_text(encoding="utf-8"))
    assert data["run_id"] == "run-123"
    assert data["timestamp"] == "2026-03-31T12:00:00.000000Z"
    assert data["summary"]["final_status"] == "completed"


def test_load_run_history_combines_yaml_replay_and_json_details(tmp_path) -> None:
    history_dir = tmp_path / ".devpipe" / "history"
    history_dir.mkdir(parents=True)

    (history_dir / "2026-04-02T10-11-12.123456.devpipe.yaml").write_text(
        yaml.dump(
            {
                "profile": "idea-lab",
                "task": "test",
                "runner": "codex",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (history_dir / "2026-04-02T10-11-12.123456.devpipe.json").write_text(
        json.dumps(
            {
                "run_id": "2026-04-02T10-11-12.123456",
                "timestamp": "2026-04-02T10:11:12.123456Z",
                "summary": {
                    "final_status": "completed",
                    "total_duration_seconds": 3.2,
                    "total_tokens": 10,
                },
                "stages": [],
            }
        ),
        encoding="utf-8",
    )

    loaded = history.load_run_history(history_dir)
    assert len(loaded) == 1
    assert loaded[0].run_id == "2026-04-02T10-11-12.123456"
    assert loaded[0].profile == "idea-lab"
    assert loaded[0].config["task"] == "test"
    assert loaded[0].summary["final_status"] == "completed"
