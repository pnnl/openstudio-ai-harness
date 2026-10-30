---
name: openstudio-terminal-editor
description: Edit minimum airflow and reheat controls on one existing single-duct VAV reheat or no-reheat terminal in place, preserving equipment and connections. Use for terminal controls in VAV or prototype CAV systems; terminal replacement and coil ratings need separate coverage.
metadata:
  version: 0.4.1
---

Prefer configured, compatible NLR through `delegated-nlr-modeling`. After a local
provider selection/transition, run `scripts/doctor.py` with host Python 3.10+ and
use its verified exact-release OpenStudio executable. Resolve files beside this
SKILL.md (Claude: `${CLAUDE_SKILL_DIR}`). These launchers use the complete plugin's
shared `sdk/`; restore the plugin for `plugin_incomplete`, rather than searching
for another library or drafting a substitute script.

Read [the terminal contract](references/terminal_edit.md) for fields and control
applicability. Inventory first, then select the terminal, served zone and air loop:

```text
<verified-cli> execute_python_script <skill>/scripts/edit_terminal.py --input <input.osm> --report <inventory.json>
<verified-cli> execute_python_script <skill>/scripts/edit_terminal.py --input <input.osm> --config <config.json> --report <plan.json>
```

If inventory or preflight returns `status: requires_preparation`, run the bundled
preparer through the same verified CLI, then inventory and preflight the returned
`output_model_path` anew:

```text
<verified-cli> execute_python_script <skill>/scripts/prepare_model.py --input <original.osm> --output <new-prepared.osm> --report <preparation.json>
```

Store the preparer's `state_patch` and lineage in workflow state. Do not reuse a
blocked plan or write a normalizer. `already_current` writes no model; invalid
current references need diagnosis. See [model preparation](references/model_preparation.md).

Requested target/settings must come from the user. Missing choices leave preflight
unready for discussion. Existing authorization persists; a request specifying the
terminal and settings authorizes those scoped edits. No prototype approval profile
is needed and no 0.3/0.5 recipe values are silently inserted. Present before/after
values, active minimum-flow method, served zone/system, reheat coil, retained
schedules, flow sizing and warnings when clarification is needed.

Constant minimum fraction is editable only under an existing Constant method.
Do not silently switch FixedFlowRate/Scheduled terminals. Reheat airflow-limit
edits require water reheat with effective ReverseWithLimits action and a numeric
fraction with the per-area field at Autosize (EnergyPlus Autocalculate). The pinned
engine ignores numeric per-area limits, including 0, and also ignores the fraction
when per-area is numeric. Numeric per-area edits are unsupported. An explicit
`maximum_reheat_flow_per_area_m3_s_m2: "Autosize"` is the one scoped sizing-field
reset here; set it only if the user chose that reset, never as an inferred fix for
a fraction request. Preflight otherwise stays unready. Retained ignored limits
warn on unrelated edits; do not claim an effective cap from their saved values.
A terminal supply-air fraction is not its outdoor-air fraction. Retained turndown schedules,
OA/DCV, occupancy, system controls and EMS can change actual flow. Review known
ventilation shortfalls and unresolved sizing; honor `simulation_ready: false`.
Reheat temperature is a discharge limit, not a loop setpoint. The control fields
can affect later sizing even though unrequested sizing inputs stay unchanged.

```text
<verified-cli> execute_python_script <skill>/scripts/edit_terminal.py --plan <plan.json> --report <apply.json>
```

Apply only an unchanged ready plan. The script preserves the terminal, contained
coil, metadata, connections, incoming references and zone service, including
LifeCycleCost/EMS. Saved validation checks only requested fields changed and
verifies their EnergyPlus translation before publishing a new copy. Keep the
model and `<stem>/` companion together and honor `requires_companion_workflow`.
Record output/report paths and retained identities in workflow state; hand sizing
and performance assessment to the selected provider.

This skill does not replace terminals or coils, alter maximum air/water flows,
change fuels/plants, edit schedules, reassign zones or reset other sizing fields.
Other terminal
classes, batch edits and minimum-method changes require separate coverage. An
out-of-scope request is not permission to broaden this operation.

Unexpected execution failures route to `report-openstudio-failure` before recovery;
pass any `failure_receipt`. Expected readiness/input questions, including
`requires_preparation`, do not submit. Do not generate substitute scripts for
covered terminal edits.
