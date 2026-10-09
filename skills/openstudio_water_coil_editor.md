---
name: openstudio-water-coil-editor
description: Edit a main-supply water coil's ratings, name, availability, autosizing and controller settings in place, preserving coil, controller, connection, metadata and reference handles.
metadata:
  version: 0.4.0
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

Prefer configured, compatible NLR through `delegated-nlr-modeling`. After selecting
or transitioning to local SDK work, run `scripts/doctor.py` with host Python 3.10+
and use its verified pinned-release OpenStudio executable. Resolve files beside
this SKILL.md (Claude: `${CLAUDE_SKILL_DIR}`); the entrypoint guards the SDK too.

Use this skill for requested settings changes to a directly connected main-supply
CoilHeatingWater or CoilCoolingWater. It calls setters on the existing coil and
controller. Nodes, plant, metadata and incoming references retain their identities;
LifeCycleCost and EMS references are supported. Read
[the edit contract](scripts/references/water_coil_edit.md) for supported fields,
partial controller edits and the explicit Autosize reset. Select the coil by exact
name or handle. Unspecified fields retain their values, including controller name
and sensor/actuator nodes. Renaming a coil does not implicitly rename its controller.

```text
<verified-cli> execute_python_script <skill>/scripts/edit_water_coil.py --input <input.osm> --report <inventory.json>
<verified-cli> execute_python_script <skill>/scripts/edit_water_coil.py --input <input.osm> --config <config.json> --report <plan.json>
<verified-cli> execute_python_script <skill>/scripts/edit_water_coil.py --plan <plan.json> --report <apply.json>
```

All changed values must reflect the user's request. Collect missing choices rather
than adopting a defaults profile. Present the before/after ratings, schedule, names,
controller settings, plant warnings and affected-zone count when review is needed.
A fully specified request already authorizes those changes. Apply only an unchanged
ready plan. An explicit `sizing: Autosize` resets heating capacity/UA/water flow or
cooling air/water flow, plus controller maximum flow; it retains design conditions.

Heating rated-temperature edits under the UA method change informational rating
metadata, not the operating design point. Explain `impact.rating_usage` when
reviewing the request. Missing plant supply equipment, pump or outlet setpoint
manager produces a warning and `simulation_ready: false`; it does not block an
in-place edit or authorize plant repair. The edit keeps that incomplete plant
unchanged; plant type/design-condition checks and saved validation still apply.

Adding a coil uses `openstudio-water-coil-connector`, which attaches only at the
main supply outlet. Class conversion, plant migration, location changes and
OA-stream/unitary/terminal locations need separate coverage. Same-class settings
changes always use this editor; the deferred clone/reconnect primitive is not an
exported operation. Report a covered failure without drafting an ad hoc substitute.
Whole-system VAV/CAV creation uses shared helpers inside its parent transaction.

Return the copied output, unchanged coil/controller handles, before/after values
and reports. Independent saved settings/identity checks and EnergyPlus translation
precede publication. Keep the OSM and `<stem>/` companion together; honor
`requires_companion_workflow`. Sizing/simulation is a separate requested workflow;
an EMS program can override runtime behavior.
