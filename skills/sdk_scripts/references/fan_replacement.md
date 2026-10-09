# Supply-fan class replacement contract

Use `replace_supply_fan.py` for `FanConstantVolume` ↔ `FanVariableVolume` on an
unsplit loop with exactly one direct supported supply fan. Select an air loop by
unique name or handle. The schema is [fan_replacement.schema.json](fan_replacement.schema.json).

Example for a variable-volume target; numbers are explicit user choices, not
defaults or a standards-compliance profile:

```json
{
  "output_model_path": "/absolute/outputs/variable_fan.osm",
  "air_loop": {"name": "Existing Air Loop"},
  "target_class": "VariableVolume",
  "end_use_subcategory": "Reviewed Supply Fans",
  "fan": {
    "total_efficiency": 0.7,
    "motor_efficiency": 0.9,
    "pressure_rise": 700.0,
    "pressure_units": "Pa"
  },
  "variable_volume": {
    "minimum_power_flow_fraction": 0.25,
    "power_coefficients": [0.0, 0.0, 0.0, 1.0, 0.0]
  },
  "sizing": "Autosize",
  "terminal_policy": "Preserve",
  "system_sizing_policy": "Preserve",
  "reference_policy": "Reject"
}
```

For `ConstantVolume`, omit `variable_volume`. Same-class requests are unready
and route to the in-place performance editor. Missing choices produce an unready
plan, with no inferred efficiencies or curve. Total efficiency must be positive
and no higher than motor efficiency. Pressure supports `Pa` or `inH2O`.
`end_use_subcategory` is an optional, explicitly selected nonempty reporting
label. Omit it to retain the existing label. Retained recognizable CAV/VAV or
constant/variable-volume labels naming the old fan type produce a warning.
Changing the label changes subcategory meter names; review those requests
separately. Fan-name keyed reporting and custom meter names are preserved.

The five coefficients describe electrical power fraction
`c1 + c2*x + c3*x² + c4*x³ + c5*x⁴`. This initial contract uses minimum-power
input method `Fraction`, requires a fraction in [0,1], and explicitly resets the
unused fixed minimum-power air flow to zero. This fraction is a power-model floor;
it does not set terminal or ventilation minimum airflow. Coefficients must be
finite, at most 1e6 in magnitude, with power in [0,1.01] throughout x∈[0,1] and
full-flow power within 0.01 of unity. Extrema, including interior extrema, are
checked; other curve ranges/methods need separate coverage. Review the curve's
applicability rather than treating the illustrative cubic as a recommended choice.

Fan maximum flow is reset to Autosize. Existing system sizing, terminal identities/
minimum-flow controls, zone assignments, OA controls, coils and plants remain
unchanged. Impact gives affected-zone/terminal counts and terminal classes;
complete terminal references are in `plan.preserved_terminals`. A constant-volume
target changes fan power behavior while retaining terminal airflow control. Review
system/terminal sizing and run sizing/simulation separately for either direction.
Impact explicitly states that fan replacement does not enforce constant airflow:
existing terminals can continue varying flow, with constant-volume fan power
proportional to requested flow at fixed pressure and efficiency.

The replacement keeps both air nodes and the fan's position, name, availability,
motor heat fraction and metadata identity; the end-use label follows the optional
choice above. Fan/connection handles change. `Reject` blocks UUID references,
including EMS actuators/LifeCycleCost and metadata pointing to the removed fan.
Unsupported fan-name references still block. Compatible `OutputVariable` keys
retain their identities/fields because the replacement retains the fan name.
Supported variables common to both pinned fan classes are `Fan Electricity Rate`,
`Fan Electricity Energy`, `Fan Rise in Air Temperature`, `Fan Heat Gain to Air`
and `Fan Air Mass Flow Rate`, matched case-insensitively. `MeterCustom` and
`MeterCustomDecrement` groups keyed to `Fan Electricity Energy` also remain
intact, together with associated exact-name `OutputMeter` requests. Each key
in a meter is checked individually; one supported key does not exempt unsafe
keys elsewhere in the object. Object display names alone are not fan references.
Impact lists up to eight retained reporting objects and their total count;
the full list is in `plan.retained_output_references`. Saved validation rechecks
that list and all protected raw fields. No references are silently retargeted.
Setpoint managers and
translated controls stay at their existing nodes; before/preview/saved translated
fields must agree. No new control manager or schedule is created.

Hash-bound plans, companion-resource checks, independent saved validation,
translation and publication protections follow the shared transaction. Keep the
output OSM with its `<stem>/` companions. Do not reuse a plan after input/config
changes. Return/relief/exhaust/unitary fans and whole-system conversion remain
outside this operation.
