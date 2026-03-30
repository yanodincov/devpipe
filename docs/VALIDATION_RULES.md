# Pipeline Validation Rules

This document defines all validation rules for `pipeline.yml` and output schemas.

## 1. Top-Level Structure

### 1.1 Required Fields
- `version: 1` (only version 1 is supported)
- `name` (string, profile name)
- `stages` (dict of stage definitions)
- `routing` (routing configuration)

### 1.2 Optional Fields
- `defaults` (dict of default values)
- `inputs` (dict of input specifications)

## 2. Inputs Validation

### 2.1 Reserved Names (cannot be used as input names)
- `task` - primary task input
- `runner` - runner selection
- `profile` - profile name
- `first_role` / `last_role` - stage bounds
- `model` - model selection
- `effort` - effort level
- `tags` - tags input (special handling, see 2.6)

### 2.2 Input Type Rules
Valid types: `string`, `int`, `bool`, `object`

ERROR: Invalid type (e.g., `string1`, `array`)
```
inputs.my_field.type: Invalid type 'string1'. Valid types: bool, int, object, string
```

### 2.3 `multi` Property Rules
- `multi: true` requires `default` to be a list
- `multi: true` without `values` requires `custom: true` (free-form multi-input)
- `multi: true` with `values` may have `custom: true` or `custom: false`

ERROR: multi without values and without custom
```
inputs.tags: multi=true requires either 'values' or 'custom=true'
```

### 2.4 `custom` Property Rules
- `custom: true` allows user to enter custom values not in `values`
- `custom: false` (default) restricts selection to `values` only
- If no `values` provided → `custom: true` is auto-set (free-form input)
- If `values` provided → `custom` can be `true` or `false`

### 2.5 `values` Property Rules
- `values` must be a list
- All values must match the declared `type`
- For `bool` type, `values` is ignored (always `["true", "false"]`)

### 2.6 Special Input: `tags`
- `tags` MUST have `multi: true` to be used as tag selector
- `tags` input creates a TAG_ROLES field (special handling)
- If `tags` is defined without `multi: true` → ERROR

ERROR: tags without multi
```
inputs.tags: tags input must have 'multi: true'
```

### 2.7 `required` Property
- `required: true` means the field must have a non-empty value
- `required: false` (default) allows empty values

### 2.8 `default` Values
- `default` must match the declared type
- For `multi: true`, default must be a list
- For `multi: false`, default must be a scalar (not a list)
- For `bool`, default must be `true` or `false`

### 2.9 `bool` Type Special Rules
- `type: bool` always creates SELECT with `["true", "false"]`
- `values` property is ignored for bool type
- `multi` property is ignored for bool type (always single select)
- `custom` property is ignored for bool type (always false)
- `required` property is ignored for bool type (always optional with default)

WARNING: bool type ignores extra properties
```
inputs.auto_approve.values: bool type ignores 'values' (always true/false)
inputs.auto_approve.multi: bool type ignores 'multi' (always single select)
inputs.auto_approve.custom: bool type ignores 'custom' (no custom values)
```

## 3. Stages Validation

### 3.1 Stage Names
- Must be valid identifiers (alphanumeric, underscore, hyphen)
- Must be unique within the `stages` dict

### 3.2 Required Stage Properties
Each stage must have:
- `runner` (string) - the runner to use

### 3.3 Optional Stage Properties
- `model` (string) - model override
- `agent` (string or dict) - agent specification
- `in` (dict) - input bindings
- `out` (dict) - output field specifications

### 3.4 Agent Specification
Two formats:
1. Short form: `agent: agent_name` - loads from `.devpipe/profiles/{profile}/agents/{agent_name}/`
2. Full form:
   ```yaml
   agent:
     prompt: path/to/prompt.md
     output_schema: path/to/schema.json
   ```

### 3.5 Input Bindings (`in`)
- Must be a dict
- Each binding source must start with: `input.`, `context.`, `stage.`, `runtime.`, or `integration.`

