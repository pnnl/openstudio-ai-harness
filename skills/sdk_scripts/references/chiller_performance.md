# Electric EIR chiller performance contract

Edit one supply-side `ChillerElectricEIR` on a Cooling plant: AirCooled or
WaterCooled, without connected heat recovery or a thermosiphon curve. Other
classes/condenser types, curve substitution, topology/class conversion and plant
repairs need separate coverage. Inventory and preflight enforce the same scope.

## Explicit inputs

```json
{
  "output_model_path": "/work/edited.osm",
  "plant_loop": {"name": "CHW"},
  "chiller": {"name": "Selected Chiller"},
  "settings": {"reference_cop": 5.0, "reference_capacity_w": 100000}
}
```

Numbers are examples, not defaults. Selectors use a unique name or handle.
Settings can contain one or more supported fields. Missing/empty choices remain
unready; invalid values and combined no-ops reject. No inferred standards values,
matching flow, sizing factor, companion limit or curve changes.

- `reference_cop`: finite positive cooling W/electric W at retained reference
  conditions, excluding any separately modeled condenser fan. Not IPLV, seasonal
  or whole-plant COP. Below2 or above10 warns without blocking/converting:
  COP=3.517/(kW per ton), COP=EER/3.412. Confirm rating basis and units.
- `reference_capacity_w`: finite positive cooling thermal W or exactly `Autosize`.
  Fixed watts are not multiplied by the sizing factor. Unrequested capacity and
  all water-flow inputs/Autosize flags stay exact.
- `minimum_part_load_ratio`, `minimum_unloading_ratio`: finite numbers ≥0.
  `maximum_part_load_ratio`, `optimum_part_load_ratio`: finite numbers >0.
  Effective requested+preserved values must satisfy minimum≤optimum≤maximum and
  minimum≤unloading≤maximum. Inconsistent choices remain unready, requiring
  explicit companion changes. Ratios do not accept Autosize. Maximum>1 warns
  about equipment capability and curve validity; no arbitrary maximum1 clipping.

## In-place preservation and reporting

Only selected setters act on the existing chiller. Identity/name, metadata,
EMS/cost/output references, curves, all circuit boundaries, reference conditions,
condenser mode/fan ratio, heat rejection fraction, sizing factor, controls and
unrequested ratings/PLRs remain protected. Only requested fields leave the raw
fingerprint; every other object stays in the exact snapshot. Requested numerical
saved values use tight serialization tolerance; source/resource hashes,
reviewed/fresh equality, types/handles, all other raw fields and translated fields
remain exact. Independent translation checks requested ratings/controls and all
three curve references. Missing/malformed/mismatched translated source settings
return normal unready errors, not unexpected-failure capture. Apply checks saved
translation before publishing a new OSM and `<stem>/` companions; source untouched.

Legacy COP-only reports retain their shape. Requested capacity/PLRs join before/
after values; `parameters.settings` contains only the request. Impact records source
capacity/flows/reference conditions, curves, PLRs, condenser context and bounded
EMS. `reference_capacity_w` at the impact top level always means source capacity.

Capacity requests add `capacity_edit`: before/after W, Autosize flow basis, other
chiller count, up to8 other supply chillers' capacities/factors and omitted count.
Unsupported contextual classes have null capacity/factor and remain uneditable.
`dispatch_load_limits_w` gives proposed reference capacity×minimum/maximum/optimal
PLR, or `Requires sizing`. Distribution scheme and
`dispatch_limits_exclude_temperature_curve: true` identify these as reference
limits, not actual temperature-modified available cooling.

PLR requests add `part_load_edit`: all ratios before/after, retained distribution
scheme, before/after reference dispatch limits and the same curve-exclusion flag.
Combined capacity requests use proposed capacity and proposed PLRs consistently
in both impact blocks. An inherited Autosize capacity does not imply a new sizing
audit, fixed value or restored prior sized result.

## Capacity, sizing and energy interpretation

