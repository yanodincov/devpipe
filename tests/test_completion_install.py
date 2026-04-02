from __future__ import annotations

from pathlib import Path

from devpipe.completion import install_shell_completion


def test_install_shell_completion_writes_zsh_file(tmp_path: Path) -> None:
    home_dir = tmp_path / "home"
    installed_path = install_shell_completion("zsh", home_dir=home_dir)

    assert installed_path == home_dir / ".zsh" / "completions" / "_devpipe"
    assert installed_path.exists()
    assert "_arguments" in installed_path.read_text(encoding="utf-8")
