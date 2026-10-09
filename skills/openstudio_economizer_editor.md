---
name: openstudio-economizer-editor
description: Edit economizer type, lockout and temperature/enthalpy cutoffs in place on an existing air loop's outdoor-air controller. Preserve ventilation, DCV, schedules, sizing, equipment and handles; use separate coverage for OA topology or heat recovery.
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

Prefer configured, compatible NLR through `delegated-nlr-modeling`. After a local
provider selection/transition, run `scripts/doctor.py` with host Python 3.10+ and
use the verified exact-release OpenStudio executable. Resolve scripts beside
this SKILL.md (Claude: `${CLAUDE_SKILL_DIR}`); the entrypoint guards the SDK too.

Use this independent operation for one explicitly selected unsplit air loop with
an existing direct outdoor-air system. Read [the contract](scripts/references/economizer.md)
and [input schema](scripts/references/economizer.schema.json). Inventory first:

```text
<verified-cli> execute_python_script <skill>/scripts/edit_economizer.py --input <input.osm> --report <inventory.json>
<verified-cli> execute_python_script <skill>/scripts/edit_economizer.py --input <input.osm> --config <config.json> --report <plan.json>
```

Ask only for missing choices. The user chooses the target and requested settings;
retain all unspecified values. Show effective before/after limits and lockout,
retained ventilation/schedule controls and warnings. All nonblank cutoffs remain
additional restrictions, even after changing the economizer type. A null limit
explicitly removes that cutoff; do not infer resets, climate/template settings,
DCV changes, sizing or savings from a request to enable economizing. An explicit
target and settings authorize those edits; preserve authorization across turns.
No prototype profile or repeated blanket approval is required.

A 100% minimum OA fraction can prevent economizer modulation; maximum OA caps,
force schedules, high-humidity control, EMS and bypass action can also affect
operation. Discuss these retained controls when the user's intended result cannot
be achieved by an economizer-only edit. Missing choices leave an unready plan
for discussion. Missing weather can remain a simulation warning for this edit.
Enabled economizers need a translated mixed-air Temperature setpoint source. The
preview inspects the requested result and reports its managers; when none is
verified, keep `simulation_ready: false` and discuss setpoint/custom EMS control.
This edit adds no managers and does not certify other equipment control.

```text
<verified-cli> execute_python_script <skill>/scripts/edit_economizer.py --plan <plan.json> --report <apply.json>
```

Apply an unchanged ready plan. The script rechecks source/resource hashes, edits
the existing controller, reloads and independently verifies requested fields and
protected model state, then translates to EnergyPlus before publishing a copied
model. Controller, mechanical-ventilation, OA-system, node, connection and metadata
handles stay stable, including incoming references. Report output/report paths,
before/after settings, warnings and the retained controller handle. Keep the OSM
and `<stem>/` companion together and honor `requires_companion_workflow`.

Minimum ventilation, DCV, schedules, action/staging, heat-recovery bypass, supply
setpoints, sizing, equipment arrangement and external references remain unchanged.
ElectronicEnthalpy requires an existing quadratic/cubic limit curve; this skill
does not create curves. Shared/dedicated OA, split-supply systems and whole-system conversion need
separate coverage.
Report covered failures without writing a substitute script or broadening the
edit. Route sizing/simulation to the selected provider; translation success does
not establish annual performance or ventilation compliance.

Use `openstudio-outdoor-air-connector` for direct OA/recovery attachment and
`openstudio-heat-recovery-editor` for existing recovery performance/control edits.
