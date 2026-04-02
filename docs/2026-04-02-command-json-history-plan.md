# Command Stages, JSON Run Mode, and Split History Plan

> Goal: add command-only stages, a machine-readable JSON execution mode, and a split run history format where `.devpipe.yaml` stores only replayable run input and `.json` stores execution details.

## Key Decisions

- Add an explicit stage type: `type: ai | cmd`.
- Require explicit `type: ai | cmd` in all pipelines.
- Keep current LLM behavior under `ai` stages only.
- Separate stage kind from model backend selection.
- Replace the current stage-level `runner` field with `default_engine`.
- `default_engine` is the final and only accepted name for AI backend selection in configs, UI labels/forms, history views, and JSON output.
- Split run history into:
  - `*.devpipe.yaml`: replay config only
  - `*.devpipe.json`: execution details, stats, outputs, attempts, errors

---

## 1. Stage Model: `type: ai | cmd`

## Why

Today `runner` is overloaded:

- it looks like the stage type;
- in reality it means the AI backend (`codex`, `claude`);
- that makes command-only stages awkward to introduce cleanly.

The fix is to separate:

- `type`: what kind of stage this is;
- `default_engine`: which AI backend executes an `ai` stage by default.

## Proposed schema

### AI stage

```yaml
stages:
  intake:
    type: ai
    default_engine: codex
    model: low
    effort: low
    agent:
      folder: intake
    out:
      summary:
        type: string
```

### Command stage

```yaml
stages:
  git_meta:
    type: cmd
    command:
      exec: ["git", "status", "--short", "--branch"]
      cwd: project_root
      env:
        LANG: C.UTF-8
      timeout: 30
      parse: text
      result:
        mode: raw
        source: stdout
    out:
      summary:
        type: string
      stdout:
        type: string
```

## Compatibility rules

- No backward compatibility layer is required.
- Existing pipelines must be migrated to explicit `type`.
- Legacy AI field `runner` should be removed from the schema.
- `cmd` stages must reject AI-only fields that do not apply.

---

## 2. Rename `runner` in AI stages

## Problem

`runner` is currently read as "stage executor type", but after introducing `type: ai | cmd` it becomes misleading.

## Final naming

The chosen field name is `default_engine`.

```yaml
type: ai
default_engine: codex
```

Final shape:

```yaml
stages:
  intake:
    type: ai
    default_engine: codex
    model: middle
    effort: middle
```

Migration behavior:

- remove `runner` from the stage schema;
- require `default_engine` for `ai` stages;
- require explicit `type` for every stage;
- update all bundled profiles, UI forms, labels, and tests in the same change.

---

## 3. Task 1: Command-only stages

## Goal

Add `type: cmd` stages that execute local commands and return structured output without calling an AI runner.

## Files to modify

- `src/devpipe/profiles/stages.py`
- `src/devpipe/profiles/loader.py`
- `src/devpipe/profiles/validator.py`
- `src/devpipe/app.py`
- `src/devpipe/ui/state.py`
- `src/devpipe/ui/actions.py`
- `src/devpipe/ui/widgets/detail_panel.py`
- `src/devpipe/ui/screens/config_screen.py`
- `tests/profiles/test_loader.py`
- `tests/profiles/test_validator.py`
- `tests/test_orchestrator_app.py`
- `tests/ui/test_state.py`
- `tests/ui/test_actions.py`
- `tests/ui/test_config_screen.py`

## Files to add

- `src/devpipe/runners/command.py`
- optionally `tests/runners/test_command_runner.py`

## Work breakdown

### 3.1. Extend stage schema

- Add `type` field to `StageSpec` with allowed values `ai`, `cmd`.
- Default `type` to `ai`.
- Add AI-only backend field: `default_engine`.
- Add `CommandSpec` models:
  - `exec`
  - `cwd`
  - `env`
  - `timeout`
  - `parse`
  - `result`
- Validate:
  - `type: ai` requires `agent`;
  - `type: ai` allows `default_engine`, `model`, `effort`;
  - `type: cmd` requires `command`;
  - `type: cmd` must reject `agent`;
  - `type: cmd` must reject `engine`, `model`, `effort` unless explicitly allowed for compatibility and ignored.

### 3.2. Update loader and validator

- Require explicit stage `type`.
- Remove support for legacy `runner`.
- Reject any stage that still uses `runner`.
- Update validation docs/messages to explain:
  - `type: ai` uses `default_engine`;
  - `type: cmd` uses `command`.
- Rename any config-facing/UI-facing references from `runner` to `default_engine` when they refer to AI backend selection at stage level.

### 3.3. Add command runner

- Implement `CommandRunner`.
- Execute `subprocess` with argv list, no shell by default.
- Collect:
  - `stdout`
  - `stderr`
  - `exit_code`
  - elapsed time
- Return `TaskResult` with:
  - `tokens = 0`
  - `transcript` built from command execution details
  - structured output according to command result mode

### 3.4. Integrate into orchestrator

