# In-place plant-pump performance and control editing

Select one existing single `PumpConstantSpeed` or `PumpVariableSpeed` by exact name
or handle within one selected plant. Supply and demand components are supported,
including an individually selected pump in a primary/secondary arrangement.
Inventory reports headered pumps but preflight refuses editing them.

Config requires a new absolute output OSM path. `plant_loop` and `pump` selectors
use exactly one `name` or `handle`. `settings` is a partial explicit patch, with at
least one effective change. Unknown fields, nonfinite values, ambiguous selectors,
missing head units and invalid ranges are rejected. See
[pump_performance.schema.json](pump_performance.schema.json).

```json
{
  "output_model_path": "/absolute/outputs/pump_edit.osm",
  "plant_loop": {"name": "Chilled Water Loop"},
  "pump": {"name": "Chilled Water Loop Pump"},
  "settings": {
    "head": 30.0,
    "head_units": "ftH2O",
    "motor_efficiency": 0.95
  }
}
```

Those numbers illustrate syntax, not design recommendations. Unspecified values
remain as loaded. Settings:

| Input | Meaning and bounds |
|---|---|
| `head` + `head_units` | Positive design pressure ≤10,000,000 Pa (≤3345.5256331296855 ftH2O), converted by pinned SDK; a bundle input ceiling, not a recommended design head |
| `motor_efficiency` | Motor electric-to-shaft efficiency, >0 and ≤1 |
| `motor_loss_fraction_to_fluid` | Fraction of motor losses added to fluid, 0–1 |
| `control_type` | `Intermittent` or `Continuous`; retained schedules still apply |
| `rated_power_w` | Explicit positive electric power or literal `Autosize`; no inferred reset |
| `power_sizing_method` | `PowerPerFlow` or `PowerPerFlowPerPressure` |
| `electric_power_per_flow` | Positive W/(m³/s); active for autosized `PowerPerFlow` |
| `shaft_power_per_flow_per_head` | W/(m³/s·Pa), ≥1 (inverse hydraulic efficiency); active for autosized `PowerPerFlowPerPressure` |
| `part_load_coefficients` | Exactly four finite bounded numbers, variable-speed only; power fraction a+b·x+c·x²+d·x³ must be nonnegative over 0≤x≤1 and positive at x=1 |

The pressure method sizes electric power as flow × head × shaft factor / motor
efficiency. The flow method uses flow × electric factor. Fixed power is retained
even when head/efficiency changes, unless a power change/reset is explicitly
requested. Plans warn about fixed power, inactive factors and full-flow curve
power differing from 1. Fixed flow/head/power cannot demand hydraulic power greater
than motor output. With fixed power and autosized flow, preflight explicitly warns
that motor-output feasibility cannot be established until sizing. It reports the
maximum feasible design flow, rated power × motor efficiency / head; after sizing,
verify flow × head / (rated power × motor efficiency) ≤1. Apply preserves this
warning and the fixed power choice; it does not run sizing or infer an Autosize
reset. The 10 MPa input ceiling is equivalent in both units; the schema enforces
exactly four coefficients before inventory/SDK planning. Curve extrema are checked
analytically, not by coarse sampling.
Existing pressure curves/VFD controls warn about overriding simple power behavior.

Standards trace (local commit `8bad404ef113019661fc0c14274a3554234219f7`):
`Prototype.hvac_systems.rb:92–109` sets HW pump head, motor efficiency and
Intermittent operation; `:257–298` sets CHW supply/demand pumps and explicit
linear/variable-speed power curves. `Standards.PumpVariableSpeed.rb:11–54` defines
four polynomial profiles and also sets Intermittent. This editor accepts explicit
coefficients without silently applying that extra control change or inferring
standards compliance. `Prototype.PumpVariableSpeed.rb:12–76` selects profiles from
served area, capacity and motor size; this template-dependent selection is not
ported into a generic performance edit.

Electric sizing/operation is verified against
[EnergyPlus 25.2 pump source](https://github.com/NatLabRockies/EnergyPlus/blob/v25.2.0/src/EnergyPlus/Pumps.cc).
A head/efficiency edit is not a guarantee of energy savings in a controlled plant.

Apply uses the shared hash-bound copy transaction, companion packaging and
EnergyPlus translation check. Independent saved checks compare scalar/curve
getters, the pump's untouched raw fields, every other protected model object,
plant ownership, both boundary nodes and supply/demand component order. Source
OSM/resources remain untouched. Incoming references are retained because the pump
handle stays stable. No node/controller/plumbing rewiring occurs.

Outputs are a new OSM, `<stem>/` companions, full JSON plan/apply reports and
compact stdout. Simulation is separate; rerun sizing before assessing autosized
power changes. Class replacement, headered/condensate pumps, flow/minimum-flow
changes and pressure-control redesign await separate contracts.
