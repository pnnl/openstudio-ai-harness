# OpenStudio AI

OpenStudio AI is a deployable agent harness for building-energy modeling
workflows. The project packages a trusted MCP runtime, reviewed knowledge,
workflow skills, SDK lookup, runtime learning contracts, and host adapters for
Claude Code, Codex, and future agent shells.

The current direction is:

```text
OpenStudio AI runtime kernel
  openstudio_mcp + SDK index + approved measures + future blackboard tools
        |
        v
Host adapters
  Claude Code plugin, Codex plugin, AUTOMA-AI YAML agent
        |
        v
Engineering workflows
  inspect/edit models, run simulations, query results, retrieve targeted SDK
  and OpenStudio Standards knowledge, propose learning candidates
```

For developer ownership and roadmap details, see:

- `docs/DEVELOPER_GUIDANCE.md`
- `docs/PACKAGING_NORTHSTAR.md`

## Current Baseline

OpenStudio AI currently includes:

- `openstudio_mcp/`, a real MCP server for model lifecycle, simulation,
  results, SDK docs, and approved measures;
- Claude Code plugin export;
- Codex plugin export;
- AUTOMA-AI YAML agent spec for local development and A2A operation;
- generated HVAC child skills from one YAML spec per skill plus a shared Jinja
  template;
- reviewed knowledge folders and SDK wiki packs;
- learning schemas and guidance exported as skill references for candidate
  drafting; host plugins do not persist candidate records;
- manual developer learning pipeline that distills logs into reviewable
  candidates;
- MCP-backed blackboard schemas and operation helpers;
- tests covering adapter export, learning, SDK docs, CLI behavior, and MCP
  smoke behavior.

The first runtime packaging phase is complete: the package exposes
`openstudio-ai-mcp`, and Claude/Codex exports support local, installed, and
marketplace runtime modes. The main deployment gap is now clean-install proof
and runtime readiness validation across real environments, including stronger
`openstudio-ai doctor` checks and OpenStudio-installed MCP verification.

## Product Boundary

OpenStudio AI has two surfaces.

Runtime harness:

- consumed by Claude Code, Codex, AUTOMA-AI, or another host;
- includes MCP config, instructions, skills, reviewed knowledge, SDK lookup
  assets, approved measures, learning schemas, and blackboard schemas;
- should stay compact, trusted, and portable.

Developer workbench:

- used to build, test, review, validate, and promote assets;
- includes source skill specs, Jinja templates, learning pipelines, evals,
  review queues, scripts, candidate measures, and policy drafts;
- is not exported wholesale to normal host-agent users.

## Architecture

### MCP Runtime Kernel

`openstudio_mcp/` is the deterministic runtime surface. It owns operations that
should not be left to free-form agent scripting:

- `model_*`: model lifecycle, weather/design-day setup, measure application,
  and validation;
- `sim_*`: asynchronous sandboxed simulation execution and artifact tracking;
- `results_*`: SQL-backed result queries and summaries;
- `sdk_docs_*`: targeted OpenStudio SDK documentation lookup;
- approved measures: reviewed deterministic workflows exposed through policy.

Near-term runtime work should prove the installed command path end to end and
make `openstudio-ai doctor` validate SDK index, approved measures, runtime
storage, SQLite registry creation, MCP startup, and OpenStudio readiness.

The MCP server now maintains a lightweight local SQLite registry under the
configured workspace root. The registry stores metadata for artifacts, jobs,
and workspaces so MCP tools can report storage usage and safely prune old local
workspace files without storing OSM/SQL/log blobs in SQLite.

Storage pruning is not automatic. The user or agent must initiate cleanup by
calling `runtime_storage_usage`, reviewing `runtime_prune_preview`, and then
calling `runtime_prune` only after approval. The detailed process diagrams live
in `openstudio_mcp/README.md`.

### Host Adapters

`adapters/` turns the host-agnostic harness into host-specific packages.

Claude Code export:

```bash
.venv/bin/python -m adapters.claude_code_adapter export-plugin \
  --output-dir /tmp/openstudio-ai-plugin
```

Claude Code install flow:

```text
/plugin marketplace add /tmp/openstudio-ai-plugin
/plugin install openstudio-ai@openstudio-ai-local
/reload-plugins
```

Codex export:

```bash
openstudio-ai export codex \
  --output-dir /tmp/openstudio-ai-codex-plugin \
  --runtime-mode marketplace
```

Codex install flow:

```bash
codex plugin marketplace add /tmp/openstudio-ai-codex-plugin
```

