from __future__ import annotations

from importlib.resources import files
from pathlib import Path


def load_resource_text(relative_path: str) -> str:
    resource = files("devpipe.resources").joinpath(relative_path)
    return resource.read_text(encoding="utf-8")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]
