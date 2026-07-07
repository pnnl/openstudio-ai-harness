---
name: openstudio_workflow_state
description: Maintain persistent task-global workflow state for long-running OpenStudio energy modeling tasks.
version: 0.3.0
output_format: markdown_with_json_state
---

## Scope

Use this skill whenever an OpenStudio energy modeling workflow spans multiple
phases, child skills, scripts, simulations, failure recovery steps, or
clarification gates.

OpenStudio AI persists workflow state through MCP blackboard tools. The parent
workflow skill owns all writes. Child skills and script phases return narrow
`state_patch` objects only.

## Parent Rules

- Read the active workflow before planning a phase.
- Write state only through MCP blackboard tools.
- Normalize child patch convenience keys before writing.
- Do not let child skills re-ask values already present in state.
- If a required value is missing, ask one focused clarification question and
  write the answer before continuing.
- Include a compact final state summary in the task answer.

## Blackboard Operations

- `blackboard_initialize_workflow`: create `workflow_id` and initialize state.
- `blackboard_get_workflow`: read complete workflow state.
- `blackboard_get_phase_state`: read narrow phase state before loading a child
  skill.
- `blackboard_update_state_patch`: merge a normalized child `state_patch` into
  the workflow state.
- `blackboard_mark_step_complete`: update canonical `completed_steps` and
  `pending_steps` lists.
- `blackboard_record_assumption`, `blackboard_record_artifact`, and
  `blackboard_record_failure`: append durable workflow records.
- `blackboard_snapshot_workflow`: create a JSON state snapshot for handoff or
  debug.

Do not use AUTOMA-AI native blackboard tools for this harness.

## Generic Workflow Fields

Every long-running workflow should keep these top-level fields. Use `null`,
empty arrays, or empty objects for unknown values. Domain-specific parent skills
may add nested sections such as `system`, `schedules`, `sizing`, `variants`, or
`results`.

```text
workflow_id
goal
status
input_model_path
current_model_path
output_model_path
openstudio_version
completed_steps
pending_steps
created_objects
artifacts
assumptions
warnings
failures
validation_results
missing_fields
last_phase
```

## Assumption Ledger

Record every approved default in `assumptions` using:

```text
Object:Name.parameter: assumed to be x
```

## Child Patch Contract

Each child phase returns only changed fields:

```json
{
  "ok": true,
  "state_patch": {
    "completed_steps": ["focused_edit"],
    "pending_steps_remove": ["focused_edit"],
    "created_objects": {"edited_model": "outputs/model_edited.osm"},
    "warnings": []
  }
}
```

The parent must convert `pending_steps_remove` into the canonical
`pending_steps` list before writing to the blackboard.

If blocked, a child phase returns:

```json
{
  "ok": false,
  "missing_fields": ["output_model_path"],
  "clarifying_question": "Where should I save the copied edited model?"
}
```

## Validation Before Handoff

Before simulation or final handoff, confirm in state:

- input and output paths are distinct unless overwrite was approved;
- created object names, assumptions, warnings, and validation results are
  recorded;
- failures are inspectable and include enough detail for recovery;
- artifacts needed by the next phase are recorded.
