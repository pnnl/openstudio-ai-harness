# OpenStudio AI Blackboard

The active OpenStudio AI harness stores workflow state through MCP blackboard
tools backed by the local MCP SQLite runtime registry. This folder contains the
shared operation helpers and schemas used by that MCP implementation.

Do not use AUTOMA-AI native blackboard tools for OpenStudio AI harness state
while evaluating the MCP blackboard path.

The parent workflow owns all state mutations. Child skills and runtime tools
return state patches, but they do not directly rewrite shared assumptions,
phase status, or promoted artifacts.

Core operations:

- `blackboard_initialize_workflow`
- `blackboard_get_workflow`
- `blackboard_update_state_patch`
- `blackboard_get_phase_state`
- `blackboard_mark_step_complete`
- `blackboard_record_assumption`
- `blackboard_record_artifact`
- `blackboard_record_failure`
- `blackboard_snapshot_workflow`
