---
name: openstudio-tower-performance-editor
description: Edit total design fan power/Autosize, minimum fan-airflow ratio or free-convection capacity fraction on an existing CoolingTowerVariableSpeed in place. Preserve its connections, design conditions, unrequested inputs, curve and identity; flag airflow sizing and low-load effects. Other tower classes and replacement need separate coverage.
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
Review water use alongside fan electricity. Power-only edits preserve other inputs.

For low-load operation, accept one or both explicit `minimum_air_flow_ratio`
(0.2–0.5) and `free_convection_capacity_fraction` (0–0.2), optionally with power.
Blank source controls use the pinned EnergyPlus defaults (0.2 minimum airflow,
0.125 free convection), labeled in `source_control_defaults`; unrequested blanks
remain untouched. An edit equal to the effective default remains a no-op.
Require a justified equipment/performance assumption; do not select either from a
savings target. Minimum airflow is the fan-on modulation floor; below it the fan
cycles, so average reported airflow can be smaller. Free convection estimates
fan-off heat rejection at current conditions, not annual free cooling or fan speed.
Higher fractions can overcool water below setpoint, and fan-off operation retains
condenser pumping. These changes affect thermal operation; review cooling, outlet
temperature, tower/chiller/pump electricity and make-up water before claiming
savings. Preserve curves, design conditions, flows, cells, staging and all
unrequested values. Missing assumptions stay unready; use no ad hoc control script.

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
plan errors. Single-/two-speed towers, user-defined thermal models, design-condition/curve/
staging/other control edits and replacement need their own contracts.


For an explicit Autosize request, review `impact.plant_sizing`: design-day/period
counts, defaulted/explicit model flag and effective translated plant-sizing flag.
Without a verified enabled sizing setup and periods, the edit can be saved but is
not ready to simulate. Configure sizing explicitly or choose justified fixed
values; this script changes neither sizing controls nor design periods. Some
fixed-flow cases still size with the flag off; the guard is conservative.
