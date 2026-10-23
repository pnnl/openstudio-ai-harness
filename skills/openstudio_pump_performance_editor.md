---
name: openstudio-pump-performance-editor
description: Edit an existing plant-loop constant- or variable-speed pump's head, efficiency, electric-power sizing or simple operating controls in place. Retain pump identity and plumbing; class changes use the pump replacer and headered pumps need separate coverage.
metadata:
  version: 0.4.1
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

Prefer configured, compatible NLR through `delegated-nlr-modeling`. After a local
provider selection/transition, run `scripts/doctor.py` with host Python 3.10+ and
use its verified exact-release OpenStudio executable. Resolve resources beside
this SKILL.md (Claude: `${CLAUDE_SKILL_DIR}`); the entrypoint guards the SDK too.

Use this independent skill for explicitly selected `PumpConstantSpeed` or
`PumpVariableSpeed` on a plant supply or demand side. Multiple pumps are allowed;
edit only the selected pump. Read [the contract](scripts/references/pump_performance.md)
for fields, power sizing and preserved state. Inventory before choosing a target:

```text
<verified-cli> execute_python_script <skill>/scripts/edit_pump_performance.py --input <input.osm> --report <inventory.json>
<verified-cli> execute_python_script <skill>/scripts/edit_pump_performance.py --input <input.osm> --config <config.json> --report <plan.json>
```

The target and requested changes must come from the user. Present the plan's
before/after values, selected plant side and warnings when choices need review.
Existing values are retained; do not infer an autosizing reset or part-load curve
from an efficiency request. Fixed electric power and `PowerPerFlow` sizing can
mask head/efficiency changes. Discuss the existing power method when the user's
goal is energy reduction. Missing choices leave preflight unready for discussion.
A request specifying target and settings authorizes those edits; preserve that
authorization across turns. No prototype-default approval profile is needed.

```text
<verified-cli> execute_python_script <skill>/scripts/edit_pump_performance.py --plan <plan.json> --report <apply.json>
```

Apply only an unchanged ready plan. Scripts check source/resource hashes, edit the
existing pump, reload and independently verify requested values and protected
objects, then translate to EnergyPlus before publishing a new model copy. Pump,
node, connection, metadata and incoming-reference handles remain stable, including
EMS actuators and LifeCycleCost. Retained EMS/schedules/pressure controls can still
affect operation; forward translation does not establish simulation performance.

This operation does not change pump class, minimum/design flow, schedules, plant
sizing, pressure-reset controls, loop arrangement or other pumps. Four explicit
variable-speed coefficients describe power versus flow; they do not install a
VFD reset system or convert a constant-flow plant. Genuine single constant ↔
variable-speed class changes use `openstudio-pump-replacer`; retain explicit
flow/power, curve/minimum-flow and reference choices. Headered/condensate pumps
and pressure-control redesign need separate coverage. Report covered failures
without writing a substitute or broadening the edit.

Return output/report paths, the retained pump handle and before/after settings.
Keep the OSM and `<stem>/` companion together; honor `requires_companion_workflow`.
Hand sizing and performance assessment to the selected simulation provider.

## Energy code values

Applies only when the user asks for code-compliant or code-minimum values or names a standard (for example "per 90.1-2019"); otherwise keep the behavior above. Load `query-energy-standards` to resolve pump motor efficiency (`hvac_minimum_requirements_motors`) and variable-flow or variable-speed drive requirements (`system_requirements_hydronic_variable_flow`) for the edit the user asked for. Do not change a pump's mode or class from a code lookup; route class changes to `openstudio-pump-replacer`. Confirm `standard`, `template`, `climate_zone` and `path` with the user instead of assuming them, and record the source of each value used. If the `building_energy_standards` tools are unavailable or return no matching row, say so and ask the user for the value; never invent a code value.
