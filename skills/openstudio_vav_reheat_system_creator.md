---
name: openstudio_vav_reheat_system_creator
description: Parent checklist skill for phased OpenStudio Python SDK workflows that add a multi-zone VAV reheat air system.
metadata:
  version: 0.4.0
  output_format: markdown_with_json_summary
---

## Scope

Use this parent skill when the user asks to add, create, prototype, or draft a
multi-zone VAV reheat air system in an OpenStudio model.

This skill does not hold object-level implementation detail. It owns workflow
state, clarification gates, phase order, child-skill routing, and final handoff.
Use host Python execution only through the bounded script workflow in
`openstudio_sdk_model_editor`. Use MCP `model_*`, `sim_*`, and `results_*` for
validation, simulation, and results after the edited model is saved.

## Bundled Preflight (OpenStudio 3.11.0)

Run the scripts beside this `SKILL.md` directly through host tools. For Claude
Code use `${CLAUDE_SKILL_DIR}`; for Codex resolve the actual skill directory.
No OpenStudio AI runtime or measure execution is involved in preflight.

1. Run `scripts/doctor.py` with host Python 3.10+. Continue only when its JSON
   reports `ok: true`. Use its verified absolute OpenStudio executable below.
2. Run `<verified-executable> execute_python_script <skill-dir>/scripts/vav_preflight.py
   --input <absolute-input.osm>` to list zones, existing HVAC, plant loops,
   schedules, and missing inputs. It never chooses zones or saves a model.
3. Read `scripts/references/vav_input.schema.json` to prepare a JSON configuration.
   Run the same command with `--config <absolute-config.json>` to resolve a plan.
   Partial inputs are supported. Missing fields or conflicts block readiness.
4. Review `plan.parameters`, `resolved_objects`, assumptions, conversions,
   expected counts, and the input hash. `ready: true` means preflight is complete;
   it does not mean model creation or simulation has been validated.

Selectors use exactly one `name` or `handle`. Duplicate names require a handle.
Water coils require a compatible existing plant loop. DX cooling requires
`dx_approved: true`. Fan pressure inputs must include units; selected zones need
spaces and a thermostat and must not already have HVAC. Replacement is outside
this operation. The output must be a new absolute `.osm` path.

`defaults_profile: prototype_vav_v1` explicitly requests generic prototype
defaults; use it only when the user's request authorizes those assumptions.
Every supplied default is listed. This profile does not represent a specific
ASHRAE template or certify code compliance. No profile is selected implicitly.

An inventory-only call exits 0 on successful inspection even when `ready` is
false. A configured call exits 2 if validation, required inputs, or model
conflicts block readiness. Read the final JSON line after any SDK log output.
The returned state patch records preflight readiness and input hash only.

Preflight needs no SDK wiki packs or freshly drafted scripts. Creation remains
in the later development phase; do not treat preflight as permission to create
a system or silently fall back to generated edits.

## Legacy Creation Workflow (Pending Migration)

Before any VAV script drafting, load:

- `openstudio_sdk_model_editor`
- `openstudio_workflow_state`
- `sdk_index`

Load exactly one child skill for the active edit phase. Do not load all child
skills or all SDK packs at once.

Load SDK context packs only when needed:

- `sdk_core_patterns`: before drafting an executable SDK script.
- `sdk_hvac`: air loop, sizing, fan, coils, outdoor air, terminals, or HVAC
  validation phases.
- `sdk_schedules`: schedule resolver phase.
- `sdk_spaces_zones_loads`: preflight or zone/space-scoped validation.

## Parent Rules

- Initialize and maintain the task-global state table from
  `openstudio_workflow_state`.
- Treat the state table as the source of truth for paths, target zones,
  schedules, coil choices, plant loops, fan inputs, assumptions, warnings,
  created objects, and checklist status.
- Pass only the relevant state subset to each phase.
- Require each child phase to return a `state_patch`; apply it before moving on.
- Do not let a child phase re-ask for values already present in state.
- If a user changes a global value, update state first and re-evaluate
  downstream pending steps.
- Keep each edit script focused and visible to the user before execution.
- Never overwrite the input `.osm` unless the user explicitly approves.

## Required Global Inputs

Known values or approved defaults are required before model-editing phases:

