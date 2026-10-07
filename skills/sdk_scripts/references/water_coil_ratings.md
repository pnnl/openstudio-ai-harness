# In-place water-coil rating contract

`edit_water_coil_ratings.py` inventories, preflights and applies copied outputs.
Use absolute paths and unused report/output names. Schema:
[water_coil_ratings.schema.json](water_coil_ratings.schema.json).

```json
{
  "output_model_path": "/absolute/path/edited.osm",
  "coil": {"name": "Main Heating Coil"},
  "ratings": {"rated_outlet_air_temperature_c": 33.0}
}
```

Only direct main-supply CoilHeatingWater/CoilCoolingWater on an unsplit air loop,
connected to a matching Heating/Cooling plant with supply equipment, an actual
pump and outlet setpoint manager, are covered. Names must resolve exactly once;
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

Effective heating temperatures must heat the air and cool the water with positive
approaches. Cooling fixed conditions must cool the air, use colder inlet water,
and not increase humidity. Plant design supply must support a fixed outlet-air
condition, and its design delta must be finite/positive. Different rated water
conditions generate an explicit plant mismatch warning; manufacturer ratings may
differ from operating conditions. Cross-checks involving Autosize require native
sizing. These checks do not establish annual performance or manufacturer validity.

Only explicitly requested raw coil fields may change. All handles, availability,
connections, sizing objects, controller settings and references are protected,
including EMS actuators and LifeCycleCost. Companion packing retains its existing
weather/external-path exceptions with resource hashes. If workflow weather fills
previously absent OSM climate metadata, the new fields must match its EPW. The saved model must pass
independent getter/fingerprint checks and EnergyPlus translation before publishing.