Reference capacity and COP are ratings. Temperature/EIR/part-load curves, cycling,
unloading, condenser conditions, EMS and dispatch determine operation. Smaller
capacity/maximum PLR can cause unmet cooling; larger capacity can change PLR,
false loading and electricity. Preserved dispatch inputs do not imply unchanged
allocation. No curve-envelope, adequacy or savings certification.

With evaporator flow Autosize, each autosized EIR chiller uses whole-plant design
flow×its own sizing factor, plant design delta-T and fluid properties; capacity is
not divided automatically among units. With fixed evaporator flow, that flow and
plant delta-T determine capacity without applying the factor again. Autosized
evaporator flow is not derived from edited fixed capacity.

Explicit capacity Autosize adds `impact.plant_sizing`: design-day/period counts,
defaulted/requested model flag, effective translated plant-sizing flag and its
verification status. Missing periods or off/unverified sizing conservatively
makes simulation unready while allowing the input edit. No day/control changes.
Some fixed-flow cases can still size with the flag off; this is not a guaranteed
failure claim. Fixed-capacity/COP/PLR edits do not introduce whole-model sizing
audits. Review other units and the recorded flow basis before choosing Autosize.

Water-cooled condenser flow Autosize uses capacity×(1+compressor heat rejection
fraction/COP)/(condenser design delta-T×rho×Cp), with the actual retained fraction.
`condenser_sizing` records flow-Autosize and supply pump/headered-pump/tower fields
using Autosize/Autocalculate. Pumps/towers can resize even with unchanged input
flags; equipment fields also warn when selected condenser flow is fixed. Compare
plant energy including pumps/towers; compressor savings are not plant savings.

Positive condenser fan ratio adds a capacity-edit warning and
`capacity_edit.condenser_fan`: ratio plus before/after full-cycling W=reference
capacity×ratio, or `Requires sizing`. Runtime multiplies by cycling fraction when
operating with positive capacity-curve modifier. This separate calculation applies
to every condenser type, including WaterCooled; it excludes external tower fans.
At full cycling, capacity scales fan power even at equal cooling. Zero ratio adds
no fan block/warning. Compare `Chiller Condenser Fan Electricity Energy` separately.
PLR edits can change that fan's runtime energy without changing rated capacity.

## Cycling and unloading

Below minimum PLR the engine cycles on/off. Minimum unloading then sets the
on-cycle PLR floor; false-load heat is available capacity×reported PLR×cycling
fraction minus useful evaporator cooling, clamped at zero. Thus reported Chiller
Part Load Ratio can include unloading and need not equal delivered cooling /
available capacity. Optimum is a dispatch hint, not an EIR curve or commanded
operating point. Review useful cooling, cycling, false-load energy, compressor,
condenser fan, pump/tower energy and unmet loads, not ratios alone.

## Readiness and references

`simulation_readiness_scope: operation_and_companions` explicitly combines known
operation and companion blockers; other operations' flags are unchanged. Missing
known pumps/outlet setpoints, water-cooled heat rejection or companions marks
simulation unready while permitting a reviewed input edit. True is no identified
blocker, not a complete audit or simulation guarantee. Run preparation when gated,
retain model/report lineage, and simulate separately through the selected provider.

Standards: `Prototype.hvac_systems.rb:385–423` creates EIR chillers and separately
sets COP/PLRs/sizing/condenser connections; `Standards.ChillerElectricEIR.rb:209–302`
can choose curves and COP together. This editor applies neither standards recipe.
Pinned [EnergyPlus25.2 source](https://github.com/NatLabRockies/EnergyPlus/blob/v25.2.0/src/EnergyPlus/ChillerElectricEIR.cc)
validates relationships, returns reference dispatch products, and applies cycling
and unloading at runtime. See the work guide for native evidence and limitations.
Controlled 12i tests use explicit fixed-return 5kW demand and flat temperature/
linear EIR fixture curves to isolate behavior; those are not recommendations or
curve changes performed by this editor. All native results are design-day evidence,
not annual savings or an exhaustive multi-unit dispatch test.
