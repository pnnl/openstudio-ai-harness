---
name: openstudio-tower-performance-editor
description: Edit total design fan electrical power, or explicitly autosize that power, on an existing CoolingTowerVariableSpeed in place. Preserve its connections, thermal/control inputs, curve and identity; flag coupled airflow sizing. Other tower classes and replacement need separate coverage.
metadata:
  version: 0.4.1
---

Prefer compatible, configured NLR through `delegated-nlr-modeling`. After selecting
or transitioning to the local provider, run `scripts/doctor.py` with host Python
3.10+ and use the verified OpenStudio executable. Resolve resources beside this
SKILL.md (Claude: `${CLAUDE_SKILL_DIR}`); launchers require the complete plugin's
shared `sdk/` directory.

Read the [tower contract](references/tower_performance.md) and
[input schema](references/tower_performance.schema.json). Inventory first, then
select one Condenser plant's supply-side CoolingTowerVariableSpeed by name or handle.
Only built-in CoolToolsCrossFlow and YorkCalc are covered.

```text
<verified-cli> execute_python_script <skill>/scripts/edit_tower_performance.py --input <input.osm> --report <inventory.json>
```

On `requires_preparation`, run the bundled preparer and retain its lineage/state
patch, then re-inventory/preflight the prepared copy. Never reuse blocked plans or
write a normalizer. See [preparation](references/model_preparation.md).

```text
<verified-cli> execute_python_script <skill>/scripts/prepare_model.py --input <original.osm> --output <prepared.osm> --report <preparation.json>
<verified-cli> execute_python_script <skill>/scripts/edit_tower_performance.py --input <input.osm> --config <config.json> --report <plan.json>
```

The user supplies positive `design_fan_power_w` for the whole tower, including all
cells, or explicitly chooses the string `Autosize`. It is electrical input at design
airflow, not per-cell power, shaft power, motor hp or a generic efficiency. Do not
infer a rating, motor conversion, standards minimum or fixed baseline from Autosize.
For percentage savings requests with no fixed baseline, obtain sizing/results via
the selected provider or discuss an explicit watt target. Existing authorization
persists; missing choices stay unready for discussion.

Review before/after power and sizing mode, design flows, thermal model, fan curve,
free convection, evaporation mode, EMS, dispatch and other towers. Autosized design
airflow follows fan power, changing reported airflow; recompute airflow-based metrics.
The supported thermal correlations use airflow ratios: changed design airflow
alone does not imply changed cooling, condenser temperatures or chiller/pump energy.
Under SaturatedExit, absolute airflow affects evaporation and make-up water.
Review water use alongside fan electricity; this bundle preserves all other inputs.

Explicit fan power Autosize is 0.0105 × water density × water specific heat × tower
design water volume flow × condenser-loop design ΔT, using sizing-condition fluid
properties. Upstream COP affects this chain when tower design water flow is also
autosized; with fixed tower flow and unchanged fluid properties/ΔT, COP does not
change the sized fan power. Fan electricity changes are not whole-plant savings.

Apply the reviewed ready plan and use its saved-model/translation results. Known
plant or companion blockers set `simulation_ready` false without preventing the
rating edit; true is not certification. The script repairs no plant controls.

```text
<verified-cli> execute_python_script <skill>/scripts/edit_tower_performance.py --plan <plan.json> --report <apply.json>
```

Keep the new OSM with its companion directory and retain report/model lineage in
active workflow state. Use `report-openstudio-failure` for unexpected execution
failures before recovery, honoring the user's reporting preference; exclude private
models and plan warnings. Source translation inconsistencies are ordinary unready
plan errors. Single-/two-speed towers, user-defined thermal models, curve/thermal/
control edits and replacement need their own contracts.


For an explicit Autosize request, review `impact.plant_sizing`: design-day/period
counts, defaulted/explicit model flag and effective translated plant-sizing flag.
Without a verified enabled sizing setup and periods, the edit can be saved but is
not ready to simulate. Configure sizing explicitly or choose justified fixed
values; this script changes neither sizing controls nor design periods. Some
fixed-flow cases still size with the flag off; the guard is conservative.
