# Blackboard Contract

The parent workflow owns blackboard mutations through MCP blackboard tools.

Child skills and tools may return state patches, assumptions, artifacts, and
failure records. The parent workflow decides whether and how to apply them.

Required operations:

- `blackboard_initialize_workflow`: initialize workflow state;
- `blackboard_get_workflow`: read workflow state;
- `blackboard_update_state_patch`: apply state patches;
- `blackboard_get_phase_state`: read narrow phase state;
- `blackboard_mark_step_complete`: mark phases complete;
- `blackboard_record_assumption`: record assumptions;
- `blackboard_record_artifact`: record artifacts;
- `blackboard_record_failure`: record failures;
- `blackboard_snapshot_workflow`: snapshot workflow state.

Do not use AUTOMA-AI native blackboard tools for OpenStudio AI harness state
while evaluating the MCP blackboard path.

Workflow patches preserve top-level history: `completed_steps` and `assumptions`
append unique entries to existing lists. Nested lists and other lists (including
`pending_steps`) retain replacement semantics. `blackboard_record_assumption`
continues to append individual events, including repeated text. Initialize a new
workflow when history must start fresh.
