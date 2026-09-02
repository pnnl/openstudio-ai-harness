# OpenStudio AI Developer Guide

This guide is for developers joining the OpenStudio AI harness work. It explains
what each repository folder is for, what can be changed safely, how assets move
from candidate work into trusted runtime content, and how to test the harness
locally, in Claude Code, and in Codex.

## Table Of Contents

- [Mental Model](#mental-model)
- [Environment Setup](#environment-setup)
- [Folder Ownership](#folder-ownership)
- [Plugin Registry](#plugin-registry)
  - [Manifest Schema](#manifest-schema)
  - [Registration Order](#registration-order)
  - [Example: Develop A New Skill](#example-develop-a-new-skill)
  - [Example: Develop A Reference For An Existing Skill](#example-develop-a-reference-for-an-existing-skill)
  - [Example: Develop A Claude Subagent Prompt](#example-develop-a-claude-subagent-prompt)
- [End-User Exposure And TODOs](#end-user-exposure-and-todos)
- [Promotion Rules](#promotion-rules)
- [Skill Development](#skill-development)
- [Host Python Execution Boundary](#host-python-execution-boundary)
- [Blackboard Boundary](#blackboard-boundary)
- [Local AUTOMA-AI Testing](#local-automa-ai-testing)
- [CLI And Runtime Checks](#cli-and-runtime-checks)
- [Claude Code Plugin Testing](#claude-code-plugin-testing)
  - [Reloading Claude Code Plugins](#reloading-claude-code-plugins)
- [Codex Plugin Testing](#codex-plugin-testing)
- [Adapter Development Rules](#adapter-development-rules)
- [Package And Release Checks](#package-and-release-checks)
- [Common Mistakes](#common-mistakes)
- [What To Update When You Change Things](#what-to-update-when-you-change-things)

## Mental Model

OpenStudio AI has three layers:

1. Developer workbench: source specs, candidates, evals, review queues, and
   tools used to build the product.
2. Trusted runtime harness: MCP tools, skills, prompts, knowledge, approved
   measures, schemas, and package metadata that are safe to ship.
3. Host plugin exports: Claude Code and Codex specific plugin layouts generated
   from the trusted runtime harness.

Do not edit exported plugin folders as source of truth. Change the repo assets,
then regenerate the export.

```text
Developer workbench
  skills/specs, skills/templates, learning, evals, measures/candidates
        |
        v
Trusted runtime harness
  openstudio_mcp, skills/*.md, prompts, knowledge, measures/approved, schemas
        |
        v
Host-specific export
  Claude Code plugin or Codex plugin
```

## Environment Setup

Use Python 3.10 or newer for the production harness. The optional AUTOMA-AI
standalone development environment requires Python 3.12 or newer.

Full developer setup:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

The `dev` extra installs test/build tools. AUTOMA-AI and Streamlit live in the
separate `standalone/` Python 3.12+ development project.

Base runtime setup:

```bash
python -m pip install openstudio-ai
openstudio-ai install-runtime
openstudio-ai doctor
```

The base runtime is what Claude Code and Codex marketplace users should need. It
does not include AUTOMA-AI or Streamlit because those hosts provide the agent
shell.

OpenStudio has two requirements:

- Python package: `openstudio>=3.10.0`.
- Native OpenStudio application or CLI resolved through `OPENSTUDIO_PATH`, a
  user-confirmed path saved by `openstudio-ai configure-openstudio`, or `PATH`.

The runtime resolves `OPENSTUDIO_PATH` first, the saved runtime configuration
second, and `openstudio` from `PATH` last.

## Folder Ownership

Use this table when deciding where a change belongs.

| Path | Purpose | Put Here | Do Not Put Here | Export Behavior |
| --- | --- | --- | --- | --- |
| `openstudio_mcp/` | MCP server and tool runtime | Model lifecycle, simulation, results, SDK doc, approved measure, runtime state tools | Host-specific plugin layout, markdown-only instructions | Shipped in the package and used by `.mcp.json` |
| `openstudio_mcp/compatibility.py` | Plugin-to-MCP interface contract | Package/contract metadata and compatibility checks | Host-specific rendering rules or individual skill content | Used by adapters, `doctor`, and MCP startup |
| `adapters/runtime_helpers.py` | Shared marketplace setup helper rendering | Cross-host `doctor_runtime.py` and `install_runtime.py` content | Claude/Codex-specific plugin layout or reload guidance | Called by both adapters; exports identical helpers except host reload text |
| `openstudio_mcp/runtime/` | Runtime registry and SQLite-backed state | Durable job/artifact/storage/blackboard persistence code | Source knowledge or skill content | Used by MCP tools at runtime |
| `openstudio_mcp/tools/` | MCP tool registration | Tool wrappers that expose service behavior | Business logic that belongs in services | Used by MCP server |
| `openstudio_mcp/simulation/`, `results/`, `sdk_docs/`, `measures/` | Runtime service modules | Deterministic runtime operations | Host adapter behavior | Used by MCP tools |
| `skills/*.md` | Trusted runtime skills | Hand-authored parent skills and generated child skill outputs | Draft notes, unreviewed lessons, specs | Exported as host skills |
| `skills/specs/` | Source specs for generated skills | YAML definitions for generated HVAC child skills | Runtime-only skill markdown edits | Not exported directly |
| `skills/templates/` | Skill generation templates | Shared Jinja templates | One-off skill content | Not exported directly |
| `prompts/` | Shared contracts and orchestration prompts | System prompt, blackboard contract, learning contract, promotion rules | Host-specific plugin manifests | Exported into skill `references/` where needed |
| `knowledge/` | Reviewed knowledge base | Trusted SDK recipes and wiki packs | Raw notes, generated candidates, unresolved findings | Exported into relevant skill `references/` |
| `sdk_index/` | Structured SDK index work | Index builders, graph/index data, lookup experiments | Broad markdown docs already owned by `knowledge/` | Exposed through MCP when lookup is implemented |
| `blackboard/` | Shared workflow-state helpers and schemas | State transformations, snapshots, and JSON schemas for long-running task state | JSON-file persistence or runtime SQLite files | Schemas are exported into `openstudio-workflow-state/references/`; SQLite state is owned by the MCP runtime |
| `learning/harness_pipeline/` | Learning contract sources | Candidate schemas and reference guidance for proposal/capture skills | Host-executable learning behavior or trusted promoted assets | Selected contract files are exported into learning skill `references/`; Python helpers are not invoked by Claude Code or Codex |
| `learning/developer_pipeline/` | Deterministic developer learning | Review/promotion pipeline code | Host runtime code | Developer only |
| `learning/developer_agent/` | AUTOMA-AI developer reflection contract | Agent spec for assisted candidate generation | Trusted assets or runtime plugin code | Developer only |
| `learning/review_queue/` | Candidate review queue | Untrusted candidate lessons/assets awaiting review | Anything treated as product truth | Developer only |
| `measures/approved/` | Intended trusted measure target | Reviewed deterministic OpenStudio measures after validation | Draft measures | TODO: current registry points at `measures/add_daylighting.py`; align approved folder and registry before treating this as the exposed source |
| `measures/candidates/` | Draft measures | Proposed measures awaiting review/evals | Approved runtime measures | Excluded from wheel/runtime export |
| `harness/` | Host-agnostic package registry | Manifest and asset discovery logic | Host-specific export decisions | Used by adapters |
| `adapters/` | Host-specific install/export logic | Claude Code and Codex plugin mapping | Product behavior or trusted modeling logic | Generates plugin folders |
| `standalone/` | Local AUTOMA-AI agent/UI project | Agent spec, launchers, UI, and AUTOMA-AI tests | Claude/Codex plugin manifests | Python 3.12+ development only |
| `evals/` | Eval cases and datasets | Regression cases for skills, planning, measures, knowledge | Runtime state or generated logs | Developer only |
| `policy/` | Governance and promotion policies | Review, retention, allowlist, and runtime gate policies | Runtime executable code | Developer only unless referenced by docs |
| `scripts/` | Build/generation scripts | Skill generation, index generation, repo maintenance scripts | Runtime MCP tool implementations | Some scripts may ship in wheel, but not as plugin UI |
| `tests/` | Automated tests | Focused unit, adapter, MCP, CLI, and integration tests | Runtime assets | Developer only |
| `docs/` | Developer and user documentation | Stable guides, release notes, architecture docs | Runtime state | Shipped as package docs |
| `state/`, `logs/`, `outputs/` | Local working artifacts | Local sessions, snapshots, logs, generated outputs | Trusted assets or source specs | Not trusted; do not promote without review |
| `.openstudio_mcp_workspace/` | Local MCP runtime workspace | Local test jobs/artifacts created by MCP | Source code | Excluded from package/export |
| `tests/fixtures/` | Local OpenStudio test fixtures | OSM and EPW files required by explicit test cases | Runtime assets, user models, or marketplace payload | Excluded from wheels and plugin exports |
| `standalone/agent.py` | Local AUTOMA-AI bootstrap | Standalone local agent entrypoint | Claude/Codex-specific logic | Used only in standalone mode |
| `standalone/ui.py` | Local Streamlit UI | Standalone UI code | Host plugin logic | Used only in standalone mode |
| `cli.py` | Package CLI | `doctor`, `install-runtime`, `repair`, `export`, `validate-export` | Host-specific implementation details beyond command routing | Shipped as `openstudio-ai` |
| `pyproject.toml` | Package metadata | Dependencies, extras, scripts, build include/exclude rules | Runtime state | Defines release package |
| `README.md`, `HANDOFF.md` | Top-level orientation | Stable overview and current status | Deep implementation docs | Shipped/read by developers |

## Plugin Registry

`harness/asset_manifest.yaml` is the product-plugin registry. It declares every
exported OpenStudio skill, Claude agent, and skill-owned reference. Adapters
translate that registry into host-native files; they do not define modeling
workflows themselves.

The machine-readable schema lives at `harness/asset_manifest.schema.json`. The
loader validates the same structure during export.

### Manifest Schema

Top-level fields:

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `$schema` | string | Optional | Relative path to `asset_manifest.schema.json`. |
| `version` | integer | Yes | Manifest schema version. Currently only `3` is valid. |
| `skills` | list | Yes | Canonical product skills exported to one or both hosts. |
| `agents` | list | Yes | Host-specific generated agents. Currently Claude only. |
| `references` | list | Yes | Supporting sources copied into an owning product skill. |

Product skill fields:

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `id` | string | Yes | Stable plugin skill identifier, such as `simulate`. |
| `source` | string | Yes | Canonical `skills/*.md` source file. |
| `hosts` | list | Yes | Hosts that receive the skill: `claude`, `codex`, or both. |

Agent fields use the same `id`, `source`, and `hosts` structure. An agent is
currently exported only to Claude. Reference fields are `source` and `owners`;
each owner supplies `hosts`, `skill`, and optional `subdirectory`. The adapter
derives `skills/<skill>/references/<source filename>`.

Developers first decide whether the work is a product skill, a Claude agent, or
a supporting reference; the manifest section makes that distinction explicit.

### Registration Order

Register every product skill under `skills` before assigning references to it.
Each `owners[].skill` value must exactly match a registered skill `id`, and the
owner hosts must be a subset of that skill's hosts. The loader validates skills
first and rejects unknown or host-incompatible reference owners.

Keep the manifest in this logical order:

1. `skills`: product behavior exported to one or both hosts.
2. `agents`: host-specific system prompts.
3. `references`: supporting files attached to registered product skills.

YAML mapping order is not a runtime dependency, but keeping this order makes
the registry easy to review and ensures a developer can find the owner before
adding its references.

### Product And Host Boundary

Manifest-register product behavior: OpenStudio model editing, simulation,
results, HVAC workflows, workflow state, learning guidance, and supporting
references. Keep marketplace setup infrastructure in adapters: setup, doctor,
repair, installer scripts, MCP configuration, and marketplace metadata. These
host-specific files are generated only in marketplace mode and are verified by
adapter tests.

Current registry mappings:

| Source | Registry Entry | Hosts | Derived Export Location | Notes |
| --- | --- | --- | --- | --- |
| `skills/openstudio_modeling_orchestrator.md` | `openstudio-modeling-orchestrator` skill | Codex | `skills/openstudio-modeling-orchestrator/SKILL.md` | Codex-only orchestration skill |
| `prompts/openstudio_agent.md` | `openstudio-modeler` agent | Claude | `agents/openstudio-modeler.md` | Claude system prompt; not a Codex reference |
| `prompts/blackboard_contract.md` | `openstudio-workflow-state` | Both | Derived skill reference | Keep schema and contract together |
| `prompts/learning_contract.md` | `propose-measure`, `capture-session-lesson` | Both | Derived skill references | Shared learning contract |
| `prompts/promotion_rules.md` | `propose-measure` | Both | Derived skill reference | Candidate promotion guidance |
| `knowledge/openstudio_sdk_recipes.md` | `openstudio-sdk-model-editor` | Both | Derived skill reference | Reviewed SDK recipes |
| `knowledge/openstudio_sdk_wiki/*.md` | `openstudio-sdk-model-editor`, `sdk_wiki` subdirectory | Both | Derived skill reference | Grouped SDK wiki pages |
| `blackboard/schemas/*.json` | `openstudio-workflow-state` | Both | Derived skill references | Long-running workflow state schemas |
| `learning/harness_pipeline/schemas/*.json` | Learning proposal/capture skills | Both | Derived skill references | Contract-only; host plugins do not run helper modules |

Manifest entry shape:

```yaml
skills:
  - id: simulate
    source: skills/simulate.md
    hosts: [claude, codex]
agents:
  - id: openstudio-modeler
    source: prompts/openstudio_agent.md
    hosts: [claude]
references:
  - source: prompts/blackboard_contract.md
    owners:
      - hosts: [claude, codex]
        skill: openstudio-workflow-state
```

When a developer adds a product skill, agent, or reference that must be exported,
they must update `harness/asset_manifest.yaml` and adapter tests in the same
change.

### Example: Develop A New Skill

Use this path when the agent needs a new workflow or tool-use procedure.

1. Create `skills/my-new-skill.md` with skill frontmatter:

   ```markdown
   ---
   name: my-new-skill
   description: When to use this skill, written for the host agent.
   ---

   # My New Skill

   Use this skill when...
   ```

2. Put detailed background material in a separate reference file if the skill
   would become too large:

   ```text
   knowledge/my_new_skill_reference.md
   ```

3. Register the product skill and its reference in `harness/asset_manifest.yaml`:

   ```yaml
   skills:
     - id: my-new-skill
       source: skills/my-new-skill.md
       hosts: [claude, codex]
   references:
     - source: knowledge/my_new_skill_reference.md
       owners:
         - hosts: [claude, codex]
           skill: my-new-skill
   ```

4. Add adapter tests that assert the exported skill and reference exist.
5. Run:

   ```bash
   .venv/bin/python -m pytest -q \
     tests/test_harness_asset_manifest.py \
     tests/test_openstudio_claude_code_adapter.py \
     tests/test_openstudio_codex_adapter.py
   ```

### Example: Develop A Reference For An Existing Skill

Use this path when the skill already exists and only needs supporting context.

1. Add the source file under the source-of-truth folder:

   ```text
   prompts/my_contract.md
   knowledge/my_sdk_note.md
   blackboard/schemas/my_schema.json
   learning/harness_pipeline/schemas/my_candidate.schema.json
   ```

2. Choose the owning skill and the host list. Use one owner entry for a shared
   destination, or add multiple owner entries when more than one skill needs the
   same source.

3. Add the skill-owned reference:

   ```yaml
   references:
     - source: prompts/my_contract.md
       owners:
         - hosts: [claude, codex]
           skill: openstudio-workflow-state
   ```

4. Do not add root plugin folders such as `knowledge/`, `instructions/`, or
   `blackboard/`. The adapter will place references under the owning skill.

### Example: Develop A Claude Subagent Prompt

Use this path when Claude needs a real `agents/*.md` subagent file.

1. Add or update the source prompt under `prompts/`.
2. Register it under `agents` in `harness/asset_manifest.yaml`:

   ```yaml
   agents:
     - id: my-subagent
       source: prompts/my_subagent.md
       hosts: [claude]
   ```

3. Add adapter rendering code if this is a new generated agent file. The
   manifest identifies the source and agent name; it does not automatically
   invent host-specific frontmatter.
4. Add tests that assert `agents/my-subagent.md` exists in the Claude export.
5. If Codex needs comparable orchestration behavior, create a separate canonical
   Codex skill under `skills/` and register it under `skills`:

   ```yaml
   skills:
     - id: my-orchestrator
       source: skills/my_orchestrator.md
       hosts: [codex]
   ```

Do not copy a Claude agent prompt into Codex as a reference. Codex behavior
belongs in a canonical Codex skill source.

## End-User Exposure And TODOs

| Capability | Exposed To End Users Today | How It Is Exposed | Not Exposed / TODO |
| --- | --- | --- | --- |
| SDK knowledge references | Indirectly | Host skills load manifest-routed `references/`; MCP SDK docs tools also expose curated SDK docs | TODO: topic-level retrieval metadata when SDK index routing is ready |
| Agent prompts | Partially | `harness/asset_manifest.yaml` declares Claude agents separately from Codex product skills; Claude uses `agents/openstudio-modeler.md` | TODO: clearer host UX for selecting specialized agents/orchestrators |
| Blackboard schemas | Indirectly | Exported as `openstudio-workflow-state/references/`; MCP tools create/read/update SQLite state | Not a user-editable schema surface; TODO: clearer host UX for starting/resuming named workflows |
| Approved measures | Partially | End users can call `model_list_measures` and `model_apply_measure` for measures allowed by `policy/measure_registry.yaml` | Users cannot add/approve measures through MCP today. TODO: admin/developer workflow for adding candidate measures, validating them, promoting to approved, and reloading registry safely |
| `measures/approved/` folder | Not meaningfully used yet | It is the intended trusted target folder | Current registered measure points at `measures/add_daylighting.py`. TODO: move approved scripts under `measures/approved/` or rename the trusted measure layout so policy and docs agree |
| Measure policy | No direct user editing | Runtime enforces `allowed`, `timeout_seconds`, and `args_schema` from `policy/measure_registry.yaml` | TODO: end-user/admin configuration story for enabling/disabling installed measures without editing package files |
| Runtime storage usage | Yes | MCP tool `runtime_storage_usage` | TODO: surface this in setup/doctor skills and host UX more explicitly |
| Prune preview | Yes | MCP tool `runtime_prune_preview`; does not delete files | TODO: expose retention settings and explanations in user-facing skills |
| Runtime prune | Yes, but should require approval | MCP tool `runtime_prune`; defaults prune unprotected measure workspaces and failed simulations only | TODO: user-configurable retention rules for successful simulations, old workspaces, max disk use, and pinned workspaces |

## Promotion Rules

Runtime agents and local learning jobs may propose candidates. They do not
promote trusted assets.

Promotion requires:

- source event or issue lineage;
- reviewer approval;
- a clear target folder;
- at least one focused test or eval covering the change;
- no hardcoded local developer paths;
- no unreviewed candidate content copied directly into trusted runtime folders.

Allowed promotion targets:

- `skills/*.md`
- `knowledge/`
- `sdk_index/`
- `openstudio_mcp/`
- `measures/approved/`
- `evals/`
- `docs/`

Never treat `state/`, `logs/`, `outputs/`, `learning/review_queue/`, or
`measures/candidates/` as product truth.

## Skill Development

Parent workflow skills are usually hand-authored in `skills/*.md`.

Generated HVAC child skills are edited through specs and templates:

```bash
.venv/bin/python scripts/generate_hvac_child_skills.py
.venv/bin/python -m pytest -q tests/test_openstudio_hvac_skill_generation.py
```

Edit:

- `skills/specs/hvac/*.yaml` for one child skill.
- `skills/templates/hvac_child_skill.md.j2` for shared child skill structure.

Do not edit generated child skill markdown directly unless the generator is also
updated or the skill is intentionally removed from generation.

## Host Python Execution Boundary

Runtime instructions must not assume AUTOMA-AI-only tools such as `run_python`.
Use host-neutral language:

- AUTOMA-AI may expose `run_python`.
- Claude Code may use Bash or script execution.
- Codex may use shell/Python execution.
- Some hosts may require asking the user to run a script manually.

Shared rule: show or reference the script, ask before running impactful actions,
keep model-editing scripts local-file only, and route simulation/results through
MCP tools when available.

## Blackboard Boundary

The blackboard contract describes long-running workflow state. It is not itself
SQLite persistence.

Persistence happens through MCP blackboard tools:

- `blackboard_initialize_workflow`
- `blackboard_get_workflow`
- `blackboard_update_state_patch`
- `blackboard_mark_step_complete`
- `blackboard_record_assumption`
- `blackboard_record_issue`
- `blackboard_snapshot_workflow`

The SQLite table is managed by `openstudio_mcp/runtime/state_store.py`. Plugin
exports include `workflow_state.schema.json`, `state_patch.schema.json`, and
`blackboard_contract.md` as references so host agents know how to call the MCP
tools. They do not create rows unless the tools are invoked.

## Local AUTOMA-AI Testing

Use this path when developing the standalone local agent or testing A2A behavior.

1. Install full developer dependencies:

   ```bash
   . .venv/bin/activate
   uv sync --project standalone
   ```

2. Configure environment:

   ```bash
   cp sample.env .env
   ```

   Add any required LLM API keys and set `OPENSTUDIO_PATH` if the OpenStudio CLI
   is not on `PATH`. Do not commit `.env`.

3. Run the local agent:

   ```bash
   uv run --project standalone python standalone/agent.py
   ```

4. Optionally run the Streamlit UI:

   ```bash
   uv run --project standalone streamlit run standalone/ui.py
   ```

5. Run focused AUTOMA-AI and MCP tests:

   ```bash
   uv run --project standalone python -m pytest -q standalone/tests
   ```

   Some smoke tests require an explicit `OPENSTUDIO_PATH` so they use a known,
   fixture-compatible OpenStudio version, as well as the required local
   resources.

Use AUTOMA-AI testing for local standalone behavior. Do not use AUTOMA-AI
assumptions in Claude/Codex runtime skills.

## CLI And Runtime Checks

Run these before testing host plugins:

```bash
.venv/bin/python -m cli doctor --json
.venv/bin/python -m cli install-runtime
.venv/bin/python -m cli validate-export --help
```

Focused checks for common edits:

```bash
.venv/bin/python -m pytest -q tests/test_openstudio_cli.py
.venv/bin/python -m pytest -q tests/test_openstudio_codex_adapter.py
.venv/bin/python -m pytest -q tests/test_openstudio_claude_code_adapter.py
```

Use `OPENSTUDIO_PATH=/path/to/openstudio` to test a specific OpenStudio CLI
installation; otherwise ensure `openstudio` is on `PATH`.

## Claude Code Plugin Testing

Use `--runtime-mode local` when testing from a source checkout. Local mode writes
an MCP config that starts the server with the repo virtualenv Python and
`python -m openstudio_mcp.server`.

Use `--runtime-mode marketplace` only when testing an installed package where
`openstudio-ai-mcp` is already visible on Claude Code's PATH.

1. Export:

   ```bash
   rm -rf /tmp/openstudio-ai-claude-test
   .venv/bin/python -m cli export claude \
     --output-dir /tmp/openstudio-ai-claude-test \
     --workspace-root "$PWD" \
     --runtime-mode local \
     --force
   ```

   On macOS, `/tmp` may appear as `/private/tmp`; they are the same location.

2. Validate:

   ```bash
   .venv/bin/python -m cli validate-export \
     /tmp/openstudio-ai-claude-test/openstudio-ai \
     --runtime-mode local

   claude plugin validate /tmp/openstudio-ai-claude-test/openstudio-ai
   ```

3. Install in Claude Code:

   ```text
   /plugin marketplace add /tmp/openstudio-ai-claude-test
   /plugin install openstudio-ai@openstudio-ai-local
   /reload-plugins
   ```

   During local development, use local scope unless you intentionally need user
   or project scope.

4. Confirm load:

   ```text
   /plugin list
   /plugin details openstudio-ai@openstudio-ai-local
   /openstudio-ai:doctor-openstudio-ai
   ```

Expected Claude plugin shape:

```text
openstudio-ai/
├── .claude-plugin/plugin.json
├── .mcp.json
├── README.md
├── settings.json
├── agents/openstudio-modeler.md
├── monitors/monitors.json
├── bin/
└── skills/
    ├── setup-openstudio-ai/
    │   ├── SKILL.md
    │   └── scripts/
    ├── openstudio-sdk-model-editor/
    │   ├── SKILL.md
    │   └── references/
    ├── openstudio-workflow-state/
    │   ├── SKILL.md
    │   └── references/
    ├── propose-measure/
    │   ├── SKILL.md
    │   └── references/
    └── capture-session-lesson/
        ├── SKILL.md
        └── references/
```

Claude Code does not automatically read arbitrary root `instructions/`,
`knowledge/`, `blackboard/`, or `learning/` folders. Put supporting material in
the relevant skill `references/` folder.

### Reloading Claude Code Plugins

Claude Code copies installed marketplace plugins into its cache. Editing the
export directory does not necessarily update the installed copy.

Clean reinstall:

```bash
claude plugin uninstall openstudio-ai@openstudio-ai-local --scope local --keep-data
rm -rf /tmp/openstudio-ai-claude-test
.venv/bin/python -m cli export claude \
  --output-dir /tmp/openstudio-ai-claude-test \
  --workspace-root "$PWD" \
  --runtime-mode local \
  --force
```

Then in Claude Code:

```text
/plugin marketplace add /tmp/openstudio-ai-claude-test
/plugin install openstudio-ai@openstudio-ai-local
/reload-plugins
```

If an old version remains, inspect scopes:

```bash
claude plugin list --json
claude plugin details openstudio-ai@openstudio-ai-local
claude plugin uninstall openstudio-ai@openstudio-ai-local --scope local --keep-data
claude plugin uninstall openstudio-ai@openstudio-ai-local --scope project --keep-data
claude plugin uninstall openstudio-ai@openstudio-ai-local --scope user --keep-data
```

Ignore "not installed" messages for scopes you did not use.

## Codex Plugin Testing

Codex export creates a local marketplace folder with `.agents/plugins` metadata
and a plugin under `plugins/openstudio-ai/`.

1. Export:

   ```bash
   rm -rf /tmp/openstudio-ai-codex-test
   .venv/bin/python -m cli export codex \
     --output-dir /tmp/openstudio-ai-codex-test \
     --workspace-root "$PWD" \
     --runtime-mode local \
     --force
   ```

   Use `--runtime-mode local` for source-checkout MCP testing. Use
   `marketplace` only when `openstudio-ai-mcp` is installed and visible to Codex.

2. Validate:

   ```bash
   .venv/bin/python -m cli validate-export \
     /tmp/openstudio-ai-codex-test/plugins/openstudio-ai \
     --runtime-mode local

   .venv/bin/python /path/to/codex/plugin-creator/scripts/validate_plugin.py \
     /tmp/openstudio-ai-codex-test/plugins/openstudio-ai
   ```

   The second command is optional and depends on where the Codex plugin validator
   is installed on the developer machine. If it is not present, run the project
   validator and focused adapter tests instead.

3. Add the marketplace in Codex:

   ```bash
   codex plugin marketplace add /tmp/openstudio-ai-codex-test
   ```

4. Install or enable `openstudio-ai` from the `openstudio-ai-local` marketplace
   in Codex.

5. Add the managed modeler policy to the project used for the test:

   ```bash
   .venv/bin/python -m cli install codex \
     --target-dir /path/to/codex-project \
     --workspace-root "$PWD"
   ```

   The command creates `AGENTS.md` if absent. Use `--dry-run` to review the
   block; an existing unmanaged file requires `--force` before appending it.
   Then ask Codex to use the setup or doctor skill.

Expected Codex plugin shape:

```text
openstudio-ai-codex-test/
├── .agents/plugins/marketplace.json
├── INSTALL.md
└── plugins/openstudio-ai/
    ├── .codex-plugin/plugin.json
    ├── .mcp.json
    ├── README.md
    ├── CONNECTORS.md
    └── skills/
        ├── setup-openstudio-ai/
        │   ├── SKILL.md
        │   └── scripts/
        ├── openstudio-modeling-orchestrator/
        │   ├── SKILL.md
        │   └── references/
        ├── openstudio-sdk-model-editor/
        │   ├── SKILL.md
        │   └── references/
        ├── openstudio-workflow-state/
        │   ├── SKILL.md
        │   └── references/
        ├── propose-measure/
        │   ├── SKILL.md
        │   └── references/
        └── capture-session-lesson/
            ├── SKILL.md
            └── references/
```

Do not add Codex plugin root `commands/`, `instructions/`, `knowledge/`,
`blackboard/`, `learning/`, or `installers/` folders. The adapter maps source
assets into skill-local `references/` and `scripts/`.

## Adapter Development Rules

Adapters are release tooling. They should translate trusted harness assets into
host-native plugin layouts. They should not contain modeling behavior.

When changing an adapter:

1. Update the exported layout in the adapter.
2. Update `validate-export` if the layout contract changes.
3. Add or update adapter tests.
4. Export a real plugin to `/tmp`.
5. Run the project validator and host validator.
6. Update this guide and `HANDOFF.md` if developers need to know the new rule.

Focused adapter tests:

```bash
.venv/bin/python -m pytest -q \
  tests/test_openstudio_claude_code_adapter.py \
  tests/test_openstudio_codex_adapter.py \
  tests/test_openstudio_cli.py
```

## Package And Release Checks

Before a release candidate:

```bash
.venv/bin/python -m pytest -q tests
rm -rf dist build
.venv/bin/python -m build --wheel
.venv/bin/python -m cli export claude --output-dir /tmp/openstudio-ai-claude --runtime-mode marketplace --force
.venv/bin/python -m cli export codex --output-dir /tmp/openstudio-ai-codex --runtime-mode marketplace --force
.venv/bin/python -m cli validate-export /tmp/openstudio-ai-claude/openstudio-ai --runtime-mode marketplace
.venv/bin/python -m cli validate-export /tmp/openstudio-ai-codex/plugins/openstudio-ai --runtime-mode marketplace
```

Also run `openstudio-ai doctor` in an environment with the native OpenStudio CLI
installed before claiming simulation readiness.

## Common Mistakes

- Adding support docs to plugin root folders instead of skill `references/`.
- Editing generated HVAC child skills without updating specs/templates.
- Treating candidate learning output as trusted knowledge.
- Assuming `run_python` exists in Claude Code or Codex instructions.
- Testing marketplace mode before `openstudio-ai-mcp` is on the host PATH.
- Expecting blackboard schema files to create SQLite state without MCP tool
  calls.
- Shipping local paths such as `/Users/...` in marketplace exports.
- Including sample models, weather files, runtime workspaces, logs, or outputs in
  release payloads.

## What To Update When You Change Things

- Folder ownership or export layout changes: update this file, adapter tests,
  `validate-export`, and `HANDOFF.md`.
- CLI behavior changes: update `README.md`, relevant docs, and CLI tests.
- Runtime MCP behavior changes: update MCP tests and any skill/prompt that
  routes to the changed tool.
- Skill behavior changes: update skill tests/evals and regenerate generated
  skills if applicable.
- Learning/promotion changes: update schemas, review docs, evals, and promotion
  rules together.

Keep changes small, testable, and tied to one layer at a time.
