"""devpipe CLI — TUI-only entry point.

The devpipe application is now exclusively a TUI (Textual) application.
Simply run `devpipe` or `mise run` to launch the interactive interface.

Subcommands:
    devpipe          Launch TUI
    devpipe validate [profile...]  Validate profiles
"""

from __future__ import annotations

import sys
from pathlib import Path

from devpipe.profiles.loader import find_project_root
from devpipe.profiles.validator import validate_profile, validate_all_profiles, format_validation_errors
from devpipe.ui.app import DevpipeTextualApp


def main() -> int:
    """Launch the devpipe Textual TUI or run subcommands."""
    args = sys.argv[1:]
    
    if args and args[0] == "validate":
        return validate_command(args[1:])
    
    # Default: launch TUI
    show_prompt = "--show-prompt" in args
    project_root = find_project_root() or Path.cwd()
    app = DevpipeTextualApp(project_root=project_root, show_prompt=show_prompt)
    app.run()
    return 0


def validate_command(args: list[str] | None) -> int:
    """Validate profiles and print results."""
    project_root = find_project_root() or Path.cwd()
    
    if args:
        # Validate specific profile(s)
        profiles_dir = project_root / ".devpipe" / "profiles"
        all_valid = True
        for profile_name in args:
            profile_dir = profiles_dir / profile_name
            if not profile_dir.exists():
                print(f"Profile '{profile_name}' not found")
                all_valid = False
                continue
            
            result = validate_profile(profile_dir)
            if result.valid:
                print(f"✓ {profile_name}: valid")
                for warning in result.warnings:
                    print(f"  ⚠ {warning}")
            else:
                print(f"✗ {profile_name}: invalid")
                for error in result.errors:
                    print(f"  ✗ {error.path}: {error.message}")
                all_valid = False
        
        return 0 if all_valid else 1
    
    # Validate all profiles
    results = validate_all_profiles(project_root)
    
    if not results:
        print("No profiles found in .devpipe/profiles/")
        return 0
    
    all_valid = True
    for profile_name, result in sorted(results.items()):
        if result.valid:
            print(f"✓ {profile_name}: valid")
            for warning in result.warnings:
                print(f"  ⚠ {warning}")
        else:
            print(f"✗ {profile_name}: invalid")
            for error in result.errors:
                print(f"  ✗ {error.path}: {error.message}")
            all_valid = False
    
    return 0 if all_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())