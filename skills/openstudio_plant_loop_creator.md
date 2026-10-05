---
name: openstudio-plant-loop-creator
description: Create hot-water and chilled-water plants, including condenser loops for water-cooled chillers, with reviewed bundled SDK scripts.
metadata:
  version: 0.4.0
---

Prefer configured, compatible NLR through `delegated-nlr-modeling`. Use this local
bundle only after provider selection/fallback and any required host-path transition.
Scripts execute directly through host tools, without a modeling MCP prerequisite.

This is an independent plant-building skill for direct plant requests and plant
stages of broader HVAC workflows, not just missing-plant preparation for VAV.
Builds include supply equipment, pumps, controls and chiller-to-condenser
connections. Air-side water coils are connected to plant demand branches by the
selected air-side skill, using this skill's output model and plant names/handles.
Do not automatically add VAV or remove existing HVAC after a plant-only request.

Run `scripts/doctor.py` with host Python 3.10+, then use its verified exact-release
OpenStudio executable. Resolve scripts from this SKILL.md's directory (Claude:
`${CLAUDE_SKILL_DIR}`). Never bypass the doctor/entrypoint guards with another SDK.

Inspect existing plants before creating duplicates. Fuel/source selection and
`defaults_profile: prototype_plants_v1` require the human's explicit choice;
missing plants do not authorize a new fuel or generic assumptions. Explain that
matching fuel alone does not establish a fair HVAC performance comparison.

Use an absolute input and new output/report paths. Inventory:

```text
<verified-cli> execute_python_script <skill>/scripts/plant_loops.py --input <input.osm> --report <inventory.json>
```

Config example after the human chooses these sources and generic defaults:

```json
{
  "output_model_path": "/absolute/path/with-plants.osm",
  "defaults_profile": "prototype_plants_v1",
  "hot_water": {"name": "Hot Water Loop", "source": "NaturalGas"},
  "chilled_water": {"name": "Chilled Water Loop", "source": "AirCooled", "pumping": "const_pri"}
}
```

Either plant can be omitted. HW sources: NaturalGas/Electricity boilers or
DistrictHeatingWater. CHW sources: AirCooled/WaterCooled electric EIR chillers or
DistrictCooling. HW pumping: Variable/Constant. CHW pumping: const_pri or
const_pri_var_sec (generic common pipe, not PRM heat-exchanger/EMS). `num_chillers`
is 1–3; district cooling uses one source. Optional SI overrides:
`supply_temperature_c`, `delta_temperature_k`; HW `boiler_efficiency`.
WaterCooled creates a new condenser loop named `<CHW name> Condenser`, or the
explicit `condenser_name`, with a variable-speed two-cell tower and wet-bulb
following setpoint. Existing condenser reuse is outside this initial bundle.

The approved profile uses prototype 180 F/20 R HW, 44 F/10.1 R CHW, 60 ft pump
head (15/45 ft primary/secondary), 0.9 motor efficiency, boiler efficiency 0.78
unless overridden, and COP 3.517/1.188 air-cooled or 3.517/0.66 water-cooled.
Condenser design is fixed 85 F/10 R, minimum setpoint 70 F, approach 7 R, pump
49.7 ft. Weather-derived/PRM sizing, heat-pump plants, waterside economizers and
standards postprocessing are outside this profile. Equipment capacity/flow and
unspecified performance curves retain the pinned SDK defaults/autosizing.

```text
<verified-cli> execute_python_script <skill>/scripts/plant_loops.py --input <input.osm> --config <config.json> --report <plan.json>
<verified-cli> execute_python_script <skill>/scripts/plant_loops.py --plan <plan.json> --report <apply.json>
```

Review the full saved assumptions and selected sources; require preflight
`ok: true`, `ready: true`. Apply requires the exact saved plan and rechecks its
hash/configuration. Require saved getter/topology and EnergyPlus translation
validation before using the output. Source and existing outputs are preserved;
resources follow the companion workflow. Keep OSM and `<stem>/` together; CSV
outputs marked `requires_companion_workflow` need Model.load/workflow attachment.

For a requested air-side stage, pass the output and plant names/handles to its
skill. For VAV, use them in a fresh VAV preflight against the output model;
its water-coil creation connects the coils to the selected plants. Plant building
and air-side creation are separate reviewed transactions. Do not draft
plant code as a workaround. Sizing, performance comparison and simulation use
their separate workflows; creation/translation do not prove annual performance.
