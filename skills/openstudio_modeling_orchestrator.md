---
name: openstudio-modeling-orchestrator
description: Route broad OpenStudio modeling requests to the appropriate skills, MCP tools, and workflow-state support.
---

# OpenStudio Modeling Orchestrator

Use this skill for broad OpenStudio modeling requests that span model lifecycle,
SDK editing, simulation, results, or long-running workflow state. Load the
task-specific skill before acting; do not recreate its procedure from memory.

## Routing

- If `nlr_openstudio` is configured, load `delegated-nlr-modeling` first. It
  performs preflight and selects NLR as the preferred exclusive provider for
  model, measure, simulation, and result work when compatible. It also owns
  the explicit NLR-to-SDK fallback boundary. If NLR is unavailable or
  unsuitable, continue with the OpenStudio AI routes below.
- Use `hvac-sizing-assistant` for deterministic sizing workflows.
- Use `openstudio-sdk-model-editor` for direct `.osm` inspection or scoped
  OpenStudio Python SDK edits.
- Use `openstudio-vav-reheat-system-creator` for multi-zone VAV reheat work.
- Use `openstudio-workflow-state` for work that spans phases, scripts,
  simulations, failures, or clarification gates.

## Runtime Boundaries

- When `delegated-nlr-modeling` is active, do not call OpenStudio AI
  `model_*`, `sim_*`, `results_*`, measure, or SDK tools until it records a
  provider transition. Do not call an NLR critical mutation before the skill's
  required blackboard checkpoint.
- Use `model_*` MCP tools for model lifecycle, validation, weather, and approved
  measures.
- Use `sim_*` MCP tools for simulation execution, polling, and artifacts.
- Use `results_*` MCP tools for SQL-backed results.
- Use `sdk_docs_*` only as directed by SDK-editing skills.
- Use MCP blackboard tools as the durable source of workflow state.
- Treat runtime observations as candidate material only; never promote them
  directly into trusted assets.
