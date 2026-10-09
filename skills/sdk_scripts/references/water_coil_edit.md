# In-place water-coil settings contract

`edit_water_coil.py` inventories, preflights and applies copied outputs.
Use absolute paths and unused report/output names. Schema:
[water_coil_edit.schema.json](water_coil_edit.schema.json).

```json
{
  "output_model_path": "/absolute/path/edited.osm",
  "coil": {"name": "Main Heating Coil"},
  "ratings": {"rated_outlet_air_temperature_c": 33.0}
}
```

Only direct main-supply CoilHeatingWater/CoilCoolingWater on an unsplit air loop,
connected to a matching Heating/Cooling plant, are covered. Missing supply
equipment, pump or outlet setpoint manager warns rather than blocking an edit;
the unchanged incomplete plant is marked `simulation_ready: false`. Matching plant
type and finite design supply/positive delta remain required. Saved validation and
translation errors still block publication. Names must resolve exactly once;
otherwise use a handle. No-op edits remain unready. Missing choices remain unready;
unknown fields and invalid types reject. A temperature is Celsius, a flow is m³/s,
a capacity is W, UA is W/K, and humidity ratio is kg water/kg dry air.

Heating fields:

- `rated_inlet_water_temperature_c`, `rated_outlet_water_temperature_c`,
  `rated_inlet_air_temperature_c`, `rated_outlet_air_temperature_c`: numbers.
- `rated_capacity_w`, `ua_w_per_k`, `maximum_water_flow_m3_s`: positive number or
  `"Autosize"`. Effective `performance_input_method` must be `NominalCapacity` for
  capacity edits, or `UFactorTimesAreaAndDesignWaterFlowRate` for UA/flow edits.
  Explicitly change the method when needed; the script never switches it silently.
- `performance_input_method`: either method above.

Cooling fields:

- `design_water_flow_m3_s`, `design_air_flow_m3_s`: positive number or `"Autosize"`.
- `design_inlet_water_temperature_c`, `design_inlet_air_temperature_c`,
  `design_outlet_air_temperature_c`, `design_inlet_air_humidity_ratio`,
  `design_outlet_air_humidity_ratio`: number or `"Autosize"`. Humidity ratios range
  from 0 to 0.1. Autosized conditions remain sizing decisions rather than fabricated
  numeric values.
- `heat_exchanger_configuration`: `CrossFlow` or `CounterFlow`.
- `type_of_analysis`: `SimpleAnalysis` or `DetailedAnalysis`.

Heating rating temperatures must satisfy EnergyPlus input relationships under
both methods. Under the UA method, they are informational and do not set the
operating design point or autosizing conditions. Plant-versus-rated-temperature
checks and manufacturer mismatch warnings apply to NominalCapacity only; its
rating point may differ from the operating point. NominalCapacity also requires
positive water/air approaches. Cooling fixed conditions must cool the air, use
colder inlet water and not increase humidity; its plant supply must support a
fixed outlet-air condition. Design delta must be finite/positive. Cross-checks
involving Autosize require native sizing. These checks do not establish annual
performance or manufacturer validity. The plan's `rating_usage`, review item and
bounded impact explain the heating method and existing sizing context.

Additional optional edit fields:

- `coil_name` and `controller_name`: explicit nonempty, unique names. Neither
  renames the other automatically.
- `availability_schedule`: exact existing name/handle with Availability type limits,
  or builtin `AlwaysOnDiscrete`/`AlwaysOffDiscrete`. A missing builtin is created
  only when requested; its new object types are recorded in the plan.
- `sizing: "Autosize"`: reset heating rated capacity, UA and maximum water flow,
  or cooling design air/water flow, and controller maximum actuated flow. Retain
  design temperatures/humidity and the heating method. Fixed sizing fields or
  fixed controller maximum flow conflict with this reset and make the plan unready.
- `controller`: a partial patch. `convergence_tolerance_k` is positive or
  `"Autosize"`; `maximum_flow_m3_s` is positive or `"Autosize"`;
  `minimum_flow_m3_s` is nonnegative and cannot exceed a fixed maximum.
  `control_variable` only accepts `Temperature`, `actuator_variable` only `Flow`,
  and `action` must be `Normal` for Heating or `Reverse` for Cooling. No sensor/
  actuator node changes are exposed. Unspecified controller fields remain unchanged.

Example of a settings edit, with choices supplied by the user:

```json
{
  "output_model_path": "/absolute/path/reconfigured.osm",
  "coil": {"name": "Main Heating Coil"},
  "coil_name": "Reviewed Heating Coil",
  "availability_schedule": {"name": "HVAC Availability"},
  "sizing": "Autosize",
  "controller": {"convergence_tolerance_k": 0.1}
}
```

At least one requested setting must differ; `ratings` is optional for name,
availability, sizing or controller edits. The approved before/after settings and
all effective ratings appear in the plan. Apply runs setters on existing objects;
no clone, disconnect, remove or reconnect is used. All original coil/controller/
connection/metadata/reference handles are protected, including EMS and LifeCycleCost.
Only the raw fields corresponding to requested changes are exempted from the
protected snapshot, and independent saved getters check those fields. Companion
packing retains its weather/external-path exceptions with resource hashes. If
workflow weather fills absent OSM climate metadata, its fields must match the EPW.
Saved settings, identities and EnergyPlus translation must pass before publication.

Adding a new coil uses the attachment skill; `operation: replace` is not accepted
by either public schema. Class/location/plant changes need a future contract.
