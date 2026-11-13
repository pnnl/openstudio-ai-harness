# Plant topology — OpenStudio 3.11.0 / EnergyPlus 25.2

Use owning skill inventory → preflight → reviewed apply. Exact shared transaction,
preparation, cascade/snapshot/graph and companion checks remain.

## remove_unused_plants — openstudio-hvac-remover

```json
{"output_model_path":"/work/cleaned.osm","plant_loops":[{"name":"Unused HW"}]}
```

Run `scripts/remove_unused_plants.py`. Select unique names/handles; no implicit
cleanup/remove-all. Demand may contain only nodes/connectors/adiabatic pipes.
Zero coils is insufficient: profiles, water use, storage, heat exchangers and
nonadiabatic pipes are loads. Cross-loop equipment blocks even if both loops are
selected. Supply scope: simple constant/variable pumps, BoilerHotWater, district
water sources, unshared EIR chillers, variable-speed towers and adiabatic plumbing.
Other classes, steam, service water and heat pumps require separate coverage.

Review the SDK cascade/counts. Only selected topology, sizing/list/managers,
owned curves and metadata may disappear. Survivors/shared resources remain exact.
External references block. For raw object-list blockers, `referenced_by` identifies
the operation scheme to remove/reassign; resolve it separately. No ideal loads
or unserved-zone certification is added.

## replace_plant_equipment — openstudio-plant-equipment-replacer

```json
{
 "output_model_path":"/work/district.osm",
 "plant_loop":{"name":"HW"}, "equipment":{"name":"HW Boiler"},
 "target_class":"DistrictHeatingWater", "nominal_capacity_w":100000,
 "capacity_fraction_schedule":{"name":"Always On Discrete"},
 "reference_policy":"Reject"
}
```

Run `scripts/replace_plant_equipment.py`. Supported: Heating BoilerHotWater →
DistrictHeatingWater; Cooling ChillerElectricEIR → DistrictCooling. AirCooled or
consistently connected WaterCooled only; no heat recovery or reverse conversion.
Water-cooled sources require dedicated single-chiller condenser branches, without
series equipment. Capacity is positive useful thermal W or `Autosize`, not fuel/
compressor input; examples are not defaults. Existing fraction schedules require
SDK-compatible Dimensionless/nonnegative type limits. Missing/incompatible limits
are ordinary input errors; no schedule repair or upper-one clipping is inferred.

Source/connections get new identities; primary nodes, name and transferred metadata
remain. Direct/name-keyed references (EMS, costs, outputs, explicit schemes) block.
Component-setpoint dispatch rejects after a native zero-cooling probe; redesign
controls separately. Other translated controls and all new district fields are
checked after saving. Unselected objects/shared curves stay exact; private curves
actually deleted appear in the cascade. Only the new source is role-mapped.

Condenser branch/private nodes are removed; its plant/supply remain. Review remaining
demand count. At zero, fixed-flow equipment may consume idle energy or autosized
equipment may size to zero. Convert-and-stop is not native-validated. Review controls
or a separate explicit 13a cleanup; never infer deletion.

District dispatch ignores schedule fraction; delivery uses it. Temperature
protection can override zero. Flow, pump energy, dispatch and sized results can
change despite preserved inputs. Upstream district losses/utility factors are
unmodeled: lower site fuel/electricity is not efficiency savings. Check demand
and unmet load separately.

Explicit Autosize without verified sizing periods/controls, or a missing selected-
plant pump/outlet setpoint, warns and marks simulation unready without repair.
Fixed capacity can cause unmet load; no flow resizing/equivalence is inferred.
Keep OSM and `<stem>/` together; saved validation is not simulation certification.
