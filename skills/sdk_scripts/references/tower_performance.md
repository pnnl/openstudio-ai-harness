# Variable-speed cooling-tower performance contract

Edit one existing supply-side `CoolingTowerVariableSpeed` on a `Condenser` plant
using built-in CoolToolsCrossFlow or YorkCalc. An empty SDK model-type field
retains its pinned EnergyPlus YorkCalc default without writing a new type. Inventory and preflight use the same
scope. SingleSpeed, TwoSpeed, Merkel, user-defined thermal models, fluid coolers,
demand-side equipment and class replacement need separate coverage.

```json
{
  "output_model_path": "/work/edited.osm",
  "plant_loop": {"name": "Condenser"},
  "tower": {"name": "Selected Tower"},
  "settings": {"design_fan_power_w": 500}
}
```

500 W is an example, not a default. `design_fan_power_w` accepts positive finite
watts or exactly `"Autosize"`; missing settings/selectors stay unready and no-ops
reject. Selectors contain a unique name or handle. Power is total fan electrical
input at design airflow for all cells, not per-cell power, motor hp or shaft power.
No inferred watts, gpm/hp compliance, motor efficiency or percentage baseline.

The power path calls `setDesignFanPower` or, only on explicit request,
`autosizeDesignFanPower` on the existing object. Identity/name, metadata and incoming
EMS/cost/output references, water boundaries and plant graph remain unchanged.
All unrequested fields and other model objects are protected, including water/air
flow inputs and Autosize flags, thermal model/coefficient inputs, fan curve, unrequested minimum
flow ratio/free convection, cells/staging, basin heater, evaporation/drift/blowdown,
sizing factor, setpoints and dispatch. Only explicitly requested fields are excluded from the
tower raw fingerprint. Tight numeric serialization tolerance applies to the chosen
value; source/resource hashes, reviewed/fresh equality, types/handles, protected
snapshots and all other raw/translated fields remain exact. Apply publishes a new
OSM plus `<stem>/` companions without changing the source.

Impact lists both power modes, design flows, the airflow-sizing coupling, thermal
model, retained curve or implicit cubic behavior, design wet bulb/approach/range,
minimum airflow/free-convection settings, evaporation mode, condenser design ΔT,
tower count and bounded EMS context.
Missing existing pump/outlet setpoint or companions blocks simulation readiness
without silently repairing the model or blocking a rating edit. Explicit
`simulation_readiness_scope: operation_and_companions` opts into combined readiness;
other operations are unchanged. True means no identified blocker, not a plant audit.
An unset source power or source power/curve translation inconsistency returns an
ordinary unready plan error; unexpected SDK/program failures keep the normal failure-reporting path.

**Preserved sizing inputs do not imply preserved design airflow.** Autosized
flow follows design fan power with altitude correction, including free-convection
flow. The supported tower correlations use airflow ratios: this change alone does
not imply altered thermal performance or chiller/pump energy. With SaturatedExit,
absolute airflow enters evaporation, affecting make-up water. Native tests verify
unchanged temperatures, cooling and chiller/pump energy and scaled tower fan energy.
Airflow-based metrics must be recalculated using the newly reported design airflow
rather than treating the original airflow as fixed.

Fan power Autosize is 0.0105 × rho × Cp × tower design water volume flow × condenser
loop design ΔT, using the engine's sizing-condition fluid properties. It is not a
direct multiplier on chiller design load. Chiller COP affects this sizing chain
through autosized tower water flow; fixed tower water flow and unchanged fluid
properties/ΔT leave the power result unchanged by COP. The fixed-water native case
(0.005 m³/s, 5 K) checks approximately 1.10 kW. Other sizing inputs remain untouched;
no whole-plant/annual savings guarantee is made.

