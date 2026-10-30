# Water district capacity contract — phase 12d

Edit one existing supply-side `DistrictHeatingWater` or `DistrictCooling` through
OpenStudio 3.11.0. Inventory includes unsupported district steam with `supported:
false`. Heating, Cooling and Condenser sizing roles are accepted for water-loop
applications; unusual direction versus sizing role raises a warning. No equipment
is created, replaced or rewired.

```json
{
  "output_model_path": "/work/variant.osm",
  "plant_loop": {"name": "Heating Plant"},
  "district_equipment": {"name": "Purchased Heating"},
  "settings": {"nominal_capacity_w": 100000}
}
```

Use a unique exact name or handle selector. Capacity is positive finite thermal
watts, or exactly `"Autosize"`; boolean, zero, negative and nonfinite values reject.
Missing choices return unready, and a no-op rejects. No defaults profile or inferred
capacity. Apply requires the exact reviewed plan and unchanged source/companions.
Older/unstable inputs require bundled preparation first.

## Runtime and sizing semantics

EnergyPlus 25.2 `OutsideEnergySources.cc`, `size()` and `calculate()`:

- Water-source Autosize = design plant volume flow × fluid density × specific heat
  × plant design ΔT. This edits the sizing *input policy*, not a saved simulation size.
- Runtime available thermal capacity = nominal capacity × max(0, capacity-fraction
  schedule). Schedule values above 1 increase capacity; it is not a binary
  availability schedule. EnergyPlus applies loop temperature protection after this
  limit; reaching a loop temperature bound can override the limit in reported heat.
  This includes a limited load of zero and a schedule fraction of 0: neither is
  a guaranteed off command. Inspect outlet temperatures and unmet loads alongside
  energy.
- Load-based dispatch receives nominal capacity as maximum and optimal load,
  **without** the capacity-fraction multiplier. Editing nominal capacity can move
  load between sources even when operation schemes and their equipment order stay
  intact. If the fraction is below 1, the source can receive a larger assignment
  than it delivers; spare capacity elsewhere does not guarantee that this shortfall
  will be reassigned. Review every source's delivered load and plant unmet demand.
  Native SequentialLoad and UniformPLR two-source cases demonstrate the shortfall;
  no claim is made about every EMS/custom dispatch arrangement.
- A nonzero assigned load requests the loop's full design water mass flow before
  capacity limiting, regardless of nominal capacity or fraction. This edit does not
  itself request proportionally lower flow or pump energy. Actual constrained flow,
  on/off hours and thermal/density feedback can still affect pump results.
- Heating supplies positive loads; cooling removes heat. Purchased thermal energy
  is the absolute delivered load integrated over time. No COP/boiler efficiency or
  upstream district production energy is represented by nominal capacity.
- Lower capacity can reduce delivered energy and worsen unmet loads. Do not report
  it as efficiency savings. Other autosized inputs are retained; actual sizing and
  operation need simulation.

The plan reports load-distribution scheme, unadjusted dispatcher design capacity,
its explicit lack of schedule adjustment, before/after capacity, retained schedule
reference, constant fraction/effective limit if available, loop role/design conditions and bounded EMS
references. A time-varying schedule has no invented constant limit. Existing
pump/setpoint or companion blockers make `simulation_ready` false without blocking
the rating edit. True means no identified blockers, not a complete model audit.

## Preservation and verification

Set only nominal capacity/Autosize on the existing object. Retain name, handle,
metadata, costs, EMS, capacity schedule, boundary nodes, plant membership, operation
schemes, all other equipment and sizing inputs. Snapshot all other objects with
existing shared companion normalization only. Require exact object/handle sets,
protected fingerprints and unchanged translated fields apart from nominal capacity.
Compare the selected saved and translated numeric capacity with 1e-9 tolerance.
Source translation mismatch/loss returns a normal bounded unready error. No hash,
report, snapshot or cascade checks are relaxed.

## References and remaining scope

Standards `prototypes/common/objects/Prototype.hvac_systems.rb:129–132` and
`:378–381` construct/autosize these sources on plant supply branches. This editor
exposes explicit capacity without repeating creation or modifying the schedule.

Pinned source: [EnergyPlus 25.2 OutsideEnergySources.cc](https://github.com/NatLabRockies/EnergyPlus/blob/v25.2.0/src/EnergyPlus/OutsideEnergySources.cc),
lines 124–133 (dispatcher design limits), 337–345 (full-loop flow request),
368–417 (sizing), 452–482 (limits/direction and post-limit temperature protection),
517–518 and 535–565 (metering).
[PlantCondLoopOperation.cc](https://github.com/NatLabRockies/EnergyPlus/blob/v25.2.0/src/EnergyPlus/PlantCondLoopOperation.cc)
3041–3168 allocates Optimal/SequentialLoad using nominal limits and subtracts
assigned loads; 3252–3356 does the same for UniformPLR.
Steam, schedule modification, district network efficiency/losses, new equipment and
replacement require separate contracts. Native tests use both water source classes,
capacity-limited loads and sizing; they are design-day evidence, not annual savings.


## Explicit Autosize readiness (F2)

For an explicit Autosize request, shared `common/plant_sizing.py` reports design-day
and sizing-period counts, whether the model flag is defaulted, its explicit value
if any, and the actual translated `SimulationControl` plant-sizing flag. It reads
the existing translation rather than translating twice or materializing a missing
model control. Configure sizing periods and plant sizing before simulation.
Missing periods, off or unverified effective sizing leave the edit ready but mark
`simulation_ready: false`; no model controls or design days are changed.

This is a conservative readiness policy, not a claim that EnergyPlus always fails
or returns zero with sizing off. Native fixed-flow cases can calculate positive
sizes without a plant-sizing run. With sizing requested but no design periods,
the tested models fail before simulation. This check covers the explicit Autosize
setting in this skill, not every inherited Autosize field elsewhere in the model;
true remains absence of identified blockers, not whole-model certification.
