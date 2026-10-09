---
name: openstudio-pump-performance-editor
description: Edit an existing plant-loop constant- or variable-speed pump's head, efficiency, electric-power sizing or simple operating controls in place. Retain pump identity and plumbing; class replacement and headered pumps require separate coverage.
metadata:
  version: 0.4.0
---

Prefer configured, compatible NLR through `delegated-nlr-modeling`. After a local
provider selection/transition, run `scripts/doctor.py` with host Python 3.10+ and
use its verified exact-release OpenStudio executable. Resolve resources beside
this SKILL.md (Claude: `${CLAUDE_SKILL_DIR}`); the entrypoint guards the SDK too.

Use this independent skill for explicitly selected `PumpConstantSpeed` or
`PumpVariableSpeed` on a plant supply or demand side. Multiple pumps are allowed;
edit only the selected pump. Read [the contract](scripts/references/pump_performance.md)
for fields, power sizing and preserved state. Inventory before choosing a target:

```text
<verified-cli> execute_python_script <skill>/scripts/edit_pump_performance.py --input <input.osm> --report <inventory.json>
<verified-cli> execute_python_script <skill>/scripts/edit_pump_performance.py --input <input.osm> --config <config.json> --report <plan.json>
```

The target and requested changes must come from the user. Present the plan's
before/after values, selected plant side and warnings when choices need review.
Existing values are retained; do not infer an autosizing reset or part-load curve
from an efficiency request. Fixed electric power and `PowerPerFlow` sizing can
mask head/efficiency changes. Discuss the existing power method when the user's
goal is energy reduction. Missing choices leave preflight unready for discussion.
A request specifying target and settings authorizes those edits; preserve that
authorization across turns. No prototype-default approval profile is needed.

```text
<verified-cli> execute_python_script <skill>/scripts/edit_pump_performance.py --plan <plan.json> --report <apply.json>
```

Apply only an unchanged ready plan. Scripts check source/resource hashes, edit the
existing pump, reload and independently verify requested values and protected
objects, then translate to EnergyPlus before publishing a new model copy. Pump,
node, connection, metadata and incoming-reference handles remain stable, including
EMS actuators and LifeCycleCost. Retained EMS/schedules/pressure controls can still
affect operation; forward translation does not establish simulation performance.

This operation does not change pump class, minimum/design flow, schedules, plant
sizing, pressure-reset controls, loop arrangement or other pumps. Four explicit
variable-speed coefficients describe power versus flow; they do not install a
VFD reset system or convert a constant-flow plant. Headered/condensate pumps and
real class replacement need separate coverage. Report covered failures without
writing a substitute or broadening the edit.

Return output/report paths, the retained pump handle and before/after settings.
Keep the OSM and `<stem>/` companion together; honor `requires_companion_workflow`.
Hand sizing and performance assessment to the selected simulation provider.
