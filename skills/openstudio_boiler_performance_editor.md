---
name: openstudio-boiler-performance-editor
description: Edit nominal thermal efficiency and on-cycle electric or off-cycle fuel parasitic loads on one existing hot-water boiler in place. Preserve its identity, fuel, capacity, flow, curves, plant connections and controls; steam boilers and replacement need separate coverage.
metadata:
  version: 0.4.1
---

Prefer configured, compatible NLR through `delegated-nlr-modeling`. After local
provider selection/transition, run `scripts/doctor.py` with host Python 3.10+ and
use its verified exact-release OpenStudio executable. Resolve resources beside
this SKILL.md (Claude: `${CLAUDE_SKILL_DIR}`). Launchers require the complete
plugin's shared `sdk/`; restore an incomplete plugin rather than substitute scripts.

Read [the boiler contract](references/boiler_performance.md) and
[input schema](references/boiler_performance.schema.json). Inventory first, then
select the heating plant and one supply-side BoilerHotWater by name or handle:

```text
<verified-cli> execute_python_script <skill>/scripts/edit_boiler_performance.py --input <input.osm> --report <inventory.json>
```

If inventory or preflight returns `requires_preparation`, run the bundled preparer
and store its `state_patch`/lineage. Re-inventory and preflight against the returned
`output_model_path`; never reuse a blocked plan or write a normalizer. `already_current`
writes no model. Invalid current references need diagnosis. See
[model preparation](references/model_preparation.md).

```text
<verified-cli> execute_python_script <skill>/scripts/prepare_model.py --input <original.osm> --output <new-prepared.osm> --report <preparation.json>
<verified-cli> execute_python_script <skill>/scripts/edit_boiler_performance.py --input <input.osm> --config <config.json> --report <plan.json>
```

Settings are explicit user choices: `nominal_thermal_efficiency` is an HHV-based
fraction greater than zero and at most one; parasitic inputs are nonnegative watts.
Electric boilers require zero off-cycle fuel: positive requests are rejected, and
retained positive inputs warn as ignored by the engine. Clear only by an explicit
user-chosen zero, never silently.
Do not substitute AFUE/combustion/LHV ratings without resolving the basis. Existing
authorization persists. Missing choices stay unready for discussion. No prototype
profile, curve inference or capacity/flow Autosize reset is needed or implied.

Review before/after values, retained fuel, sizing, normalized curve, part-load
ratios, flow mode, EMS and other boilers/dispatch. A curve can change effective
efficiency with temperature/load; nominal efficiency is not realized plant
efficiency or a savings guarantee. Check whether the curve survives EnergyPlus
translation; an omitted curve warns and marks simulation unready without a hidden
control repair. On-cycle electric power scales with PLR; pinned off-cycle fuel
updates on the active calculation path and carries its last rate while idle,
including later summer periods. It is metered under Heating / Boiler Parasitic,
not a constant idle standby load. See the contract before interpreting results.
An existing ignored electric-boiler off-cycle fuel value warns without blocking
simulation; clearing it is optional. Boiler plans explicitly opt into combining
operation and companion blockers in `simulation_ready`; this is not a simulation
guarantee and does not change other operations' readiness flags. Honor
simulation readiness, including existing pump/setpoint deficiencies; rating edits
do not repair the plant. Hand operating/sizing assessment to the selected provider.

```text
<verified-cli> execute_python_script <skill>/scripts/edit_boiler_performance.py --plan <plan.json> --report <apply.json>
```

Apply only the unchanged ready report. Setters retain boiler, metadata, costs/EMS
references, nodes and connections. Saved validation verifies requested values,
every unrequested raw field, other model objects, topology and translated boiler
fields before publishing a new copy. Store the retained handle, before/after
values and report/output paths in workflow state. Keep the OSM and `<stem>/`
companions together; honor `requires_companion_workflow`.

This skill does not change fuel, capacity, design flow, part-load ratios, curves,
temperature limits, schedules, plant setpoints/sizing, dispatch or topology. Steam
boilers, heat pumps, district equipment and boiler replacement require separate
coverage. Use the plant creator for missing plants. Do not write a substitute
script or broaden the edit for covered work. Unexpected execution failures route
to `report-openstudio-failure` before recovery, passing any `failure_receipt`;
expected readiness/input questions and preparation gates do not submit. Keep
model-specific plan warnings out of public diagnostics.
