# Variable-speed cooling-tower fan-power contract

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

The transaction calls `setDesignFanPower` or, only on explicit request,
`autosizeDesignFanPower` on the existing object. Identity/name, metadata and incoming
EMS/cost/output references, water boundaries and plant graph remain unchanged.
All unrequested fields and other model objects are protected, including water/air
flow inputs and Autosize flags, thermal model/coefficient inputs, fan curve, minimum
flow ratio, free convection, cells/staging, basin heater, evaporation/drift/blowdown,
sizing factor, setpoints and dispatch. Only Design Fan Power is excluded from the
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
only accepts explicit watts/Autosize, without selecting a standard or motor.
`Prototype.CoolingTower.rb:9–104` sets thermal design and condenser reset policy;
those policies are preserved, not applied by this rating editor. See the pinned
[EnergyPlus 25.2 variable-speed tower reference](https://bigladdersoftware.com/epx/docs/25-2/input-output-reference/group-condenser-equipment.html#coolingtowervariablespeed)
and the work guide for native fixed/autosized-airflow comparisons and limitations.


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
