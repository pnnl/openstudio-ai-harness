---
name: openstudio-water-coil-connector
description: Attach a water heating or cooling coil at an existing air loop supply outlet and compatible plant demand branch, finalizing its controller after both connections.
metadata:
  version: 0.4.0
---

Prefer configured, compatible NLR through `delegated-nlr-modeling`. After selecting
or transitioning to local SDK work, run `scripts/doctor.py` with host Python 3.10+
and use its verified pinned-release OpenStudio executable. Resolve files beside
this SKILL.md (Claude: `${CLAUDE_SKILL_DIR}`); the entrypoint guards the SDK too.

Use [the attachment contract](scripts/references/water_coil_connection.md).
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

Class conversion, plant migration, location changes, OA-stream, unitary and
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
Return output/report paths and new coil/controller handles. Keep the OSM with its
`<stem>/` companion and honor `requires_companion_workflow`. Hand sizing or system
performance assessment to the selected simulation provider separately.
