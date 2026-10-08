---
name: openstudio-water-coil-connector
description: Attach a water coil at an air loop supply outlet, or migrate an existing main-supply water coil to another compatible plant while retaining coil and controller identity.
metadata:
  version: 0.4.0
---

Prefer configured, compatible NLR through `delegated-nlr-modeling`. After selecting
or transitioning to local SDK work, run `scripts/doctor.py` with host Python 3.10+
and use its verified pinned-release OpenStudio executable. Resolve files beside
this SKILL.md (Claude: `${CLAUDE_SKILL_DIR}`); the entrypoint guards the SDK too.

Use [the attachment and migration contract](scripts/references/water_coil_connection.md).
Settings changes to an existing coil, including name, availability, Autosize resets
and controller settings, use `openstudio-water-coil-editor` in place.

Attachment requires an explicitly selected air loop, main-supply outlet node,
compatible existing plant, coil name, availability schedule, cooling design conditions,
autosizing decision and controller settings. Only the air loop's supply outlet is
supported; interior and inlet nodes remain
unready even with a Temperature setpoint manager. The outlet must already have
a Temperature setpoint manager. The coil is inserted immediately upstream of it.
Use `openstudio-plant-loop-creator` for a requested new plant, then pass its copied
output and plant handle here. This module connects plant demand and air supply;
it does not create plants or change the system's sizing/terminal strategy.

Heating attachment uses the UA method. Its four rated temperatures are optional
nominal-rating metadata, not operating design conditions; omitted fields retain
pinned SDK defaults shown in the plan. Review `impact.rating_usage` and the full
`assumption_review` so the user sees that plant/air-system sizing governs the coil.
Do not solicit these temperatures as required design choices. Input relationship
checks still apply. Cooling design inputs remain required.

For `operation: migrate_plant`, select the existing coil and destination plant,
and explicitly choose `sizing: Autosize`. The source coil must occupy a dedicated
single-coil demand branch and use Temperature/Flow control with matching action
and zero minimum flow. Both plants must use water. The destination requires supply
equipment, a pump, outlet setpoint control and compatible design temperatures.
Review both plant temperatures, sizing resets, affected zones and
`source_plant_remaining_coil_count` in `impact`. A zero count warns that source
equipment/pumps remain with their current sizing settings. Other demand equipment
is counted separately, so a plant serving other loads is not called unserved.
Review retention/cleanup with the user; `openstudio-hvac-remover` currently excludes
plant deletion, and migration does not authorize it. Active fixed cooling water
design temperatures or NominalCapacity heating rated temperatures stay unchanged.
If they differ from the destination, review `retained_water_rating_mismatches` and
use `openstudio-water-coil-editor` for explicitly selected follow-up rating changes
on the copied output before sizing when needed. UA metadata and Autosize cooling
inlet temperatures do not produce this active-rating follow-up warning.
Coil, controller, air nodes, metadata and incoming coil/controller references
retain their handles. Water nodes and demand connection handles may change;
external references to the removed water nodes block the move. Existing branches
and air-system settings remain protected; the source plant is retained even if unused.
Create a requested destination with the plant-loop skill first. This operation
does not resize the plant or certify performance; request sizing separately.

Class conversion, air-location changes, OA-stream, unitary and
terminal coils need separate coverage. Same-class replacement is not exported;
the clone/reconnect primitive remains internal pending a real replacement contract.

```text
<verified-cli> execute_python_script <skill>/scripts/connect_water_coil.py --input <input.osm> --report <inventory.json>
<verified-cli> execute_python_script <skill>/scripts/connect_water_coil.py --input <input.osm> --config <config.json> --report <plan.json>
<verified-cli> execute_python_script <skill>/scripts/connect_water_coil.py --plan <plan.json> --report <apply.json>
```

Collect missing choices instead of adopting an unrequested prototype profile.
User-specified targets/settings authorize those changes; preserve authorization.
Present placement, plant, design conditions, controller settings, autosizing and
identity changes when review is needed. Apply only an unchanged ready plan.

The script finalizes controller action, flow limits, convergence and sensor/
actuator nodes after both connections. It reloads the model, checks original
objects/topology, controller ownership/settings and EnergyPlus translation before
publishing a new copy. Do not substitute an ad hoc script for a covered failure.
Return output/report paths and the resulting coil/controller handles. Keep the OSM with its
`<stem>/` companion and honor `requires_companion_workflow`. Hand sizing or system
performance assessment to the selected simulation provider separately.
