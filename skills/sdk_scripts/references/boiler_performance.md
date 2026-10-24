# Hot-water boiler performance and capacity — phases 12a / 12e

Operation `edit_boiler_performance`, exact OpenStudio 3.11.0 / EnergyPlus 25.2.
One existing BoilerHotWater on a heating plant supply side. This is an in-place
performance/capacity edit, not fuel/class conversion or plant-control redesign.

```json
{
  "output_model_path": "/work/boiler-edited.osm",
  "plant_loop": {"name": "HW"},
  "boiler": {"name": "Selected Boiler"},
  "settings": {
    "nominal_thermal_efficiency": 0.9,
    "on_cycle_parasitic_electric_load_w": 100,
    "off_cycle_parasitic_fuel_load_w": 15
  }
}
```

Numbers above illustrate explicit input, not recommended assumptions. Choose
only the requested fields. Selectors accept a unique name or handle; missing
selectors/settings remain unready. Empty/no-op settings do not produce a ready
plan. No profile defaults or implicit sizing resets are inserted. Phase 12e adds
explicit `nominal_capacity_w` as positive useful thermal output watts or exactly
`"Autosize"`. Omit it to retain capacity and its sizing policy exactly; the existing
rating-only request and report value sets remain unchanged.

| Field | Units and meaning | Scope |
| --- | --- | --- |
| nominal_capacity_w | Positive finite thermal output watts or `"Autosize"` | Explicit capacity policy; preserve flow policy and all sizing/control fields |
| nominal_thermal_efficiency | HHV-based fraction, >0 and ≤1 | Nominal rating; retained normalized curve can multiply it |
| on_cycle_parasitic_electric_load_w | Nonnegative rated watts | Active rate = input × PLR, zero when idle; not useful water heat |
| off_cycle_parasitic_fuel_load_w | Nonnegative configured watts; zero for Electricity | Active calculation updates input × (1 − PLR); last rate persists while idle |

