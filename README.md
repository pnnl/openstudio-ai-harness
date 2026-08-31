# OpenStudio AI Harness

OpenStudio AI Harness packages a local MCP runtime, host adapters, skills,
knowledge, and workflow-state tools for AI-assisted building-energy modeling.

## Current Capabilities

- OpenStudio MCP server for model lifecycle, simulation, results, SDK lookup,
  runtime storage, and MCP-backed blackboard workflow state.
- Claude Code plugin export.
- Codex plugin export.
- Learning contracts for candidate drafting; host plugins do not persist
  candidate records yet.
- HVAC workflow skills and generated child skills.
- Reviewed OpenStudio SDK knowledge packs.
- Packaging north-star plan for stable `pip install` and marketplace agentic
  installation paths.

## Development Setup

From this repository root:

```bash
python -m pip install -e ".[dev]"
```

The production harness supports Python 3.10 or newer. The `dev` extra installs
its test and release tools.

Install the runtime package after it is published:

```bash
python -m pip install openstudio-ai
openstudio-ai install-runtime
openstudio-ai doctor
openstudio-ai-mcp --transport stdio
```

OpenStudio AI requires both the PyPI `openstudio` Python package, installed as
a dependency of `openstudio-ai`, and the native OpenStudio application/CLI. Set
`OPENSTUDIO_PATH` when the CLI is not on `PATH` or when selecting a specific
installation.

The base package is the recommended install for Claude Code, Codex, and other
marketplace-style host integrations. It intentionally does not install
AUTOMA-AI or Streamlit. The standalone local AI app is a separate Python 3.12+
development environment:

```bash
uv sync --project standalone
uv run --project standalone python standalone/agent.py
uv run --project standalone streamlit run standalone/ui.py
```

Standalone mode requires Python 3.12 and user-provided LLM configuration, such
as API keys or model endpoint settings, in the local environment.

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
openstudio-ai export claude \
  --output-dir /tmp/openstudio-ai-claude-plugin \
  --runtime-mode local

openstudio-ai export codex \
  --output-dir /tmp/openstudio-ai-codex-plugin \
  --runtime-mode local
```

Export marketplace-oriented plugins that expect an installed runtime command:

```bash
openstudio-ai export claude \
  --output-dir /tmp/openstudio-ai-claude-plugin \
  --runtime-mode marketplace

openstudio-ai export codex \
  --output-dir /tmp/openstudio-ai-codex-plugin \
  --runtime-mode marketplace
```

Export a publishable repository containing both host packages, generated install
guides, and source provenance:

```bash
openstudio-ai export marketplace \
  --output-dir /path/to/openstudio-ai-plugins \
  --runtime-mode marketplace \
  --force
```

This produces a generated release tree; it validates both exports before
completion. Keep the harness repository as the source of truth and do not edit
generated plugin files directly.

After installing the Codex marketplace plugin, add the shared OpenStudio
modeler policy to each Codex project that should route plain-language
OpenStudio requests through the workflow orchestrator:

```bash
openstudio-ai install codex --target-dir /path/to/codex-project
```

This creates `AGENTS.md` when it does not exist. Use `--dry-run` to preview;
an existing unmanaged `AGENTS.md` requires `--force` before the managed block
is appended.

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
