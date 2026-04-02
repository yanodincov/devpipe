from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_zsh_completion_covers_exec_flags() -> None:
    content = (ROOT / "completions" / "_devpipe").read_text(encoding="utf-8")

    assert "--pipe-file" in content
    assert ".devpipe.yaml" in content
    assert "--with-thinking" in content
    assert "--runner" in content
    assert "list-engines" in content
    assert "--profile" in content


def test_bash_completion_covers_exec_flags() -> None:
    content = (ROOT / "completions" / "devpipe.bash").read_text(encoding="utf-8")

    assert "--pipe-file" in content
    assert ".devpipe.yaml" in content
    assert "--with-thinking" in content
    assert "--runner" in content
    assert "--profile" in content
