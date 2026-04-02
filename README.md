# devpipe

`devpipe` is a pipeline orchestrator for development workflows. A pipeline is made of typed stages:

- `ai` stages run an agent through an AI engine such as `codex` or `claude`
- `cmd` stages run a local command without calling an LLM

Pipelines are defined in `.devpipe/profiles/<profile>/pipeline.yml` and can be executed either through the interactive TUI or through `devpipe exec`.

## Installation

### End-user installation

`python3` is required. The recommended install flow is a single command:

```bash
curl -fsSL https://raw.githubusercontent.com/yanodincov/devpipe/main/install.sh | sh
```

The installer:

- creates `~/.devpipe/venv`
- installs `devpipe` from GitHub
- creates the launcher at `~/.local/bin/devpipe`
- creates `~/.devpipe/config.yaml` if it does not exist yet
- installs shell completion for the current shell when possible

After installation:

```bash
devpipe doctor
```

By default the installer uses `main`. To install a specific tag:

```bash
curl -fsSL https://raw.githubusercontent.com/yanodincov/devpipe/main/install.sh | DEVPIPE_REF=v0.1.0 sh
```

### Local development

```bash
mise install
mise run install
```

Without `mise`:

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
```

## Commands

```bash
devpipe
devpipe validate
devpipe doctor
devpipe list-engines
devpipe install-completion zsh
devpipe install-completion bash
devpipe exec --profile=... --task=...
```

`devpipe` can run from any directory. If the current project does not contain `.devpipe/`, global profiles from `~/.devpipe/profiles/` are used.

## Non-interactive Execution

`devpipe exec` supports two explicit modes:

1. Replay config file:

```bash
devpipe exec --pipe-file=release.devpipe.yaml
```

2. Flags only:

```bash
devpipe exec \
  --profile=delivery \
  --task="prepare release notes" \
  --runner=codex \
  --model=middle \
  --effort=middle \
  --tags=release,docs \
  --start-agent=intake \
  --stop-agent=finalize \
  --topic="release notes"
```

Mixed mode is also supported:

- `--pipe-file` loads the base replay config
- explicit flags override values from the file

Example:

```bash
devpipe exec \
  --pipe-file=release.devpipe.yaml \
  --runner=codex \
  --task="prepare release notes" \
  --start-agent=intake \
  --stop-agent=finalize \
  --topic="release notes"
```

### `exec` output contract

- `devpipe exec` always writes JSON to `stdout`
- without `--with-thinking`, `stdout` contains exactly one final JSON object
- with `--with-thinking`, `stdout` is JSONL:
  - stage events
  - action events
  - thinking events
  - final event as the last line

There are no plain-text banners in `exec` mode.

## Shell Completion

The installer configures completion automatically when possible.

Completion for `devpipe exec` includes:

- `--pipe-file=*.devpipe.yaml`
- `--profile=<profile>`
- `--runner=auto|<available engines>`
- `--with-thinking`

## Global Profiles

To use `devpipe` outside a specific project, create profiles in `~/.devpipe/profiles/`:

```bash
mkdir -p ~/.devpipe/profiles/<profile_name>/
```

Copy `pipeline.yaml` or `pipeline.yml` there, and optionally `agents/`.

You can also define a global default profile in `~/.devpipe/config.yaml`:

```yaml
defaults:
  profile: my-global-profile
```

## Interactive TUI

Typical fields:

```text
task          <- required
task-id       MRC-123        (from git branch)
runner        auto
target-branch u1
service       acquiring
namespace     auto
tags          acquiring-service, go
roles         architect -> qa_stand
```

Notes:

- `task-id` can be inferred from the current branch name, for example `MRC-123-my-feature -> MRC-123`
- `target_branch` controls later release/deploy stages
- `tags` support multi-select
- `first_role` and `last_role` are bounded by the pipeline graph
- the pipeline can only be started when required fields are filled

## Project Configuration

Create `.devpipe/` in the target project repository, not inside the `devpipe` repository.

Example:

```yaml
defaults:
  runner: auto
  service: my-service
  tags:
    - my-service
    - go

