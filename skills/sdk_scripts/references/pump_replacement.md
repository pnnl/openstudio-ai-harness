# Single-pump class replacement

This contract changes one connected `PumpConstantSpeed` ↔ `PumpVariableSpeed`.
Select exact `name` or `handle` for a plant and one of its supply/demand pumps.
Multiple pumps and common-pipe primary/secondary arrangements are supported by
individual selection. Other pumps, supply equipment, demand branches, coils,
setpoints, fluid, schedules and plant sizing stay intact. Same-class changes use
`openstudio-pump-performance-editor` in place.

```json
{
  "output_model_path": "/absolute/outputs/pump_replaced.osm",
  "plant_loop": {"name": "Chilled Water Loop"},
  "pump": {"name": "Chilled Water Secondary Pump"},
  "target_class": "VariableSpeed",
  "flow_policy": "Preserve",
  "power_policy": "Preserve",
  "plant_policy": "Preserve",
  "reference_policy": "Reject",
  "variable_speed": {
    "minimum_flow_m3_s": 0.0,
    "power_coefficients": [0.0, 0.0205, 0.4101, 0.5753]
  }
}
```

The curve illustrates an explicitly selected standards profile, not a recommended
universal reset strategy. A ConstantSpeed target omits `variable_speed` entirely.
[The schema](pump_replacement.schema.json) validates strict partial configs; missing
policy/curve choices stay unready. Optional explicit `end_use_subcategory` can
change the reporting label; otherwise it stays as loaded.

`flow_policy` and `power_policy` independently choose Preserve or Autosize for
rated flow and electric power. Preserve retains fixed values or Autosize exactly;
Autosize explicitly resets just that dimension. Common head, motor efficiency,
motor losses to fluid, Continuous/Intermittent control, sizing method/factors,
flow schedule, name and zone heat-loss split are copied from the old pump.
Constant-speed blank zone radiation is effectively zero; it is explicitly carried
to VariableSpeed rather than accepting that class's 0.5 default. VariableSpeed's
existing split similarly carries to ConstantSpeed.

VariableSpeed requires a fixed `minimum_flow_m3_s` (0–100) and exactly four bounded
coefficients. Power fraction is a+b·x+c·x²+d·x³, nonnegative over x∈[0,1], positive
at full flow. Non-unit full-flow power warns. Min flow must be below fixed rated
flow; if rated flow is autosized, positive min flow warns to check after sizing.
Its design minimum-flow fraction is explicitly zero/inactive for the specified
fixed minimum flow. ConstantSpeed removes the old polynomial and variable-speed
minimum-flow settings; its simple running-power fraction is 1. Plant controls
still determine operation/flow. This does not install VFD/pressure reset or make
a whole plant a variable-flow plant.

The impact includes `demand_bypass`: explicit OSM uncontrolled-branch status/count,
verified translated uncontrolled branch names/count, common-pipe mode and whether
this is a constant-speed supply target. Detection checks complete parallel paths
between the demand splitter and mixer: pipe-only or empty paths count; inlet/outlet
pipes and pipes sharing a controlled coil branch do not. Unknown passive equipment
is not classified. Summaries show up to eight paths; full detail stays in the plan.

A constant-speed supply target without an explicit OSM bypass emits a warning;
it remains ready without an extra acknowledgement field. The warning distinguishes
an existing translated path from none found. OpenStudio 3.11.0 can synthesize a
bypass absent from the OSM; this is checked in the translated workspace rather
than assumed from the pump class. Removing such paths in downstream measures
can force excess flow through active loads. Common-pipe primary/secondary flow
may be decoupled and needs separate flow review. A path's presence does not prove
capacity or flow adequacy. Preserve does not insert an OSM bypass, and saved
validation independently checks the explicit and translated status.
The [EnergyPlus 25.2 flow-resolver reference](https://bigladdersoftware.com/epx/docs/25-2/engineering-reference/plant-condenser-loops.html)
explains excess-flow allocation to bypass/passive paths and then active branches.

The shared pump power check reports fixed power, active autosizing and deferred
motor feasibility when flow is autosized. After sizing check
flow × head / (rated power × motor efficiency) ≤1. Fixed flow/head/power cannot
exceed motor output. No sizing run or implicit power reset occurs during editing.

Replacement retains the inlet/outlet node identities and plant position; pump and
two connections get new handles. Metadata retains its handle/features with its
owner remapped. Direct pointers/UUIDs and unsupported name references to the old
pump reject, including EMS actuators/sensors and LifeCycleCost. Compatible
name-keyed output variables remain unchanged: Pump Electricity Rate/Energy,
Shaft Power, Fluid Heat Gain Rate/Energy, Outlet Temperature and Mass Flow Rate.
Custom/decrement electricity-energy meter keys and their exact-name output meter
requests also remain; plans list counts, up to eight examples and full-report details.
All surviving objects are protected, with only boundary-port/metadata-owner fields
permitted to change; the full connection graph is independently checked afterward.

Supported source pumps have no pressure curve, impeller/RPM fields, VFD schedules
or active plant pressure simulation. Such controls, banks and condensate pumps
need a separate contract; nothing is silently dropped. Incoming references are
handled by explicit Reject only, not automatic migration. Unsupported plant-flow
redesign or common-parameter changes should not be smuggled into this operation.

Preflight previews SDK side effects and compares all translated setpoint,
availability and plant-operation controls. A component-setpoint operation may
reference the selected pump: only that exact pump's equipment-class field changes
to the target class; nodes, flow and operation values remain protected. Any other
translated control difference blocks preflight. Apply rechecks the complete plan and
source/companion hashes, reloads the staged copy, checks independent getters,
raw replacement fields, object/graph deltas and reporting references, then performs
EnergyPlus translation. It publishes a new OSM plus `<stem>/` companions and a
JSON report; compact stdout omits protected-object inventories. Simulation follows
separately, and output/report paths must be new.

Source trace: local `openstudio-standards` commit
`8bad404ef113019661fc0c14274a3554234219f7`, `Prototype.hvac_systems.rb:92–109`
(HW pump class/head/control), `:257–298` (CHW supply/demand pumps and explicit
polynomial). `Standards.PumpVariableSpeed.rb:11–54` defines profiles and also calls
`setPumpControlType('Intermittent')`; this replacement preserves existing control
rather than applying that template-dependent setter. Native
[EnergyPlus 25.2 pump source](https://github.com/NatLabRockies/EnergyPlus/blob/v25.2.0/src/EnergyPlus/Pumps.cc)
uses a constant-speed running-power fraction of 1. The fixture's RDD confirms the
seven shared reporting variables. Native fixture behavior is verification evidence,
not annual savings or compliance certification.
