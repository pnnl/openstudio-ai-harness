# OpenStudio AI Host Adapters

`adapters/` is release tooling. It translates trusted OpenStudio AI assets into
the native plugin layouts required by Claude Code and Codex. It must not own
modeling behavior, OpenStudio operations, or durable workflow state.

## Ownership

- `claude_code_adapter.py`: Claude Code marketplace and project-local exports.
- `codex_adapter.py`: Codex marketplace exports and managed project guidance.
- `contracts.py`: shared host configuration and launch-plan types.
- `base.py`: common adapter interface.

The adapters render product skills, agents, and references from
`harness/asset_manifest.yaml`. They own only host infrastructure such as
marketplace setup/doctor/repair skills, installer scripts, and MCP configuration.
Durable workflow state is owned by the MCP runtime in
`openstudio_mcp/runtime/state_store.py`, not by an adapter.

## Runtime Modes

| Mode | MCP command in the export | Use |
| --- | --- | --- |
| `local` | Current virtualenv Python running `openstudio_mcp.server` | Source-checkout development. |
| `installed` | `openstudio-ai-mcp` | An already installed runtime. |
| `marketplace` | `openstudio-ai-mcp` | Marketplace package with setup, doctor, and repair skills. |

Use `local` while changing this repository. Use `marketplace` only after the
runtime is installed in the environment that will load the plugin.

## Claude Code Export

```bash
.venv/bin/python -m cli export claude \
  --output-dir /tmp/openstudio-ai-claude \
  --workspace-root "$PWD" \
  --runtime-mode local \
  --force

.venv/bin/python -m cli validate-export \
  /tmp/openstudio-ai-claude/openstudio-ai \
  --runtime-mode local
```

The marketplace export has this shape:

```text
openstudio-ai-claude/
├── .claude-plugin/marketplace.json
├── INSTALL.md
└── openstudio-ai/
    ├── .claude-plugin/plugin.json
    ├── .mcp.json
    ├── README.md
    ├── CONNECTORS.md
    ├── settings.json
    ├── agents/openstudio-modeler.md
    ├── monitors/monitors.json
    ├── bin/openstudio-ai-learning-monitor
    └── skills/
        ├── add-vav-reheat/
        ├── simulate/
        ├── query-results/
        ├── setup-openstudio-ai/
        ├── doctor-openstudio-ai/
        ├── repair-openstudio-ai/
        ├── openstudio-sdk-model-editor/
        ├── openstudio-workflow-state/
        ├── propose-measure/
        └── capture-session-lesson/
```

References such as SDK knowledge, workflow schemas, and learning contracts are
copied under the owning skill's `references/` directory. Claude Code does not
load arbitrary plugin-root `knowledge/`, `instructions/`, or `blackboard/`
folders.

For development, add the marketplace and reload it in Claude Code:

```text
/plugin marketplace add /tmp/openstudio-ai-claude
/plugin install openstudio-ai@openstudio-ai-local
/reload-plugins
```

The `install` subcommand remains a project-local debugging path. It writes a
managed OpenStudio AI block to `.claude/CLAUDE.md` and a project `.mcp.json`; it
is not the distributable plugin format.

## Codex Export

```bash
.venv/bin/python -m cli export codex \
  --output-dir /tmp/openstudio-ai-codex \
  --workspace-root "$PWD" \
  --runtime-mode local \
  --force

.venv/bin/python -m cli validate-export \
  /tmp/openstudio-ai-codex/plugins/openstudio-ai \
  --runtime-mode local
```

The export has this shape:

```text
openstudio-ai-codex/
├── .agents/plugins/marketplace.json
├── INSTALL.md
└── plugins/openstudio-ai/
    ├── .codex-plugin/plugin.json
    ├── .mcp.json
    ├── README.md
    ├── CONNECTORS.md
    └── skills/
        ├── setup-openstudio-ai/
        ├── openstudio-modeling-orchestrator/
        ├── openstudio-sdk-model-editor/
        ├── openstudio-workflow-state/
        ├── propose-measure/
        └── capture-session-lesson/
```

Add the exported marketplace with:

```bash
codex plugin marketplace add /tmp/openstudio-ai-codex
```

Codex references also live under the relevant skill. Do not add root plugin
folders such as `commands/`, `instructions/`, `knowledge/`, `blackboard/`,
`learning/`, or `installers/`.

After installing or enabling the Codex plugin, install the project-level
modeler policy with the public CLI:

```bash
openstudio-ai install codex --target-dir /path/to/codex-project
```

The command creates `AGENTS.md` if it is absent. It otherwise updates only its
marked block; preview with `--dry-run`, and use `--force` to append to an
unmanaged file without replacing existing instructions.

## Change Checklist

When changing an adapter or exported layout:

1. Update the adapter and its expected export contract.
2. Update `cli validate-export` when the contract changes.
3. Update the relevant adapter tests and asset-manifest tests.
4. Export to `/tmp`, run `validate-export`, and run the host validator when it
   is available.

See `docs/DEVELOPER_GUIDANCE.md` for the complete local, Claude Code, and Codex
testing workflows.
