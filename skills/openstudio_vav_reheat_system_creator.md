---
name: openstudio_vav_reheat_system_creator
description: Create a multi-zone VAV system in an OSM using bundled, version-pinned scripts and saved-model topology validation.
metadata:
  version: 0.4.0
  output_format: markdown_with_json_summary
---

## Direct script workflow

First honor provider selection: when NLR OpenStudio MCP is configured and
compatible, use `delegated-nlr-modeling` as the preferred provider. This local
bundle applies when NLR is absent/unavailable/incompatible or its documented
fallback records that it cannot cover the request. Preserve the provider
transition and host-visible model path before local SDK execution.

Run this skill's scripts through host tools, independently of OpenStudio AI's
runtime or measure registry. Claude Code resolves `${CLAUDE_SKILL_DIR}`; Codex
uses this `SKILL.md`'s actual directory. Run implementation files without reading
them into context. Do not load SDK wiki packs for this supported workflow.
Legacy object-level VAV skills have been removed.

1. Run host Python 3.10+ on `scripts/doctor.py`. Require exit 0 and `ok: true`;
   use its absolute `openstudio_executable` for every SDK command. The package
   requires the exact package release in `scripts/compatibility.json`. Explicit executable paths are authoritative;
   mismatches block. Request the exact installation/path reported by doctor;
   do not install automatically or try another SDK/project virtualenv.
2. Set `defaults_profile: prototype_vav_v1` only when the human user explicitly
   chose the generic prototype defaults. Set `dx_approved: true` only when the
   human explicitly chose DX cooling. A broad request to add VAV, an agent's own
   suggestion, or missing input is not approval. Prior explicit human selections
   persist across turns; do not ask again for the same choice. Keep these fields
   absent until that choice is established.
   Read [the input contract](scripts/references/vav_input.schema.json). Prepare
   configuration JSON from the user's selections. If names/handles are unknown,
   inspect with `vav_preflight.py --input <absolute-input.osm>` first; otherwise
   go directly to configured preflight. Partial configurations return missing
   inputs and conflicts without saving a model.
3. Run configured preflight and persist its full report using the commands
   below. Review the summary's parameters, resolved references, units, and
   warnings. The full plan contains the assumption ledger. Clarify only missing
   or conflicting choices; approval already provided by the user persists.
   Require `ok: true` and `ready: true` before creation.
4. When the user's request authorizes those selections/defaults, run apply on
   the saved version-2 plan. Require `ok: true` and `validation.ok: true` in the
   summary. Apply rechecks the SDK, source hash and resolved plan, creates the
   system, reloads a staged OSM, independently checks topology/settings, and
   exclusively publishes to the selected new output path.
5. Return the output path, completed creation/topology checks, key assumptions
   and warnings, and report paths. Sizing/simulation remain pending. When those
   are requested, hand the saved model to the simulation/results skills.

Entrypoints persist full reports directly with `--report` and print compact
summaries. Use the report file and exit code as authoritative; SDK logging before
or after stdout cannot invalidate the saved plan. Normal runs need two commands:

```text
<verified-executable> execute_python_script <skill-dir>/scripts/vav_preflight.py --input <input.osm> --config <config.json> --report <plan.json>
<verified-executable> execute_python_script <skill-dir>/scripts/vav_apply.py --plan <plan.json> --report <apply-report.json>
```

Use absolute paths and new report paths; quote shell paths containing spaces.
Check each exit code separately. Require the persisted plan's `ready: true` and
apply's `validation.ok: true` plus `translation.ok: true`. Full inventories and
assumption ledgers stay on disk. Unready summaries show at most eight candidates
per category, total counts, and a truncation marker. Use `--candidate-filter`
with a name fragment or read the full report only for the relevant selection.
`report.py` remains a troubleshooting utility for old logs, not the normal flow.

## Supported inputs and assumptions

Selectors use exactly one name or handle; duplicate names require handles.
Selected zones need spaces and a thermostat, must not be plenums, and must have
no existing HVAC. Specify a new absolute `.osm` output; replacement and partially
constructed systems are outside this operation.

Water coils require explicitly selected compatible existing plants with supply
equipment, an outlet setpoint manager, and suitable design supply/return
temperatures. These checks do not establish equipment capacity or control
performance. Plants are not created. Central heating supports Water, NaturalGas, Electricity, or None;
reheat supports the same choices; cooling supports Water or explicitly approved
DXTwoSpeed (`dx_approved: true`). Fan pressure needs a value and Pa/inH2O units.
The contract covers existing operation/OA schedules, optional return plenum,
economizer, airflow fractions, sizing option, and design temperatures.

`defaults_profile: prototype_vav_v1` selects generic prototype assumptions only
when the human explicitly selected those generic defaults. The plan lists every supplied default.
This follows the inner standards VAV builder; the outer prototype dispatcher
always selects hydronic VAV and can create plants. Independent coil/plant-role
selection and central heating None are explicit extensions. Template controls,
compliance processing, and ventilation adequacy are not established by this
profile. New SDK UUIDs differ across runs; settings and topology are deterministic.

## Failures and continuity

On failure, read the persisted error, resolve that cause, and rerun preflight if
inputs or configuration changed. Do not edit bundled code, generate an alternative
VAV script, or switch SDK/runtime to work around the failure. Unsupported scope
needs a separately scoped development/repair task. If report publication fails after a model was created, retain the returned output
path and diagnose the report destination; never repeat creation merely to obtain
a report. A new plan/report must use new paths.

Existing output and concurrent destination writers are preserved. Repeating apply
refuses the existing output and companion folder. Apply carries referenced weather,
external files, referenced measures and supported file arguments into the Application-style
`<output-stem>/` folder, hashes dependencies, rewrites portable paths and emits
`workflow.osw`. Missing required external files/measures and ambiguous workflows block.
Missing weather warns and leaves simulation pending.
EnergyPlus translation is checked before publishing. Hard-link publication is
atomic when supported; otherwise exclusive copy still refuses an existing output,
but concurrent readers can see a partial file until the success report. Cloud
sync completion is not guaranteed by local publication. Failed writes clean up
owned partial files; failed creation can leave parent directories.

The saved configuration, plan, logs and apply report provide local continuity.
If an active long-running task already uses `openstudio-workflow-state`, normalize
and record the reports' `state_patch`, output path, assumptions and validation.
Workflow-state MCP calls are separate from script execution; their availability
is not a prerequisite for this local operation. If NLR currently owns the model,
respect its recorded provider transition and host-visible path before SDK work.

Missing weather produces a warning and `simulation_ready=false`; it does not block
VAV editing. Missing referenced external data or measures blocks editing. Copying
uses OpenStudio workflow lookup, omits repository metadata, blocks secret-like
files and limits referenced resources to 256 MiB. Move the OSM and its companion
folder together; resolve resources through the companion workflow.
