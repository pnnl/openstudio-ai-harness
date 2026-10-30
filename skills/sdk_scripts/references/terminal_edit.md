# In-place VAV terminal controls

Use `edit_terminal.py` for one existing, connected
`AirTerminalSingleDuctVAVReheat` or `AirTerminalSingleDuctVAVNoReheat` on the
selected zone and air loop. The air system may be VAV or the prototype CAV recipe;
the latter also uses VAV terminals. Selectors are exact names or handles, scoped
air loop → zone → terminal. Unconnected and other terminal classes are unsupported.

Input is validated against [terminal_edit.schema.json](terminal_edit.schema.json).
All values are SI; there are no edit defaults or implicit Autosize resets.

```json
{
  "output_model_path": "/work/terminal-edited.osm",
  "air_loop": {"name": "Office VAV"},
  "zone": {"name": "Office East"},
  "terminal": {"name": "Office East VAV Terminal"},
  "settings": {"minimum_airflow_fraction": 0.2}
}
```

The example fraction is illustrative, not a ventilation recommendation. Obtain
the user's target/settings; discuss preflight's context and unresolved choices.
Missing selectors/settings return an unready plan; invalid types/unknown fields
are rejected. A no-op is unready.

| Setting | Scope and effect |
| --- | --- |
| `minimum_airflow_fraction` | Number 0–1; existing Constant minimum method only. FixedFlowRate/Scheduled methods are preserved and cannot be switched here. Retained turndown schedules scale the floor. |
| `maximum_reheat_temperature_c` | Number 0–100 °C; reheat terminal with a water, electric or gas heating coil. A discharge limit, not a supply setpoint or coil rating. |
| `damper_heating_action` | Normal, Reverse or ReverseWithLimits; changing to a reverse action requires water reheat in this initial contract. |
| `maximum_reheat_flow_fraction` | Number 0–1; water reheat with effective ReverseWithLimits and per-area Autosize/Autocalculate only. |
| `maximum_reheat_flow_per_area_m3_s_m2` | Only `"Autosize"`: an explicit user-chosen reset to SDK Autosize / EnergyPlus Autocalculate, with a numeric effective fraction. Numeric per-area edits are unsupported at the pin. Zero does not disable just the per-area contribution. |

Only supplied settings change. An explicitly supplied numeric fraction replaces
that fraction field's existing Autosize value if present. The per-area field alone
accepts `"Autosize"`; do not infer or add that reset to a fraction request. A
fraction edit retaining numeric per-area (including 0) is unready. Existing maximum air flow, water-flow limits, coil
ratings/plant/controller state, schedules, sizing objects and all other fields
remain protected. The requested controls can still affect results of a new sizing
run; retaining sizing inputs does not promise identical sized capacities.

The plan records full private context under `plan.context`; stdout/impact stays
compact. Context includes availability/fraction/turndown schedules, zone design
OA/occupancy evidence, direct OA/DCV state, relevant terminal/coil EMS actuators,
current sizing state and reheat class. Nominal zone OA evidence excludes schedule
variation, distribution effectiveness, exhaust and ventilation compliance. Its
zone multiplier is applied once to OA and floor area; terminal flow inputs are
already on that multiplied basis and are not multiplied again. A fixed
maximum supply flow below nominal OA even at 100% OA warns and sets
`simulation_ready: false` pending review of sizing/alternate ventilation sources;
an unknown autosized flow warns to size and verify. A minimum floor below OA
demand warns but does not itself mark simulation unready: controls may raise flow.
Schedules, EMS, OA control and system flow constraints may mask a requested floor.

Under ReverseWithLimits, the pinned EnergyPlus 25.2 sizing routine behaves as
follows. Saving/translating a number does not establish its runtime effect:

| Per-area input | Fraction input | Sizing/runtime basis |
| --- | --- | --- |
| Autocalculate | Autocalculate | Design-calculated flow; requires sizing |
| Autocalculate | Numeric | Fraction-only; minimum-flow bounds can raise the cap |
| Numeric, including 0 | Autocalculate | Design-calculated flow; per-area input ignored |
| Numeric, including 0 | Numeric | Design-calculated flow; both user limits ignored |

The editor permits flow-limit changes only to the fraction-only form. Retained
ignored limits warn when other fields are edited; no runtime cap is calculated
from them. Impact records before/after mode and, when possible, a nominal fraction-
only cap before retained schedule/OA overrides. Requested per-area flow is reported
only as input evidence using multiplied floor area, never as an effective limit.
Under Normal/Reverse those fields remain inactive; editing an inactive limit is
rejected. This behavior is confirmed by native runs and the
[EnergyPlus 25.2 SingleDuct control/sizing code](https://github.com/NREL/EnergyPlus/blob/v25.2.0/src/EnergyPlus/SingleDuct.cc).
The native EIO's Design Size fraction stays design-calculated even in the
effective fraction-only case; compare its User-Specified row and heating-hour
flow too. The prototype CAV builder's existing per-area 0/fraction 0.5 combination
falls in the ignored row. This editor flags it and requires a user-chosen reset;
this review fix does not silently change existing models or the creation recipe.
The standards' 0.3 minimum / water Dual Maximum 0.5 remain recipe decisions, not
defaults applied by this editor.

The shared transaction enforces exact source/resource hashes and reviewed/fresh
plan equality, stable-load preparation, companion packaging, staged save/reload,
protected raw-field snapshots and translation before publishing a new OSM. The
terminal has a narrow explicit field whitelist; every other model object,
reference and connection stays protected. An independent translated-field check
confirms the requested controls reach EnergyPlus. Reports retain original/output
hashes and local failures use the existing sanitized-reporting workflow.

This initial skill has no terminal/coil replacement, coil-rating edits, topology
changes, batch mode, zone reassignment or method/schedule edits. Native design-day
evidence verifies exercised airflow/discharge control, not annual energy or
ventilation adequacy. Keep the complete plugin for installation/relocation.
