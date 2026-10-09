---
name: openstudio-cav-system-creator
description: Create a prototype CAV air system with water heating/reheat and water or approved two-speed DX cooling using reviewed bundled scripts.
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

Prefer configured, compatible NLR through `delegated-nlr-modeling`. This local
skill runs directly through host tools after provider fallback/path transition.
Run `scripts/doctor.py` with host Python 3.10+, then use its verified exact-release
OpenStudio executable. Resolve scripts relative to this SKILL.md (Claude:
`${CLAUDE_SKILL_DIR}`). The entrypoint independently guards the SDK.

This skill creates the generic `model_add_cav` arrangement: constant-volume supply
fan, central water heating, zone water reheat and VAV-reheat terminals. Its name
does not mean every zone has constant airflow. Clarify another requested CAV
arrangement rather than silently substituting it. It does not select Hospital,
ASHRAE or building-specific ventilation/damper policies.

Read [the input contract](scripts/references/cav_input.md). Inventory if needed:

```text
<verified-cli> execute_python_script <skill>/scripts/cav_system.py --input <input.osm> --report <inventory.json>
```

Use explicit unserved target zones with spaces and dual-setpoint thermostats.
For replacement, independently select removal scope through `openstudio-hvac-remover`.
Use `openstudio-plant-loop-creator` for requested plant construction; CAV creation
consumes explicitly selected compatible plants and connects water coils to their
demand branches. Missing CHW does not authorize choosing DX or creating a plant.

Example after the human selects generic settings, the plants and target zones:

```json
{
  "system_name": "Office CAV",
  "output_model_path": "/absolute/path/cav.osm",
  "target_zones": [{"name": "Office Zone"}],
  "defaults_profile": "prototype_cav_v1",
  "outdoor_air_schedule": null,
  "central_heating": {"type": "Water", "plant_loop": {"name": "HW"}},
  "central_cooling": {"type": "Water", "plant_loop": {"name": "CHW"}},
  "reheat": {"type": "Water", "plant_loop": {"name": "HW"}}
}
```

Require an explicit outdoor-air choice, even with an accepted profile:
`outdoor_air_schedule: null` uses ZoneSum minimum ventilation;
`{"builtin":"AlwaysOnDiscrete"}` on the minimum-fraction field means **100%
outdoor air whenever the system runs**. Show that meaning in the human review.
The latter enables both all-outdoor-air sizing flags, and an economizer cannot
increase its outdoor-air fraction. Other positive or variable fraction schedules
conservatively size both coils for 100% outdoor air; show this possible oversizing
in the review. Profile acceptance cannot make this choice for the human.

Set `defaults_profile` only after explicit human selection. If undecided or
declined, omit it and run partial preflight with the new output path specified;
the saved `plan.assumption_review` proposes settings without authorizing apply.
Present a grouped table/form showing user inputs, proposed defaults and fixed
controls; use "Use proposed settings" or "Review and adjust", with cancellation
separate. Preserve previous choices. Supported edits stay explicit in config;
unsupported changes remain pending for scoped development/provider coverage.
DX requires `central_cooling: {"type": "DXTwoSpeed", "dx_approved": true}` after
the human explicitly chooses it. A broad CAV request is not defaults/DX approval.

```text
<verified-cli> execute_python_script <skill>/scripts/cav_system.py --input <input.osm> --config <config.json> --report <plan.json>
<verified-cli> execute_python_script <skill>/scripts/cav_system.py --plan <plan.json> --report <apply.json>
```

Require `ok: true`, `ready: true` and review the saved assumptions. Apply consumes
the unchanged ready plan, rechecks input/configuration/resources, assembles shared
equipment in one transaction, reloads and independently validates actual settings,
connections/counts and EnergyPlus translation before exclusive publication.
Source and existing outputs are preserved. There is no per-equipment agent chain.
Do not draft substitute code for a failed covered operation.

Return the new output/report paths, assumptions and warnings. Keep OSM and
`<stem>/` companion together; honor `requires_companion_workflow` for CSV references.
Creation/translation does not establish ventilation adequacy, annual performance
or code compliance. Sizing and simulation remain separate workflows.
