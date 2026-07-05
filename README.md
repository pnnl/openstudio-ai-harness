# OpenStudio AI Harness

OpenStudio AI Harness packages a local MCP runtime, host adapters, skills,
knowledge, and workflow-state tools for AI-assisted building-energy modeling.

## Current Capabilities

- OpenStudio MCP server for model lifecycle, simulation, results, SDK lookup,
  runtime storage, and MCP-backed blackboard workflow state.
- Claude Code plugin export.
- Codex plugin export.
- Runtime learning schemas and candidate folders.
- HVAC workflow skills and generated child skills.
- Reviewed OpenStudio SDK knowledge packs.
- Packaging north-star plan for stable `pip install` and marketplace agentic
  installation paths.

## Development Setup

From this repository root:

```bash
python -m pip install -e ".[dev]"
```

Install the runtime package after it is published:

```bash
python -m pip install openstudio-ai
OPENSTUDIO_PATH=/path/to/openstudio-3.10-or-newer openstudio-ai doctor
openstudio-ai-mcp --transport stdio
```

Run focused tests:

```bash
python -m pytest -q \
  tests/test_mcp_openstudio_smoke.py \
  tests/test_openstudio_sdk_docs.py \
  tests/test_openstudio_learning_pipeline.py \
  tests/test_openstudio_codex_adapter.py \
  tests/test_openstudio_claude_code_adapter.py
```

Start the MCP server in stdio mode:

```bash
openstudio-ai-mcp --transport stdio
```

Export local development plugins:

```bash
python -m adapters.claude_code_adapter export-plugin \
  --output-dir /tmp/openstudio-ai-claude-plugin

python -m adapters.codex_adapter export-plugin \
  --output-dir /tmp/openstudio-ai-codex-plugin
```

Export marketplace-oriented plugins that expect an installed runtime command:

```bash
python -m adapters.claude_code_adapter export-plugin \
  --output-dir /tmp/openstudio-ai-claude-plugin \
  --runtime-mode marketplace

python -m adapters.codex_adapter export-plugin \
  --output-dir /tmp/openstudio-ai-codex-plugin \
  --runtime-mode marketplace
```

## Key Docs

- [Harness Details](docs/HARNESS_DETAILS.md)
- [Packaging North Star](docs/PACKAGING_NORTHSTAR.md)
- [Runtime Installation Contract](docs/RUNTIME_INSTALLATION_CONTRACT.md)
- [Marketplace Install Guide](docs/MARKETPLACE_INSTALL_GUIDE.md)
- [PyPI Release Guide](docs/RELEASE.md)
- [Developer Guidance](docs/DEVELOPER_GUIDANCE.md)

## Runtime State

Local runtime state is intentionally ignored by Git:

- `.openstudio_mcp_workspace/`
- `.openstudio_ai_blackboards/`
- `logs/`
- `outputs/`

The MCP runtime uses local SQLite metadata and filesystem workspaces for large
OSM, SQL, and log artifacts.
