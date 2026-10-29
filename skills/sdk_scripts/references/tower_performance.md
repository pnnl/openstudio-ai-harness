# Variable-speed cooling-tower performance contract

One existing supply CoolingTowerVariableSpeed on a Condenser plant, with built-in
CoolToolsCrossFlow or YorkCalc. Empty model type retains EnergyPlus 25.2's YorkCalc
default without writing it. OpenStudio remains pinned to 3.11.0. Inventory matches
preflight; SingleSpeed/TwoSpeed/Merkel/user-defined models, fluid coolers, demand-side
equipment and class replacement need separate coverage.

```json
{
  "output_model_path":"/work/edited.osm",
  "plant_loop":{"name":"Condenser"},
  "tower":{"name":"Selected Tower"},
  "settings":{"design_fan_power_w":500}
}
```

Choose unique names/handles and one or more explicit settings. Missing choices
stay unready; invalid/empty/no-op requests reject. Examples are not defaults or
savings targets; obtain manufacturer/performance assumptions.

| Setting | Accepted input |
| --- | --- |
| design_fan_power_w | Positive finite total electrical W for all cells, or exactly `Autosize` |
| minimum_air_flow_ratio | Finite dimensionless 0.2–0.5 inclusive |
| free_convection_capacity_fraction | Finite dimensionless 0–0.2 inclusive |

Power is not per-cell, motor hp or shaft power. No inferred efficiency, compliance
rating, percentage baseline or generic power floor. Ratios do not accept Autosize.
Before/after values include power plus requested controls; `parameters.settings`
contains only requested fields. Power-only report shape remains unchanged.
`impact.low_load_controls` gives selected controls before/after, valid limits and
retained configured/implicit fan curve.

## Physical interpretation

Minimum airflow ratio is the minimum **modulating fan-on** ratio. When that
speed overcools, EnergyPlus cycles between minimum speed and fan off, so average
reported airflow can be below the entered floor. Power follows the retained curve
or implicit cubic, weighted by cycling/cells. Minimum ratio × design airflow also
sets reported free-convection **design** airflow.

Free-convection capacity is the fraction of current full-speed water-temperature
drop used to estimate fan-off cooling. Runtime fan-off airflow reporting uses that
fraction, whereas design free-convection airflow uses minimum airflow ratio. It
is not annual free cooling, literal fan minimum speed or guaranteed savings.
Fan-off water can fall below setpoint and pumps can still run. For this class,
`Cooling Tower Fan Part Load Ratio` reports fan cycling; `Cooling Tower Fan Cycling
Ratio` is an output for other classes.

Control edits can change heat rejection, temperatures, chiller energy, electricity
and make-up water. Higher free convection need not help under every control/load
arrangement. This operation does not calibrate thermal correlations or choose
approach/range, staging or curves.

**Power-only edits with airflow on Autosize** change calculated design airflow
(altitude-adjusted), including free-convection flow. The supported thermal models
use airflow ratios; changed absolute design airflow alone does not imply changed
thermal performance or chiller/pump energy. Under SaturatedExit, absolute airflow
enters evaporation and can change make-up water. Native evidence verifies unchanged
temperatures/cooling/chiller/pump energy and scaled tower electricity. Recalculate
airflow-based metrics using the new reported airflow; retained input sizing flags
do not promise unchanged sized results.

Fan power Autosize is 0.0105 × density × Cp × tower design water volume flow ×
condenser-loop design ΔT, using engine sizing fluid properties. It is not directly
chiller load × a factor. COP affects the chain through autosized tower water flow;
with fixed water flow/fluid/ΔT it does not change fan Autosize. The fixed-water
native case (0.005 m³/s, 5 K) gives about 1.10 kW.

## Blank controls and sizing readiness

For genuinely blank/reset control fields the pinned EnergyPlus IDD applies 0.2
minimum airflow ratio and 0.125 free-convection fraction, despite empty SDK getters.
Before/context values use these effective defaults. `source_control_defaults`
identifies requested blank fields and provenance. Preflight does not write them;
only selected setters execute, and an unrequested blank remains blank under the
exact fingerprint. Translation reads IDD defaults only for blank controls.
Default-equivalent requests remain no-ops with provenance in the unready plan.
Malformed nonblank translation rejects; unset fan power gets no fallback.

Only an explicit power `Autosize` invokes shared plant-sizing readiness: design-day/
period counts, defaulted/explicit model flag and actual translated SimulationControl
flag. Missing periods or off/unverified sizing permit editing but mark simulation
unready; no sizing controls or periods change. This is conservative, not a guarantee
of failure/zero size: some fixed-flow cases size positively with the flag off;
tested cases requesting sizing without periods fail. Controls-only edits retain
inherited Autosize without starting a whole-model audit.

## Preservation and validation

Setters update the original tower without rewiring. Name/class/handle, metadata,
EMS/cost/output references, water boundaries and graph remain. All unrequested
fields remain exact, including flows and sizing flags, thermal model/coefficient
inputs, fan curve, other controls, factor, cells/staging, basin heater, evaporation/
drift/blowdown, plant setpoints and dispatch. Impact reports power/flow modes,
sizing coupling, curve/implicit cubic, wet bulb/approach/range, minimum airflow,
free convection, evaporation mode, condenser ΔT, tower count and bounded EMS.

Only requested fields are excluded from the raw fingerprint; chosen numbers use
tight serialization tolerance. Source/resource hashes, reviewed/fresh equality,
object identities, protected snapshots and all other raw/translated fields remain
exact. Translation verifies chosen settings and preserved fields. Unset source power
or malformed/mismatched source translation yields ordinary unready errors; unexpected
SDK/program failures retain failure reporting.

Missing pump/outlet setpoint or companions marks simulation unready without
repairing equipment or blocking a scoped edit. Scope `operation_and_companions`
combines known blockers; other operations are unchanged. True is no identified
blocker, not a run/whole-plant certificate. Preparation and companion rules apply;
new OSM and `<stem>/` are published without modifying source. No annual or plant
savings claim is implied by a saved/translated result.

## Trace and evidence

Creation: `Prototype.CoolingTower.rb:9–104`, `Prototype.hvac_systems.rb:593–598`.
Rating: `Standards.CoolingTowerVariableSpeed.rb:10–12`, `Standards.CoolingTower.rb:22–161`.
No recipe is reapplied. Pinned `CondenserLoopTowers.cc::calculateVariableSpeedTower`
implements fan-off cooling/cycling. See the [tower reference](https://bigladdersoftware.com/epx/docs/25-2/input-output-reference/group-condenser-equipment.html#coolingtowervariablespeed)
and work guide for native evidence and design-flow coupling.
