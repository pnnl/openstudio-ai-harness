---
name: openstudio-chiller-performance-editor
description: Edit reference COP on one existing air- or water-cooled ChillerElectricEIR in place, preserving curves, sizing inputs, water circuits, controls and identities. Use for explicit COP changes; other chiller classes, heat recovery, thermosiphon and replacement need separate coverage.
metadata:
  version: 0.4.1
---

Prefer configured, compatible NLR through `delegated-nlr-modeling`. After selecting
or transitioning to the local provider, run `scripts/doctor.py` with host Python
3.10+ and use its verified OpenStudio executable. Resolve resources beside this
SKILL.md (Claude: `${CLAUDE_SKILL_DIR}`). The complete plugin owns shared `sdk/`.

Read the [chiller contract](references/chiller_performance.md) and
[input schema](references/chiller_performance.schema.json). Inventory the model,
then select one Cooling plant's supply-side electric EIR chiller by name or handle.

```text
<verified-cli> execute_python_script <skill>/scripts/edit_chiller_performance.py --input <input.osm> --report <inventory.json>
```

On `requires_preparation`, run the bundled preparer, retain its lineage/state patch,
then re-inventory and preflight against the prepared copy. Never reuse a blocked
plan or write an ad hoc normalizer. See [preparation](references/model_preparation.md).

```text
<verified-cli> execute_python_script <skill>/scripts/prepare_model.py --input <original.osm> --output <prepared.osm> --report <preparation.json>
<verified-cli> execute_python_script <skill>/scripts/edit_chiller_performance.py --input <input.osm> --config <config.json> --report <plan.json>
```

The user supplies `reference_cop`, a positive finite cooling W/electric W value at
the retained reference conditions. Do not substitute IPLV, seasonal or whole-plant
COP or infer a standards minimum. If the retained condenser fan power ratio is
positive, COP must exclude that separately modeled fan power. Resolve an unclear
rating basis before preflight. Missing choices stay unready for discussion;
existing authorization persists. Review before/after COP, reference temperatures,
curves, sizing, condenser type/plant, EMS and other chillers/dispatch. A curve and
retained controls can change actual efficiency. Capacity/flow inputs and Autosize
flags are preserved. A COP change alters condenser heat rejection: on the next
sizing run, autosized condenser flow, pumps and towers can acquire new sizes and
energy use. Review the plan's listed autosized condenser equipment and compare
plant energy separately from chiller electricity. Curve replacement, condenser
conversion and plant-readiness repairs require separate operations.

COP below 2 or above 10 produces a non-blocking plausibility warning. Confirm units:
COP = 3.517 / (kW per ton), or COP = EER / 3.412. The script retains the explicit
COP without converting it or choosing a substitute. Source COP/curve translation
inconsistencies return unready plan errors for diagnosis, not unexpected failures.

Ready-to-edit and ready-to-simulate are separate. This operation explicitly combines
known operation and companion blockers in `simulation_ready`; it is not simulation
certification. Discuss missing pumps/setpoints or heat rejection without silently
repairing them. Apply only the reviewed plan, then hand simulation/results to the
selected provider. Other chiller classes, heat-recovery and thermosiphon operation
need their own contracts.

```text
<verified-cli> execute_python_script <skill>/scripts/edit_chiller_performance.py --plan <plan.json> --report <apply.json>
```

Use report files, keep the new OSM with its companion directory, and retain source,
plan, apply and output artifact lineage in workflow state when active. On unexpected
execution failures use `report-openstudio-failure` before recovery, honoring the
user's reporting preference; do not publish private models or plan warnings.
