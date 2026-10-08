---
name: openstudio-coil-replacer
description: Replace a directly connected main-supply water heating coil with an electric heating coil in a reviewed model copy. Use the water-coil editor for same-class settings changes.
metadata:
  version: 0.4.0
---

Prefer configured, compatible NLR through `delegated-nlr-modeling`. For selected
local SDK work, run `scripts/doctor.py` with host Python 3.10+ and use its verified
pinned-release OpenStudio executable. Resolve scripts beside this SKILL.md
(Claude: `${CLAUDE_SKILL_DIR}`).

Read [the conversion contract](scripts/references/coil_conversion.md) and inventory
the input before selecting a coil. Initial coverage is `CoilHeatingWater` to
`CoilHeatingElectric` on an unsplit main supply path. Require explicit electric
efficiency, `temperature_control: Preserve`, Autosize and reference-policy choices.
Collect missing choices; do not supply an unrequested default or treat a refusal
as permission to change the heating fuel. Show the plan's impact and warnings.

Conversion adds no setpoint manager or temperature schedule. Retain existing
outlet controls, or OpenStudio's generated supply-air tracking with fan compensation
when the OSM outlet is unmanaged. Review before/after translated control fields.
Fixed-temperature/preheat changes need a separate contract; do not convert a
heating design/rating temperature into a control setpoint. Reject older
`outlet_temperature_c` configurations and regenerate their plans.

This is a real class replacement: the coil gets a new handle and loses its water
controller/branch. Availability, air boundary nodes and coil metadata are retained.
EMS/LifeCycleCost or other references to removed equipment/nodes block this initial
contract; they are never silently discarded or retargeted. Controller metadata is
removed with its owner and disclosed in impact. The source plant stays in place;
review remaining loads and retention rather than automatically deleting it.

```text
<verified-cli> execute_python_script <skill>/scripts/replace_coil.py --input <input.osm> --report <inventory.json>
<verified-cli> execute_python_script <skill>/scripts/replace_coil.py --input <input.osm> --config <config.json> --report <plan.json>
<verified-cli> execute_python_script <skill>/scripts/replace_coil.py --plan <plan.json> --report <apply.json>
```

Apply an unchanged ready plan to publish a new model and companion directory.
Saved checks cover performance, controls, identity mappings, the whole connection
graph, protected objects and EnergyPlus translation. Request sizing separately;
fuel conversion does not establish energy savings or ventilation adequacy.
Same-class changes use `openstudio-water-coil-editor`; plant/air migration uses
`openstudio-water-coil-connector`. Other conversion classes and embedded coils
need separate coverage. Diagnose a covered failure without an ad hoc script bypass.