available:
  target_branch:
    - u1
    - u1-1
  namespace:
    - my-service-u1
    - my-service-u1-1
```

Rules:

- `defaults` define initial values for the TUI and CLI defaults
- `available` turns fields into dropdown/select values in the UI
- local `.devpipe/config.yaml` is merged on top of global `~/.devpipe/config.yaml`
- engine-specific model and effort mapping belongs in `~/.devpipe/config.yaml`

## User-Level Engine Mapping

Global engine mapping is configured in `~/.devpipe/config.yaml`.

Example:

```yaml
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
  claude:
    model:
      low: haiku
      middle: sonnet
      high: opus
    effort:
      low: low
      middle: medium
      high: high
      extra: high
```

Runtime behavior:

- only engines that are actually available in `PATH` are shown in the UI and completion
- if no AI engines are available, validation and `devpipe doctor` fail
- if `runner=auto`, `devpipe` tries the stage `default_engine` first and falls back to another available engine

Example:

- stage `default_engine: claude`
- `claude` is missing
- `codex` is installed
- `auto` resolves to `codex`

## Tags

Tags add role-specific rules to prompts.

Tags can be defined in three places:

1. In `pipeline.yml` as an input:

```yaml
inputs:
  tags:
    type: string
    multi: true
    default: []
    custom: true
    values: [go, backend, frontend]
```

2. In a stage:

```yaml
stages:
  developer:
    type: ai
    default_engine: codex
    tags: [go, backend]
    agent:
      folder: developer
```

3. In config defaults:

```yaml
defaults:
  tags:
    - my-service
    - go
```

Prompt assembly order:

```text
<base prompt from agents/<agent>/prompt.md>

## Project-Specific Rules
<content from .devpipe/<STAGE>_RULES.md if present>

## Tag Rules: go
<content from tags/go/<stage>/rules.md>

## Tag Rules: my-service
<content from .devpipe/tags/my-service/<stage>/rules.md>
```

Lookup order for tag rules:

1. `.devpipe/tags/<tag>/<stage>/rules.md`
2. builtin `tags/<tag>/<stage>/rules.md`

Example tag directory layout:

```text
tags/
└── go/
    ├── developer/
    │   └── rules.md
    └── test_developer/
        └── rules.md

.devpipe/
└── tags/
    └── my-service/
        ├── architect/
        │   └── rules.md
        ├── developer/
        │   └── rules.md
        └── qa_stand/
            └── rules.md
```

Builtin tags:

| Tag | Stages | Description |
|-----|--------|-------------|
| `go` | `developer`, `test_developer` | Rules for Go projects |

## Agents

Agents define the prompt and the output schema for an `ai` stage. They live in `.devpipe/profiles/<profile>/agents/<agent_name>/`.

```text
agents/
└── my_agent/
    ├── prompt.md
    └── output.schema.json
```

Two supported forms:

1. Folder-based:

```yaml
agent:
  folder: builder
```

2. Explicit paths:

```yaml
agent:
  prompt: agents/builder/prompt.md
  schema: agents/builder/output.schema.json
```

## Pipeline Schema

Profiles are stored in `.devpipe/profiles/<name>/pipeline.yml`.

Example:

```yaml
version: 1
name: my-pipeline

defaults:
  runner: auto
  model: middle
  effort: middle

inputs:
  task:
    type: string
    required: true
    default: ""
    custom: true

stages:
  build:
    type: ai
    default_engine: codex
    model: high
    effort: middle
    retry_limit: 2
    agent:
      folder: builder
    in:
      task: input.task
      config: context.config
    out:
      artifacts:
        type: object

routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: completed
          default: true
```

### Top-level fields

| Field | Type | Description |
|------|------|-------------|
| `version` | integer | Profile schema version. Currently only `1` is supported |
| `name` | string | Profile name |
| `defaults` | object | Run-level defaults |
| `inputs` | object | User-facing pipeline inputs |
| `stages` | object | Stage definitions |
| `routing` | object | Stage graph |

### `defaults`

| Field | Type | Description |
|------|------|-------------|
| `runner` | string | `auto`, `codex`, `claude` |
| `model` | string | `auto`, `low`, `middle`, `medium`, `high` |
| `effort` | string | `auto`, `low`, `middle`, `medium`, `high`, `extra` |

### `inputs`

Example:

```yaml
inputs:
  my_field:
    type: string
    required: true
    default: ""
    values: [a, b, c]
    multi: false
    custom: true
