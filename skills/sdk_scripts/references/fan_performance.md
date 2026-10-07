# Supply-fan performance-edit contract

`edit_supply_fan_performance.py` supports inventory, partial preflight and reviewed
apply. Use absolute input/config/report paths, a new absolute `.osm` output and
unused report filenames. Schema: [fan_performance.schema.json](fan_performance.schema.json).

```json
{
  "output_model_path": "/absolute/path/edited.osm",
  "air_loop": {"name": "Office Air Loop"},
  "fan": {
    "total_efficiency": 0.7,
    "pressure_rise": 750,
    "pressure_units": "Pa"
  }
}
```

- `air_loop`: exactly one exact name or handle; ambiguous names require a handle.
- `fan`: at least one explicit performance change. `total_efficiency` and
  `motor_efficiency` lie in (0,1]; effective total must not exceed effective motor
  efficiency, including retained values. Pressure is finite and nonnegative;
  `pressure_rise` and `pressure_units` (`Pa` or `inH2O`) must appear together.
- Unspecified values retain source settings. No profile or approval boolean fills
  missing intent. A no-op edit remains unready.
- Missing target/settings yield `ready: false` with `missing_inputs`; unsupported
  topology or incompatible effective values yield errors and cannot apply.
  Unknown fields, nonfinite values and invalid schema types reject.

Select an AirLoopHVAC with a single supply outlet, no supply splitter and exactly
one direct FanVariableVolume or FanConstantVolume. Fans inside unitary/packaged
equipment, return/relief/exhaust or zone fans, other classes, multiple direct fans
and class conversions are excluded. Existing LifeCycleCost, EMS actuator and other
incoming references are permitted and checked unchanged after reload.

The saved plan records loop/fan/node handles, requested SI values, effective
before/after values, supply order, fan counts and protected fingerprints. The
compact summary shows target, zone count and values; full fingerprints stay in the
report. Apply re-preflights and rejects stale input, changed resources, modified
plans and existing outputs. Performance edits call only the requested setters on
the existing object; they never clone, remove or reconnect the fan.

Every fan, connection, metadata and reference handle stays unchanged. Saved checks
preserve availability, maximum-flow/autosize, minimum-flow method, fan curve,
motor-in-air fraction, end-use category and name. Other objects are independently
fingerprinted, including node links, component order, setpoint managers, air/plant/
zone sizing, plant equipment, terminals, thermostats, schedules and loads.
Companion packaging may rewrite external filenames and weather path/checksum or
create an empty weather singleton; contents are hash-verified and climate metadata
stays protected. Missing weather warns without preventing the edit.

Both the system planner and this editor use `common/fan_equipment.py:pressure_pa`.
That module requires complete performance values for VAV/CAV fan construction;
only the editor explicitly opts into partial setters. The retained clone/reconnect
primitive is unexported pending a real class-changing replacement contract covering
curves, terminals, sizing and reference migration.

The output must pass saved-model validation and EnergyPlus translation before
publication. Re-run sizing/simulation through the selected provider to assess fan
selection, ventilation, annual savings and capacity after the change. An EMS
program may override the changed values at runtime; preserving its actuator does
not establish runtime performance.
