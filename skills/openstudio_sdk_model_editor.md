---
name: openstudio_sdk_model_editor
description: Route local OSM inspection and edits to bundled SDK skills, or guide bespoke SDK scripts when no bundled operation applies.
metadata:
  version: 0.4.1
  output_format: markdown_with_json_summary
---

If inventory or preflight returns `status: requires_preparation`, run this bundled
operation through the verified CLI before any modeling plan:

```text
<verified-cli> execute_python_script <skill>/scripts/prepare_model.py --input <original.osm> --output <new-prepared.osm> --report <new-preparation.json>
```

Store its `state_patch` and original → prepared `lineage` in workflow state. Use
`output_model_path` for a fresh inventory and preflight; never reuse the blocked
plan or write an ad hoc normalizer. `already_current` reuses the input and writes
no model. Invalid current-version references require diagnosis rather than
manufactured repair. See [model preparation](references/model_preparation.md).

These script paths are fixed launchers into the installed plugin's shared `sdk/`
library. Keep the complete plugin together when copying or distributing it. A
`plugin_incomplete` result requires restoring the complete plugin; do not search
for another SDK library or generate a replacement script. Setup remains the
usual plugin installation plus this skill's doctor.

Unexpected execution failures route to `report-openstudio-failure` before
recovery; pass any `failure_receipt`. Expected readiness/input questions,
including `requires_preparation`, do not submit.

## Scope

Route HVAC component/connection diagrams to `openstudio-hvac-visualizer`, which
owns read-only graph extraction and Mermaid/Markdown artifacts. Follow the same
NLR provider selection and preparation gates before local visualization.

Use this skill only for OpenStudio model inspection and model editing. Do not use
it to run simulations or retrieve simulation results. Simulation execution,
polling, artifacts, and SQL-backed result retrieval belong to the OpenStudio MCP
tools.

Use host execution for bundled SDK scripts and scoped generated scripts against
a local `.osm` file. Bundled SDK scripts run directly through the host, without
the OpenStudio AI MCP runtime or measure registry. Host execution means the mechanism
available in the current agent host: AUTOMA-AI may expose `run_python`, Codex
may use its shell/Python execution environment, Claude Code may use its
approved command or script execution path, and some hosts may require asking the
user to run the displayed script manually. Simulation and results use MCP
`sim_*` and `results_*` tools. Bundled model-edit operations use their skill scripts.

When NLR is configured and compatible, prioritize `delegated-nlr-modeling` before
local SDK work. Requests mentioning scripts do not bypass that provider gate.
When NLR is selected as the modeling provider, this skill is available only
after `delegated-nlr-modeling` records a supported provider transition. It must
use the host-visible staged model path recorded in the blackboard, never an NLR
container path such as `/runs/...`.

Allowed uses:

- inspect spaces, thermal zones, surfaces, constructions, schedules, loads, and
  other model objects;
- compute model-level summaries from `.osm` content;
- copy a model and apply scoped edits requested by the user;
- report object counts, names, before/after values, assumptions, warnings, and
  the output model path.

Disallowed uses:

- simulation execution;
- simulation polling;
- SQL result retrieval;
- artifact retrieval;
- network calls;
- shell commands or subprocesses inside model-edit scripts (the bundled doctor
  may launch read-only CLI and embedded SDK probes);
- overwriting the original model unless explicitly requested.

## Choose the operation first

- For multi-zone VAV creation, load `openstudio_vav_reheat_system_creator` and
  run its bundle after provider selection. Do this before loading SDK docs or
  wiki packs. No routine object-level code drafting is needed.
- For prototype CAV construction, use `openstudio-cav-system-creator`; its parent
  composes shared equipment modules with a reviewed system-specific recipe.
  Confirm the requested CAV topology matches its supported arrangement.
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
- Use `openstudio-plant-equipment-replacer` for a selected hot-water boiler →
  district heating or air/water-cooled EIR chiller → district cooling conversion.
  Explicit capacity, fraction schedule and reference policy are required. Keep
  same-class settings in performance editors. Condenser branch removal is shown
  separately; the condenser plant remains.
- Use `openstudio-hvac-remover`'s `remove_unused_plants.py` for explicitly selected
  unused plant cleanup after fresh inventory. Zero coils alone is insufficient;
  active demand, shared cross-loop equipment or external references block cleanup.
  Never infer plant deletion from a coil migration or source conversion.
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
- For standalone plant construction or a plant stage of broader HVAC work, use
  `openstudio-plant-loop-creator`; pass its output/plant selectors to the selected
  air-side skill for water-coil connections when requested.
- For scoped HVAC removal, independently or before requested replacement, use
  `openstudio-hvac-remover`.
  These are bundled operations, not bespoke-code fallbacks.
- For other local inspection/edits, read
  [bespoke SDK guidance](references/openstudio_sdk_generated_edits.md) only
  after confirming that no specific energy-modeling skill provides the requested
  operation. Bespoke SDK programming is the fallback for uncovered requests.
- A failed or unsupported bundled operation is not permission to draft a
  substitute; report the cause and scope any extension/repair separately.

## Exact SDK Release Gate

This package requires the exact OpenStudio release recorded in
the plugin-root `sdk/compatibility.json`. Build metadata is allowed; prereleases and other
patch releases are rejected. Do not change the contract to accommodate an installed version.

Before SDK model execution, run `scripts/doctor.py` beside this skill with a host
Python 3.10+ interpreter. Prefer the current project's `./.venv/bin/python`, or
its nearest project root's `.venv/bin/python` when working in a subdirectory;
then try a project-configured interpreter, followed by host `python3` or `python`.
Check the Python version without modifying the environment and use the first
usable interpreter to launch doctor. `OPENSTUDIO_PATH` selects the native
OpenStudio executable, not this host Python interpreter.

Doctor uses only the standard library; the host Python does not need OpenStudio
or OpenStudio AI installed. For Claude Code resolve the
script through `${CLAUDE_SKILL_DIR}`; for Codex resolve it relative to this
`SKILL.md`'s actual directory, not the user's current working directory.

Doctor can discover the required executable or accept `--openstudio /absolute/path`
(also accepts `OPENSTUDIO_PATH`). Explicit paths are authoritative: incompatibility
blocks execution rather than triggering fallback. Read its JSON report and exit
code. Continue only when `ok` is true, using the returned absolute
`openstudio_executable` to launch SDK scripts:

```text
<verified-executable> execute_python_script <absolute-script-path> <arguments>
```

Every executable SDK script must independently call the bundled
`common.version_guard.require_sdk()` before loading or editing a user's model.
The embedded launcher needs the script's folder added to `sys.path` to import
its local helpers; follow `scripts/sdk_probe.py` when developing entrypoints.
Doctor verifies CLI identity and the embedded SDK/model binding, but a prior
successful doctor report never replaces the entrypoint's version check.

On failure, report the required and detected versions and the installation link
from doctor. Request installation of the exact release or its executable path.
Do not install automatically, use a different release, or fall back to a host
virtualenv. CLI/SDK mismatch must be resolved before any model operation.

Compatibility checks and supported bundled execution need no SDK wiki packs
or API documentation lookup. Bespoke scripts follow the linked reference,
including its API verification, required-input, result, and review rules.
Execute them through the doctor-selected CLI with the shared guard; project
Python environments are not an incompatible-version fallback.
