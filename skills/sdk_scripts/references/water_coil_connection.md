# Main-supply water-coil attachment, plant migration and air relocation

`connect_water_coil.py` inventories, preflights and applies copied outputs.
Use absolute input/config/report paths and new output/report names. Schema:
[water_coil_connection.schema.json](water_coil_connection.schema.json).

Heating attachment example; optional `design` values below are nominal-rating
metadata, not UA design conditions. Omit that group when no rating metadata was
requested. Every explicit choice must reflect user intent:

```json
{
  "output_model_path": "/absolute/path/attached.osm",
  "operation": "attach",
  "kind": "Heating",
  "air_loop": {"name": "Office Air Loop"},
  "air_node": {"name": "Office Supply Outlet"},
  "plant_loop": {"name": "Office HW"},
  "coil_name": "Added Water Heating Coil",
  "availability_schedule": {"builtin": "AlwaysOnDiscrete"},
  "sizing": "Autosize",
  "design": {
    "rated_inlet_water_temperature_c": 82.2,
    "rated_outlet_water_temperature_c": 71.1,
    "rated_inlet_air_temperature_c": 16.6,
    "rated_outlet_air_temperature_c": 32.2
  },
  "controller": {
    "control_variable": "Temperature",
    "minimum_flow_m3_s": 0,
    "convergence_tolerance_k": 0.1
  }
}
```

Names/handles select exactly one object. The loop must have one unsplit main supply
path; `air_node` must be that loop's **supply outlet**, have an incoming connection, and already have
a Temperature setpoint manager. The new coil is inserted immediately upstream;
its air outlet remains that node. Other nodes insert downstream and are rejected
at preflight, including interior nodes with Temperature setpoint managers.
Inventory flags supported attachment nodes and exposes each loop's outlet.
Choose the system deliberately: this operation
preserves existing sizing, fan, terminals and other coils rather than making an
arbitrary system arrangement adequate.

The plant must match Heating/Cooling, have supply equipment, an actual pump and an
outlet setpoint manager, with finite supply temperature and positive design delta.
Existing demand branches remain intact, including when adding the first demand
component. No plant is created. Availability is an existing schedule with
Availability type limits, or explicit builtin `AlwaysOnDiscrete`/
`AlwaysOffDiscrete`. Coil names must be unique. Missing choices remain unready.

Heating attachment uses `UFactorTimesAreaAndDesignWaterFlowRate` with autosized
UA, maximum water flow and capacity. The four `rated_*_temperature_c` fields in
`design` are optional nominal-rating metadata; omitting `design` is valid for
Heating. Missing values retain the pinned SDK defaults, shown in the plan's
`after_values` and `rating_usage.defaulted_rating_fields`. They do **not** set the
UA coil's design point. Plant and air-system sizing govern autosizing; the plan
shows their existing temperatures in `rating_usage.sizing_context`. Do not ask the
user to supply unused rated temperatures as operating design conditions.
The full `assumption_review` and bounded `impact.rating_usage` explain this role.
EnergyPlus still validates input temperature relationships, so invalid metadata
is rejected; plant-versus-rated-temperature checks apply only to NominalCapacity.

Cooling attachment requires `design_inlet_water_temperature_c`,
`design_inlet_air_temperature_c`, `design_outlet_air_temperature_c`,
`design_inlet_air_humidity_ratio`, `design_outlet_air_humidity_ratio`,
`heat_exchanger_configuration` (`CrossFlow`/`CounterFlow`) and `type_of_analysis`
(`SimpleAnalysis`/`DetailedAnalysis`). Cooling design numbers may explicitly be
`"Autosize"`; water/air flow are autosized. Design relationships and plant warnings
follow the [edit contract](water_coil_edit.md). Flow/capacity fields in `design` reject rather than
silently overriding user choices. Manual sizing needs separate coverage. For system
design-day sizing, prefer explicit
Autosize for cooling air temperatures/humidity unless the user supplies fixed
design conditions. Fixed conditions override that part of autosizing and change
coil capacity; review their suitability for the selected outdoor-air strategy.

Controller choices are explicit: Temperature control, minimum flow 0, numeric
positive convergence tolerance or `"Autosize"`; maximum flow is autosized. Heating
uses Normal action, cooling Reverse; the actuator is Flow. Finalization runs after
both connections, setting sensor to air outlet and actuator to water inlet. This
is dry-bulb temperature control, without humidity-control/setpoint creation.

Existing coil ratings, name, availability, Autosize resets and controller settings
use the in-place editor. `operation: replace` is rejected by both public schemas.
The same-class clone/reconnect primitive remains unexported. Genuine heating-water
to electric conversion uses `openstudio-coil-replacer` with explicit performance,
outlet-control and reference choices.
Plant migration uses the existing objects rather than cloning their identities.

Attachment previews native topology in an isolated handle-preserving model copy.
Only graph-link changes and connector extensions may differ; expected additions
and removals are recorded. Saved checks independently verify exact supply order,
plant ownership/supply order, existing demand components, protected raw fields,
original identities, object deltas, rating getters and controller nodes/settings.
No OA-stream, unitary, terminal, coil-class conversion
or plant-supply attachment is covered. Previously absent weather metadata may be populated from the companion EPW;
its fields are checked independently against that hash-bound resource. Existing
climate metadata stays protected. Saved validation and EnergyPlus translation
are required before publication; sizing/simulation is a separate workflow.

## Move an existing coil to another plant

```json
{
  "output_model_path": "/absolute/path/migrated.osm",
  "operation": "migrate_plant",
  "coil": {"name": "Office Main Heating Coil"},
  "plant_loop": {"name": "New Office HW"},
  "sizing": "Autosize"
}
```

