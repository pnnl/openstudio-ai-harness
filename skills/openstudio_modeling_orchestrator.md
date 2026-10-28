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
- Use `openstudio-hvac-visualizer` to inspect HVAC components, directed ports and
  served zones as local JSON/Mermaid/Markdown before selection/removal or after
  an edit. Keep NLR priority and the recorded fallback boundary. Link the compact
  overview or selected diagrams; full topology and private labels stay local.
- Use `openstudio-vav-reheat-system-creator` for multi-zone VAV work through
  its exact-release doctor, bundled preflight/apply, and saved-model validator.
  Do not draft objects individually; the legacy child skills have been removed.
- Use `openstudio-cav-system-creator` for the prototype CAV arrangement with a
  constant-volume fan, water heating/reheat and VAV-reheat terminals. Clarify a
  different CAV arrangement before routing; generic prototype controls do not
  imply fixed airflow in every zone or template compliance. VAV/CAV parent scripts
  compose shared equipment functions inside one reviewed model transaction.
- Use `openstudio-district-capacity-editor` for an existing supply-side
  DistrictHeatingWater or DistrictCooling nominal thermal capacity: explicit watts
  or Autosize, preserving schedule, connections and identity. Review the retained
  capacity-fraction schedule; a capacity limit is not an efficiency saving. Steam,
  schedule changes and district production/loss modeling require separate coverage.
- Use `openstudio-tower-performance-editor` for one existing condenser supply-side
  CoolingTowerVariableSpeed design fan electrical power (watts/Autosize), minimum
  airflow ratio or free-convection fraction edits. Require explicit performance
  choices; retain design conditions, unrequested inputs, curves and identity.
  Low-load controls affect fan cycling/fan-off heat rejection and coupled energy;
  fan-off does not mean pumps off or guaranteed savings.
  Review autosized design airflow/airflow-based metrics coupled to fan power,
  evaporation/make-up water and tower electricity;
  other tower classes, user-defined thermal models and replacement need coverage.
- Use `openstudio-chiller-performance-editor` for one existing air- or water-cooled
  ChillerElectricEIR reference COP, cooling capacity (watts/Autosize) or explicit
  part-load/unloading edit on a
  Cooling plant. Preserve curves, unrequested sizing/flow inputs, condenser
  connections, controls and identities. Review effective plant-sizing readiness
  for explicit Autosize and its retained evaporator-flow/factor sizing basis;
  require minimum ≤ optimum ≤ maximum and minimum ≤ unloading ≤ maximum,
  with optimum/maximum > 0; cycling and false loading affect energy. Review autosized
  condenser pump/tower changes after sizing; chiller electricity is not plant
  savings. No inferred standards minimum,
  curve substitution or class conversion. Heat recovery, thermosiphon and other
  chiller classes need separate coverage.
- Use `openstudio-boiler-performance-editor` for explicit nominal thermal capacity
  or capacity Autosize, minimum/maximum/optimum PLRs, HHV efficiency and
  on-cycle electric/off-cycle fuel parasitics
  on a heating-plant BoilerHotWater. Retain identity, fuel, design-flow policy,
  curves, unrequested PLRs, sizing factor and controls. Explicit PLR choices must
  satisfy minimum ≤ optimum ≤ maximum, maximum > 0; minimum can force
  overproduction, and optimum is a dispatch hint. Capacity/PLR changes alter dispatch,
  PLR/curve/parasitic energy or unmet loads; no inferred matching flow or savings.
  Steam boilers, fuel conversion and replacement require separate coverage.
- Use `openstudio-terminal-replacer` for one connected single-duct VAV no-reheat
  ↔ constant-volume no-reheat terminal class change. Require explicit maximum-flow
  policy, VAV target minimum fraction and preservation/reheat/reference policies.
  Review new identity, changed airflow behavior, retained zone branch and sizing;
  this is not a whole-system VAV/CAV conversion. Reheat and unsupported terminal
  classes need separate coverage. Same-class VAV controls use the terminal editor.
  Do not draft substitute scripts for covered terminal replacements.
