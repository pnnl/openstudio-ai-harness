# OpenStudio AI Packaging North Star

This document defines the long-term packaging direction for OpenStudio AI. It
should be reviewed before future packaging, adapter, MCP runtime, marketplace,
or installer work. When OpenStudio AI moves to its own repository, move this
document with it and keep it as the packaging roadmap.

## Goal

OpenStudio AI should be usable by energy modelers through their preferred AI
assistant without requiring them to understand the internals of Python packages,
MCP servers, or agent configuration.

The product has two required pieces:

1. OpenStudio AI MCP runtime
2. Claude Code / Codex / future host plugin

The plugin carries the agent-facing harness: skills, knowledge, instructions,
commands, and `.mcp.json`. The MCP runtime carries the engineering execution
surface: OpenStudio model tools, simulation tools, result queries, SDK lookup,
approved measures, local SQLite runtime state, and MCP blackboard workflow
state.

The harness does not work without the MCP runtime.

## Two Installation Paths

OpenStudio AI should support two installation paths.

### Path 1: Stable Runtime Installation

This is the primary engineering and enterprise path.

Target user flow:

```bash
pip install openstudio-ai
openstudio-ai doctor
openstudio-ai export claude --output-dir ./openstudio-ai-claude-plugin
openstudio-ai export codex --output-dir ./openstudio-ai-codex-plugin
openstudio-ai install codex --target-dir ./my-codex-project
```

The exported plugin `.mcp.json` should point to the installed runtime command:

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

This path is best for:

- advanced users;
- enterprise deployment;
- controlled environments;
- CI and validation;
- clear version pinning;
- reproducible support.

### Path 2: Agentic Marketplace Installation

This is the reach and adoption path for energy modelers who may have little or
no programming experience.

Target user flow:

1. User installs OpenStudio AI from the Claude Code or Codex marketplace.
2. User runs a setup command in the AI tool, such as:

   ```text
   /openstudio-ai:setup
   ```

3. The agent checks whether the OpenStudio AI MCP runtime is installed.
4. If missing, the agent guides or performs an approved runtime installation.
5. The agent runs:

   ```bash
   openstudio-ai doctor
   ```

6. The agent confirms the MCP server can start and the plugin is ready.

The marketplace plugin should behave like an onboarding harness. It should not
assume users know how to install Python packages or debug environment paths.

The marketplace plugin should include:

```text
plugin manifest
.mcp.json
agents/
skills/
skills/*/references/
skills/setup-openstudio-ai/scripts/
monitors/
bin/
settings.json
INSTALL.md
CONNECTORS.md
```

This path is best for:

- non-programmer energy modelers;
- marketplace discovery;
- guided onboarding;
- low-friction trials;
- broader industry adoption.

## Product Boundary

### MCP Runtime Package

The MCP runtime package should provide:

- `openstudio-ai-mcp`
- `openstudio-ai doctor`
- `openstudio-ai export claude`
- `openstudio-ai export codex`
- `openstudio-ai install codex`
- `openstudio-ai validate-export`
- `openstudio-ai repair`
- `openstudio-ai uninstall` where appropriate

Runtime responsibilities:

- model lifecycle tools;
- simulation execution;
- SQL result queries;
- SDK lookup;
- approved measures;
- local SQLite runtime state;
- MCP blackboard workflow state;
- runtime storage usage and prune tools;
- cross-platform workspace management.

### Host Plugin Package

The host plugin package should provide:

- `.mcp.json` connection to `openstudio-ai-mcp`;
- skills;
- reviewed knowledge;
- instructions;
- learning contract schemas for candidate drafting;
- setup/doctor/repair commands;
- marketplace installation guidance.

Host plugin responsibilities:

- guide the host agent;
- route user workflows;
- expose energy-modeler commands;
- help install or validate the MCP runtime;
- avoid carrying heavy runtime implementation logic.

## Cross-Platform Requirements

Both paths must work on macOS and Windows.

Requirements:

- no hardcoded `/Users/...` paths;
- no shell-specific assumptions when avoidable;
- Python commands should use `python -m ...` fallbacks;
- console scripts should be validated with `doctor`;
- user data paths should use `platformdirs`;
- workspace paths should live under user-local app data by default;
- failure messages should be written for energy modelers, not Python experts.

Target runtime data locations:

- macOS: `~/Library/Application Support/OpenStudioAI/`
- Windows: `%LOCALAPPDATA%/PNNL/OpenStudioAI/`

## Current Standalone-Repo Foundation Work

OpenStudio AI currently lives under:

```text

```

Current work should build the foundation for the future package while the
project structure is stabilized.

### Current Work To Do In This Repository

1. Define the runtime installation contract.

   Required command:

   ```bash
   openstudio-ai-mcp
   ```

   Desired command:

   ```bash
   openstudio-ai doctor
   ```

2. Add adapter runtime modes.

   ```bash
   --runtime-mode local
   --runtime-mode installed
   --runtime-mode marketplace
   ```

   Meanings:

   - `local`: current source-checkout development mode.
   - `installed`: plugin assumes `openstudio-ai-mcp` is already installed.
   - `marketplace`: plugin includes setup/doctor/repair commands and installer
     guidance for non-programmers.