After enabling the plugin, add the managed OpenStudio modeler policy to the
Codex project that will use it:

```bash
openstudio-ai install codex --target-dir /path/to/codex-project
```

This creates `AGENTS.md` when it is absent. Use `--dry-run` to preview; an
existing unmanaged `AGENTS.md` requires `--force` before appending the marked
block without replacing project instructions.

Exported packages keep host-visible content in native plugin locations. Claude
Code exports use Claude plugin folders such as `skills/`, `agents/`,
`monitors/`, and `.mcp.json`. Codex exports use `.codex-plugin/plugin.json`,
`.mcp.json`, `CONNECTORS.md`, `README.md`, and `skills/`.

For both plugin exports, source prompts, knowledge packs, blackboard schemas, and
learning schemas are mapped into the `references/` folder of the skill that uses
them. They are not exported as root `knowledge/`, `instructions/`,
`blackboard/`, or `learning/` plugin folders.

### AUTOMA-AI Local Agent

The local AUTOMA-AI development agent is defined by:

- `standalone/openstudio_agent.yaml`
- `standalone/agent.py`
- `prompts/openstudio_agent.md`

It is useful for local development, A2A testing, telemetry, blackboard behavior,
and MCP integration work. It is not the only target runtime anymore.

### Skills And Knowledge

Skills represent workflow instructions. The VAV workflow is split into a parent
skill and smaller generated child skills so the agent can load only the phase it
needs.

Knowledge represents reviewed context. The next knowledge milestone is to build
token-light OpenStudio Standards HVAC system cards from:

```text
/Users/xuwe123/github/openstudio-standards/lib/openstudio-standards/prototypes/common/objects/Prototype.hvac_systems.rb
```

The target pattern is targeted retrieval:

1. query the HVAC system inventory;
2. retrieve one system card;
3. retrieve only needed SDK methods;
4. load only the child skill for the active phase;
5. load broad docs only after targeted lookup fails.

### Learning

OpenStudio AI has two learning paths.

Developer learning:

- manually triggered;
- reads telemetry, failure logs, warnings, corrections, and review notes;
- writes reviewable candidates to `learning/review_queue/`;
- requires review, eval linkage, and explicit promotion before trusted assets
  change.

Run the current deterministic curation pass:

```bash
.venv/bin/python -m learning.developer_pipeline.run_pipeline
```

Host learning contracts:

- exported to Claude/Codex as skill-local instructions and schemas;
- let host agents draft candidate recipes, session lessons, or measures without
  claiming that the candidate was persisted;
- never directly updates trusted `knowledge/`, `skills/`, `openstudio_mcp/`, or
  `measures/approved/`.

Host learning contracts can guide drafting. Developer learning can promote.

### Blackboard

The blackboard is now exposed through MCP tools and persisted in the local MCP
SQLite runtime registry. It helps parent workflow skills preserve assumptions,
phase progress, created objects, warnings, and validation results across long
tasks.

For this harness evaluation, do not use AUTOMA-AI native blackboard tools.
Use MCP tools such as `blackboard_initialize_workflow`,
`blackboard_update_state_patch`, `blackboard_get_phase_state`, and
`blackboard_mark_step_complete`.

## Setup For Local Development

1. Copy `sample.env` to `.env`.
2. Set the model provider values used by `standalone/openstudio_agent.yaml`.
3. Ensure `openstudio` is on `PATH`, or set `OPENSTUDIO_PATH` to select a local
   OpenStudio CLI executable explicitly.
4. Ensure the configured Python executable can import the OpenStudio Python SDK
   when using SDK inspection/editing.
5. Optional: set `OPENSTUDIO_SDK_DOCS_DIR` to override the bundled
   OpenStudio SDK YAML documentation directory.

The YAML spec reads local environment settings and configures:

- MCP client connection;
- bounded host Python execution workspace;
- skills and knowledge roots;
- telemetry JSONL path;
- Python script failure log path;
- local JSON blackboard path.

## Run Locally

Start the AUTOMA-AI agent and MCP server:

```bash
uv run --project standalone python standalone/agent.py
```

Optional Streamlit UI:

```bash
uv run --project standalone streamlit run standalone/ui.py
```

Combined launcher:

```bash
bash standalone/run_all.sh
```

## SDK Documentation Tools

The `sdk_docs_*` tools look up OpenStudio SDK class and method information from
bundled YAML files at `openstudio_mcp/sdk_docs/docs/api/`. Set
`OPENSTUDIO_SDK_DOCS_DIR` to override the bundled directory with a custom one.

Available MCP tools include:

