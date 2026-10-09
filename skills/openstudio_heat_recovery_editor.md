---
name: openstudio-heat-recovery-editor
description: Edit performance and controls of an existing direct outdoor-air sensible/latent heat exchanger in place, preserving equipment, curves, nodes and references. Use the outdoor-air connector for new attachment.
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
(Claude: `${CLAUDE_SKILL_DIR}`); the entrypoint guards the SDK version.

Read [the contract](scripts/references/heat_recovery.md) and
[schema](scripts/references/heat_recovery.schema.json). Select one existing
`HeatExchangerAirToAirSensibleAndLatent` serving both OA and relief streams of an
unsplit, uniquely owned direct air-loop OA system. Use `mode: edit` with explicit
partial `settings`. Ask only for missing choices; honor existing authorization.

```text
<verified-cli> execute_python_script <skill>/scripts/manage_heat_recovery.py --input <input.osm> --report <inventory.json>
<verified-cli> execute_python_script <skill>/scripts/manage_heat_recovery.py --input <input.osm> --config <config.json> --report <plan.json>
```

Show before/after effectiveness, power, nominal flow, availability, frost and
outlet control; explain retained curve multipliers and bypass. Changing 100%
effectiveness also scales retained part-load performance. This operation does
not replace curves, add managers, infer frost protection, adjust fan pressure,
resize equipment or apply a standards template. Enabled outlet control needs a
verified translated Temperature setpoint, including its mixed-air reference
when using pretreat. Discuss simulation-unready warnings before running.
When outlet control is off on a loop with downstream cooling or a cool scheduled supply target, explain
the uncontrolled-recovery warning: winter/shoulder recovery can add cooling
load. Review explicit control/bypass choices and heating/cooling coil energy;
more recovered watts alone do not establish savings.

```text
<verified-cli> execute_python_script <skill>/scripts/manage_heat_recovery.py --plan <plan.json> --report <apply.json>
```

Apply an unchanged ready plan. Fresh planning, resource/source hashes, saved-value
checks, whole-model preservation and EnergyPlus translation precede publishing a
new copy. Exchanger, curve, control, node, connection and incoming-reference
handles remain stable, including costs and EMS actuators. Report output paths,
warnings and simulation readiness; carry the OSM and `<stem>/` companion together.
Use `openstudio-outdoor-air-connector` for attachment, the economizer/ventilation
editors for their controller settings, and the selected provider for sizing and
simulation. Report covered failures without generating a substitute script.
