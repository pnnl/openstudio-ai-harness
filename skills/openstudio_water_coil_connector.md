---
name: openstudio-water-coil-connector
description: Attach a water heating or cooling coil to an existing main air-supply path and plant, or explicitly replace a water coil on that same plant while managing its controller.
metadata:
  version: 0.4.0
---

Prefer configured, compatible NLR through `delegated-nlr-modeling`. After selecting
or transitioning to local SDK work, run `scripts/doctor.py` with host Python 3.10+
and use its verified pinned-release OpenStudio executable. Resolve files beside
this SKILL.md (Claude: `${CLAUDE_SKILL_DIR}`); the entrypoint guards the SDK too.

Use [the connection contract](scripts/references/water_coil_connection.md) to choose
between attachment and explicit replacement. Rating-only changes use
`openstudio-water-coil-ratings-editor` and preserve identity without rewiring.

Attachment requires an explicitly selected air loop, main-supply outlet node,
compatible existing plant, coil name, availability schedule, design conditions,
autosizing decision and controller settings. The selected node must already have
a Temperature setpoint manager. The coil is inserted immediately upstream of it.
Use `openstudio-plant-loop-creator` for a requested new plant, then pass its copied
output and plant handle here. This module connects plant demand and air supply;
it does not create plants or change the system's sizing/terminal strategy.

Replacement requires an explicit request for a new coil identity and `operation:
replace`. Initial coverage retains the water-coil class and existing plant, four
boundary nodes, metadata and unspecified ratings. It creates new coil/controller/
connection handles, resets capacity/flow sizing to the chosen Autosize contract,
and rejects references needing migration. Show old/new identity implications in
the plan review. Efficiency or design-temperature changes alone do not justify
replacement. Class conversion, plant migration, OA-stream, unitary and terminal
locations require separate coverage.

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
