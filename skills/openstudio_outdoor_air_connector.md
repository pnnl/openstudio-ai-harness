---
name: openstudio-outdoor-air-connector
description: Attach a direct outdoor-air intake to a served air loop without one, or attach sensible/latent heat recovery to empty direct OA and relief streams. Preview scoped rewiring and require explicit equipment and control choices.
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

Prefer configured, compatible NLR through `delegated-nlr-modeling`. After local
provider selection/transition, run `scripts/doctor.py` with host Python 3.10+ and
use the verified exact-release executable. Resolve scripts beside this SKILL.md
(Claude: `${CLAUDE_SKILL_DIR}`); the entrypoints guard the SDK version.

Choose the independent operation matching the request:

- **New intake:** [contract](scripts/references/outdoor_air_attach.md) and
  [schema](scripts/references/outdoor_air_attach.schema.json), entrypoint
  `scripts/attach_outdoor_air.py`. One served, unsplit loop with no OA system;
  attachment is at the main supply inlet ahead of a direct fan/coil. Require
  explicit flow limits, schedule references/nulls, DCV, MV availability, ZoneSum,
  NoEconomizer and bypass choices. Economizer enablement is a subsequent editor
  operation with its own translated-control check. Zone OA/People, terminals,
  system sizing and existing equipment remain intact.
- **New heat recovery:** [contract](scripts/references/heat_recovery.md) and
  [schema](scripts/references/heat_recovery.schema.json), entrypoint
  `scripts/manage_heat_recovery.py`, `mode: attach`. Existing uniquely owned
  direct OA system with nodes only in both OA/relief streams. Require explicit
  75%/100% effectiveness, interpolation policy, type, availability, nominal
  flow/power, frost settings, economizer lockout, bypass and outlet-control choice.
  Optional pretreat control requires explicit limits and a verified mixed-air
  reference setpoint. This wires both streams; no fan or fixed SAT is added.

```text
<verified-cli> execute_python_script <skill>/<entrypoint> --input <input.osm> --report <inventory.json>
<verified-cli> execute_python_script <skill>/<entrypoint> --input <input.osm> --config <config.json> --report <plan.json>
```

Ask only for missing choices. Present the impact, created objects, changed
connections, ventilation/sizing warnings and simulation readiness. Do not infer
manufacturer effectiveness, wheel/pressure-loss power, frost strategy or a
standards template from a generic prototype example. Explain economizer lockout
and bypass interaction, relief-flow limits and any recirculation frost impact.
When outlet control is off with downstream cooling or a cool scheduled supply
target, discuss uncontrolled recovery and heat-then-cool risk. Review explicit
pretreat/bypass choices and compare coil heating/cooling energy alongside recovery;
more recovered watts alone do not establish savings. Preserve prior authorization;
no blanket defaults profile is required.

```text
<verified-cli> execute_python_script <skill>/<entrypoint> --plan <plan.json> --report <apply.json>
```

Apply an unchanged ready plan. Fresh preview, hashes, scoped graph and object
fingerprints, saved validation and EnergyPlus translation precede publishing a
new copy. Existing equipment retains its handles; boundary connection objects
change as shown. Carry the OSM and `<stem>/` companion together. Use
`openstudio-heat-recovery-editor` for in-place ratings/control edits, independent
ventilation/economizer editors for controller changes, and the selected provider
for sizing/simulation. Shared/dedicated OA, embedded equipment, replacing an
existing exchanger, extra OA-stream coils/fans and air-balancing redesign need
separate coverage. Report covered failures without substitute scripts.
