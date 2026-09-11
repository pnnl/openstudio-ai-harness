# NLR OpenStudio-MCP in Claude Desktop

This guide configures NLR's Docker-based OpenStudio-MCP server for the
standalone Claude Desktop application. It is an optional provider alongside
OpenStudio AI; it does not replace the OpenStudio AI plugin or runtime.

## Important limitation: the configuration is global, but file access is not

Claude Desktop reads one global MCP configuration file. NLR starts a Docker
container from that configuration, and Docker exposes only the host folders
listed in its `-v` mounts. NLR's sandbox then restricts its file operations to
those mounted folders.

As a result, a configuration that mounts
`/Users/you/openstudio_ai/claude` cannot load a model stored only in
`/Users/you/openstudio_ai_demo`. The active Claude chat's folder does **not**
automatically become available to the NLR container.

This can be reported by Claude as a failure to transfer a file to a local
simulation server or to reach `localhost`. In this setup, first verify the
mount path: it is usually a file-access boundary, not a network problem.

Choose one of these workflows before starting a modeling chat:

1. **Shared NLR workspace (recommended):** keep models to be handled by NLR
   under one mounted `inputs` folder and use that folder from every chat.
2. **Project-specific workspace:** before opening a chat for another project,
   update the three host paths in the global configuration to that project's
   NLR workspace, then fully restart Claude Desktop.

Do not mount your home directory, credentials, or the Docker socket merely to
make every project visible. Use a narrow, intentional project or shared
workspace instead.

## Prerequisites

1. Install and start Docker Desktop.
2. Pull the NLR image that the configuration will run:

   ```bash
   docker pull nrel/openstudio-mcp:dev
   docker image inspect nrel/openstudio-mcp:dev
   ```

3. Create a dedicated shared workspace. This example uses
   `/Users/you/openstudio_ai/claude`; replace it everywhere with a real
   absolute path on your machine.

   ```bash
   mkdir -p /Users/you/openstudio_ai/claude/{inputs,nlr_runs,nlr_measures}
   ```

Put `.osm` files that NLR should load in `inputs`. NLR writes run artifacts to
`nlr_runs` and reads or writes approved measures through `nlr_measures`.

## Configure Claude Desktop

1. In Claude Desktop, open **Settings → Developer → Edit Config**.
2. Open `claude_desktop_config.json` in the editor that Claude launches.
3. Add the `openstudio-mcp` entry to the existing `mcpServers` object. Preserve
   any other server entries and make sure the enclosing JSON remains valid.

```json
{
  "mcpServers": {
    "openstudio-mcp": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "-v",
        "/Users/you/openstudio_ai/claude/inputs:/inputs:ro",
        "-v",
        "/Users/you/openstudio_ai/claude/nlr_runs:/runs",
        "-v",
        "/Users/you/openstudio_ai/claude/nlr_measures:/measures",
        "-e",
        "OPENSTUDIO_MCP_MODE=prod",
        "-e",
        "OSMCP_SANDBOX=posix",
        "nrel/openstudio-mcp:dev",
        "openstudio-mcp"
      ]
    }
  }
}
```

`/inputs`, `/runs`, and `/measures` are paths *inside* the container. The path
before each colon is the host path that must exist on your Mac. Keep `/inputs`
read-only (`:ro`); use the writable run and measure mounts for NLR outputs.

The OpenStudio AI integration recognizes the MCP connection name
`openstudio-mcp`. `nlr_openstudio` is the name shown for its optional provider
capability, but is not the supported Claude Desktop connection name.

4. Quit Claude Desktop completely and reopen it. Editing the file does not
   alter a server already attached to an open chat.
5. Start a new chat and ask Claude to verify that the NLR OpenStudio-MCP tools
   are available before asking it to load a model.

## Working with a different chat or project folder

For a chat rooted at `/Users/you/openstudio_ai_demo`, choose one approach:

- Copy or stage the model into
  `/Users/you/openstudio_ai/claude/inputs`, then tell Claude to load it as
  `/inputs/model.osm`. This leaves the configuration unchanged.
- Or create
  `/Users/you/openstudio_ai_demo/nlr-workspace/{inputs,nlr_runs,nlr_measures}`
  and replace all three host paths in `claude_desktop_config.json` with those
  paths. Quit and reopen Claude Desktop before starting the project chat.

Example project-specific input mount:

```text
/Users/you/openstudio_ai_demo/nlr-workspace/inputs:/inputs:ro
```

The host-side file path and the NLR path are intentionally different. Tell NLR
to use `/inputs/model.osm`; do not give it an unmounted host path such as
`/Users/you/openstudio_ai_demo/model.osm`.

## Troubleshooting

| Symptom | Likely cause | Smallest corrective action |
| --- | --- | --- |
| Claude finds a model but cannot send it to the simulation server | The model's host directory is outside the configured Docker input mount. | Stage the model in the mounted `inputs` directory, or change the three project mounts and restart Claude Desktop. |
| NLR cannot find `/inputs/model.osm` | The file is not in the host folder mounted to `/inputs`, or the filename differs. | Check the host `inputs` folder and use the exact container path `/inputs/<filename>`. |
| Docker server fails to start | Docker Desktop is stopped or the image is absent. | Start Docker Desktop; run `docker pull nrel/openstudio-mcp:dev`; restart Claude Desktop. |
| NLR is configured but OpenStudio AI does not select it | The server uses an unsupported connection name. | Rename the entry to `openstudio-mcp`, then restart Claude Desktop. |
| Changes to the JSON appear to have no effect | The current chat retained its old MCP server process. | Quit and relaunch Claude Desktop, then begin a new chat. |

Before reporting a Docker or `localhost` error, record the model's absolute host
path and compare it with the three `-v` host paths in the global configuration.
If the model is not below the mounted input root, the configuration must be
changed or the model must be staged; no retry in the same chat can grant the
container access to that file.
