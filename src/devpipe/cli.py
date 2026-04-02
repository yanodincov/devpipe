"""devpipe CLI entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from devpipe.app import build_default_app
from devpipe.completion import install_shell_completion
from devpipe.engines import discover_available_engines, load_runner_runtime_config
from devpipe.output_formatter import build_exec_error_response, build_exec_json_response
from devpipe.profiles.loader import find_project_root
from devpipe.profiles.validator import validate_profile, validate_all_profiles
from devpipe.run_request import load_exec_request
from devpipe.ui.app import DevpipeTextualApp


def main(argv: list[str] | None = None) -> int:
    """Launch TUI or execute CLI subcommands."""
    args = list(sys.argv[1:] if argv is None else argv)

    if args and args[0] == "validate":
        return validate_command(args[1:])
    if args and args[0] == "doctor":
        return doctor_command(args[1:])
    if args and args[0] == "install-completion":
        return install_completion_command(args[1:])
    if args and args[0] == "list-engines":
        return list_engines_command(args[1:])
    if args and args[0] == "exec":
        return exec_command(args[1:])

    show_prompt = "--show-prompt" in args or "--with-thinking" in args
    project_root = find_project_root() or Path.cwd()
    app = DevpipeTextualApp(project_root=project_root, show_prompt=show_prompt)
    app.run()
    return 0


def exec_command(argv: list[str]) -> int:
    """Run pipeline in non-interactive mode."""
    parser = argparse.ArgumentParser(prog="devpipe exec")
    parser.add_argument("--pipe-file")
    parser.add_argument("--profile")
    parser.add_argument("--task")
    parser.add_argument("--task-id")
    parser.add_argument("--runner")
    parser.add_argument("--model")
    parser.add_argument("--effort")
    parser.add_argument("--tags")
    parser.add_argument("--start-agent")
    parser.add_argument("--stop-agent")
    parser.add_argument("--topic")
    parser.add_argument("--with-thinking", action="store_true")
    ns = parser.parse_args(argv)

    overrides = {
        "profile": ns.profile,
        "task": ns.task,
        "task_id": ns.task_id,
        "runner": ns.runner,
        "model": ns.model,
        "effort": ns.effort,
        "tags": [item.strip() for item in ns.tags.split(",") if item.strip()] if ns.tags else None,
        "start_agent": ns.start_agent,
        "stop_agent": ns.stop_agent,
        "topic": ns.topic,
        "with_thinking": ns.with_thinking,
    }
    request = load_exec_request(ns.pipe_file, overrides)
    config = request.to_run_config()

    project_root = find_project_root() or Path.cwd()
    bundle_root = Path(__file__).resolve().parents[2]
    app = build_default_app(bundle_root, show_prompt=request.with_thinking)
    if request.with_thinking:
        _attach_jsonl_output_callbacks(app.runners)

    try:
        state = app.run(
            config,
            on_stage_start=_emit_stage_start if request.with_thinking else None,
            on_stage_complete=_emit_stage_complete if request.with_thinking else None,
        )
    except Exception as exc:
        print(json.dumps(build_exec_error_response(exc), ensure_ascii=False))
        return 1

    history_dir = project_root / ".devpipe" / "history"
    print(json.dumps(build_exec_json_response(state, request, history_dir), ensure_ascii=False))
    return 0 if state.status == "completed" else 1


def _attach_jsonl_output_callbacks(runners) -> None:
    """Wire runner output to stdout for JSONL thinking mode."""
    for runner in runners.values():
        if hasattr(runner, "output_callback"):
            runner.output_callback = _stdout_chunk


def _stdout_chunk(text: str) -> None:
    if not text:
        return
    sys.stdout.write(text)
    sys.stdout.flush()


def _emit_stage_start(stage: str, runner: str, model: str, effort: str) -> None:
    payload = {
        "type": "stage_started",
        "stage": stage,
        "runner": runner,
        "model": model,
        "effort": effort,
    }
    print(json.dumps(payload, ensure_ascii=False))


def _emit_stage_complete(stage: str, output: dict, tokens: int = 0) -> None:
    payload = {
        "type": "stage_completed",
        "stage": stage,
        "tokens": tokens,
        "output": output,
    }
    print(json.dumps(payload, ensure_ascii=False))


def validate_command(args: list[str] | None) -> int:
    """Validate profiles and print results."""
    project_root = find_project_root() or Path.cwd()

    if args:
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


def list_engines_command(args: list[str] | None = None) -> int:
    del args
    project_root = find_project_root() or Path.cwd()
    runner_config = load_runner_runtime_config(project_root=project_root).get("runners", {})
    for engine in discover_available_engines(runner_config):
        print(engine)
    return 0


def doctor_command(args: list[str] | None = None) -> int:
    del args
    project_root = find_project_root() or Path.cwd()
    runner_config = load_runner_runtime_config(project_root=project_root).get("runners", {})
    available = discover_available_engines(runner_config)
    if not available:
        print("No available AI engines found. Install codex or claude.")
        return 1
    print("Available AI engines: " + ", ".join(available))
    return 0


def install_completion_command(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="devpipe install-completion")
    parser.add_argument("shell", choices=("zsh", "bash"))
    ns = parser.parse_args(argv)
    target = install_shell_completion(ns.shell)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
