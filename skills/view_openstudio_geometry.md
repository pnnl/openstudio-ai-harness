---
name: view-openstudio-geometry
description: Generate a downloadable, self-contained HTML page for inspecting OpenStudio model geometry by space, story, and name.
version: 0.2.2
---

# View OpenStudio Geometry

Use this skill when the user asks to visualize, browse, inspect, search, or
highlight geometry from a local `.osm` model. It produces an offline HTML file
for geometry inspection; it does not edit the model or run a simulation.

## Workflow

1. Call `runtime_plugin_compatibility` before loading the model. This viewer
   requires MCP interface contract `3`. Continue only when the returned
   `compatibility.runtime_contract_version` is `3` and `compatibility.ok` is
   true. If the tool is absent, reports another contract, or reports an
   incompatibility, explain that this conversation is connected to a stale
   runtime. Run the OpenStudio AI setup workflow to upgrade the runtime with
   user approval, then restart or reconnect the host MCP server and retry in
   the refreshed session. In Claude Code use `/reload-plugins` when available;
   in Codex restart Codex or reconnect the MCP server.
2. Call `model_load` with the local model URI when the caller has not already
   supplied a `model_id` for the same artifact.
3. Call `model_export_geometry_viewer` with the model ID. Keep both
   `include_subsurfaces` and `include_shading` enabled unless the user requests
   a simpler view.
4. Report the generated `viewer_path`, `viewer_uri`, counts, and warnings.
5. When the host supports opening a local file, open `viewer_path` for the user.
   Otherwise provide the absolute path and explain that it can be downloaded or
   opened directly as a local HTML file.

## Viewer Behavior

The generated page is self-contained: it requires no web server, external
JavaScript library, CDN, network connection, or separate scene-data download.
It provides a 3D canvas, orbit/zoom controls, search by space name/story/zone/
space type, story filtering, sorting by name/story/floor area/volume, and
click-to-highlight space inspection.

## Boundaries

- Treat this as a read-only model-inspection workflow.
- Do not modify the source `.osm` model or run a simulation.
- The viewer must be produced through `model_export_geometry_viewer`. If that
  tool is unavailable, do not parse the OSM directly or create a substitute
  HTML page. Do not retry the current connection: explain that an MCP tool list
  is fixed for its session, then ask the user to upgrade the runtime and restart
  or reconnect the host MCP server.
- Surface/space names and geometry are model data; report malformed geometry as
  warnings rather than silently discarding the fact that it was skipped.
- The returned artifact is stored in the MCP workspace and is subject to normal
  runtime retention and pruning policy.
