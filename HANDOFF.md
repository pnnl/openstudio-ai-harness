# OpenStudio AI Harness Handoff

## Current Status

- Package version: `0.1.8`.
- The package exposes an OpenStudio MCP runtime, Claude Code and Codex plugin
  exports, trusted skills and references, runtime learning contracts, and
  MCP-backed SQLite workflow state.
- Claude and Codex exports use host-native plugin structures. Shared reference
  routing is declared in `harness/asset_manifest.yaml`.
- Marketplace exports start the installed `openstudio-ai-mcp` command. Local
  exports start `python -m openstudio_mcp.server` from the source virtualenv.
- Marketplace setup and repair skills diagnose the Python scripts directory
  when the runtime installs but the MCP command is absent from the host PATH.
  They keep `.mcp.json` portable and direct repository users to a separate
  `--runtime-mode local` export rather than hard-coding a virtualenv path.
- Exports declare a plugin package version and MCP interface contract version.
  A mismatch is visible through `doctor` and `runtime_plugin_compatibility`, but
  does not prevent MCP startup; users should refresh the plugin or upgrade the
  runtime before using newer workflows.
- Doctor validates the resolved versioned SDK YAML bundle with a bounded gzip
  metadata probe. Its JSON output reports the SDK docs source, path, and
  selected version; an invalid `OPENSTUDIO_SDK_DOCS_DIR` raises a warning but
  does not block MCP readiness because lookup falls back to the bundled SDK
  documentation.
- The base package requires the OpenStudio Python package. Model edits,
  simulation, and measures also require the native OpenStudio application or
  CLI through `OPENSTUDIO_PATH` or `PATH`.
- Core plugin readiness is blocking: Python 3.10+, the installed MCP command,
  MCP startup, the OpenStudio Python SDK, a native executable, and plugin
  compatibility must all pass before doctor reports the plugin ready for energy
  modeling. NLR is reported as a separate optional capability.
- The MCP runtime resolves an executable `OPENSTUDIO_PATH` first, then a
  user-confirmed path stored by `openstudio-ai configure-openstudio`, then
  `openstudio` on its own `PATH` with `shutil.which`. The resolved absolute path
  is used for both measures and simulations.
- The simulation skill prevents repeated executable failures: it does not edit
  marketplace `.mcp.json` automatically, requires a reconnect after an approved
  environment change, and retries only once.
- `runtime_openstudio_status` is the required simulation preflight. It reports
  the MCP process's executable path/source and directs the agent to read-only
  platform-specific discovery before proposing an OpenStudio installation.
- MCP contract version `2` is required for the simulation preflight. Simulation
  skills are MCP-only: if the preflight or reconnection is unavailable, they
  stop and ask the user to refresh the plugin/runtime rather than invoke a
  local OpenStudio CLI fallback.
- Codex projects can install a managed OpenStudio block into `AGENTS.md` with
  `openstudio-ai install codex --target-dir <project>`. The block loads
  `openstudio-modeling-orchestrator` first, then reuses the shared modeler
  policy; it preserves surrounding project guidance and does not alter Claude's
  plugin-agent activation.
- The Codex marketplace setup skill installs that project guidance as a required
  completion step after runtime readiness. It warns at setup start, previews
  the managed `AGENTS.md` block, then creates, updates, or safely appends it
  without replacing unrelated project instructions.
- `openstudio-ai export marketplace` emits a paired Claude/Codex marketplace
  tree with separate host install guides, stable source provenance, and strict
  validation of both generated plugin packages.
- The production package supports Python 3.10+ and does not include AUTOMA-AI
  or Streamlit. The `standalone/` subproject is separately locked for Python
  3.12+ local AUTOMA-AI and Streamlit testing. Host-facing skills use
  host-neutral Python execution instructions.

## Current Boundaries

- SQLite persistence is owned by `openstudio_mcp/runtime/state_store.py` and
  exposed through MCP blackboard tools. Plugin reference files describe that
  contract; they never write state on their own.
- `skills/`, `prompts/`, `knowledge/`, `policy/`, and approved measures are
  trusted source assets. Candidate material remains developer-only until review
  and validation promote it.
- Local OpenStudio fixtures belong under `tests/fixtures/`; they are not release
  assets and must not enter wheels or plugins.

## Verification Baseline

Run from the repository root with `.venv/bin/python`:

```bash
.venv/bin/python -m pytest -q \
  tests/test_harness_asset_manifest.py \
  tests/test_openstudio_cli.py \
  tests/test_openstudio_claude_code_adapter.py \
  tests/test_openstudio_codex_adapter.py

.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
```

Run OpenStudio-gated simulation tests only with a configured native CLI:

```bash
OPENSTUDIO_PATH=/path/to/openstudio \
  .venv/bin/python -m pytest -q tests/test_mcp_openstudio_smoke.py
```

Run AUTOMA-AI-only checks with Python 3.12+:

```bash
uv sync --project standalone
uv run --project standalone python -m pytest -q standalone/tests
```

## Next Steps

1. Add CI for focused tests, build, wheel-content inspection, `doctor`, and
   marketplace export validation.
2. Decide and document the long-term supply-chain source for the Python-3.12+
   `automa-ai` standalone dependency before publishing a standalone workflow.
3. Align `measures/approved/` with the live measure registry before exposing it
   as the trusted measure source.
4. Design end-user configuration for runtime retention and installed-measure
   administration.