Local standards trace: `Standards.CoolingTowerVariableSpeed.rb:10–12` delegates to
`Standards.CoolingTower.rb:22–161`, which derives motor input from flow/rating
criteria and sets design fan power while leaving flow sizing intact. This editor
accepts explicit watts/Autosize for power, without selecting a standard or motor.
`Prototype.CoolingTower.rb:9–104` sets thermal design and condenser reset policy;
design conditions and reset policy are preserved, not applied by this editor. See the pinned
[EnergyPlus 25.2 variable-speed tower reference](https://bigladdersoftware.com/epx/docs/25-2/input-output-reference/group-condenser-equipment.html#coolingtowervariablespeed)
and the work guide for native fixed/autosized-airflow comparisons and limitations.


## Explicit Autosize readiness (F2)

For an explicit Autosize request, shared `common/plant_sizing.py` reports design-day
and sizing-period counts, whether the model flag is defaulted, its explicit value
if any, and the actual translated `SimulationControl` plant-sizing flag. It reads
the existing translation rather than translating twice or materializing a missing
model control. Configure sizing periods and plant sizing before simulation.
Missing periods, off or unverified effective sizing leave the edit ready but mark
`simulation_ready: false`; no simulation-sizing controls or design days are changed.

This is a conservative readiness policy, not a claim that EnergyPlus always fails
or returns zero with sizing off. Native fixed-flow cases can calculate positive
sizes without a plant-sizing run. With sizing requested but no design periods,
the tested models fail before simulation. This check covers the explicit Autosize
setting in this skill, not every inherited Autosize field elsewhere in the model;
true remains absence of identified blockers, not whole-model certification.


## Low-load operation (12g)

`settings` may contain one or more of `design_fan_power_w`,
`minimum_air_flow_ratio` and `free_convection_capacity_fraction`.
The two control fields are finite dimensionless numbers: respectively 0.2–0.5
and 0–0.2 inclusive, as enforced by the pinned EnergyPlus model. They do not
accept Autosize. Example: `{"minimum_air_flow_ratio": 0.3}` edits only that
control; 0.3 is not a recommended default. Empty/missing choices stay unready,
invalid values reject and a combined no-op rejects. The user supplies a justified
manufacturer/performance assumption, not a desired savings percentage.

Explicit setters update the existing tower without rewiring or replacing it.
Unrequested fan power/Autosize, the other control, thermal design conditions,
model, curves, sizing factor, cells/staging, water losses, plant controls and all
identities remain exact. Before/after values retain fan power and include requested
controls; `parameters.settings` contains only the request. Legacy report shape
remains unchanged for power-only requests.
`impact.low_load_controls` records selected controls before/after, their limits
and the retained configured/implicit fan-curve policy. No generic power floor is
inferred from the airflow setting. Translation must preserve edited values and
all other translated fields; malformed or mismatched source controls return an
ordinary unready plan error. All exact transaction, source, resource and companion
protections continue to apply.

Minimum airflow ratio is the minimum modulating fan-on ratio. If minimum-speed
cooling exceeds demand, EnergyPlus cycles the fan between minimum speed and fan
off; the average reported airflow ratio can be below the entered floor. Fan power
uses the retained configured curve or implicit cubic, weighted by cycling/cells.
Changing the minimum ratio changes reported free-convection design airflow
(minimum ratio × design airflow), even with unchanged design-airflow input.

Free convection estimates fan-off cooling as the chosen fraction of the current
full-speed water-temperature drop. Runtime fan-off airflow ratio reporting uses
that fraction, whereas the free-convection design airflow above uses minimum
ratio. It is not an annual free-cooling fraction, a literal minimum fan speed,
or guaranteed savings. Fan-off water can fall below setpoint and condenser pumps
can still run. Native output `Cooling Tower Fan Part Load Ratio` corresponds to
fan cycling for this tower class; `Cooling Tower Fan Cycling Ratio` belongs to
other tower classes and is not its output name.

Low-load control changes can affect water temperatures, heat rejected, chiller
energy and make-up water as well as tower electricity. Preserve upstream equipment
and assess the coupled results; higher free convection need not help under every
load/control arrangement. This extension does not calibrate or certify the thermal
correlation or choose approach/range, fan curves or staging.

A controls-only request retains even an inherited Autosize fan-power field without
adding a whole-model plant-sizing audit. The existing conservative setup guard
runs only for an explicit `design_fan_power_w: "Autosize"` request. Simulation
remains separate and `simulation_ready` means no identified operation/companion
blocker, not a guarantee of annual or low-load performance.

Standards trace: `Prototype.hvac_systems.rb:593–598` constructs the variable-speed
tower, sets range/approach and free-convection fraction 0.125, then assigns the
fan curve. This editor leaves that recipe choice unchanged unless the user
explicitly requests an edit. Pinned `CondenserLoopTowers.cc` validates the two
control ranges, models fan-off outlet temperature and minimum-speed cycling in
`calculateVariableSpeedTower`, and derives free-convection design flow during
sizing. No Ruby recipe is executed by the independent editor.


### Blank source controls (H1)

For a blank/reset control field, EnergyPlus 25.2 applies 0.2 minimum airflow ratio
or 0.125 free-convection capacity fraction even though the OpenStudio optional
getter is empty. Before-values and context use these effective defaults, and
`source_control_defaults` explicitly identifies requested blank fields and their
values. Preflight reads no values into the source model. Only requested setters
write values; an unrequested blank stays blank under the exact raw fingerprint.
Translation resolves blank controls through its EnergyPlus IDD defaults. Nonblank
malformed translation still rejects; unset fan power does not gain a fallback.
A request equal to the effective default is still a no-op, with the default
provenance retained in the blocked plan. Different explicit values can proceed.
