"""devpipe CLI — TUI-only entry point.

The devpipe application is now exclusively a TUI (Textual) application.
Simply run `devpipe` or `mise run` to launch the interactive interface.
"""

from __future__ import annotations

import sys
from pathlib import Path

from devpipe.profiles.loader import find_project_root
from devpipe.ui.app import DevpipeTextualApp


def main() -> int:
    """Launch the devpipe Textual TUI."""
    # Try to find project root with .devpipe/, fallback to cwd for global profiles
    project_root = find_project_root() or Path.cwd()
    app = DevpipeTextualApp(project_root=project_root)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