- Use `openstudio-terminal-editor` for one existing connected single-duct VAV
  reheat/no-reheat terminal's explicit Constant-method minimum fraction or applicable
  reheat controls, including terminals in prototype CAV systems. Preserve the
  terminal/coil, connections, references, schedules and unrequested sizing. Review
  supply-air versus OA, turndown/EMS overrides and flow/sizing warnings; honor
  simulation readiness. Reverse/reheat-flow-limit edits require supported water
  reheat controls. Terminal class/method changes, coil ratings and topology need
  separate coverage. Do not generate substitute scripts for covered terminal edits.
- Use `openstudio-economizer-editor` for explicit in-place economizer type,
  lockout and temperature/enthalpy cutoff edits on an existing direct OA controller.
  It preserves ventilation, DCV, schedules, sizing, topology and handles. Review
  retained additive limits, 100% OA floors and overriding controls; route minimum
  OA/DCV edits to `openstudio-ventilation-editor`. Use the OA connector for
  intake/recovery attachment. Do not draft a substitute script for covered economizer work.
- Use `openstudio-ventilation-editor` for explicit in-place minimum/maximum OA
  flow, OA schedule-reference and ZoneSum DCV edits on an existing direct OA system.
  It preserves zone OA/People, schedule contents, sizing, economizer and handles.
  DCV does not implicitly reset minimum flow or fraction floors: discuss masking
  floors and require explicit changes. Review occupancy, airflow caps, schedule
  ranges and sizing warnings; honor simulation readiness. Other MV-method DCV,
  CO2/IAQ and zone policy need separate coverage; route intake/recovery attachment
  to `openstudio-outdoor-air-connector`.
  Do not generate a substitute script for covered ventilation work.
- Use `openstudio-outdoor-air-connector` to attach a direct OA system at a served
  loop's main supply inlet, or sensible/latent heat recovery to empty OA/relief
  streams. Preview both-stream wiring and require explicit flow, effectiveness,
  power, frost, bypass and outlet-control choices. It does not infer template
  defaults or resize existing equipment. Shared/dedicated and embedded OA need
  separate coverage. Use `openstudio-heat-recovery-editor` for explicit in-place
  performance/control changes on an existing exchanger, preserving its handles,
  curves and references. Retained curves scale with 100% effectiveness edits.
  Verify translated outlet/reference setpoints and honor simulation readiness.
  Do not generate substitute scripts for covered intake or recovery work.
- Use `openstudio-pump-performance-editor` for explicit in-place head, motor,
  electric-power sizing, operating-mode or variable-speed power-curve edits on
  a selected single plant supply/demand pump. Preserve its handles and plumbing;
  inspect fixed-power/inactive-sizing warnings before promising energy savings.
  Use `openstudio-pump-replacer` for genuine single constant ↔ variable-speed
  class changes with explicit curve/minimum flow and flow/power policies. It
  retains plant boundaries/controls and rejects references requiring migration.
  Banks and pressure-reset/plant-flow redesign need separate coverage.
  Do not generate an ad hoc script for a covered pump edit.
- Use `openstudio-supply-fan-performance-editor` for explicit efficiency/pressure changes
  to an existing air loop's sole direct constant- or variable-volume supply fan.
  It edits the existing fan in place and preserves its handle, connections,
  metadata, incoming references, flow controls and unselected model state.
  Use `openstudio-supply-fan-replacer` for a genuine constant-volume ↔ variable-
  volume class change, with explicit performance/curve, Autosize and terminal/
  system-sizing preservation choices. It preserves air boundaries and translated
  controls, reports new identities, and rejects references requiring migration.
  Whole-system VAV/CAV conversion needs separate coverage.
  Embedded fans need separate coverage. Whole-system VAV/CAV construction uses
  the shared fan functions inside its parent transaction.
