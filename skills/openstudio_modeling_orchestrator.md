---
name: openstudio-modeling-orchestrator
description: Route broad OpenStudio modeling requests to the appropriate skills, MCP tools, and workflow-state support.
---

# OpenStudio Modeling Orchestrator

Use this skill for broad OpenStudio modeling requests that span model lifecycle,
SDK editing, simulation, results, or long-running workflow state. Load the
task-specific skill before acting; do not recreate its procedure from memory.

## Routing

- If NLR is configured as `openstudio-mcp`, load `delegated-nlr-modeling` first. It
  performs preflight and selects NLR as the preferred exclusive provider for
  model, measure, simulation, and result work when compatible. It also owns
  the explicit NLR-to-SDK fallback boundary. If NLR is unavailable or
  unsuitable, continue with the OpenStudio AI routes below. This priority applies
  to VAV and requests mentioning local bundled scripts. If NLR cannot cover the
  operation, record the evidence and provider transition before local SDK work.
- Use `hvac-sizing-assistant` for deterministic sizing workflows.
- Use `openstudio-sdk-model-editor` for other direct `.osm` inspection or scoped
  edits. It checks for a bundled operation before its bespoke-edit guidance.
- Use `view-openstudio-geometry` to generate a read-only, self-contained HTML
  geometry viewer from an `.osm` model.
- Use `openstudio-vav-reheat-system-creator` for multi-zone VAV work through
  its exact-release doctor, bundled preflight/apply, and saved-model validator.
  Do not draft objects individually; the legacy child skills have been removed.
- Use `openstudio-cav-system-creator` for the prototype CAV arrangement with a
  constant-volume fan, water heating/reheat and VAV-reheat terminals. Clarify a
  different CAV arrangement before routing; generic prototype controls do not
  imply fixed airflow in every zone or template compliance. VAV/CAV parent scripts
  compose shared equipment functions inside one reviewed model transaction.
- Use `openstudio-supply-fan-performance-editor` for explicit efficiency/pressure changes
  to an existing air loop's sole direct constant- or variable-volume supply fan.
  It edits the existing fan in place and preserves its handle, connections,
  metadata, incoming references, flow controls and unselected model state.
  Class-changing replacement (including a request to swap CAV for variable-speed)
  requires a separate contract; do not route it to this performance editor.
  Embedded fans need separate coverage. Whole-system VAV/CAV construction uses
  the shared fan functions inside its parent transaction.
- Use `openstudio-water-coil-editor` for existing main-supply water-coil ratings,
  name, availability, Autosize resets and controller settings. These are in-place
  setters preserving coil, controller, connection, metadata and reference handles,
  including EMS/LifeCycleCost. Use `openstudio-water-coil-connector` only to attach
  a new water coil at the selected air loop's supply outlet and compatible existing
  plant demand branch. Interior/inlet nodes are unsupported. Select design,
  schedule, sizing and controller choices explicitly; finalize a new controller
  after both connections. Same-class replacement is not exported. Class conversion,
  location changes, plant migration and OA/unitary/terminal coils need separate
  coverage. Whole VAV/CAV creation shares these setters within its parent transaction.
- Use `openstudio-plant-loop-creator` as an independent plant-building module for
  hot-water, chilled-water and associated condenser systems. Route direct plant
  requests and plant stages of broader HVAC workflows here; it is not restricted
  to missing plants or VAV preparation. It creates plant supply equipment,
  pumping and controls, including chiller-to-condenser connections. Pass its
  output model and plant names/handles to the appropriate air-side skill, which
  connects its water coils to plant demand branches. The current VAV skill supports
  that connection; check coverage for other air-side systems before choosing a route.
- Use `openstudio-hvac-remover` independently for explicitly selected existing
  HVAC removal. Include removal in a replacement workflow only when requested;
  plant creation alone does not require removal or subsequent VAV creation.
  Each operation produces a reviewed model copy for the next selected operation.
  Do not generate ad hoc scripts for covered plant/removal work.
- Use bespoke SDK programming only when no specific energy-modeling skill covers
  the request. A failed covered workflow requires diagnosis, not a generated-code
  bypass.
- Use `openstudio-workflow-state` for active long-running workflows that span
  simulations or multiple modeling tasks; standalone bundled operations keep
  their configuration, plans and reports locally.

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
- Use MCP blackboard tools for an active long-running workflow. Standalone
  bundled VAV execution persists its configuration, plan, logs and report
  locally and does not require MCP state or modeling-runtime readiness.
- When the active workflow has learning tools, before a non-trivial modeling
  action call `learning_search_lessons` with the
  task type and relevant tags. Use only returned personal lessons that fit the
  current model/version scope, and still validate the model independently.
- At the end of meaningful work, offer to save a concise observation. Capture
  or review learning only after the user explicitly agrees.
- Personal lessons are local guidance. Never promote them directly into trusted
  skills, knowledge, measures, or MCP tools.
