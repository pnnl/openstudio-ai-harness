# Hot-water boiler performance edit — initial phase 12a

Operation `edit_boiler_performance`, exact OpenStudio 3.11.0 / EnergyPlus 25.2.
One existing BoilerHotWater on a heating plant supply side. This is an in-place
performance edit, not fuel/class conversion, sizing or plant-control redesign.

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
plan. No profile defaults or sizing resets are inserted.

| Field | Units and meaning | Scope |
| --- | --- | --- |
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

Fuel, name/class/handle, capacities/flow and their sizing states, PLRs, curve and
temperature evaluation, limits, parasitics not requested, sizing factor, end-use
label, plant operation/dispatch, schedules and all other raw fields are retained.
Only requested setters execute on the original object. Metadata, cost/EMS/output
references, air/water equipment, water nodes and connection handles stay intact.

The reviewed report binds exact source/resource hashes and fresh-preflight equality.
Saved checks verify all three performance values with serialization tolerance,
unrequested boiler raw fields, every protected model object and identity, component
order and inlet/outlet service. The translator independently checks all three
numeric EnergyPlus inputs plus all other translated boiler fields. Raw mismatches
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
Broader boiler controls/curves/sizing, true replacements, chillers/towers/district
equipment and unused-plant cleanup remain separate work. Reheat-terminal
conversion remains on the equipment backlog, not silently folded into this phase.
