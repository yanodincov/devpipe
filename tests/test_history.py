from __future__ import annotations

from types import SimpleNamespace

from devpipe import history


def test_finish_run_marks_latest_matching_entry(tmp_path, monkeypatch) -> None:
    history_path = tmp_path / "history.yaml"
    monkeypatch.setattr(history, "HISTORY_PATH", history_path)
    monkeypatch.setattr(history, "_now_iso", lambda: "2026-03-28 10:00:00")

    config = SimpleNamespace(
        task="Build feature X",
        task_id="MRC-1",
        runner="codex",
        model="auto",
        effort="auto",
        target_branch="main",
        service="acquiring",
        namespace="u1",
        tags=["go"],
        tag_roles={},
        extra_params={},
        first_role="architect",
        last_role="qa_stand",
    )

    history.save_run(config)
    monkeypatch.setattr(history, "_now_iso", lambda: "2026-03-28 10:05:00")
    history.finish_run(config)

    entries = history.load_history()

    assert entries[0]["date"] == "2026-03-28 10:00:00"
    assert entries[0]["finished_at"] == "2026-03-28 10:05:00"