Select an existing direct main-supply CoilHeatingWater or CoilCoolingWater on an
unsplit air loop and a different, existing destination plant of the same kind.
Missing selectors or sizing choice remain unready. The source must have a
dedicated single-coil demand branch: serial pipes/equipment are rejected because
the SDK removes the entire selected branch. Both source and destination must use
Water without glycol. The destination must satisfy the attachment plant checks.
The source is retained; existing deficiencies remain warnings with simulation
readiness false. Coil/plant temperature relationships use the existing rating
checks, including the informational role of heating UA rated temperatures.

`sizing: Autosize` explicitly resets heating capacity/UA/maximum water flow or
cooling design air/water flow, plus controller maximum flow. All other ratings,
names, availability and controller scalar settings are retained. The current
controller must use Temperature/Flow, Normal (heating) or Reverse (cooling) action,
and zero minimum flow. Custom sensor/actuator locations need separate coverage.
Changing other settings belongs to the in-place editor before or after this move.

The impact reports `source_plant_remaining_coil_count`,
`source_plant_remaining_demand_equipment_count` and `source_plant_will_be_unserved`.
These counts exclude the migrated coil and passive nodes, connectors, pipes and
pumps. A plant serving no remaining coils produces a warning: its supply equipment
and pumps remain, including existing Autosize settings. Other demand equipment is
reported separately, so a plant still serving a heat exchanger or other load is
not called unserved. Review whether to retain it. `openstudio-hvac-remover` covers
supported HVAC cleanup but currently excludes plant deletion; cleanup of the plant
requires separate supported coverage and explicit intent.

`retained_water_rating_mismatches` identifies active fixed cooling inlet water
temperature or NominalCapacity heating inlet/outlet water rating temperatures that
differ from destination design conditions, with both values shown. The warning
names `openstudio-water-coil-editor` for an explicit follow-up change on the copied
output before sizing/simulation when needed. There is no automatic alignment to
plant temperatures: manufacturer ratings may deliberately differ. Heating UA
rated-temperature metadata is informational, and an Autosize cooling inlet water
temperature is not a retained fixed rating.

The plan shows both plant design temperatures, affected zones, sizing resets and
counts of removed water nodes/connections. Existing coil/controller handles,
air boundary nodes and air connections, metadata, EMS and cost references remain
stable. Native branch removal deletes the attached controller by default; the
script temporarily transfers its ownership within the unpublished transaction,
then restores the original controller and sets sensor to air outlet and actuator
to the new water inlet. No holding coil or disposable controller is published.
Water-node and demand connection handles can change, including connection records
for preserved source branches when the SDK compacts connector ports. Rerun later
plans/inventories; do not reuse those old water-node/connection handles. External
references to removed water nodes block preflight rather than being retargeted.

Preflight previews topology on a private handle-preserving clone. Only selected
coil water links, controller control-node links and the two plants' demand graph
links may change. Saved validation checks scalar getters, exact air order, both
plants' supply order/component membership, protected fields/identities/counts,
controller ownership/nodes, and the whole-model connection graph independently
of apply. Fresh-plan/hash checks, saved validation and translation run before
publication through the shared transaction. This does not size plants, change
air-system sizing or verify annual performance. Keep the copied output and its
companion directory together; request sizing separately.

## Relocate an existing coil on air supply

```json
{
  "output_model_path": "/absolute/path/relocated.osm",
  "operation": "relocate_air",
  "coil": {"name": "Office Main Cooling Coil"},
  "air_loop": {"name": "Destination Air Loop"},
  "air_node": {"name": "Destination Supply Outlet"},
  "sizing": "Autosize"
}
```

Select a direct main-supply heating/cooling water coil and an unsplit destination
loop's supply outlet. It can be the same loop if the coil is not already at that
outlet. The destination needs existing upstream equipment, an incoming connection
and a Temperature setpoint manager. Empty supply paths, interior/inlet destinations,
custom sensor/actuator locations and non-Temperature/Flow controller strategies
remain unready. Existing source-plant deficiencies are warnings with simulation
readiness false; its connections are not changed by this operation.

The old location merges into a single shared node: one interior air node is removed
to avoid adjacent nodes producing different EnergyPlus branch names. The destination
gets one new inlet node. External references to the source interior air nodes block
preflight; coil/controller references, including EMS and LifeCycleCost, are retained.
Review `impact.removed_air_node`, original/new air nodes, source/destination zone
counts and full affected-zone records. Supply order changes intentionally; source
and destination sizing, terminals, zone assignments and plant graph stay protected.

Heating capacity/UA/maximum water flow or cooling design air/water flow reset to
Autosize, as does controller maximum flow. Other ratings, schedule, metadata and
controller scalar values stay unchanged. `impact.before_control` / `after_control` show translated managers/reference nodes
and fan position. Moving a heating coil from before the fan to the supply outlet
changes draw-through to blow-through, and fan-compensated MixedAir tracking to
direct supply-outlet control. The change can alter cooling/heating sizing and
operation even when every rating is retained. These control fields are checked
independently after saving. The sensor follows the destination outlet;
its actuator remains the water inlet. Heating UA sizing context in the plan refers
to the destination air loop. Relocation does not guarantee either loop can still
meet its loads; size both systems and review their intended conditioning strategy.

Apply rewires explicit connections rather than calling `addToNode` on an already
connected coil. Saved independent checks cover both air paths, exact plant branch,
whole-model connection graph, retained identities/fields/settings, removed/new
objects and result mappings. Translation precedes publication; native design-day
tests additionally guard branch integrity because translation alone does not
detect adjacent-node branch errors.
