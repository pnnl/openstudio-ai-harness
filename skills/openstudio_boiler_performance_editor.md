---
name: openstudio-boiler-performance-editor
description: Edit explicit nominal heating capacity or Autosize, minimum/maximum/optimum part-load ratios, HHV efficiency and electric/fuel parasitic loads on one existing hot-water boiler in place. Preserve identity, fuel, flow policy, curves, plant connections and controls; steam and replacement need separate coverage.
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
profile, curve inference or implicit capacity/flow Autosize reset is applied.
`nominal_capacity_w` accepts positive useful thermal output watts or explicit
`Autosize`; leave it out to preserve capacity exactly. Do not infer thermal capacity
from electrical/fuel input or a percentage without a sized/fixed baseline. Capacity
Autosize retains the boiler sizing factor and uses plant design flow/ΔT with fluid
properties at EnergyPlus HWInitConvTemp (60 °C); reported plant capacity can use a
different property evaluation. Design water flow and its Autosize policy stay intact.

Review before/after values, retained fuel, sizing, normalized curve, part-load
ratios, flow mode, EMS and other boilers/dispatch. A curve can change effective
efficiency with temperature/load; nominal efficiency is not realized plant
efficiency or a savings guarantee. Check whether the curve survives EnergyPlus
translation; an omitted curve warns and marks simulation unready without a hidden
control repair. On-cycle electric power scales with PLR; pinned off-cycle fuel
updates on the active calculation path and carries its last rate while idle,
including later summer periods. It is metered under Heating / Boiler Parasitic,
not a constant idle standby load. Capacity also changes PLR, retained efficiency-curve
inputs and parasitic energy. Dispatcher minimum/maximum/optimal loads are capacity
× retained PLRs, so load can move between sources and a maximum PLR above 1 can
permit heat above nominal. A nonzero minimum PLR can impose a running output
floor that rises with capacity and can exceed assigned load. Smaller capacity can cause unmet loads; do not label it
an efficiency saving or infer proportional pump savings. See the contract before
interpreting results.
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

For part-load operation, accept explicit `minimum_part_load_ratio`,
`maximum_part_load_ratio` and/or `optimum_part_load_ratio`. Resolve the combined
choices so 0 ≤ minimum ≤ optimum ≤ maximum and maximum > 0; never silently
change a companion limit. Review `impact.part_load_edit` before/after ratios and
heat-output limits. Minimum PLR can force overproduction at low load rather than
modeling burner cycling; maximum can cause unmet heating or permit above-nominal
output when >1. Optimum is a dispatch hint, not an efficiency point or requested
operating PLR. Preserve curves, capacity/flow policies and operation schemes unless
a supported setting is explicitly requested. Verify heat delivered, fuel, outlet
temperatures and ancillary energy before claiming savings; a lower cap is not an
efficiency improvement. Positive off-cycle fuel can go negative above PLR1 under
the pinned engine; discuss the warning without silently changing parasitics.

This skill does not change fuel, design flow, unrequested part-load ratios, curves,
temperature limits, schedules, plant sizing objects, operation-scheme inputs or
topology. Capacity/Autosize changes occur only when explicitly requested; sizing
results and actual dispatch can change. Steam
boilers, heat pumps, district equipment and boiler replacement require separate
coverage. Use the plant creator for missing plants. Do not write a substitute
script or broaden the edit for covered work. Unexpected execution failures route
to `report-openstudio-failure` before recovery, passing any `failure_receipt`;
expected readiness/input questions and preparation gates do not submit. Keep
model-specific plan warnings out of public diagnostics.


For an explicit Autosize request, review `impact.plant_sizing`: design-day/period
counts, defaulted/explicit model flag and effective translated plant-sizing flag.
Without a verified enabled sizing setup and periods, the edit can be saved but is
not ready to simulate. Configure sizing explicitly or choose justified fixed
values; this script changes neither sizing controls nor design periods. Some
fixed-flow cases still size with the flag off; the guard is conservative.
On multi-boiler loops, Autosize applies the whole plant design load times each
boiler's own sizing factor, not an inferred share. Review the bounded other-boiler
capacity/factor list before accepting total installed capacity. The top-level
nominal capacity is the current value; `capacity_edit` records before/after.