ERROR: Invalid binding source
```
stages.develop.in.message: Invalid binding source 'my_var'. Must start with input., context., stage., runtime., or integration.
```

### 3.6 Output Fields (`out`)
- Must be a dict
- Each field must have a `type`
- Valid types: `string`, `int`, `bool`, `object`

## 4. Routing Validation

### 4.1 Required Routing Fields
- `start_stage` (string) - must reference a defined stage
- `by_stage` (dict) - routing rules for each stage

### 4.2 Start Stage
- Must be defined in `stages`
- Must have at least one path leading to `completed`

ERROR: No path to completed
```
routing: No path from start_stage 'architect' to 'completed'. Pipeline cannot reach completion.
```

### 4.3 Stage Routing (`by_stage`)
- Each key must be a stage name defined in `stages`
- `completed` and `failed` are special system stages (cannot be in `stages`)
- Each stage routing has `next_stages` (list of rules)

### 4.4 Routing Rules
Each rule in `next_stages` must have:
- `stage` (string) - target stage name
- Optional: `default: true` - default transition
- Optional: `condition` - routing condition
- Optional: `all` / `any` - condition groups

### 4.5 Path Validation
Must have at least one path from `start_stage` to `completed`:
```
start_stage -> stage1 -> stage2 -> ... -> completed
```

ERROR: Unreachable completed
```
routing: No path from 'start_stage' to 'completed'. Pipeline cannot reach completion.
```

## 5. Defaults Section

### 5.1 Standard Defaults
- `runner`: must be one of available runners (e.g., "auto", "codex", "claude")
- `model`: must be one of available models (e.g., "auto", "low", "middle", "high")
- `effort`: must be one of available effort levels (e.g., "auto", "low", "middle", "high")

### 5.2 Custom Defaults
- Must reference a field defined in `inputs`
- Must match the field's type

## 6. Runner/Model/Effort Validation

### 6.1 Available Runners
Predefined runners: `auto`, `codex`, `claude`

### 6.2 Available Models
Predefined models depend on runner:
- For `codex`: `auto`, `low`, `middle`, `high`
- For `claude`: `auto`, `low`, `middle`, `high`

### 6.3 Available Effort Levels
Predefined levels: `auto`, `low`, `middle`, `high`

## 7. Output Schema Validation (`output.schema.json`)

### 7.1 Schema Structure
Must be a valid JSON Schema

### 7.2 Required Fields
- `$schema` (optional) - JSON Schema version
- `type` - must be `"object"`
- `properties` - defines output fields

### 7.3 Property Types
Valid types: `string`, `integer`, `boolean`, `object`, `array`, `null`

### 7.4 Required Properties
- If `required` array is present, all listed properties must be in `properties`

## 8. Agent Prompt Validation (`prompt.md`)

### 8.1 File Requirements
- Must exist if `agent` is specified
- Should contain valid Markdown

### 8.2 Placeholder Validation
- Placeholders like `{{input.field}}` should reference valid inputs
- Placeholders like `{{stage.field}}` should reference valid stage outputs

## 9. Cross-Reference Validation

### 9.1 Input Bindings to Inputs
- `in.my_field: input.some_input` → `inputs.some_input` must exist

### 9.2 Input Bindings to Stage Outputs
- `in.my_field: stage.prev_stage.output_field` → `stages.prev_stage.out.output_field` must exist

### 9.3 Routing References
- All stages referenced in routing must be defined in `stages`
- Stage names in conditions must exist

## 10. Validation Error Levels

### 10.1 Errors (blocking)
- Invalid structure
- Missing required fields
- Type mismatches
- Invalid references
- No path to completion

### 10.2 Warnings (non-blocking)
- Deprecated properties
- Ignored properties (e.g., `values` on `bool`)
- Auto-fixed values (e.g., `multi` default auto-conversion)