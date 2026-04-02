from __future__ import annotations

from pathlib import Path

import pytest

from devpipe.app import build_default_app
from devpipe.engines import discover_available_engines, resolve_engine_choice
from devpipe.project_config import load_project_config


def test_load_project_config_merges_global_and_local_and_exposes_engines(tmp_path: Path) -> None:
    home_dir = tmp_path / "home"
    project_root = tmp_path / "project"
    (home_dir / ".devpipe").mkdir(parents=True)
    (project_root / ".devpipe").mkdir(parents=True)

    (home_dir / ".devpipe" / "config.yaml").write_text(
        """
defaults:
  runner: auto
engines:
  codex:
    model:
      low: gpt-5.4-mini
      middle: gpt-5.3-codex
      high: gpt-5.4
    effort:
      low: low
      middle: medium
      high: high
      extra: xhigh
""".strip(),
        encoding="utf-8",
    )
    (project_root / ".devpipe" / "config.yaml").write_text(
        """
defaults:
  profile: delivery
available:
  namespace:
    - u1
""".strip(),
        encoding="utf-8",
    )

    cfg = load_project_config(project_root, home_dir=home_dir)

    assert cfg.default("runner") == "auto"
    assert cfg.default("profile") == "delivery"
    assert cfg.available_list("namespace") == ["u1"]
    assert cfg.engines["codex"]["model"]["low"] == "gpt-5.4-mini"


def test_discover_available_engines_filters_missing_binaries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_which(binary: str) -> str | None:
        calls.append(binary)
        return "/usr/bin/codex" if binary == "codex" else None

    monkeypatch.setattr("devpipe.engines.shutil.which", fake_which)

    available = discover_available_engines(
        {
            "codex": {"command": ["codex"]},
            "claude": {"command": ["claude"]},
        }
    )

    assert available == ["codex"]
    assert calls == ["codex", "claude"]


def test_resolve_engine_choice_falls_back_from_stage_default() -> None:
    chosen = resolve_engine_choice(
        requested_runner="auto",
        stage_default_engine="claude",
        available_engines=["codex"],
    )

    assert chosen == "codex"


def test_build_default_app_only_registers_available_engines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "devpipe.engines.shutil.which",
        lambda binary: "/usr/bin/codex" if binary == "codex" else None,
    )

    app = build_default_app(Path.cwd())

    assert list(app.runners.keys()) == ["codex"]
