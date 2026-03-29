"""Allow running `python -m devpipe` to launch the TUI."""
from devpipe.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
