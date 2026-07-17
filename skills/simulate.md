---
name: simulate
description: Run, poll, and collect artifacts from an OpenStudio simulation.
---

# Simulate

Use the `openstudio_ai` MCP simulation tools to run, poll, and collect artifacts
from OpenStudio simulations. Do not run simulations through ad hoc shell
commands when MCP tools are available.

## MCP-Only Boundary

Run model loading, simulation, and result retrieval only through `model_*`,
`sim_*`, and `results_*` MCP tools. Never invoke `openstudio`, EnergyPlus, an
`.osw`, or local SQL result extraction as a fallback. If the required MCP
preflight tool is unavailable or the service cannot be reconnected, stop and
ask the user to reload or refresh the OpenStudio AI plugin/runtime.

## Workflow

1. Call `runtime_openstudio_status`. Do not load a model or call `sim_run` when
   it is unavailable or reports `available: false`; follow **Executable
   Recovery** instead.
2. Load the model with `model_load`.
3. Set the required weather file and design days with the relevant `model_*`
   tools when the requested run requires them.
4. Start the simulation with `sim_run`.
5. Poll using `sim_status` until the job reaches a terminal state.
6. Retrieve outputs with `sim_artifacts`, then use `results_*` tools for the
   requested end-use or energy summary.

## Executable Recovery

The status is from the MCP process, which resolves `OPENSTUDIO_PATH` first and
then `shutil.which("openstudio")`; it can differ from the host shell.

If `runtime_openstudio_status` or `sim_run` reports that the executable is unavailable:

- Do not immediately retry or automatically edit marketplace `.mcp.json`.
- If the server cannot be reconnected from the current host, stop after
  reporting the required reload; do not use a local CLI fallback.
- Before suggesting installation, use read-only discovery to distinguish
  installed-but-hidden from not installed: macOS uses Applications, `mdfind`,
  and `which`; Windows uses `where`, Program Files, and uninstall registry
  entries; Linux uses `which`, `whereis`, and package locations.
- If found, report the path, ask approval to expose it through `OPENSTUDIO_PATH`
  or the MCP launch `PATH`, reconnect, recheck status, then retry once.
- Only when discovery finds no executable, offer the platform-specific
  installation guide. If recheck still fails, run the doctor workflow.
