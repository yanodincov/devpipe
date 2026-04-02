from __future__ import annotations

from pathlib import Path

from devpipe.resource_loader import load_resource_text


def install_shell_completion(shell: str, *, home_dir: Path | None = None) -> Path:
    home = home_dir or Path.home()
    if shell == "zsh":
        target = home / ".zsh" / "completions" / "_devpipe"
        content = load_resource_text("completions/_devpipe")
    elif shell == "bash":
        target = home / ".local" / "share" / "bash-completion" / "completions" / "devpipe"
        content = load_resource_text("completions/devpipe.bash")
    else:
        raise ValueError(f"Unsupported shell '{shell}'")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target