- Use `openstudio-water-coil-editor` for existing main-supply water-coil ratings,
  name, availability, Autosize resets and controller settings. These are in-place
  setters preserving coil, controller, connection, metadata and reference handles,
  including EMS/LifeCycleCost. Use `openstudio-water-coil-connector` to attach
  a new water coil at the selected air loop's supply outlet and compatible existing
  plant demand branch, or to migrate an existing main-supply coil to another ready
  water plant with explicit Autosize resets. Migration preserves coil/controller/
  air identities; it requires a dedicated single-coil demand branch and may rebuild
  water nodes/connections. Present both plants and sizing/identity effects. New
  attachment requires explicit design, schedule, sizing and controller choices;
  interior/inlet attachment is unsupported. Same-class replacement is not exported.
  Use the connector's `relocate_air` operation for a main-supply water coil moved
  immediately upstream of a selected supply outlet on the same or another unsplit
  air loop, with explicit Autosize. It preserves equipment/controller and plant
  branch identities, updates the sensor, and reports the removed interior air node
  and all affected zones. No zone reassignment or system resizing is implicit.
  Use `openstudio-coil-replacer` for genuine main-supply heating-water to electric
  conversion, with explicit efficiency, preserved temperature control, Autosize and reference
  policy. It preserves schedule/air boundaries/coil metadata, creates a new coil
  and removes the owned water controller/branch; external references block its
  initial Reject policy. Show fuel, remaining-plant-load and identity effects.
  Other class conversions and OA/unitary/terminal coils need separate coverage.
  Whole VAV/CAV creation shares these setters within its parent transaction.
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
- Use `query-energy-standards` when a task has a code basis (a named standard, "code minimum" or compliance) to resolve equipment efficiency, fan power, economizer, energy recovery, pump, ventilation, envelope or lighting values before the owning skill's configuration is prepared. The owning skill applies the values; the standards skill only looks them up.
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

For a local bundle returning `requires_preparation`, run that owning skill's
`scripts/prepare_model.py` through its verified CLI with a new copied output and
JSON report. Store original → prepared lineage/state patch, then re-inventory
and re-preflight the prepared path. Do not write ad hoc normalization scripts
or bypass exact plan checks. This applies after the existing NLR-first provider
transition; preparation does not change provider priority.

Bundled SDK skill commands are fixed launchers into the installed plugin's
shared `sdk/` library. A `plugin_incomplete` report requires restoring that whole
plugin; do not search a different checkout or substitute generated scripts.


## Unexpected failures and resume

On an unexpected execution failure, invoke `report-openstudio-failure` before
recovery, abandoning the step or continuing to another modeling step. Reuse a
bundled `failure_receipt`; if absent (MCP error, crash, doctor/probe failure or
broken plugin), use that skill's independent host-Python collector to capture
minimal configuration, versions, expected/actual behavior, publication state and
reproduction evidence. The selected policy automatically submits allowlisted,
sanitized diagnostics to `pnnl/openstudio-ai-harness`; no per-incident approval is
required. Issues are created under the user's own authenticated GitHub account.
Do not upload models, companions, transcripts or credentials. Security-
sensitive incidents remain local for private reporting. Explicit user bug reports
qualify; ordinary missing inputs, scope refusals, cancellation, version readiness
and `requires_preparation` do not automatically create issues.

Use the project root as CWD, or set the same absolute `OPENSTUDIO_AI_FAILURE_DIR`
and reporter `--state-dir`. On resume, run its `pending` command and process
pending receipts before new modeling work. Preserve the original incident across
successful workarounds and repeated retries. Store receipt/issue under
`failure_incidents[fingerprint]` in an active blackboard. If reporting is offline,
disabled, locked or uncertain, retain the draft and state the reason, then continue
otherwise safe recovery. Never repeat a mutation to get evidence or issue a second
POST for an uncertain submission. Reporting does not change NLR-first routing or
any preparation/transaction checks.

Do not recursively report reporter/auth/network failures; retain their reason in
the original receipt and continue safe modeling work.