- `sdk_docs_route`
- `sdk_docs_find_classes`
- `sdk_docs_list_methods`
- `sdk_docs_get_method`
- `sdk_docs_search_methods`

Build an optional local cache summary:

```bash
python3 scripts/build_sdk_doc_index.py \
  --docs-dir openstudio_mcp/sdk_docs/docs \
  --output .sdk_doc_index.json
```

The long-term plan is to move from broad SDK context packs to compact SDK method
and Standards HVAC indexes queried through MCP.

## Measures

Approved deterministic workflows live under `measures/approved/` and are
registered through policy.

Key files:

- `policy/measure_registry.yaml`
- `measures/approved/`
- `measures/candidates/`
- `openstudio_mcp/runtime/measure_registry.py`

Runtime proposal is allowed through learning candidates, but publication into
approved measures requires review and validation.

## Verification

Focused test set for the current OpenStudio AI harness:

```bash
.venv/bin/python -m pytest -q \
  tests/test_openstudio_learning_pipeline.py \
  tests/test_openstudio_codex_adapter.py \
  tests/test_openstudio_claude_code_adapter.py \
  tests/test_openstudio_sdk_docs.py \
  tests/test_mcp_openstudio_smoke.py
```

## Troubleshooting

- If MCP tools are unavailable, confirm the MCP server startup log under
  `logs/`.
- If plugin export works but the host cannot start MCP, remember the current
  export points to the local checkout and active Python environment.
- If `sim_run` fails, verify `OPENSTUDIO_PATH` points to a valid OpenStudio
  executable and the model has a valid weather file or one is supplied through
  MCP setup.
- Simulation runtime files are generated under
  `.openstudio_mcp_workspace/<job_id>/`.
- If SDK lookup fails, verify `OPENSTUDIO_SDK_DOCS_DIR` points to a directory
  containing `api/classes-<version>.yaml.gz` (or the legacy
  `api/classes.yaml.gz`), or that the bundled docs at
  `openstudio_mcp/sdk_docs/docs/` are present. `openstudio-ai doctor --json`
  reports the resolved path and selected documentation version.
- If measure application fails, verify `policy/measure_registry.yaml` and the
  approved measure entrypoint.
- If local storage grows too large, use `runtime_storage_usage` and
  `runtime_prune_preview` before calling `runtime_prune`.

## File Map

- `standalone/agent.py`: local AUTOMA-AI YAML-backed MCP and A2A bootstrap.
- `adapters/`: Claude Code and Codex export/install logic.
- `harness/`: host-agnostic package manifest, registry, and loader.
- `standalone/openstudio_agent.yaml`: local AUTOMA-AI agent spec.
- `prompts/`: system prompt and harness, blackboard, learning, and promotion
  contracts.
- `openstudio_mcp/`: MCP runtime kernel.
- `openstudio_mcp/tools/`: model, simulation, results, and SDK docs tools.
- `openstudio_mcp/runtime/`: workspace, artifact, job, and measure registry
  managers.
- `skills/`: parent skills, generated child skills, specs, and templates.
- `knowledge/`: reviewed knowledge base and SDK wiki packs.
- `sdk_index/`: structured SDK and Standards knowledge index boundary.
- `blackboard/`: workflow-state operation helpers and schemas used by the MCP
  blackboard implementation.
- `learning/`: developer pipeline, developer agent contract, runtime pipeline,
  schemas, and review queue.
- `evals/`: workflow, planning, promotion, and regression eval area.
- `measures/approved/`: reviewed deterministic measures.
- `measures/candidates/`: proposed measures pending review.
- `policy/`: allowlists, run gates, measure registry, and promotion policy.
- `docs/PACKAGING_NORTHSTAR.md`: packaging roadmap and distribution plan.
- `docs/DEVELOPER_GUIDANCE.md`: developer-facing product boundary and roadmap.

## Near-Term Roadmap

Runtime distribution:

- harden `openstudio-ai doctor` into the primary runtime readiness check;
- validate source, editable install, wheel install, and marketplace exports in
  fresh environments;
- add CI for package, CLI, and adapter export checks;
- run OpenStudio-installed MCP verification with `OPENSTUDIO_PATH` configured;
- package SDK index and approved measures as runtime assets;
- continue MCP-backed blackboard reliability checks for long-running tasks.

SDK and knowledge optimization:

- extract HVAC system inventory from OpenStudio Standards;
- build function trace graph for `model_add_hvac_system`;
- create token-light HVAC system cards;
- expose Standards HVAC queries through MCP;
- add SDK method micro-index;
- evaluate token savings against broad-context loading.
