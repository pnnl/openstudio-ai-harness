# Main-supply outlet water-coil attachment contract

`connect_water_coil.py` inventories, preflights and applies copied outputs.
Use absolute input/config/report paths and new output/report names. Schema:
[water_coil_connection.schema.json](water_coil_connection.schema.json).

Heating attachment example; optional `design` values below are nominal-rating
metadata, not UA design conditions. Omit that group when no rating metadata was
requested. Every explicit choice must reflect user intent:

```json
{
  "output_model_path": "/absolute/path/attached.osm",
  "operation": "attach",
  "kind": "Heating",
  "air_loop": {"name": "Office Air Loop"},
  "air_node": {"name": "Office Supply Outlet"},
  "plant_loop": {"name": "Office HW"},
  "coil_name": "Added Water Heating Coil",
  "availability_schedule": {"builtin": "AlwaysOnDiscrete"},
  "sizing": "Autosize",
  "design": {
    "rated_inlet_water_temperature_c": 82.2,
    "rated_outlet_water_temperature_c": 71.1,
    "rated_inlet_air_temperature_c": 16.6,
    "rated_outlet_air_temperature_c": 32.2
  },
  "controller": {
    "control_variable": "Temperature",
    "minimum_flow_m3_s": 0,
    "convergence_tolerance_k": 0.1
  }
}
```

Names/handles select exactly one object. The loop must have one unsplit main supply
path; `air_node` must be that loop's **supply outlet**, have an incoming connection, and already have
a Temperature setpoint manager. The new coil is inserted immediately upstream;
its air outlet remains that node. Other nodes insert downstream and are rejected
at preflight, including interior nodes with Temperature setpoint managers.
Inventory flags supported attachment nodes and exposes each loop's outlet.
Choose the system deliberately: this operation
preserves existing sizing, fan, terminals and other coils rather than making an
arbitrary system arrangement adequate.

The plant must match Heating/Cooling, have supply equipment, an actual pump and an
outlet setpoint manager, with finite supply temperature and positive design delta.
Existing demand branches remain intact, including when adding the first demand
component. No plant is created. Availability is an existing schedule with
Availability type limits, or explicit builtin `AlwaysOnDiscrete`/
`AlwaysOffDiscrete`. Coil names must be unique. Missing choices remain unready.

Heating attachment uses `UFactorTimesAreaAndDesignWaterFlowRate` with autosized
UA, maximum water flow and capacity. The four `rated_*_temperature_c` fields in
`design` are optional nominal-rating metadata; omitting `design` is valid for
Heating. Missing values retain the pinned SDK defaults, shown in the plan's
`after_values` and `rating_usage.defaulted_rating_fields`. They do **not** set the
UA coil's design point. Plant and air-system sizing govern autosizing; the plan
shows their existing temperatures in `rating_usage.sizing_context`. Do not ask the
user to supply unused rated temperatures as operating design conditions.
The full `assumption_review` and bounded `impact.rating_usage` explain this role.
EnergyPlus still validates input temperature relationships, so invalid metadata
is rejected; plant-versus-rated-temperature checks apply only to NominalCapacity.

Cooling attachment requires `design_inlet_water_temperature_c`,
`design_inlet_air_temperature_c`, `design_outlet_air_temperature_c`,
`design_inlet_air_humidity_ratio`, `design_outlet_air_humidity_ratio`,
`heat_exchanger_configuration` (`CrossFlow`/`CounterFlow`) and `type_of_analysis`
(`SimpleAnalysis`/`DetailedAnalysis`). Cooling design numbers may explicitly be
`"Autosize"`; water/air flow are autosized. Design relationships and plant warnings
follow the [edit contract](water_coil_edit.md). Flow/capacity fields in `design` reject rather than
silently overriding user choices. Manual sizing needs separate coverage. For system
design-day sizing, prefer explicit
Autosize for cooling air temperatures/humidity unless the user supplies fixed
design conditions. Fixed conditions override that part of autosizing and change
coil capacity; review their suitability for the selected outdoor-air strategy.

Controller choices are explicit: Temperature control, minimum flow 0, numeric
positive convergence tolerance or `"Autosize"`; maximum flow is autosized. Heating
uses Normal action, cooling Reverse; the actuator is Flow. Finalization runs after
both connections, setting sensor to air outlet and actuator to water inlet. This
is dry-bulb temperature control, without humidity-control/setpoint creation.

Existing coil ratings, name, availability, Autosize resets and controller settings
use the in-place editor. `operation: replace` is rejected by both public schemas.
The clone/reconnect primitive is unexported pending a class/location/plant-changing
contract with explicit reference migration and controller lifecycle decisions.

Attachment previews native topology in an isolated handle-preserving model copy.
Only graph-link changes and connector extensions may differ; expected additions
and removals are recorded. Saved checks independently verify exact supply order,
plant ownership/supply order, existing demand components, protected raw fields,
original identities, object deltas, rating getters and controller nodes/settings.
No OA-stream, unitary, terminal, coil-class conversion, plant migration
or plant-supply attachment is covered. Previously absent weather metadata may be populated from the companion EPW;
its fields are checked independently against that hash-bound resource. Existing
climate metadata stays protected. Saved validation and EnergyPlus translation
are required before publication; sizing/simulation is a separate workflow.