- input model path and output model path;
- system name;
- target thermal zones;
- reheat type: `Water`, `NaturalGas`, `Electricity`, or `None`;
- central heating type: hot-water loop, gas, electric, or none;
- central cooling type: chilled-water loop or explicit DX fallback;
- HVAC operation schedule or approved Always On Discrete default;
- optional outdoor-air damper schedule or approved unset value;
- fan total efficiency, motor efficiency, pressure rise, and pressure units;
- minimum system airflow ratio;
- sizing option, usually `Coincident`;
- economizer control type or approved default;
- optional return plenum.

For water coils, require an existing plant-loop name. Do not create hot-water or
chilled-water plant loops in this parent workflow unless the user starts a
separate loop-creation task.

Record every default in `assumptions` using:

```text
Object:Name.parameter: assumed to be x
```

## Phase Map

Run these phases in order unless the current state proves a phase is already
complete. Each phase must return a `state_patch`.

| Step | Phase | Child Skill |
| --- | --- | --- |
| 0 | Initialize state | `openstudio_workflow_state` |
| 1 | Preflight inspection | bundled `scripts/vav_preflight.py` |
| 2 | Clarification gate | parent state update |
| 3 | Air loop | `openstudio_hvac_air_loop_creator` |
| 4 | Schedules and SAT setpoint manager | `openstudio_hvac_schedule_resolver` |
| 5 | Sizing system | `openstudio_hvac_sizing_system_configurator` |
| 6 | Supply fan | `openstudio_hvac_supply_fan_creator` |
| 7 | Central heating coil | `openstudio_hvac_central_heating_coil_creator` |
| 8 | Central cooling coil | `openstudio_hvac_central_cooling_coil_creator` |
| 9 | Outdoor air and air-loop controls | `openstudio_hvac_outdoor_air_system_creator` |
| 10 | Zone terminals and zone sizing | `openstudio_hvac_vav_terminal_creator` |
| 11 | Validation | `openstudio_hvac_system_validator` |
| 12 | Simulation/results handoff | MCP `model_*`, `sim_*`, `results_*` |

## Preflight

Use the bundled preflight above. It reads the input model and returns:

- thermal zones, spaces, plenum status, and thermostat presence (not an inferred
  conditioned-zone selection);
- existing air loops and served zones;
- hot-water and chilled-water plant loops;
- candidate HVAC operation and outdoor-air schedules;
- relevant thermostats, sizing objects, and availability managers when useful;
- whether an air loop with the requested system name already exists;
- missing required state fields.

## Clarification Gate

Ask one focused clarification question when state is missing or risky. Combine
missing fields from the state table and child skills whenever practical.

Clarify before drafting edit scripts when:

- target zones are ambiguous;
- water coils are requested without plant-loop names;
- fan pressure rise lacks units;
- DX cooling fallback lacks explicit approval;
- schedule names/defaults are unresolved;
- the requested air-loop name already exists;
- output path would overwrite the input model.

## Standards-Derived Defaults

The workflow follows the OpenStudio Standards VAV reheat sequence from
`model_add_vav_reheat`. Keep detailed implementation in child skills, but keep
these global defaults in state:

- design temperatures: preheat 45 F, precool 55 F, central heating 55 F,
  central cooling 55 F, zone heating 104 F, zone cooling 55 F;
- sizing load type `Sensible`;
- system outdoor-air method `ZoneSum`;
- sizing option `Coincident` unless user overrides;
- minimum system airflow ratio `0.3` unless user overrides;
- fan end-use subcategory `VAV System Fans`;
- OA minimum limit type `FixedMinimum`;
- night-cycle control `CycleOnAny`;
- night-cycle runtime `1800` seconds;
- terminal minimum airflow input method `Constant`;
- damper heating action `Normal`;
- zone heating maximum airflow fraction `1.0`.

Convert all numeric SDK setter inputs to SI before execution and record
conversions in state.

## Phase Result Contract

Every phase script must print the standard `openstudio_sdk_model_editor` JSON
result plus a narrow `state_patch`:

```json
{
  "ok": true,
  "mode": "edit_model",
  "input_model_path": "...",
  "output_model_path": "...",
  "changes": [],
  "warnings": [],
  "counts": {},
  "summary": "...",
  "state_patch": {
    "completed_steps": [],
    "pending_steps_remove": [],
    "created_objects": {},
    "assumptions": [],
    "warnings": []
  }
}
```

## Final Handoff

After validation, summarize:

- final model path;
- completed and pending steps;
- created object names;
- assumptions and warnings;
- validation results.

Then recommend MCP handoff: `model_load`, `model_validate`, `sim_run`,
`results_query` with `sizing_summary`, and review of autosized flow/capacity
outputs before annual simulation.
