# OpenStudio AI MCP

This package contains the OpenStudio AI MCP server.

Main surfaces:

- `simulation/`: async, sandboxed, parallel simulation workflow surface.
- `results/`: SQL-backed result retrieval surface.
- `measures/`: MCP-published deterministic measures.
- `tools/`: current model, simulation, results, and SDK-doc tool handlers.
- `runtime/`: SQLite-backed local runtime registry, workspace management,
  artifact tracking, job tracking, and measure registry support.
- `sdk_docs/`: current SDK documentation lookup implementation.

Imports should use `openstudio_mcp`.

## Local Runtime Persistence

The MCP server stores runtime metadata in a lightweight SQLite database under
the configured workspace root:

```text
.openstudio_mcp_workspace/
├── openstudio_ai_runtime.sqlite
├── measure-.../
└── <simulation-job-id>/
```

SQLite stores metadata only:

- artifact records and lineage;
- job records and status;
- workspace records, size, kind, status, and timestamps;
- pin/protection status for future retention policies.
- MCP blackboard workflow state documents.

Large files remain on disk in workspaces:

- OSM model copies;
- EnergyPlus SQL files;
- stdout/stderr and simulation logs.

## Runtime Storage Tools

The MCP server exposes runtime management tools:

- `runtime_plugin_compatibility`: report plugin/runtime MCP interface status and
  the refresh action for a mismatch.
- `runtime_openstudio_status`: report the native OpenStudio CLI resolution used
  by the MCP process before simulation.
- `runtime_storage_usage`: report registered workspace usage and unregistered
  directories.
- `runtime_prune_preview`: list prune candidates without deleting files.
- `runtime_prune`: delete safe prune candidates.

Pruning is explicit. The MCP server does not automatically delete workspaces
during normal model, measure, simulation, or result-query workflows. Cleanup is
initiated only when the agent calls the runtime storage tools or when the user
asks the agent to inspect and prune local storage. The intended flow is:

1. The agent or user requests storage inspection.
2. The agent calls `runtime_storage_usage`.
3. The agent calls `runtime_prune_preview` and shows the protected workspaces,
   candidate workspaces, and reclaimable bytes.
4. The user or agent policy approves deletion.
5. The agent calls `runtime_prune`.

Default prune behavior is conservative:

- active model workspaces are protected;
- running jobs are protected;
- pinned workspaces are protected;
- successful simulation workspaces are protected unless explicitly requested;
- unprotected measure workspaces and failed simulation workspaces may be pruned.

![OpenStudio MCP pruning workflow](docs/assets/pruning_workflow.svg)

The data model is split intentionally: SQLite stores small metadata and the
filesystem stores large runtime files. SQLite is the source of truth for what a
workspace is, why it exists, and whether it can be pruned. It does not store OSM
models, EnergyPlus SQL files, or logs as blobs.

![OpenStudio MCP runtime data model](docs/assets/runtime_data_model.svg)

## MCP Blackboard Tools

The OpenStudio AI harness now evaluates MCP-owned blackboard state instead of
AUTOMA-AI native blackboard state. Workflow state is stored in the same local
SQLite runtime registry as artifact/job/workspace metadata.

Available tools:

- `blackboard_initialize_workflow`
- `blackboard_list_workflows`
- `blackboard_get_workflow`
- `blackboard_update_state_patch`
- `blackboard_get_phase_state`
- `blackboard_mark_step_complete`
- `blackboard_record_assumption`
- `blackboard_record_artifact`
- `blackboard_record_failure`
- `blackboard_snapshot_workflow`

The parent workflow skill remains responsible for state mutation semantics.
Child skills should return narrow `state_patch` objects; the parent applies
those patches through MCP blackboard tools.
