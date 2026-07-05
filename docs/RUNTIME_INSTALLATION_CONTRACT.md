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

Expected behavior:

- `openstudio-ai doctor`: checks Python, MCP startup, initialized runtime
  storage, SQLite support, SDK index availability, measure registry
  availability, OpenStudio Python SDK availability, native OpenStudio CLI
  availability, and basic simulation readiness.

OpenStudio AI has a two-part OpenStudio prerequisite:

1. the PyPI `openstudio` Python package, installed as a required dependency of
   `openstudio-ai`;
2. the native OpenStudio application/CLI, visible through `OPENSTUDIO_PATH` or
   `PATH`.
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
non-programmer through installation:

```text
commands/
  setup-openstudio-ai.md
  doctor-openstudio-ai.md
  repair-openstudio-ai.md
installers/
  install_runtime.py
  doctor_runtime.py
```

The setup command should ask the host agent to:

1. Check whether Python is available.
2. Check whether `openstudio-ai-mcp` is available.
3. Run `python installers/doctor_runtime.py`.
4. If the runtime is missing, run `python installers/install_runtime.py` after
   explaining what will happen.
5. Run `openstudio-ai doctor` when available.
6. Explain failures in normal energy-modeler language.

`install_runtime.py` should install or upgrade the runtime package after the
host agent has explained the action and received user approval. It should accept
`OPENSTUDIO_AI_PACKAGE_SPEC` for pinned versions, local wheel paths, or internal
package indexes, then initialize user-local runtime storage. Installer failures
should be explained in normal energy-modeler language.