EnergyPlus supports special nominal efficiencies above one, but that special-use
range is outside this initial schema. An existing out-of-range rating is preserved
when editing another field; no implied normalization occurs. AFUE, combustion or
LHV efficiency is not interchangeable with the nominal HHV rating. Resolve the
rating basis before input. The pinned
[EnergyPlus boiler reference](https://bigladdersoftware.com/epx/docs/25-2/input-output-reference/group-plant-equipment.html#boilerhotwater)
defines rating and curve inputs. The pinned
[Boilers.cc source](https://github.com/NatLabRockies/EnergyPlus/blob/v25.2.0/src/EnergyPlus/Boilers.cc)
controls the following parasitic behavior, which is more specific than the generic
off-cycle description in the input reference:

- A newly requested positive off-cycle fuel load on an electric boiler is unready:
  EnergyPlus warns and resets its internal value to zero, despite the OSM/IDF value.
  Existing nonzero values warn and remain stored on unrelated edits; impact records
  ignored-before/after and effective input zero. This warning does not block
  simulation: EnergyPlus treats the input as zero. An explicit user-chosen zero
  can clear the stored value; no automatic reset occurs.
- During active calculation (positive requested load and run flag), ancillary fuel
  rate is configured off-cycle watts × (1 − PLR). The idle path does not reset it:
  it retains the last computed rate, even in later summer periods, or zero if it
  has never been updated. It is not a constant idle standby-load model. There is
  no zero clamp when PLR exceeds one; a retained maximum above one warns.
- On-cycle ancillary electric rate is configured watts × operating PLR while the
  boiler supplies heat, and is reset to zero on idle paths. Both ancillary energy
  outputs are metered under Heating with subcategory `Boiler Parasitic`; inspect
  `Boiler Ancillary <fuel> Rate/Energy` separately from the boiler's main fuel.


Inventory lists boiler classes on plant supply sides and flags BoilerHotWater
support only when the loop type is Heating, matching preflight. Steam/detached/
demand-side boilers and nonheating plants (including Condenser) do not qualify.
Impact records fuel, fixed/Autosize capacity and flow, curve reference/type and
temperature-variable field, part-load ratios, flow mode, outlet limit, sizing
factor, EMS and other boiler count. A retained curve warns that runtime efficiency
depends on its shape/domain; this edit does not certify its envelope or clipping.
Impact separately records whether EnergyPlus translation retains the curve. On
3.11.0 a configured curve can be omitted when its temperature-evaluation field
is unset, even for a one-variable curve. Such a model warns and is simulation
unready; this operation preserves both fields rather than silently repairing them.
Retained EMS and dispatch can override when the selected boiler runs. Missing
identified supply pump or supply-outlet setpoint warns and marks simulation
unready while allowing the scoped rating edit; it never creates plant equipment.

Fuel, name/class/handle, unrequested capacity and flow sizing states, PLRs, curve and
temperature evaluation, limits, parasitics not requested, sizing factor, end-use
label, plant operation/dispatch, schedules and all other raw fields are retained.
Only requested setters execute on the original object. Metadata, cost/EMS/output
references, air/water equipment, water nodes and connection handles stay intact.

The reviewed report binds exact source/resource hashes and fresh-preflight equality.
Saved checks verify the three rating values and explicitly requested capacity
with serialization tolerance,
unrequested boiler raw fields, every protected model object and identity, component
order and inlet/outlet service. The translator independently checks all three
rating inputs and explicit numeric/Autosize capacity plus all other translated
boiler fields. Unrequested capacity stays in the exact raw/translated protection. Raw mismatches
fail before translation. Common preparation/companion publishing rules apply.
The source is unchanged; output is a new OSM and `<stem>/` companion directory.
Boiler plans always contain boolean `simulation_ready`. A ready plan combines
known operation and companion-file blockers by explicitly setting
`simulation_readiness_scope: operation_and_companions`. Other operations retain
their existing operation-only flags. True means no known blocker found, not a
simulation or performance certification. Unready input plans report false.
Keep both together and attach its workflow when `requires_companion_workflow`.

Local standards trace: `Prototype.BoilerHotWater.rb:22–119` selects fuel, nominal
efficiency, flow/temperature policy, PLRs and sizing, with version-specific design
temperature handling before OpenStudio 3.0. `Standards.BoilerHotWater.rb` contains
template/rating conversions and efficiency-curve policy. Those creation/standards
defaults are not reapplied by this edit. Existing plant creation is composed
through `common/plant_create.py`; performance editing is independent.

This checkpoint makes no annual-energy, comfort, sizing or compliance claim.
Boiler flow, sizing factor, part-load/control/curve changes, true replacements and
unused-plant cleanup remain separate work. The district editor owns district
capacity, and chiller/tower editors retain their independent contracts. Reheat-terminal
conversion remains on the equipment backlog, not silently folded into this phase.


## Explicit boiler capacity (phase 12e)

Use `"settings": {"nominal_capacity_w": 20000}` for an explicit thermal-watt target,
or `"nominal_capacity_w": "Autosize"` for a chosen sizing policy. This may be
combined with independently chosen supported rating/parasitic fields. Booleans,
zero, negative/nonfinite values and alternate strings reject; no-op requests remain
unready. Source translation inconsistencies are normal unready errors rather than
unexpected-failure submissions. Old plans require fresh preflight.

EnergyPlus 25.2 `Boilers.cc:126–134` exposes nominal capacity × retained minimum,
maximum and optimum PLRs to load-based dispatch. A capacity edit can move loads
between sources while preserving operation-scheme inputs. A maximum PLR above 1
permits output above nominal; do not treat nominal watts as an unconditional cap.
The plan reports these three dispatch loads, current scheme and before/after
capacity. Actual heat depends on flow, outlet limit, controls and retained faults.

`Boilers.cc:599–610` sizes capacity from design plant volume flow × fluid density
× specific heat × plant design ΔT × retained boiler sizing factor. Fluid properties
are evaluated at `HWInitConvTemp` (60 °C, `DataGlobalConstants.hh:616`), which can
differ from the property basis of the plant's reported design capacity. Native
fixture sizing is 68,578.2 W for factor 1.5 and 45,718.8 W for factor 1.0.
`Boilers.cc:659–717` independently sizes boiler water flow from design plant flow ×
sizing factor; this editor preserves both that input policy and any fixed flow.
A fixed capacity edit does not infer a matching flow or plant redesign.

`Boilers.cc:869–904,1007–1010` ties realized PLR, efficiency-curve inputs and
ancillary loads to capacity. A capacity-only change can alter fuel and ancillary
energy at unchanged delivered heat. In locked-flow running calculation, minimum PLR can impose an output floor
above the assigned load; increasing capacity raises this floor. Minimum/maximum
PLRs and low-load controls must be reviewed; retained off-cycle fuel still carries its last active rate when idle.
Reduced metered heating from undersizing is not an efficiency saving. This bundle
does not model a physical boiler replacement, repair controls, infer pump savings
or certify the retained curve's domain.

Native checks cover capacity-dependent PLR/ancillaries with and without a curve,
explicit Autosize with retained flow and independently verified sizing factor,
output above nominal at retained maximum PLR 1.2, and load shifting to a retained
backup under SequentialLoad. They use design days and NaturalGas; other fuel
classes have saved/translated identity checks, not new annual/native savings claims.


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

On multi-boiler loops, each autosized boiler uses the whole plant design load times
its own sizing factor; capacity is not automatically split among sources. Impact
lists other boiler capacities (numeric or Autosize) and factors, up to eight with
total/omitted counts. Unsupported boiler classes have null sizing details. Review
factors and installed capacity explicitly; no division or factor reset is inferred.
`impact.nominal_capacity_w` consistently means the current/source value; use
`capacity_edit.before_w/after_w` for the proposed change.
