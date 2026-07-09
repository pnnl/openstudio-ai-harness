# OpenStudio AI Harness Handoff

## Current Status

- Package version: `0.1.3`.
- The package exposes an OpenStudio MCP runtime, Claude Code and Codex plugin
  exports, trusted skills and references, runtime learning contracts, and
  MCP-backed SQLite workflow state.
- Claude and Codex exports use host-native plugin structures. Shared reference
  routing is declared in `harness/asset_manifest.yaml`.
- Marketplace exports start the installed `openstudio-ai-mcp` command. Local
  exports start `python -m openstudio_mcp.server` from the source virtualenv.
- The base package requires the OpenStudio Python package. Model edits,
  simulation, and measures also require the native OpenStudio application or
  CLI through `OPENSTUDIO_PATH` or `PATH`.
- AUTOMA-AI and Streamlit are only supplied through the `standalone` extra for
  local developer testing. Host-facing skills use host-neutral Python execution
  instructions.

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

## Next Steps

1. Add CI for focused tests, build, wheel-content inspection, `doctor`, and
   marketplace export validation.
2. Decide and document the long-term supply-chain source for the optional
   `automa-ai` standalone dependency before PyPI publication.
3. Align `measures/approved/` with the live measure registry before exposing it
   as the trusted measure source.
4. Design end-user configuration for runtime retention and installed-measure
   administration.
