---
name: openstudio-terminal-replacer
description: Replace one connected single-duct VAV no-reheat terminal with a constant-volume no-reheat terminal, or the reverse, in a reviewed model copy. Use the terminal editor for same-class VAV controls; reheat, plant, zone reassignment and whole-system conversions need separate coverage.
metadata:
  version: 0.4.1
---

Prefer configured, compatible NLR through `delegated-nlr-modeling`. After local
provider selection/transition, run `scripts/doctor.py` with host Python 3.10+ and
use its verified exact-release OpenStudio executable. Resolve paths beside this
SKILL.md (Claude: `${CLAUDE_SKILL_DIR}`). The launchers use the complete plugin's
shared `sdk/`; restore an incomplete plugin rather than writing substitute scripts.

Read [the replacement contract](references/terminal_replacement.md) and
[input schema](references/terminal_replacement.schema.json). Inventory first:

```text
<verified-cli> execute_python_script <skill>/scripts/replace_terminal.py --input <input.osm> --report <inventory.json>
```

If inventory/preflight returns `requires_preparation`, run the bundled preparer,
store its `state_patch`/lineage, and re-inventory/preflight the returned
`output_model_path`. Do not reuse the blocked plan or write a normalizer.
`already_current` writes no model. Invalid current references need diagnosis.
See [model preparation](references/model_preparation.md).

```text
<verified-cli> execute_python_script <skill>/scripts/prepare_model.py --input <original.osm> --output <new-prepared.osm> --report <preparation.json>
<verified-cli> execute_python_script <skill>/scripts/replace_terminal.py --input <input.osm> --config <config.json> --report <plan.json>
```

Explicitly select air loop, thermal zone, terminal, target class, maximum airflow
policy (Preserve, Autosize or positive m³/s) and, for a VAV target, Constant minimum
fraction. Record availability/zone-sizing/system-sizing Preserve, reheat None and
reference Reject policies. Missing choices remain unready for discussion; existing
user authorization persists. Do not infer a minimum fraction or reset sizing to
make a request pass. Present the report's before/after values and warnings.

Only VAVNoReheat ↔ ConstantVolumeNoReheat is covered. A VAV source must have a
Constant minimum, no minimum/turndown schedules and terminal OA control off.
Incompatible name-keyed outputs and direct-object references (EMS/costs) block;
supported name-keyed OA Output:Variable requests survive. Name-keyed EMS sensors
remain blocked by reference policy even for that compatible output; retaining
EMS control dependencies needs separate coverage. Do not delete references as a workaround.
Same-class VAV controls use `openstudio-terminal-editor`. Reheat addition/removal,
coil/fuel changes, PIU/dual-duct terminals, zone reassignment and whole-system
VAV/CAV conversions require separate coverage, not ad hoc topology scripts.

This changes one terminal's airflow behavior. Constant-volume requests maximum
flow when available; VAV modulates down to the explicit minimum fraction. Neither
target adds reheat. Review overcooling, ventilation, combined service, retained
fan/OA/DCV and zone/system sizing. Honor `simulation_ready: false`. Run sizing and
simulation separately before drawing comfort or energy conclusions. Review the
reported supply-fan classes: VAV with a retained constant-volume fan uses
flow-proportional fan power without a variable-volume part-load curve. Route a
user-chosen fan-class/curve change to `openstudio-supply-fan-replacer`. If system
fans use Discrete FanSystemModel control, review the reported speed count and
power curve: single-speed cycling and multiple discrete speed levels do not imply
continuous VAV fan-power behavior. FanSystemModel changes need separate coverage;
the bundled fan replacer covers constant-/variable-volume classes only. Plan
warnings can contain model-object names and remain local; do not add their text
to failure diagnostics. If system
sizing or mechanical ventilation uses VRP, terminal conversion can change the
recalculated system OA requirement despite preserved sizing objects; re-run
sizing and verify OA. Do not interpret preservation as unchanged calculated sizing.

```text
<verified-cli> execute_python_script <skill>/scripts/replace_terminal.py --plan <plan.json> --report <apply.json>
```

Apply only the unchanged ready report. The new terminal and two air connections
receive new handles. Zone service, boundary nodes, schedule, equipment-list handle,
slot/priorities/sequential fractions and metadata handle remain. Saved validation
checks the complete scoped raw fields, graph, unrelated objects and translated
terminal/distribution unit/control/zone sequencing before publishing a new copy.
Keep the OSM and `<stem>/` companion together; honor `requires_companion_workflow`.
Store the old→new mapping and report paths in workflow state so later operations
use the new handle. Unexpected failures route to `report-openstudio-failure` before
recovery, including any `failure_receipt`; expected readiness questions do not submit.
