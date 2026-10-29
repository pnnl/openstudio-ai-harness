# Hot-water boiler performance, capacity and part-load limits

Operation `edit_boiler_performance`, exact OpenStudio 3.11.0 / EnergyPlus 25.2.
One existing supply BoilerHotWater on a Heating plant; inventory and preflight
reject steam/detached/demand-side and nonheating boilers, including Condenser loops.
This in-place operation preserves identity and does not change fuel/class or topology.

```json
{
  "output_model_path":"/work/boiler-edited.osm",
  "plant_loop":{"name":"HW"},
  "boiler":{"name":"Selected Boiler"},
  "settings":{"nominal_thermal_efficiency":0.9}
}
```

Example values are explicit inputs, not recommendations. Select a unique name or
handle. Missing selectors/settings stay unready; empty/no-op requests reject.
Only selected setters execute, with no profile, sizing reset or companion-ratio
adjustment. The existing value/report shape is retained for rating-only requests;
requested capacity/PLR fields appear only when selected.

| Setting | Accepted value / meaning |
| --- | --- |
| nominal_capacity_w | Positive finite useful thermal output W or exactly `Autosize`; not fuel input |
| nominal_thermal_efficiency | HHV fraction >0 and ≤1; retained normalized curve can multiply it |
| on_cycle_parasitic_electric_load_w | Nonnegative rated W; active input × PLR, zero when idle |
| off_cycle_parasitic_fuel_load_w | Nonnegative configured W; a positive request on Electricity rejects |
| minimum_part_load_ratio | Finite ≥0; useful-heat floor while firing, not chiller cycling |
| maximum_part_load_ratio | Finite >0; useful-heat/dispatch cap; above 1 is allowed with warning |
| optimum_part_load_ratio | Finite ≥0; plant-dispatch hint, not runtime efficiency/setpoint |

Requested plus preserved ratios must satisfy 0 ≤ minimum ≤ optimum ≤ maximum,
maximum >0. No implicit clipping; the standards prototype uses maximum 1.2.
Zero maximum is outside this operation; use a justified availability/removal
workflow. Autosize is not a ratio. AFUE, combustion and LHV efficiencies are not
interchangeable with HHV; resolve basis first. Special nominal efficiency >1 is
outside this input schema, but an existing value is preserved on unrelated edits.

## Parasitics and runtime interpretation

Pinned [Boilers.cc](https://github.com/NatLabRockies/EnergyPlus/blob/v25.2.0/src/EnergyPlus/Boilers.cc)
provides more specific behavior than the generic off-cycle field description:

- Electricity discards configured off-cycle fuel internally. New positive requests
  reject. Existing nonzero values warn and remain stored on unrelated edits;
  impact shows ignored before/after and effective zero. This does not block
  simulation. Only an explicit zero clears the stored value.
- During active calculation with positive requested load/run flag, off-cycle fuel
  rate updates to configured W × (1 − PLR). Idle paths retain that last rate,
  even in later summer periods, or zero if never updated. It is not constant idle
  standby consumption. There is no zero clamp above PLR 1, so a proposed/preserved
  maximum above 1 warns that off-cycle ancillary fuel may become negative.
- On-cycle electric rate is configured W × operating PLR while firing, reset to
  zero when idle. Both ancillary energies meter under Heating / `Boiler Parasitic`;
  inspect `Boiler Ancillary <fuel> Rate/Energy` separately from main fuel.

In locked-flow operation, minimum PLR can impose heat above assigned demand,
raise water temperature or trip the retained outlet high limit. Maximum PLR can
cause unmet load; above-one maximum allows heat above nominal capacity. Actual
behavior depends on flow, curves, outlet limit, dispatch and faults. Less useful
heat or lower metered fuel from undersizing is not an efficiency saving.

## Capacity, sizing and dispatch

Capacity × minimum/maximum/optimum PLRs gives the numerical dispatch limits.
`impact.part_load_edit` shows all ratios and limits before/after and retained load
distribution; combined capacity edits use proposed capacity and proposed ratios.
`capacity_edit` holds before/after capacity and dispatch limits, while top-level
`impact.nominal_capacity_w` consistently means current/source capacity. Inherited
Autosize reports `Requires sizing`, without inventing watts or starting a sizing
audit for a ratios-only edit.

Capacity edits can move loads between sources while keeping operation-scheme
inputs. `Boilers.cc::getDesignCapacities` exposes the three products to dispatch.
Capacity also changes realized PLR, curve inputs, ancillary consumption and the
minimum output floor; fixed flow is preserved and need not match a new capacity.

Autosize uses plant design flow × density × Cp × design ΔT × retained boiler
sizing factor. Properties use `HWInitConvTemp` (60 °C), potentially differing
from plant reports. Flow sizing separately uses plant flow × factor; neither
flow policy nor factor changes here. Native sizing values are in the work guide.

On multiple-boiler loops, **each** autosized boiler uses the whole plant design
load × its own sizing factor; the load is not automatically split. Impact lists
other capacities and factors (up to eight plus omitted count, null for unsupported
classes). Review total capacity and factors; no inferred division is applied.

Explicit capacity `Autosize` reports design-day/period counts, defaulted/explicit
model sizing flag and effective translated flag through `plant_sizing.py`.
Missing periods or off/unverified sizing mark simulation unready without changing
controls/periods. This conservative guard is not a prediction of zero/failure:
some fixed-flow cases size with the flag off, whereas requesting sizing without
periods fails. Unrelated inherited Autosize does not trigger a whole-model audit.

## Preservation, readiness and validation

Impact reports fuel, capacity/flow, curves/evaluation, PLRs, flow mode, limits,
factor, EMS and other boilers. Retained curves warn about runtime shape/domain.
OpenStudio 3.11 can omit a configured curve with an unset evaluation variable,
even for a one-variable curve. Impact identifies this; it warns and marks
simulation unready without repair. Missing pump/outlet setpoint behaves likewise.
EMS/dispatch can override operation; curves/controls are not certified.

Only requested setters run. Every unrequested boiler field, metadata/reference,
node/connection and other model object remains protected. Requested numbers permit
tight serialization tolerance; all other raw/translated fields, identities,
hashes, fresh-plan equality and snapshots stay exact. Independent translation
checks requested and preserved values. Malformed/mismatched source translation
is an ordinary unready result; unexpected execution retains failure reporting.

Boolean `simulation_ready` with `operation_and_companions` combines known blockers;
other operations retain their scope. True is not a simulation certificate. Shared
preparation/publishing rules preserve source bytes and create a new OSM plus
`<stem>/`; retain both and attach its workflow when `requires_companion_workflow`.
Sizing/simulation remains separate.

## Trace and evidence

Creation policy: `Prototype.BoilerHotWater.rb:22–119`; template/rating conversions:
`Standards.BoilerHotWater.rb`. No recipe is reapplied. See the pinned
[boiler reference](https://bigladdersoftware.com/epx/docs/25-2/input-output-reference/group-plant-equipment.html#boilerhotwater),
work guide and phase-12 summary for native evidence and limitations. Annual energy,
other fuels and all dispatch arrangements are not certified. Fuel/flow/factor/
curve/control redesign, replacement and cleanup remain separate operations.