3. Add marketplace setup commands to exports.

   Required setup workflows:

   - `setup-openstudio-ai`
   - `doctor-openstudio-ai`
   - `repair-openstudio-ai`
   - future `uninstall-openstudio-ai`

4. Add cross-platform installer scripts.

   ```text
   Claude: skills/setup-openstudio-ai/scripts/install_runtime.py
   Claude: skills/setup-openstudio-ai/scripts/doctor_runtime.py
   Codex: skills/setup-openstudio-ai/scripts/install_runtime.py
   Codex: skills/setup-openstudio-ai/scripts/doctor_runtime.py
   ```

   These should validate prerequisites, install or upgrade the runtime package
   after user approval, support pinned/internal package specs through
   `OPENSTUDIO_AI_PACKAGE_SPEC`, initialize runtime storage, and explain
   failures in normal energy-modeler language.

5. Add export tests.

   Tests should confirm:

   - marketplace exports include setup/doctor/repair skills;
   - `.mcp.json` points to `openstudio-ai-mcp` in installed/marketplace mode;
   - local mode still points to the source checkout;
   - exported instructions are cross-platform;
   - no hardcoded developer machine paths appear in marketplace mode;
   - blackboard, runtime storage, SDK, and measure MCP tools are expected.

6. Add user-facing marketplace install guide.

   Target audience: energy modelers with no programming background.

## Future Separate Repository Work

When OpenStudio AI moves to its own repository, the package should become a
first-class installable product.

Target repo shape:

```text
openstudio-ai/
├── pyproject.toml
├── 
│   ├── cli.py
│   ├── mcp/
│   ├── blackboard/
│   ├── sdk_index/
│   ├── measures/
│   ├── skills/
│   ├── knowledge/
│   └── adapters/
├── plugins/
│   ├── claude/
│   └── codex/
└── tests/
```

Required console scripts:

```toml
[project.scripts]
openstudio-ai = "cli:main"
openstudio-ai-mcp = "mcp.server:main"
```

Required CLI commands:

```bash
openstudio-ai doctor
openstudio-ai export claude
openstudio-ai export codex
openstudio-ai install codex
openstudio-ai validate-export
openstudio-ai repair
openstudio-ai version
openstudio-ai paths
```

Package responsibilities after migration:

- publish to PyPI or an approved internal package index;
- produce marketplace plugin packages;
- produce optional offline bundles;
- provide signed or checksum-validated artifacts if needed;
- maintain clear version compatibility between plugin and MCP runtime;
- keep all user-facing installation messages cross-platform.

## Marketplace Agentic Installer Behavior

Marketplace setup should follow this sequence:

```text
User runs setup command
        |
        v
Agent checks Python availability
        |
        v
Agent checks openstudio-ai-mcp command
        |
        +-- found --> run openstudio-ai doctor
        |
        +-- missing --> ask user approval to install runtime
                         |
                         v
                    install runtime
                         |
                         v
                    run openstudio-ai doctor
        |
        v
Agent confirms MCP starts and reports readiness
```

The agent should not silently install dependencies. It should explain what it
will run, ask for approval when appropriate, and report results in plain
energy-modeler language.

## Progress Checklist

Use this checklist to estimate progress.

### Foundation In This Repository

- [x] Runtime installation contract documented.
- [x] Adapter `--runtime-mode local` supported.
- [x] Adapter `--runtime-mode installed` supported.
- [x] Adapter `--runtime-mode marketplace` supported.
- [x] Claude export includes setup/doctor/repair commands.
- [x] Codex export includes setup/doctor/repair commands.
- [x] Installer scripts exist and perform package installation plus runtime
      storage initialization.
- [x] Marketplace install guide exists.
- [ ] Export tests cover local vs installed vs marketplace modes.
- [x] Export tests reject hardcoded developer paths in marketplace mode.

### Runtime Package After Repo Migration

- [ ] Flattened runtime package directories exist at the repository root.
- [x] `openstudio-ai-mcp` console script exists.
- [x] `openstudio-ai` CLI exists.
- [ ] `doctor` command validates Python, OpenStudio, SDK index, measures,
      workspace, SQLite, and MCP startup.
- [x] `export claude` command exists.
- [x] `export codex` command exists.
- [x] `install codex` command installs managed project guidance.
- [x] `validate-export` command exists.
- [ ] Runtime data paths use `platformdirs`.
- [ ] Package can be installed on macOS.
- [ ] Package can be installed on Windows.
- [ ] Marketplace plugin can bootstrap or guide runtime installation.

### Product Readiness

- [x] Plugin/runtime compatibility mismatches are detected and explained.
- [x] MCP startup failure is explained in user-friendly language.
- [ ] Energy modeler setup guide is complete.
- [ ] Offline/enterprise bundle strategy is documented.
- [ ] Minimal smoke workflow works after clean install:
      model load, blackboard init, SDK lookup, simulation readiness check.
- [ ] Full workflow works after clean install:
      HVAC task planning, model edit, simulation, result query, state snapshot.

## North-Star Principle

Do not let the host plugin become the runtime. The plugin should guide the AI
assistant and help install or connect to the runtime. The MCP runtime should own
the deterministic engineering operations.

The long-term architecture is:

```text
Installed OpenStudio AI MCP runtime
        ^
        |
Claude/Codex marketplace plugin
        ^
        |
Energy modeler workflow in preferred AI assistant
```
