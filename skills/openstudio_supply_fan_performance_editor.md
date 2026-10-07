---
name: openstudio-supply-fan-performance-editor
description: Edit efficiency and pressure on an existing direct constant- or variable-volume air-loop supply fan in place, preserving its identity, controls and references.
metadata:
  version: 0.4.0
---

Prefer configured, compatible NLR through `delegated-nlr-modeling`. After a local
provider selection/transition, run `scripts/doctor.py` with host Python 3.10+ and
use its verified exact-release OpenStudio executable. Resolve resources beside
this SKILL.md (Claude: `${CLAUDE_SKILL_DIR}`); the entrypoint also guards the SDK.

Use this independent equipment skill to edit an existing air loop's sole directly
connected `FanVariableVolume` or `FanConstantVolume`. Only explicitly requested
total efficiency, motor efficiency and pressure rise change. The existing fan,
connections, metadata and references retain their handles. Whole-system VAV/CAV
creation uses shared fan functions inside its parent transaction.

Read [the performance-edit contract](scripts/references/fan_performance.md) for
inputs, supported locations and preserved state. Inventory and review targets:

```text
<verified-cli> execute_python_script <skill>/scripts/edit_supply_fan_performance.py --input <input.osm> --report <inventory.json>
<verified-cli> execute_python_script <skill>/scripts/edit_supply_fan_performance.py --input <input.osm> --config <config.json> --report <plan.json>
```

The selected loop and requested changes must come from the user. Existing values
are retained without adopting a prototype defaults profile. Present before/after
values and affected-zone count when choices need review. A request specifying the
target and values authorizes those changes; preserve authorization across turns.
Missing choices leave preflight unready for discussion.

```text
<verified-cli> execute_python_script <skill>/scripts/edit_supply_fan_performance.py --plan <plan.json> --report <apply.json>
```

Apply only an unchanged `ok: true`, `ready: true` plan. The script rechecks source,
configuration and companions, calls setters on the existing fan in memory, then
reloads, checks protected objects and EnergyPlus translation before publishing a
new model copy. It preserves schedules, fan curve/flow settings, sizing, plants,
other systems and incoming references such as LifeCycleCost and EMS actuators.

A request to replace a constant-volume fan with a variable-volume or variable-speed
fan requires a separate class-changing replacement contract. Do not route that
request here or reduce it to an efficiency edit. Embedded packaged/unitary or zone
fans, split supply paths and multiple direct fans also need separate coverage.
Report covered failures without drafting a substitute or broadening the edit.

Return output/report paths, the unchanged fan handle and before/after values. Keep
the OSM and `<stem>/` companion together; honor `requires_companion_workflow`. Hand
sizing or performance assessment to the selected simulation provider separately.
