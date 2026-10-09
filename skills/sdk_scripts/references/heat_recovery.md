# Direct OA sensible/latent heat recovery

`manage_heat_recovery.py` supports two explicit modes, each using a fresh-plan,
source/resource-hash-bound copied-model transaction. Exact SDK compatibility is
read from the bundled contract. Reports are written by the script, never parsed
from an assumed last stdout line. Use the outdoor-air connector skill for attach
and the heat-recovery editor for edit.

Both modes select one served unsplit loop with a uniquely owned direct OA system.
Shared/dedicated OA, zone ERVs, desiccant/flat-plate object classes, existing-stream
rearrangement and exchanger replacement are outside this contract.

## Choices to review

| Choice | Meaning |
| --- | --- |
| Four `*_100` effectiveness values | Sensible/latent, heating/cooling at nominal flow; each in [0,1] |
| `part_load_effectiveness` (attach) | Four effectiveness values at 75% nominal flow, not normalized curve multipliers |
| `part_load_policy` (attach) | Explicit `Linear75To100ConstantOutside`: interpolate between .75 and 1; hold endpoint effectiveness outside that interval |
| `heat_exchanger_type` | Plate or Rotary; explicit performance assumption |
| `nominal_flow_m3_s` | Positive fixed nominal flow or Autosize; rerun sizing separately |
| `nominal_power_w` | Explicit nonnegative wheel/auxiliary and intended pressure-loss energy; no inferred fan changes or prototype formula |
| `availability_schedule` | Exact existing typed Constant/Ruleset [0,1] schedule; positive enables recovery |
| `economizer_lockout` | Whether economizer/high-humidity operation suspends recovery |
| `bypass_control` (attach) | OA-controller bypass strategy; explicit choice, independent of HX lockout |
| `supply_outlet_temperature_control` | False adds no setpoint manager. True on attach creates OutdoorAirPretreat, not a fixed hot-air setpoint |
| `pretreat_limits` (attach with control true) | Explicit temperature/humidity bounds; minimum strictly below maximum; mixed-air reference must have translated Temperature control |
| `frost_control` and three frost parameters | Explicit frost type, threshold, initial defrost fraction [0,1], nonnegative fraction increase per K; active frost needs all three |

Attachment requires every settings field, a unique name/prefix and empty OA and
relief paths (nodes only). It adds one HX, two boundary nodes, four normalized
TableLookup curves with their variable lists, one shared independent variable,
and optionally one pretreat manager. SDK wiring connects both air streams. Four
100% scalars multiply the normalized curves; zero 100% effectiveness requires
zero 75% effectiveness. No deprecated 75% SDK setters are used. Constant
extrapolation deliberately differs from the standards helper's linear
extrapolation: this bounded two-point contract avoids extrapolated effectiveness
outside [0,1]. All added objects/fields and the entire graph must match preview.

In `mode: edit`, select `heat_exchanger` by exact name/handle and supply only
requested `settings`. Attach-only fields are rejected. Existing curve multipliers
are preserved, so a change to a 100% scalar also changes part-load performance.
Names, curves, managers, bypass, node/connection identities, costs, EMS references
and all unrelated objects remain protected. Enabling outlet control does not add
a manager: an unverified temperature setpoint/reference marks simulation unready.

With outlet temperature control off, downstream cooling equipment or a
scheduled supply temperature below verified served-zone heating-setpoint minima
triggers an uncontrolled-recovery warning. Recovery can warm mixed air beyond
its need and increase downstream cooling (heat-then-cool). The schedule-range
comparison screens for possible risk; it does not establish coincident operation.
Review explicit pretreat control and economizer/bypass choices. This is advisory:
readiness and the chosen control settings are retained. Compare heating/cooling
coil energy and HX electricity, not recovered watts alone. Thermal coil loads
are not fuel/input energy or net HVAC savings.

The standards reference additionally applies template frost/efficiency/bypass
policy and estimates nominal power from sized/minimum OA. This bundle does not
silently adopt those policies. Actual relief flow can be less than OA because of
zone exhaust. Frost recirculation interrupts ventilation; no frost protection
requires cold-climate review. Keep fan pressure loss and nominal HX power from
double counting the same energy. Translation is checked before publication;
annual performance, air balance, pressure networks and ventilation compliance
remain separate assessments. Read `simulation_ready` and companion warnings.

Example structure for an in-place power edit (selectors must match inventory):

```json
{
  "output_model_path": "/absolute/edited.osm",
  "mode": "edit",
  "air_loop": {"name": "Selected Air Loop"},
  "heat_exchanger": {"name": "Selected Recovery"},
  "settings": {"nominal_power_w": 85}
}
```

For attachment, collect every choice in the table; the schema and preflight list
missing inputs. Numerical examples in tests are test data, not recommendations.
