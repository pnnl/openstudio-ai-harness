---
name: openstudio-ventilation-editor
description: Edit minimum/maximum outdoor-air flow, OA schedule references and ZoneSum demand-controlled ventilation in place on an existing direct air-loop OA system. Preserve zone OA definitions, People, schedules, sizing, economizer, topology and handles.
metadata:
  version: 0.4.0
---

Prefer configured, compatible NLR through `delegated-nlr-modeling`. After a local
provider selection/transition, run `scripts/doctor.py` with host Python 3.10+ and
use the verified exact-release OpenStudio executable. Resolve scripts beside this
SKILL.md (Claude: `${CLAUDE_SKILL_DIR}`); the entrypoint also guards the SDK version.

Use this independent operation on one explicitly selected unsplit air loop with
an existing uniquely owned direct OA system. Read [the contract](scripts/references/ventilation.md)
and [schema](scripts/references/ventilation.schema.json). Inventory first:

```text
<verified-cli> execute_python_script <skill>/scripts/edit_ventilation.py --input <input.osm> --report <inventory.json>
<verified-cli> execute_python_script <skill>/scripts/edit_ventilation.py --input <input.osm> --config <config.json> --report <plan.json>
```

Ask only for missing choices. Show the effective before/after flow limits, DCV,
schedule roles/ranges, nominal zone OA, occupancy inputs, sizing and warnings.
The user chooses explicit settings; preserve all omitted values. Enabling DCV
does not authorize resetting the controller minimum to zero, clearing a fraction
schedule, changing OA methods, zone definitions or sizing. Review `dcv_effective`
and `dcv_floor` in the impact: a verified fixed floor at/above nominal design OA
sets false and states that DCV cannot reduce OA, with an explicit flow change
needed (for example `minimum_flow_m3_s: 0`). Partial/uncertain floors keep qualified
warnings. OpenStudio can translate a retained Autosize minimum to zero with DCV;
report that verified translated value instead of calling Autosize ineffective.
Null effectiveness does not establish a benefit. Preserve prior authorization;
no defaults profile or blanket approval is required.

DCV toggles require an existing `ZoneSum` mechanical-ventilation controller.
Other retained methods can receive flow/schedule edits, but VRP, CO2/IAQ methods
and template/code policy require separate coverage. Schedule selectors reference
existing typed Constant/Ruleset schedules whose values are all in [0,1]. Null
explicitly clears that controller reference; it does not delete the schedule.
Prepare schedule contents/type limits separately; this operation changes neither.
Minimum flow schedule multiplies the controller floor; minimum fraction acts on
current supply flow. Maximum fraction can cap the ventilation request. Avoid
presenting these as interchangeable occupancy schedules.

Discuss `simulation_ready: false` warnings before simulation: contradictory/zero
caps, unverified occupancy/OA schedules, 100% OA with minimum-OA sizing, fixed
airflow/sizing conflicts, or an enabled economizer lacking a verified mixed-air
temperature setpoint. A ready edit can still be copied with those warnings; do
not promise ventilation compliance, automatic resizing or annual savings.

```text
<verified-cli> execute_python_script <skill>/scripts/edit_ventilation.py --plan <plan.json> --report <apply.json>
```

Apply an unchanged ready plan. The transaction rechecks source/resource hashes,
edits existing controller fields, reloads, independently verifies the requested
values and all protected objects/connections, then translates to EnergyPlus
before publishing a copied model. It preserves controller/MV/OA-system identities,
incoming references, zone OA and People, schedule objects, sizing, economizer and
equipment order. Report paths, before/after values and warnings; carry the OSM and
`<stem>/` companion together and honor `requires_companion_workflow`.

Use `openstudio-economizer-editor` for economizer settings. Use `openstudio-outdoor-air-connector` for direct OA/recovery attachment and
`openstudio-heat-recovery-editor` for existing recovery performance/control edits.
Shared/dedicated OA, ventilation-method redesign and zone/load editing need
separate coverage. Report covered failures without drafting a
substitute script. Sizing, simulation and results use the selected provider.
