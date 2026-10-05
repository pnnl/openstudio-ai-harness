---
name: openstudio-hvac-remover
description: Remove selected air loops, VRF systems or zone HVAC equipment from a copied OSM before replacement, using a reviewed cascade plan.
metadata:
  version: 0.4.0
---

Prefer compatible configured NLR through `delegated-nlr-modeling`. This local
bundle applies after provider fallback/transition, using the recorded host model
path. It runs directly through host tools and preserves the source model.

Run this skill's `scripts/doctor.py` with host Python 3.10+ and use the returned
verified exact-release CLI. Resolve scripts relative to this SKILL.md (Claude:
`${CLAUDE_SKILL_DIR}`). Every entrypoint independently rechecks its SDK.

First inventory systems and their served zones:

```text
<verified-cli> execute_python_script <skill>/scripts/remove_hvac.py --input <input.osm> --report <inventory.json>
```

Select exact names or handles in `air_loops`, `vrf_systems`, `zone_equipment`.
Missing/ambiguous names and duplicate selectors block. Removing a shared air loop
or VRF system affects **all its served zones** and SDK-owned components. Show
that scope to the human; do not infer removal of other systems from a zone list.
Full inventories/cascade details remain in the report; compact inventory output
is capped at eight entries per category.

Example when the user selects VRF and outdoor-air removal while retaining stairs:

```json
{
  "output_model_path": "/absolute/path/hvac-removed.osm",
  "vrf_systems": [{"name": "Office VRF"}],
  "air_loops": [{"name": "Office OA"}]
}
```

Additional stair PTAC/unit-heater removal needs explicit `zone_equipment`
selectors. Use all intended root selectors to remove all space-conditioning
systems; there is no implicit remove-all or plant-loop deletion. Do not select
terminals redundantly when their parent system is selected. Existing plants,
unselected systems, geometry, loads, schedules, thermostats and zone multipliers
are protected; service-water plants and unconditioned zones remain intact.

```text
<verified-cli> execute_python_script <skill>/scripts/remove_hvac.py --input <input.osm> --config <config.json> --report <plan.json>
<verified-cli> execute_python_script <skill>/scripts/remove_hvac.py --plan <plan.json> --report <apply.json>
```

Preflight clones in memory and records the actual SDK removal cascade, affected
zones and preserved object state. Review the full plan before apply, especially
shared-system impacts. Require `ok: true`, `ready: true`. Apply rechecks input hash
and the complete plan; saved validation compares removals and protected state,
then checks EnergyPlus translation before publishing to a new path. Unsupported
cascades that change protected state block; do not substitute an agent-written
removal script to bypass them. Source and existing/concurrent outputs are preserved.

A removed system leaves its zones unserved; do not silently enable ideal loads,
remove thermostats or alter loads. Replacement sizing/simulation stays pending.
Keep OSM and companion folder together, honoring `requires_companion_workflow`
for portable CSV references. For replacement, pass this output to the plant/VAV
skills and run fresh preflight. Do not remove additional equipment just because
VAV preflight reports existing HVAC; return to the explicitly selected scope.
