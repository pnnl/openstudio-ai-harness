# Electric EIR chiller reference-rating contract

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
no-op is rejected. Unrequested capacity, reference temperatures/flows, curves, PLRs,
unloading, condenser type, fan/basin heater, heat rejection fraction, sizing factor,
flow controls, end-use label, schedules and plant dispatch are not editable here.

`setReferenceCOP`, `setReferenceCapacity` or `autosizeReferenceCapacity` updates the existing object only for explicitly requested fields. Its handle/name, metadata, EMS,
cost/output references, curves and all water boundaries stay intact. A protected
snapshot covers every other model object, including both plant graphs. The chiller's
raw fingerprint excludes only the explicitly requested reference-rating fields. Saved checks compare the requested
value with tight numeric serialization tolerance and preserve all other fields.
Independent EnergyPlus translation must retain the three curve references and
match the reviewed ratings while preserving every other translated chiller field. A source COP
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

## Reference-capacity extension (12f)

`settings` accepts one or both `reference_cop` and `reference_capacity_w`.
For a capacity-only edit, for example `{"reference_capacity_w": 100000}`, COP
remains unchanged. Capacity is strictly positive finite cooling thermal W, or the
exact string `"Autosize"`. This example is not a recommendation. Empty settings
stay unready, unknown fields and invalid values reject, and a combined no-op
rejects. Fixed watts are not multiplied by the retained sizing factor.

`impact.reference_capacity_w` always describes the source. `capacity_edit` holds
`before_w`, `after_w`, other-chiller count, up to eight other supply chillers with
capacity/factor, and omitted count. Unsupported chiller classes have null capacity
and factor in this contextual list; they remain uneditable. Existing curves, PLRs,
minimum unloading, sizing factor, water-flow inputs/Autosize flags, circuits and
controls stay unchanged. EMS and name/handle references are retained.

EnergyPlus dispatch limits use reference capacity times minimum/maximum/optimum
PLR. Actual available capacity additionally depends on the temperature curve;
capacity edits change operating PLR, cycling/unloading and false loading. Small
capacity can cause unmet cooling; large capacity can alter efficiency. No energy
saving or adequacy guarantee is made. Autosized evaporator flow uses plant design
flow times sizing factor; it is not derived from the edited fixed capacity.
Autosized water-cooled condenser flow uses reference capacity, reference COP and
the actual compressor heat rejection fraction, so pumps and towers can resize.
Retained input fields do not guarantee retained sizing results.

With evaporator flow autosized, each autosized EIR chiller uses the entire plant
design flow times its sizing factor and plant design delta-T. With fixed evaporator
flow, that fixed flow and plant design delta-T are the basis; the factor is not
applied again. Neither path automatically divides capacity among units. Review
other units and dispatch before requesting Autosize. Explicit Autosize adds
`impact.plant_sizing`: design-day and sizing-period counts, default/requested
plant-sizing flag, translated effective flag and verification status. Missing
periods or off/unverified plant sizing conservatively marks `simulation_ready`
false but does not block applying the reviewed input change or silently add days
or turn sizing on. This is not a claim that every such model fails; some fixed-flow
cases can size without a plant-sizing run. COP-only and fixed-capacity edits do
not introduce a whole-model sizing audit. All exact transaction protections remain.


### Capacity review details (G1–G3)

`capacity_edit.dispatch_load_limits_w` reports proposed `minimum`, `maximum`,
`optimal`: reference capacity times the retained respective PLRs. Autosize yields
`"Requires sizing"` for each. `load_distribution_scheme` records the retained
scheme. `dispatch_limits_exclude_temperature_curve: true` distinguishes these
reference dispatch limits from actual available capacity after temperature-curve
modification; they are not guaranteed delivered cooling.

When the retained condenser fan power ratio is positive, capacity requests warn
and add `capacity_edit.condenser_fan`: `power_ratio`, `before_full_cycling_w` and
`after_full_cycling_w`. Each watt value is reference capacity × ratio, or
`"Requires sizing"` for Autosize. Runtime power multiplies that value by cycling
fraction while operating with a positive capacity-curve modifier. Above minimum
PLR, cycling fraction is 1, so changing capacity changes fan power even at the
same delivered cooling. Below minimum PLR, cycling fraction matters too. EnergyPlus
applies this separate condenser-fan calculation for every condenser type, including
WaterCooled; it is distinct from external cooling-tower fan power and compressor
power. Zero ratio adds no fan warning or fan impact block. Compare the dedicated
`Chiller Condenser Fan Electricity Energy` output when evaluating energy.

A malformed/empty/non-finite translated capacity produces a fixed descriptive
unready plan error, not an unexpected failure capture. The explicit Autosize token
is still supported. Apply's saved-value/translation checks remain strict.
