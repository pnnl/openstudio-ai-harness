---
name: openstudio-pump-replacer
description: Replace one existing plant-loop single constant-speed pump with a variable-speed pump, or the reverse, with explicit flow/power policies and variable-speed power curve. Same-class performance changes use the in-place pump editor.
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
use its verified exact-release OpenStudio executable. Resolve resources beside
this SKILL.md (Claude: `${CLAUDE_SKILL_DIR}`); the entrypoint guards the SDK too.

Use this independent skill to change a directly connected single
`PumpConstantSpeed` ↔ `PumpVariableSpeed` on the selected plant supply or demand
side. Read [the replacement contract](scripts/references/pump_replacement.md)
when preparing the request. Inventory and preflight:

```text
<verified-cli> execute_python_script <skill>/scripts/replace_pump.py --input <input.osm> --report <inventory.json>
<verified-cli> execute_python_script <skill>/scripts/replace_pump.py --input <input.osm> --config <config.json> --report <plan.json>
```

Obtain the selected pump, target class, flow/power Preserve or Autosize choices,
plant Preserve and reference Reject policy from the user. A variable-speed target
also requires four explicit power coefficients and a fixed minimum flow. Do not
infer a standards profile, pressure reset or plant redesign from a class change.
A request specifying these choices authorizes the corresponding replacement;
preserve that authorization across turns. Missing choices stay unready for review.

Present before/after settings, selected plant side, retained nodes and controls,
changed pump/connection identities, retained reporting references and warnings.
Constant-speed power is rated power whenever running in this simple model;
variable-speed power follows the chosen curve. Existing demand, coil/valve and
flow-schedule controls remain. Neither choice guarantees the intended plant flow
or energy reduction. Fixed-power/autosized-flow feasibility requires sizing.
For a constant-speed supply target, show the explicit OSM demand-bypass status
and verified translated uncontrolled paths. If the OSM has no bypass, explain the
warning even when OpenStudio generates one during translation; downstream measures
may remove it. Presence alone does not establish flow adequacy. Preserve leaves
the OSM plumbing intact; adding a bypass is a separate plant change.

```text
<verified-cli> execute_python_script <skill>/scripts/replace_pump.py --plan <plan.json> --report <apply.json>
```

Apply only an unchanged ready plan. The script checks source/resources, rewires
only the selected pump between its retained nodes, reloads and independently
checks plant graphs, settings, translated controls, metadata and protected objects,
then translates to EnergyPlus before publishing a new model copy. Supported
pump-name outputs/custom energy meters retain identity. Direct object references,
EMS actuators/sensors and costs needing migration block under Reject.

Same-class head/efficiency/control changes use `openstudio-pump-performance-editor`
in place; retain the pump handle. For combined class/performance requests, compose
the two copied-output operations with their reviewed plans. Headered/condensate
pumps, pressure/VFD/impeller/RPM controls and plant pressure simulation need separate
coverage. Report covered failures without an ad hoc substitute or broader removal.

Return output/report paths, old→new pump mapping, node preservation and warnings.
Keep the OSM and `<stem>/` companions together; honor `requires_companion_workflow`.
Hand sizing/simulation to the selected provider separately.
