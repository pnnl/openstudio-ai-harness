# OpenStudio AI Agent Adapters

This folder defines the host-specific adapter layer for packaging OpenStudio AI
into agent shells such as Codex or Claude Code.

Adapters are responsible for:

- loading the harness system prompt and prompt contracts;
- exposing the skill directory to the host agent;
- connecting the OpenStudio MCP server;
- wiring the blackboard state store;
- recording learning events from host-agent activity.

Adapters should stay thin. Product behavior belongs in `harness/`,
`blackboard/`, `learning/`, `skills/`, and `openstudio_mcp/`.

## Claude Code Plugin Export

Export a Claude plugin-style package:

```bash
.venv/bin/python -m adapters.claude_code_adapter export-plugin \
  --output-dir /tmp/openstudio-ai-plugin
```

Preview package files without writing:

```bash
.venv/bin/python -m adapters.claude_code_adapter export-plugin \
  --output-dir /tmp/openstudio-ai-plugin \
  --dry-run
```

Runtime modes:

- `--runtime-mode local`: development mode; `.mcp.json` starts the MCP server
  from this source checkout.
- `--runtime-mode installed`: assumes `openstudio-ai-mcp` is already installed.
- `--runtime-mode marketplace`: assumes `openstudio-ai-mcp` is the runtime
  command and adds setup/doctor/repair commands plus installer helper scripts.

Marketplace export:

```bash
.venv/bin/python -m adapters.claude_code_adapter export-plugin \
  --output-dir /tmp/openstudio-ai-plugin \
  --runtime-mode marketplace
```

The exported package has this shape:

```text
openstudio-ai-plugin/
├── .claude-plugin/marketplace.json
├── INSTALL.md
└── openstudio-ai/
    ├── .claude-plugin/plugin.json
    ├── .mcp.json
    ├── README.md
    ├── CONNECTORS.md
    ├── settings.json
    ├── agents/
    ├── monitors/
    ├── bin/
    ├── skills/
    │   ├── openstudio-sdk-model-editor/
    │   │   └── references/
    │   ├── openstudio-vav-reheat-system-creator/
    │   │   └── references/
    │   ├── setup-openstudio-ai/
    │   │   └── scripts/
    │   ├── propose-measure/
    │   │   └── references/
    │   └── capture-session-lesson/
    │       └── references/
```

Claude Code plugin context is exported through Claude-native components:
`agents/`, `skills/`, `.mcp.json`, `monitors/`, `bin/`, and `settings.json`.
SDK knowledge, prompt contracts, blackboard schemas, and learning schemas are
placed as supporting files under the skills that use them.

Install the exported plugin from inside Claude Code:

```text
/plugin marketplace add /tmp/openstudio-ai-plugin
/plugin install openstudio-ai@openstudio-ai-local
/reload-plugins
```

Then use the namespaced commands:

```text
/openstudio-ai:add-vav-reheat
/openstudio-ai:simulate
/openstudio-ai:query-results
/openstudio-ai:propose-measure
/openstudio-ai:setup-openstudio-ai
```

## Claude Code Project Install

Preview the files that would be installed into a Claude Code project:

```bash
.venv/bin/python -m adapters.claude_code_adapter install \
  --target-dir /path/to/claude/project \
  --dry-run
```

Install into a Claude Code project:

```bash
.venv/bin/python -m adapters.claude_code_adapter install \
  --target-dir /path/to/claude/project
```

The installer writes:

- `.mcp.json`
  Project-scoped MCP server registration for `openstudio_ai`.
- `.claude/CLAUDE.md`
  Project instructions containing OpenStudio AI harness paths, prompt
  contracts, and runtime skill references.

If `.claude/CLAUDE.md` already exists and is not managed by OpenStudio AI, the
installer stops unless `--force` is provided. With `--force`, it appends a
generated OpenStudio AI block.

Project install is mainly useful for local development and debugging. The
plugin export command is the intended distributable path.

## Codex Plugin Export

Export a Codex plugin-style package and repo-local marketplace:

```bash
.venv/bin/python -m adapters.codex_adapter export-plugin \
  --output-dir /tmp/openstudio-ai-codex-plugin
```

Preview package files without writing:

```bash
.venv/bin/python -m adapters.codex_adapter export-plugin \
  --output-dir /tmp/openstudio-ai-codex-plugin \
  --dry-run
```

Marketplace export:

```bash
.venv/bin/python -m adapters.codex_adapter export-plugin \
  --output-dir /tmp/openstudio-ai-codex-plugin \
  --runtime-mode marketplace
```

The exported package has this shape:

```text
openstudio-ai-codex-plugin/
├── .agents/plugins/marketplace.json
├── INSTALL.md
└── plugins/
    └── openstudio-ai/
        ├── .codex-plugin/plugin.json
        ├── .mcp.json
        ├── README.md
        ├── CONNECTORS.md
        ├── commands/
        ├── installers/
        ├── skills/
        ├── knowledge/
        ├── instructions/
        ├── learning/
        └── blackboard/schemas/
```

Validate the plugin:

```bash
python -m json.tool \
  /tmp/openstudio-ai-codex-plugin/plugins/openstudio-ai/.codex-plugin/plugin.json
```

Install the marketplace in Codex:

```bash
codex plugin marketplace add /tmp/openstudio-ai-codex-plugin
```

Then install or view `openstudio-ai` from the `openstudio-ai-local` marketplace
in the Codex plugin UI.
