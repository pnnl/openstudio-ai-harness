# OpenStudio AI Runtime Installation Contract

This contract defines what a Claude, Codex, or future host plugin may assume
about the local OpenStudio AI runtime.

## Required Command

Every distributed plugin starts this command. `installed` plugins expect it on
the user's `PATH`; `marketplace` plugins launch it through `uvx` with an exact
package spec (see Adapter Runtime Modes):

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

Contract version `2` requires `runtime_openstudio_status`. Contract version `3`
adds `model_export_geometry_viewer`, required by the standalone geometry-viewer
skill. Contract version `4` adds the personal-learning tools used by the
curate-learning workflow. Contract version `5` adds durable engineering-session,
finding, and checkpoint tools. The simulation skill uses its preflight as an
MCP-only workflow and must not fall back to direct OpenStudio, EnergyPlus,
workflow, or SQL commands when the tool or MCP reconnection is unavailable.

Marketplace doctor helpers run:

```bash
openstudio-ai doctor \
  --plugin-version <plugin-version> \
  --plugin-contract-version <contract-version>
```

Use this form after exporting a plugin or when repairing a failed MCP
connection. Re-exporting the plugin and upgrading the runtime are the normal
recovery path for a contract mismatch. A host discovers MCP tools when it
starts its server connection; updating a plugin or runtime cannot add a newly
contracted tool to an already-running conversation. After an upgrade, restart
the host or reconnect the MCP server before retrying the workflow.

`doctor` reports `mcp_ready` for the runtime itself and `plugin_ready` when the
selected plugin has no known incompatibility with that running MCP runtime.
`core_ready` is the blocking energy-modeling readiness signal: it additionally
requires supported Python, the OpenStudio Python SDK, and a native OpenStudio
executable that returns a recognized version. A declared contract mismatch
blocks both `plugin_ready` and `core_ready`. An undeclared contract produces a
warning that compatibility cannot be verified, but does not block readiness so
existing marketplace exports without contract metadata remain usable.

`openstudio-ai doctor` returns exit code `0` only when `core_ready` is true. It
returns `1` when a core readiness check fails, including a contract mismatch or
a missing/unusable native OpenStudio CLI. Setup automation must treat a
nonzero exit code as not ready for energy modeling; optional MCP capabilities
such as NLR do not affect this result.

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
2. the native OpenStudio application/CLI, resolved through `OPENSTUDIO_PATH`, a
   user-confirmed path saved by `openstudio-ai configure-openstudio`, or `PATH`.

The MCP runtime resolves an executable `OPENSTUDIO_PATH` first. If it is unset,
it resolves the user-confirmed path saved by `openstudio-ai configure-openstudio`.
Finally, it resolves `openstudio` from the MCP server's `PATH` using
`shutil.which("openstudio")`. Use the environment variable to select a
temporary or externally managed override; use `configure-openstudio` to persist
a nonstandard installation or a specific version.

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
| `local` | current Python executable with `-m openstudio_ai_mcp.server` | Developer checkout testing. |
| `installed` | `openstudio-ai-mcp` | User or enterprise already installed the runtime. |
| `marketplace` | `uvx --python 3.12 --from openstudio-ai==<plugin-version> --with openstudio==<sdk-version> openstudio-ai-mcp` plus setup skills | Marketplace/no-code onboarding. Requires only uv. |

`local` mode may reference a source checkout. `installed` and `marketplace`
mode must not require a developer path such as `/Users/...`.

Marketplace mode pins the runtime release to the plugin version, so the plugin
and runtime contracts match by construction; publish the matching
`openstudio-ai` release to PyPI before publishing the plugin export. Host-side
SDK scripts use the interpreter reported by `runtime_openstudio_status`
(`sdk_python.executable`), which is the MCP server's own environment in every
mode.

## Marketplace Setup Contract

Marketplace exports must include setup files that let an AI host guide a
non-programmer through installation.

Claude Code marketplace exports place setup as Claude-native skills:

```text
skills/
  setup-openstudio-ai/
    SKILL.md
  doctor-openstudio-ai/
    SKILL.md
  repair-openstudio-ai/
    SKILL.md
```

Codex marketplace exports expose the same setup skills. Do not export root
`commands/` or `installers/` folders for Codex.

Codex does not activate a plugin agent prompt as the main conversation policy.
After enabling the marketplace plugin, users who want plain-language OpenStudio
requests to follow the shared orchestration policy run:

```bash
openstudio-ai install codex --target-dir /path/to/codex-project
```

This creates or updates only the marked OpenStudio block in that project's
`AGENTS.md`; it never replaces unrelated project instructions.

The setup workflow should ask the host agent to:

1. Check whether `uvx` is available. If not, ask before installing uv,
   preferring `pipx install uv` when pipx is present. pipx installs only uv,
   never the runtime itself.
2. Prepare the pinned runtime with `uvx ... openstudio-ai install-runtime` so
   uv's cache is warm before the host's MCP startup timeout matters. This needs
   no approval: it changes only uv's cache, which the MCP launch fills anyway.
   Tell the user about the roughly 100 MB download.
3. Run `uvx ... openstudio-ai doctor` with the plugin version and contract.
4. If `plugin_ready` is false, rebuild the cached runtime with
   `uvx --reinstall ...` after explaining what will happen and receiving
   approval.
5. Diagnose a `uvx` missing from the PATH that launches the host.
6. Explain failures in normal energy-modeler language.
7. Warn at the start that setup also enables automatic OpenStudio routing in
   the current project. It is a required completion step, not a separate
   opt-in process. After the runtime is ready, preview
   `openstudio-ai install codex --target-dir . --dry-run --force`, then run
   `openstudio-ai install codex --target-dir . --force`. The command creates
   `AGENTS.md`, updates its marked block, or appends that block to an unmanaged
   file without replacing existing project instructions.

Organizations that do not install from PyPI configure uv's package index (for
example `UV_DEFAULT_INDEX`) rather than editing the plugin's launch command.
Installer failures should be explained in normal energy-modeler language.