```

Supported input types:

| Type | Description |
|------|-------------|
| `string` | string value |
| `int` | integer |
| `bool` | boolean |
| `object` | JSON object |
| `array` | JSON array |

Validation notes:

- `required: true` means the field must be filled
- if `custom: false` and `values` exist, the value must come from that set
- reserved input names: `runner`, `profile`, `first_role`, `last_role`, `model`, `effort`

### `stages`

There are two stage types:

- `type: ai`
- `type: cmd`

For `ai` stages, use `default_engine`. The field `runner` is only run-level.

Example:

```yaml
stages:
  build:
    type: ai
    default_engine: codex
    model: high
    effort: middle
    retry_limit: 2
    tags: [go, backend]
    agent:
      folder: builder
    in:
      task: input.task
    out:
      result:
        type: object
```

Stage fields:

| Field | Type | Required | Description |
|------|------|----------|-------------|
| `type` | string | yes | `ai` or `cmd` |
| `default_engine` | string | for `ai` | preferred engine for the stage |
| `model` | string | for `ai` | model level |
| `effort` | string | for `ai` | reasoning level |
| `retry_limit` | int | no | retry count |
| `tags` | list | no | tags applied to the stage |
| `agent` | object | for `ai` | agent spec |
| `command` | object | for `cmd` | command execution spec |
| `in` | object | no | input bindings |
| `out` | object | no | output schema |

Example `cmd` stage:

```yaml
stages:
  git_meta:
    type: cmd
    command:
      exec: ["git", "status", "--short", "--branch"]
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

### Input bindings

Examples:

```yaml
in:
  task: input.task
  config: context.config
  artifacts: stage.build.out.artifacts
  branch: runtime.git.current_branch
```

Supported sources:

- `input.<field>`
- `context.<field>`
- `stage.<name>.out.<field>`
- `runtime.<source>.<field>`
- `integration.<service>.<field>`

### `routing`

Routing defines stage transitions.

Example:

```yaml
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: test
          default: true
    test:
      next_stages:
        - stage: completed
          default: true
```

Conditional routing example:

```yaml
by_stage:
  test:
    next_stages:
      - stage: deploy
        all:
          - field: out.passed
            op: eq
            value: true
      - stage: failed
        default: true
```

Operators:

| Operator | Description |
|---------|-------------|
| `eq` | equals |
| `neq` | not equals |
| `gt` | greater than |
| `gte` | greater than or equal |
| `lt` | less than |
| `lte` | less than or equal |
| `in` | value is in a list |
| `contains` | collection contains value |

Special terminal stages:

- `completed`
- `failed`

There must be a path from `start_stage` to `completed`.

## Example Project Layout

```text
acquiring-repo/
  .devpipe/
    config.yaml
    tags/
      acquiring-service/
        architect/rules.md
        developer/rules.md
        test_developer/rules.md
        qa_local/rules.md
        release/rules.md
        qa_stand/
          rules.md
          params.yaml
```

Example config:

```yaml
defaults:
  runner: auto
  service: acquiring
  tags:
    - acquiring-service
    - go

available:
  target_branch:
    - u1
    - u1-1
    - u1-4
  namespace:
    - acquiring-u1
    - acquiring-u1-1
    - acquiring-u1-4
```

## Repository Layout

```text
devpipe/
├── config/
│   └── runners.yaml
├── tags/
│   └── go/
├── install.sh
└── src/devpipe/
    ├── app.py
    ├── cli.py
    ├── completion.py
    ├── engines.py
    ├── history.py
    ├── project_config.py
    ├── run_request.py
    ├── runtime/
    ├── runners/
    ├── storage/
    └── ui/
```
