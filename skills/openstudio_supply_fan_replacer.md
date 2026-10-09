---
name: openstudio-supply-fan-replacer
description: Replace a directly connected air-loop supply fan between constant-volume and variable-volume classes in a reviewed model copy. Use the performance editor for same-class efficiency or pressure changes.
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

Prefer configured, compatible NLR through `delegated-nlr-modeling`. For selected
local SDK work, run `scripts/doctor.py` with host Python 3.10+ and use the verified
pinned-release OpenStudio executable. Resolve scripts beside this SKILL.md
(Claude: `${CLAUDE_SKILL_DIR}`).

Read [the replacement contract](scripts/references/fan_replacement.md), then
inventory the model. Initial coverage is the sole directly connected
`FanConstantVolume` or `FanVariableVolume` on an unsplit main supply path.
Require the opposite class and explicit efficiency, motor efficiency, pressure,
fan Autosize, terminal/system-sizing preservation and reference-policy choices.
For a variable-volume target, collect all five power coefficients and the minimum
power-flow fraction. Show these choices together with the plan impact/warnings;
do not select a curve or preservation policy on behalf of the user to make a
plan ready. Explain that terminal/system-sizing changes need separate coverage.

Preserve fan boundary nodes, position, availability, motor heat fraction and
metadata. Keep the end-use label unless the user explicitly selects
`end_use_subcategory`; show a retained old-type label warning and the effects on
subcategory meter names. The fan and its two connection objects receive new
identities. Direct references such as EMS actuators and costs remain blocked.
Compatible fan-name keyed output variables and custom electricity meters are
retained and listed in impact; unsupported variable keys still block the plan.
Retain translated setpoint
controls, including MixedAir compensation; a class change must not relocate or
override temperature controls.

```text
<verified-cli> execute_python_script <skill>/scripts/replace_supply_fan.py --input <input.osm> --report <inventory.json>
<verified-cli> execute_python_script <skill>/scripts/replace_supply_fan.py --input <input.osm> --config <config.json> --report <plan.json>
<verified-cli> execute_python_script <skill>/scripts/replace_supply_fan.py --plan <plan.json> --report <apply.json>
```

Apply an unchanged ready plan to publish a new model with its companion folder.
Saved checks cover independent performance/curve getters, identity mappings,
controls, air order, whole-model graph, protected equipment and translation.
Sizing/simulation are separate follow-ups. A fan-class change retains existing
terminal airflow and outdoor-air operation and does not convert the entire
system to VAV/CAV or establish energy savings. Present `airflow_behavior` in
impact: a constant-volume replacement does not force constant airflow; existing
terminals can vary flow and fan power is proportional to that flow at fixed
pressure and efficiency.

Same-class performance edits use `openstudio-supply-fan-performance-editor`.
Return, relief, exhaust, embedded and other fan classes need separate coverage;
diagnose covered failures without generating an ad hoc bypass script.