- In `OrchestratorApp.run()`, branch by stage type:
  - `ai` stage: current envelope flow;
  - `cmd` stage: command execution flow.
- Preserve:
  - retries;
  - routing;
  - artifacts;
  - run logger integration;
  - history recording.

### 3.5. Result handling for `cmd`

- Support `parse: json` for JSON stdout parsing.
- Support `parse: text` for raw text capture.
- Non-zero exit code should fail the stage by default.
- Route on `out.*` exactly as for AI stages.

### 3.6. Tests

- command stage success with JSON stdout;
- command stage success with text stdout;
- command stage failure on non-zero exit;
- routing from command-stage output;
- validation failure for old pipelines that still use `runner` or omit `type`.

---

## 4. Task 2: Non-interactive execution via `devpipe exec`

## Goal

Add a dedicated non-interactive CLI entrypoint for running pipelines from terminal commands and scripts.

## Command shape

```bash
devpipe exec [flags]
```

This command is the only supported non-interactive execution interface.

## Input sources

- `--pipe-file=*.devpipe.yaml`
- direct CLI flags

Inline JSON request payloads are not needed if `devpipe exec` already accepts a stable flag-based contract plus replayable `.devpipe.yaml`.

## Output

Support two output modes:

- `--output default`
- `--output json`

### `--output default`

- human-readable terminal output;
- suitable for local manual execution;
- preserves current interactive-friendly log style where reasonable.

### `--output json`

Return a final JSON object including:

- `run_id`
- `status`
- `profile`
- `final`
- `summary`
- `history`
- `error` when failed

## Files to modify

- `src/devpipe/cli.py`
- `src/devpipe/__main__.py`
- `src/devpipe/app.py`

## Files to add

- `src/devpipe/run_request.py`
- `src/devpipe/output_formatter.py`

## Work breakdown

### 4.1. Normalize request loading

- Create one normalized request model for:
  - `--pipe-file`
  - direct flags
- Merge priority:
  - CLI flags
  - `.devpipe.yaml`
  - project defaults

### 4.2. Add `devpipe exec`

- Add subcommand:

```bash
devpipe exec \
  --pipe-file=release.devpipe.yaml \
  --profile=delivery \
  --task="prepare release notes" \
  --runner=codex \
  --model=middle \
  --effort=middle \
  --tags=release,docs \
  --start-agent=intake \
  --stop-agent=finalize \
  --topic="release notes" \
  --show-prompts \
  --output=json
```

- Keep TUI entry path unchanged for plain `devpipe`.
- `devpipe exec` must never open the TUI.
- `devpipe exec` must be suitable for CI, scripts, and shell automation.

### 4.3. Supported flags

The non-interactive command should support at least:

- `--pipe-file=<path>`
- `--profile=<name>`
- `--task=<text>`
- `--task-id=<id>`
- `--runner=<name>`
- `--model=<level>`
- `--effort=<level>`
- `--tags=<comma-separated>`
- `--start-agent=<stage>`
- `--stop-agent=<stage>`
- `--topic=<text>`
- `--show-prompts`
- `--output=default|json`

Notes:

- `--pipe-file` loads replayable launch config from `.devpipe.yaml`.
- direct flags override values from `--pipe-file`.
- `--runner` remains top-level run selection for the CLI command itself;
  it is separate from stage-level `default_engine`.
- `--start-agent` and `--stop-agent` map to current `first_role` / `last_role` runtime fields.
- `--topic` should be treated as a first-class input and land in normalized request data instead of being hidden in an ad hoc free-form params bag.
- `--tags` should support comma-separated values and normalize to a list.
- `--show-prompts` controls prompt/transcript visibility in non-interactive execution logs.
- `--output=default` is the default mode.

### 4.4. `.devpipe.yaml` contract for `--pipe-file`

`.devpipe.yaml` should contain only replayable launch input, for example:

```yaml
profile: delivery
task: prepare release notes
task_id: DEV-123
runner: codex
model: middle
effort: middle
tags:
  - release
  - docs
start_agent: intake
stop_agent: finalize
topic: release notes
```

Rules:

- no `run_id`
- no `timestamp`
- no tokens
- no outputs
- no execution summary
- only fields required to replay the same pipeline invocation

### 4.5. Argument normalization and mapping

- Map `--start-agent` to internal `first_role`.
- Map `--stop-agent` to internal `last_role`.
- Decide whether `--runner` should remain internal `runner` or be renamed later at run level; do not mix it with stage-level `default_engine`.
- Normalize `topic` into structured request data so it is available to profiles and history replay.
- Preserve existing fields like `extra_params` only where needed; do not hide first-class flags inside it if a dedicated field exists.

### 4.6. Output behavior

For `--output default`:

- print readable execution progress;
- print final result in a concise human-oriented format;
- keep it stable enough for humans, not for parsers.

For `--output json`:

- build response from final pipeline state plus history details;
- `final` should come from the last completed stage output;
- on failure return structured error payload instead of raw traceback in stdout;
- when stage metadata is exposed, use `default_engine` naming in JSON output instead of `runner`.

