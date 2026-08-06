# OpenStudio AI Runtime Installation Contract

This contract defines what a Claude, Codex, or future host plugin may assume
about the local OpenStudio AI runtime.

## Required Command

Every distributed plugin expects this command to be available on the user's
machine:

```bash
openstudio-ai-mcp
```

The command must start the OpenStudio AI MCP server. The plugin connects to it
with stdio:

```json
{
  "mcpServers": {
    "openstudio_ai": {
      "command": "openstudio-ai-mcp",
      "args": ["--transport", "stdio"]
    }
  }
}
```

## Optional Runtime Commands

The runtime package should eventually provide:

```bash
openstudio-ai doctor
openstudio-ai install-runtime
openstudio-ai repair
```

## Plugin And Runtime Compatibility

An OpenStudio AI plugin contains skills that call MCP tools. A newer plugin can
therefore require MCP tool names or argument shapes that an older runtime does
not provide. Plugin exports include these MCP environment fields:

```text
OPENSTUDIO_AI_PLUGIN_VERSION
OPENSTUDIO_AI_PLUGIN_CONTRACT_VERSION
```

The package version identifies the release. The contract version identifies the
plugin-to-MCP interface and changes only when that interface breaks. A runtime
starts when the contract differs, reports a compatibility notice, and continues
to expose tools that remain compatible. The user should refresh the plugin or
upgrade the runtime before relying on newly added skill workflows.

Contract version `2` requires `runtime_openstudio_status`. The simulation skill
uses it as an MCP-only preflight and must not fall back to direct OpenStudio,
EnergyPlus, workflow, or SQL commands when the tool or MCP reconnection is
unavailable.

Marketplace doctor helpers run:

```bash
openstudio-ai doctor \
  --plugin-version <plugin-version> \
  --plugin-contract-version <contract-version>
```

Use this form after exporting a plugin or when repairing a failed MCP
connection. Re-exporting the plugin and upgrading the runtime are the normal
recovery path for a contract mismatch.

`doctor` reports `mcp_ready` for the runtime itself and `plugin_ready` for the
selected plugin. A contract mismatch leaves `mcp_ready` true when the runtime
otherwise works, emits a compatibility notice, and lets existing compatible MCP
tools remain available.

The bundled `doctor_runtime.py` helper returns exit code `1` for a contract
mismatch so setup automation can require acknowledgement, while the MCP server
itself continues to start. It returns `0` only when the plugin and runtime are
compatible.

`openstudio-ai validate-export` validates the structure and presence of
compatibility metadata for any export by default. Use
`--strict-runtime-version` only when an artifact must match the currently
installed runtime exactly.

Expected behavior:

- `openstudio-ai doctor`: checks Python, MCP startup, initialized runtime
  storage, SQLite support, package assets, measure registry, and a bounded gzip
  health probe against the resolved versioned SDK documentation bundle. The JSON
  result reports the SDK docs source, path, selected version, and header
  metadata. An invalid `OPENSTUDIO_SDK_DOCS_DIR` raises a warning but does not
  block MCP readiness. When a selected versioned gzip is unavailable, SDK
  lookup falls back to the available default bundle. Doctor also checks
  OpenStudio Python SDK availability, native OpenStudio CLI availability, and
  basic simulation readiness.

OpenStudio AI has a two-part OpenStudio prerequisite:

1. the PyPI `openstudio` Python package, installed as a required dependency of
   `openstudio-ai`;
2. the native OpenStudio application/CLI, visible through `OPENSTUDIO_PATH` or
   `PATH`.

The MCP runtime resolves an executable `OPENSTUDIO_PATH` first. If it is unset,
it resolves `openstudio` from the MCP server's `PATH` using
`shutil.which("openstudio")`. Use the environment variable to select a
nonstandard installation or a specific version.

Before a simulation, hosts should call `runtime_openstudio_status`. It reports
the executable path and discovery source from the MCP process itself, not from
the host shell. When unavailable, the simulation workflow performs read-only
platform-specific discovery before offering installation guidance.
- `openstudio-ai install-runtime`: installs or completes installation of the
  runtime package after user approval.
- `openstudio-ai repair`: attempts non-destructive fixes such as rebuilding
  indexes, recreating runtime folders, and explaining missing prerequisites.

## Adapter Runtime Modes

Adapters must support three runtime modes:

| Mode | MCP command | Intended use |
| --- | --- | --- |
| `local` | current Python executable with `-m openstudio_mcp.server` | Developer checkout testing. |
| `installed` | `openstudio-ai-mcp` | User or enterprise already installed the runtime. |
| `marketplace` | `openstudio-ai-mcp` plus setup assets | Marketplace/no-code onboarding. |

`local` mode may reference a source checkout. `installed` and `marketplace`
mode must not require a developer path such as `/Users/...`.

## Marketplace Setup Contract

Marketplace exports must include setup files that let an AI host guide a
non-programmer through installation.

Claude Code marketplace exports place setup as Claude-native skills:

```text
skills/
  setup-openstudio-ai/
    SKILL.md
    scripts/
      install_runtime.py
      doctor_runtime.py
  doctor-openstudio-ai/
    SKILL.md
  repair-openstudio-ai/
    SKILL.md
```

Codex marketplace exports expose setup as Codex skills and place helper scripts
under `skills/setup-openstudio-ai/scripts/`. Do not export root `commands/` or
`installers/` folders for Codex.

Codex does not activate a plugin agent prompt as the main conversation policy.
After enabling the marketplace plugin, users who want plain-language OpenStudio
requests to follow the shared orchestration policy run:

```bash
openstudio-ai install codex --target-dir /path/to/codex-project
```

This creates or updates only the marked OpenStudio block in that project's
`AGENTS.md`; it never replaces unrelated project instructions.

The setup workflow should ask the host agent to:

1. Check whether Python is available.
2. Check whether `openstudio-ai-mcp` is available.
3. Run the bundled `doctor_runtime.py` helper.
4. If the runtime is missing, run the bundled `install_runtime.py` helper after
   explaining what will happen and receiving approval.
5. Run `openstudio-ai doctor` when available.
6. Explain failures in normal energy-modeler language.
7. Warn at the start that setup also enables automatic OpenStudio routing in
   the current project. It is a required completion step, not a separate
   opt-in process. After the runtime is ready, preview
   `openstudio-ai install codex --target-dir . --dry-run --force`, then run
   `openstudio-ai install codex --target-dir . --force`. The command creates
   `AGENTS.md`, updates its marked block, or appends that block to an unmanaged
   file without replacing existing project instructions.

`install_runtime.py` should install or upgrade the runtime package after the
host agent has explained the action and received user approval. It should accept
`OPENSTUDIO_AI_PACKAGE_SPEC` for pinned versions, local wheel paths, or internal
package indexes, then initialize user-local runtime storage. Installer failures
should be explained in normal energy-modeler language.
