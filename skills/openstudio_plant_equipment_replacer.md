---
name: openstudio-plant-equipment-replacer
description: Replace a heating-supply hot-water boiler with district heating, or an air/water-cooled EIR chiller with district cooling, using a reviewed copied model. Same-class ratings use performance editors; new plants use the plant creator.
metadata:
  version: 0.4.1
---

Prefer configured compatible NLR through `delegated-nlr-modeling`. After choosing
local modeling, run this skill's `scripts/doctor.py` with host Python 3.10+ and use
its verified OpenStudio 3.11.0 CLI. Resolve scripts beside this SKILL.md (Claude:
`${CLAUDE_SKILL_DIR}`); retain the complete plugin and shared `sdk/` library.
Read the [plant topology contract](references/plant_operations.md) and
[replacement schema](references/plant_replacement.schema.json).

Inventory plants and select one source, target district class, explicit positive
thermal capacity or `Autosize`, and an existing capacity-fraction schedule. Do not
infer useful thermal capacity from boiler fuel input or compressor electric watts.
Existing capacity-fraction schedules need SDK-compatible Dimensionless/nonnegative
type limits; missing/incompatible limits return an ordinary unready plan. Choose
a compatible schedule rather than retrying the SDK setter or reporting a bug.
No reverse conversion, heat recovery, new mechanical source or implicit efficiency/
curve/fuel choice is supported. Same-class requests use the corresponding editor.

```text
<verified-cli> execute_python_script <skill>/scripts/replace_plant_equipment.py --input <input.osm> --report <inventory.json>
<verified-cli> execute_python_script <skill>/scripts/replace_plant_equipment.py --input <input.osm> --config <config.json> --report <plan.json>
```

On `requires_preparation`, run bundled `scripts/prepare_model.py`, retain its lineage
and state patch, then re-inventory and re-preflight the prepared copy. See
[preparation](references/model_preparation.md); do not generate a normalizer.

Review changed fuel/electricity versus purchased thermal energy accounting,
nominal dispatch capacity, capacity schedule, source identity and connections.
Component-setpoint dispatch is unsupported; redesign controls separately rather
than deleting managers implicitly. All direct/name-keyed external source
references, including EMS, costs and output
requests, block under explicit `reference_policy: Reject`; resolve them separately.
Metadata is retained and reassigned. Primary water nodes, plant sizing, pumps,
setpoints, demand equipment and unselected sources remain. Calculated autosizing
results and plant dispatch can change. This does not predict efficiency savings.

A water-cooled chiller requires a dedicated condenser branch without series
equipment; unsupported topology returns an unready plan. Conversion removes that branch. The condenser loop, pumps and
towers remain; show the remaining demand-equipment count. If empty, offer a
separate explicitly selected cleanup through `openstudio-hvac-remover`. Never
silently delete the condenser loop as part of conversion. At zero demand, review
the idle-energy/zero-sizing warning even if `simulation_ready` remains true;
convert-and-stop is not native-validated.

Apply only the reviewed ready plan:

```text
<verified-cli> execute_python_script <skill>/scripts/replace_plant_equipment.py --plan <plan.json> --report <apply.json>
```

Require saved validation and translation success. Keep the new OSM with its
companion folder, store source→replacement lineage and re-run sizing/simulation.
`simulation_ready` combines known operation/companion blockers; it is not a run
certificate. Unexpected failures route to `report-openstudio-failure` before
recovery; expected scope/readiness questions stay local.