### 4.7. Tests

- run from `.devpipe.yaml`;
- CLI flag override over file config;
- run with direct flags only;
- `--start-agent` and `--stop-agent` map correctly;
- `--tags` parsing is stable;
- `--topic` is present in normalized request;
- `--show-prompts` toggles prompt visibility behavior;
- `--output default` prints human-readable result;
- success response with `final`;
- failure response with structured `error`.

---

## 5. Task 3: Split history into YAML config and JSON details

## Goal

Move all execution details out of `.devpipe.yaml` into `.json`.

## New file contract

### `<run_id>.devpipe.yaml`

Contains only:

- fields needed to run the same pipeline again
- no execution metadata

Example:

```yaml
profile: delivery
task: prepare release notes
task_id: DEV-123
first_role: intake
last_role: finalize
default_engine: codex
extra_params:
  target_branch: main
```

No:

- run_id
- timestamp
- tokens
- duration
- outputs
- attempts
- summary
- errors

### `<run_id>.devpipe.json`

Contains:

- run_id
- timestamp
- summary
- final status
- tokens
- per-stage outputs
- attempts
- timings
- errors
- transcript/artifact references

## Files to modify

- `src/devpipe/history.py`
- `src/devpipe/app.py`
- `src/devpipe/ui/actions.py`
- `src/devpipe/ui/screens/history_screen.py`
- `src/devpipe/ui/widgets/history_preview.py`
- `src/devpipe/ui/widgets/detail_panel.py`
- `tests/test_history.py`
- `tests/ui/test_history_screen.py`
- `tests/ui/test_app.py`

## Work breakdown

### 5.1. Split history models

- Introduce separate models:
  - `RunReplayConfig`
  - `RunDetailsEntry`
- Keep YAML strictly rerun-oriented.
- Keep execution identity and runtime metadata in JSON only.

### 5.2. Change persistence API

- Replace single `save_run_history()` with:
  - config-save function
  - details-save function
- Add matching loaders.

### 5.3. Update UI

- History list loads from YAML only.
- Preview/details panel loads JSON lazily.
- Restore action uses YAML config only.
- Missing JSON should degrade gracefully.
- Everywhere in UI where stage AI backend is shown or edited, display `default_engine`, not `runner`.
- Keep top-level run selector naming separate from stage-level `default_engine` to avoid overloading terms.
- UI should treat `.devpipe.yaml` as replay input, not as execution record.

### 5.4. History cleanup

- Stop reading old monolithic history files.
- Keep only the new split format.
- If needed, add a one-off migration script separately, but do not complicate runtime code with legacy parsing.
- The authoritative execution record is `.json`; `.devpipe.yaml` is only reusable launch input.

### 5.5. Tests

- YAML contains config only;
- YAML contains nothing except replayable launch inputs;
- JSON contains summary and outputs;
- history UI works with new format;
- restore still works;
- old history files are not supported.

---

## 6. Update bundled and existing pipeline schemas

## Goal

Make the new shape explicit in shipped examples and validators.

## Required changes

- Update bundled profiles under `.devpipe/profiles/*/pipeline.yml`:
  - add explicit `type: ai`
  - rename `runner` to `default_engine`
- Update UI/config terminology:
  - form field labels
  - detail preview labels
  - history metadata labels
  - any serialized config snapshots that currently say `runner` at stage level
- Update validation rules and test fixtures.
- Update all bundled profiles and fixtures to the new schema in one pass.

## Example migrated AI stage

```yaml
stages:
  finalize:
    type: ai
    default_engine: codex
    model: low
    effort: low
    agent:
      folder: finalize
    out:
      final:
        type: string
```

---

## 7. Recommended implementation order

1. Split history storage.
2. Introduce `type: ai | cmd` and rename AI `runner`.
3. Implement command runner flow.
4. Update bundled pipelines, UI labels/forms, and validation fixtures.
5. Add JSON request/response mode.

This order minimizes ambiguity in the stage schema and gives the JSON mode a stable history/output contract.

---

## 8. Acceptance checklist

- Bundled profiles use explicit `type: ai` and `default_engine`.
- UI uses `default_engine` consistently wherever stage AI backend is configured or displayed.
- Command stages run without any AI backend call.
- Routing works for both `ai` and `cmd` stages.
- `.devpipe.yaml` stores only replayable launch input.
- `.devpipe.yaml` contains no `run_id`, `timestamp`, or any execution result metadata.
- `.devpipe.json` stores execution details and outputs.
- JSON execution mode returns machine-readable `final`.
- Old pipeline schema with `runner` is rejected fast and explicitly.

---

## 9. Final recommendation

- Introduce explicit stage kinds: `type: ai | cmd`.
- Rename AI-stage `runner` to `default_engine`.
- Do not keep any runtime compatibility layer for the old stage schema.
- Migrate bundled profiles immediately so the public schema becomes unambiguous.
