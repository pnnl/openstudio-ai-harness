---
name: openstudio-district-capacity-editor
description: Edit nominal purchased-thermal capacity or explicit Autosize on an existing supply-side DistrictHeatingWater or DistrictCooling in place. Preserve schedule, plant connections and identity. Use plant creator for new sources; steam and efficiency changes need separate coverage.
metadata:
  version: 0.4.1
---

Prefer compatible, configured NLR through `delegated-nlr-modeling`. After selecting
or transitioning to local modeling, run `scripts/doctor.py` with host Python 3.10+
and use its verified OpenStudio 3.11.0 executable. Resolve resources beside this
SKILL.md (Claude: `${CLAUDE_SKILL_DIR}`); retain the complete plugin's shared `sdk/`.
Read the [contract](references/district_capacity.md) and
[schema](references/district_capacity.schema.json).

Inventory, select one plant and district source by unique name or handle, then
preflight an explicit positive `nominal_capacity_w` or the string `Autosize`.
Do not infer capacity from COP, efficiency, electrical watts, a percentage without
a fixed baseline or an unavailable sizing result. Obtain missing choices from the
user or selected provider; existing authorization persists.

```text
<verified-cli> execute_python_script <skill>/scripts/edit_district_capacity.py --input <input.osm> --report <inventory.json>
<verified-cli> execute_python_script <skill>/scripts/edit_district_capacity.py --input <input.osm> --config <config.json> --report <plan.json>
```

On `requires_preparation`, run bundled `scripts/prepare_model.py`, retain lineage,
then re-inventory and preflight the prepared copy. Do not write a normalizer or
reuse the blocked plan. See [preparation](references/model_preparation.md).

Review before/after capacity, capacity-fraction schedule and effective constant
limit, loop design conditions, dispatch and retained EMS. The schedule multiplies
nominal capacity and may exceed 1. Loop temperature protection is applied afterward
and can override that limit even at a schedule fraction of 0; a zero fraction is
not a guaranteed off switch. Load-based dispatch uses nominal capacity without
that fraction: editing capacity can redistribute load between sources, and a
schedule-induced shortfall may remain unmet despite spare equipment capacity.
Review all source loads, the load-distribution scheme and plant unmet demand.
The source requests full loop design flow for nonzero assigned load; reducing
capacity does not itself request proportionally lower flow or pump energy.
Autosize uses plant design flow, fluid properties and ΔT. Limiting purchased heat/cooling can cause unmet loads; lower metered energy
alone is not an efficiency saving. No district production or distribution loss model
is added. Pump, flow and plant sizing inputs stay unchanged; calculated results can
change. Nonstandard loop roles are visible for condenser/water-loop applications.

```text
<verified-cli> execute_python_script <skill>/scripts/edit_district_capacity.py --plan <plan.json> --report <apply.json>
```

Use saved-model and translation validation; `simulation_ready` combines known
operation and companion blockers, not certification. Keep the OSM with its companion
directory and retain report/model lineage in active workflow state. Unexpected
execution failures use `report-openstudio-failure` before recovery, honoring the
user's preference; private models and plan warnings stay local. Ordinary source
translation inconsistencies return unready plans. Schedule edits, steam, plant
creation, replacement and efficiency/utility-factor modeling are outside this skill.


For an explicit Autosize request, review `impact.plant_sizing`: design-day/period
counts, defaulted/explicit model flag and effective translated plant-sizing flag.
Without a verified enabled sizing setup and periods, the edit can be saved but is
not ready to simulate. Configure sizing explicitly or choose justified fixed
values; this script changes neither sizing controls nor design periods. Some
fixed-flow cases still size with the flag off; the guard is conservative.
