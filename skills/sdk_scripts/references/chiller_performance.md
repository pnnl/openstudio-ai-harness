# Electric EIR chiller reference-COP contract

One existing `ChillerElectricEIR` on the supply side of a plant typed `Cooling`.
AirCooled and WaterCooled are supported. A connected heat-recovery plant,
thermosiphon curve, EvaporativelyCooled or another chiller class needs separate
coverage. Inventory flags the same scope that preflight enforces. A rating-only
edit may proceed on an incomplete existing plant with warnings and false simulation
readiness; no pump, setpoint or heat-rejection source is added implicitly.

```json
{
  "output_model_path": "/work/edited.osm",
  "plant_loop": {"name": "CHW"},
  "chiller": {"name": "Selected Chiller"},
  "settings": {"reference_cop": 5.0}
}
```

This number is an example, not a recommended default. Selectors accept exactly one
name or handle; a missing selector/settings stays unready. COP must be finite and
strictly positive. Values below 2 or above 10 warn without blocking or converting
input: COP = 3.517 / (kW per ton), COP = EER / 3.412. These are plausibility review
thresholds, not schema limits or a standard; validate the user's rating basis. A
no-op is rejected. Capacity, reference temperatures/flows, curves, PLRs,
unloading, condenser type, fan/basin heater, heat rejection fraction, sizing factor,
flow controls, end-use label, schedules and plant dispatch are not editable here.

`setReferenceCOP` updates the existing object. Its handle/name, metadata, EMS,
cost/output references, curves and all water boundaries stay intact. A protected
snapshot covers every other model object, including both plant graphs. The chiller's
raw fingerprint excludes only Reference COP. Saved checks compare the requested
value with tight numeric serialization tolerance and preserve all other fields.
Independent EnergyPlus translation must retain the three curve references and
match COP while preserving every other translated chiller field. A source COP
translation mismatch or missing translated curve returns a normal unready plan
with a fixed error message; these model-state problems do not invoke automatic
unexpected-failure reporting. Fresh-report,
source/resource hashes, object types/handles and snapshot checks remain exact.
Apply publishes a new OSM plus `<stem>/` companions without overwriting the source.

The plan records before/after COP, reference temperatures/capacity/flows and sizing
flags, curves, condenser context, other supply chillers and bounded EMS references.
Water-cooled
impact includes `condenser_sizing.reference_condenser_flow_autosized` and
`autosized_equipment`, each with identity/type and its Autosize/Autocalculate fields.
The latter lists supply-side condenser pumps, headered pumps and cooling towers.
An autosized selected-chiller condenser flow triggers a specific resizing warning;
autosized condenser pump/tower fields also warn when the selected flow is fixed.
`simulation_readiness_scope: operation_and_companions` explicitly opts into combined
readiness; it does not change other operations' flags. Missing known plant controls,
water-cooled heat rejection or companions marks simulation unready while permitting
the edit. True means no identified blocker, not that the entire plant was audited.

Reference COP is not IPLV or seasonal/whole-plant COP. The three retained curves
modify capacity and EIR; part-load/cycling and condenser conditions affect operating
power. Pumps, towers and condenser fans can contribute additional electric use.
When condenser fan power ratio is positive, reference COP must exclude that
separately modeled fan power; inspect the retained ratio before accepting a rating.
On a water-cooled plant, changing compressor electricity also changes condenser
heat rejection and may change autosized condenser flow, pump and tower sizes and
energy, even though all sizing inputs/flags are preserved. Compare plant energy
including pumps/towers; a compressor electricity reduction is not plant savings.
No savings guarantee or curve-envelope
certification is made. Retained EMS and dispatch may prevent the chiller from
running. Simulation remains a separate workflow.

Local standards trace: `Prototype.hvac_systems.rb:385–423` creates electric EIR
chillers, sets reference COP separately from PLRs, sizing and condenser connections.
`Standards.ChillerElectricEIR.rb:209–302` can select standards-specific curves and
COP together. This editor implements an explicit rating change, not that whole
standards recipe: it does not select minimum efficiency or substitute curves.
Pinned [EnergyPlus 25.2 inputs](https://bigladdersoftware.com/epx/docs/25-2/input-output-reference/group-plant-equipment.html#chillerelectriceir)
and [engine source](https://github.com/NatLabRockies/EnergyPlus/blob/v25.2.0/src/EnergyPlus/ChillerElectricEIR.cc)
are the reference for operating behavior. Native tests compare cooling, chiller
electricity, condenser heat and sizing for unchanged curves/controls; see the work
guide for actual evidence and its limits.
