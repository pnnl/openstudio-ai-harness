---
name: openstudio-water-coil-ratings-editor
description: Edit ratings on an existing main-supply heating or cooling water coil in place, preserving coil, connection, controller and reference identities.
metadata:
  version: 0.4.0
---

Prefer configured, compatible NLR through `delegated-nlr-modeling`. After selecting
or transitioning to local SDK work, run `scripts/doctor.py` with host Python 3.10+
and use its verified pinned-release OpenStudio executable. Resolve files beside
this SKILL.md (Claude: `${CLAUDE_SKILL_DIR}`); the entrypoint guards the SDK too.

Use this skill for explicit rating changes to a directly connected main-supply
CoilHeatingWater or CoilCoolingWater. It calls setters on the existing coil;
availability, nodes, plant, controller, metadata and incoming references remain
unchanged. LifeCycleCost and EMS references are supported. Read
[the rating contract](scripts/references/water_coil_ratings.md) for supported fields
and effective-condition checks. Select the coil by exact name or handle.

```text
<verified-cli> execute_python_script <skill>/scripts/edit_water_coil_ratings.py --input <input.osm> --report <inventory.json>
<verified-cli> execute_python_script <skill>/scripts/edit_water_coil_ratings.py --input <input.osm> --config <config.json> --report <plan.json>
<verified-cli> execute_python_script <skill>/scripts/edit_water_coil_ratings.py --plan <plan.json> --report <apply.json>
```

The target and changed values must reflect the user's request. Retain unspecified
ratings; do not choose a defaults profile or turn a rating edit into replacement.
Present the plan's before/after values, plant warnings and affected-zone count when
choices need review. A fully specified request already authorizes those changes.
Missing choices remain unready for discussion. Apply only an unchanged ready plan.

A request to add a coil, create a new coil identity or change its connections uses
`openstudio-water-coil-connector`. OA-stream, unitary, terminal/reheat or other coil
classes need separate coverage. Report a covered failure without drafting an ad
hoc substitute. Whole-system VAV/CAV creation shares the equipment helpers within
its parent transaction and does not invoke this skill for each coil.

Return the copied output, unchanged coil handle, before/after values and reports.
Saved-model identity/settings checks and EnergyPlus translation precede publication.
Keep the OSM and `<stem>/` companion together; honor `requires_companion_workflow`.
Sizing/simulation is a separate request; an EMS program can override runtime behavior.
