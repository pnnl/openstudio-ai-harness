"""Reviewed unused-plant removal and mechanical-to-district source conversion."""

from collections import Counter
import json
from pathlib import Path

from common.coil_topology import freeze, connection_graph, protected_state
from common.district_edit import translated_state
from common.hvac_equipment import call
from common.hvac_inventory import resolve
from common.input_validation import validate
from common.model_preservation import fingerprint
from common.plant_sizing import require_plant_sizing
from common.pump_class_replacement import controls
from common.water_coil import ref, raw_fields, original_types, object_by_ref

PASSIVE = {
    "OS_Node",
    "OS_Connector_Mixer",
    "OS_Connector_Splitter",
    "OS_Pipe_Adiabatic",
}
SOURCES = {
    "OS_Boiler_HotWater": ("BoilerHotWater", "Heating", "DistrictHeatingWater"),
    "OS_Chiller_Electric_EIR": ("ChillerElectricEIR", "Cooling", "DistrictCooling"),
}
CLEANABLE = PASSIVE | {
    *SOURCES,
    "OS_DistrictHeating_Water",
    "OS_DistrictCooling",
    "OS_Pump_ConstantSpeed",
    "OS_Pump_VariableSpeed",
    "OS_CoolingTower_VariableSpeed",
}


def demand(loop):
    return sorted(
        [
            ref(x)
            for x in loop.demandComponents()
            if x.iddObjectType().valueName() not in PASSIVE
        ],
        key=lambda x: x["handle"],
    )


def source_supported(obj, loop):
    info = SOURCES.get(obj.iddObjectType().valueName())
    if not info or info[1] != loop.sizingPlant().loopType():
        return False
    if info[0] != "ChillerElectricEIR":
        return True
    chiller = obj.to_ChillerElectricEIR().get()
    return (
        not chiller.heatRecoveryLoop().is_initialized()
        and chiller.condenserType() in ("AirCooled", "WaterCooled")
        and (chiller.condenserType() == "WaterCooled")
        == chiller.secondaryPlantLoop().is_initialized()
    )


def inventory(model):
    return dict(
        plant_loops=sorted(
            [
                dict(
                    ref(loop),
                    loop_type=loop.sizingPlant().loopType(),
                    demand_equipment=demand(loop),
                    supply_equipment=sorted(
                        [
                            dict(
                                ref(x),
                                replacement_supported=source_supported(x, loop),
                            )
                            for x in loop.supplyComponents()
                            if x.iddObjectType().valueName() not in PASSIVE
                        ],
                        key=lambda x: x["handle"],
                    ),
                )
                for loop in model.getPlantLoops()
            ],
            key=lambda x: x["handle"],
        ),
        schedules=sorted(
            [ref(x) for x in model.getSchedules()], key=lambda x: x["handle"]
        ),
    )


def base(config, schema, fields):
    schema = json.loads(
        (Path(__file__).resolve().parents[1] / "references" / schema).read_text()
    )
    errors = validate(config, schema)
    if errors:
        raise ValueError("Invalid plant operation configuration: " + "; ".join(errors))
    return dict(
        ready=False,
        simulation_ready=False,
        simulation_readiness_scope="operation_and_companions",
        parameters=dict(output_model_path=config["output_model_path"]),
        errors=[],
        warnings=[],
        assumptions=[],
        missing_inputs=[key for key in fields if not config.get(key)],
    )


def outside_references(model, removed, allowed=()):
    """Block dangling direct and name-keyed references; never rewrite EMS or costs."""
    names = {
        x.nameString().casefold()
        for x in model.modelObjects()
        if str(x.handle()) in removed and x.nameString()
    }
    result = [
        ref(x)
        for x in model.modelObjects()
        if str(x.handle()) not in removed
        and str(x.handle()) not in allowed
        and x.iddObjectType().valueName() != "OS_Connection"
        and any(
            name not in ("Name", "Handle")
            and value
            and (value in removed or value.casefold() in names)
            for name, value in raw_fields(x).values()
        )
    ]
    for item in result:
        if item["type"] == "OS_ModelObjectList":
            obj = next(
                x for x in model.modelObjects() if str(x.handle()) == item["handle"]
            )
            item["referenced_by"] = [
                ref(model.getModelObject(x.handle()).get()) for x in obj.sources()
            ][:8]
    return result


def scope(loop, model, sdk):
    objects = {
        str(x.handle()): x
        for x in [
            loop,
            loop.sizingPlant(),
            *loop.supplyComponents(),
            *loop.demandComponents(),
        ]
    }
    # Managers, lists, curves and metadata referenced by selected topology only.
    pending = list(objects.values())
    while pending:
        obj = pending.pop()
        for name, handle in raw_fields(obj).values():
            target = (
                model.getModelObject(sdk.toUUID(handle))
                if handle.startswith("{")
                else None
            )
            if target is None or not target.is_initialized():
                continue
            target = target.get()
            kind = target.iddObjectType().valueName()
            if kind.startswith(
                ("OS_SetpointManager_", "OS_Curve_", "OS_AvailabilityManager")
            ):
                key = str(target.handle())
                if key not in objects:
                    objects[key] = target
                    pending.append(target)
        if obj.iddObjectType().valueName() == "OS_Node":
            for manager in obj.to_Node().get().setpointManagers():
                key = str(manager.handle())
                if key not in objects:
                    objects[key] = manager
                    pending.append(manager)
    for obj in model.getAdditionalPropertiess():
        if dict(raw_fields(obj).values()).get("Object Name") in objects:
            objects[str(obj.handle())] = obj
    return objects


def remove_plants(model, sdk, planned):
    for selected in planned["parameters"]["plant_loops"]:
        object_by_ref(model, sdk, selected, "PlantLoop").remove()
    return dict(plant_loops=planned["parameters"]["plant_loops"])


def removal_plan(model, sdk, config):
    planned = base(config, "plant_removal.schema.json", ("plant_loops",))
    if planned["missing_inputs"]:
        return planned
    selected, owned = [], set()
    catalog = inventory(model)["plant_loops"]
    for selector in config["plant_loops"]:
        item = resolve(selector, catalog, "plant_loop", planned["errors"])
        if item is None:
            continue
        if item["handle"] in {x["handle"] for x in selected}:
            planned["errors"].append("Duplicate plant selection")
            continue
        loop = object_by_ref(model, sdk, item, "PlantLoop")
        selected.append(ref(loop))
        if demand(loop):
            planned["errors"].append(
                "Selected plant has active demand equipment; migrate/remove loads first"
            )
        components = [*loop.supplyComponents(), *loop.demandComponents()]
        handles = {str(x.handle()) for x in components}
        if any(x.iddObjectType().valueName() not in CLEANABLE for x in components):
            planned["errors"].append(
                "Unsupported plant equipment; service water, steam and advanced sources are outside cleanup"
            )
        if any(
            handles.intersection(
                str(x.handle())
                for x in [*other.supplyComponents(), *other.demandComponents()]
            )
            for other in model.getPlantLoops()
            if other.handle() != loop.handle()
        ):
            planned["errors"].append(
                "Cross-loop equipment is still connected; convert or disconnect it before cleanup"
            )
        owned.update(scope(loop, model, sdk))
    if planned["errors"]:
        return planned
    planned["parameters"]["plant_loops"] = sorted(selected, key=lambda x: x["handle"])
    preview = model.clone(True).to_Model()
    remove_plants(preview, sdk, planned)
    removed = original_types(model).keys() - original_types(preview).keys()
    unexpected = [
        h for h in removed - owned if original_types(model)[h] != "OS_Connection"
    ]
    if unexpected:
        planned["errors"].append(
            "Removal would cascade into unsupported external references or owned objects"
        )
        return planned
    references = outside_references(model, removed)
    if references:
        planned["errors"].append(
            "Resolve external references before cleanup; for object lists, remove/reassign the operation scheme shown in referenced_by"
        )
        planned["impact"] = dict(
            blocking_reference_count=len(references), blocking_references=references[:8]
        )
        return planned
    planned.update(
        freeze(
            model,
            preview,
            sdk,
            allowed={},
            removable=owned,
            connection_scope=owned,
            tokens={},
            new_types=(),
        )
    )
    planned["impact"] = dict(
        plant_loops=planned["parameters"]["plant_loops"],
        removed_object_count=len(removed),
        removed_by_type=dict(Counter(planned["before_objects"][h] for h in removed)),
        demand_equipment_count=0,
    )
    planned["assumptions"] = [
        "Explicit unused-plant cascade only; all surviving model objects and shared resources preserved"
    ]
    planned["ready"] = True
    planned["simulation_ready"] = True
    return planned


def verify_graph(model, sdk, planned, tokens):
    current = original_types(model)
    before = planned["before_objects"]
    return {
        "Removed identities differ from reviewed cascade": sorted(
            before.keys() - current.keys()
        )
        == planned["removed_objects"],
        "Added object counts differ": dict(
            Counter(current[h] for h in current.keys() - before.keys())
        )
        == planned["added_counts"],
        "Protected model fields or identities changed": protected_state(
            model, sdk, planned
        ),
        "Saved connection graph differs": connection_graph(model, tokens)
        == planned["connection_graph"],
    }


def validation(checks):
    return dict(
        ok=all(checks.values()),
        checks=len(checks),
        errors=[key for key, ok in checks.items() if not ok],
    )


def source_signature(obj):
    # Raw service fields point to new connection identities, not water nodes.
    # Node identity and all connection endpoints are checked independently.
    ignored = ["Handle"] + [
        name
        for name, _ in raw_fields(obj).values()
        if name.endswith(("Inlet Node Name", "Outlet Node Name"))
    ]
    return fingerprint(obj, ignored=ignored)


def validate_removal(model, sdk, planned, result):
    checks = verify_graph(model, sdk, planned, {})
    checks["Removal report mapping differs"] = result == dict(
        plant_loops=planned["parameters"]["plant_loops"]
    )
    return validation(checks)


def replace_source(model, sdk, planned):
    r, p = planned["resolved_objects"], planned["parameters"]
    old = object_by_ref(model, sdk, r["equipment"], SOURCES[r["equipment"]["type"]][0])
    # Constructors create an Always On Continuous schedule when absent. Remove
    # only those new constructor defaults after selecting the explicit schedule.
    before = original_types(model)
    new = getattr(sdk.model, p["target_class"])(model)
    generated = original_types(model).keys() - before.keys() - {str(new.handle())}
    schedule = object_by_ref(model, sdk, r["capacity_fraction_schedule"], "Schedule")
    call(new, "setCapacityFractionSchedule", schedule)
    for kind in ("OS_Schedule_Constant", "OS_ScheduleTypeLimits"):
        for h in generated:
            item = model.getModelObject(sdk.toUUID(h))
            if item.is_initialized() and item.get().iddObjectType().valueName() == kind:
                item.get().remove()
    if p["nominal_capacity_w"] == "Autosize":
        new.autosizeNominalCapacity()
    else:
        call(new, "setNominalCapacity", p["nominal_capacity_w"])
    inlet, outlet = [
        object_by_ref(model, sdk, {"handle": h}, "Node") for h in r["ports"]
    ]
    model.disconnect(
        old, getattr(old, "inletPort", getattr(old, "supplyInletPort", None))()
    )
    model.disconnect(
        old, getattr(old, "outletPort", getattr(old, "supplyOutletPort", None))()
    )
    model.connect(inlet, inlet.outletPort(), new, new.inletPort())
    model.connect(new, new.outletPort(), outlet, outlet.inletPort())
    if r["metadata"]:
        call(
            object_by_ref(model, sdk, r["metadata"], "AdditionalProperties"),
            "setPointer",
            1,
            new.handle(),
        )
    old.remove()
    call(new, "setName", r["equipment"]["name"])
    return dict(
        removed_equipment=r["equipment"],
        replacement_equipment=ref(new),
        plant_loop=r["plant_loop"],
        water_nodes=r["ports"],
    )


def replacement_plan(model, sdk, config):
    planned = base(
        config,
        "plant_replacement.schema.json",
        (
            "plant_loop",
            "equipment",
            "target_class",
            "nominal_capacity_w",
            "capacity_fraction_schedule",
            "reference_policy",
        ),
    )
    if planned["missing_inputs"]:
        return planned
    catalog = inventory(model)
    item = resolve(
        config["plant_loop"], catalog["plant_loops"], "plant_loop", planned["errors"]
    )
    if item is None:
        return planned
    selected = resolve(
        config["equipment"], item["supply_equipment"], "equipment", planned["errors"]
    )
    if selected is None:
        return planned
    info = SOURCES.get(selected["type"])
    if not selected["replacement_supported"] or info[2] != config["target_class"]:
        planned["errors"].append(
            "Source must be a heating boiler or consistent air/water cooling chiller without heat recovery; the district target must match"
        )
        return planned
    loop = object_by_ref(model, sdk, item, "PlantLoop")
    old = object_by_ref(model, sdk, selected, info[0])
    schedule = resolve(
        config["capacity_fraction_schedule"],
        catalog["schedules"],
        "capacity_fraction_schedule",
        planned["errors"],
    )
    if schedule is None:
        return planned
    chosen = object_by_ref(model, sdk, schedule, "Schedule")
    limits = chosen.scheduleTypeLimits()
    if not limits.is_initialized() or not sdk.model.isCompatible(
        config["target_class"], "Capacity Fraction", limits.get()
    ):
        planned["errors"].append(
            "Choose a capacity-fraction schedule with compatible existing Dimensionless, nonnegative type limits"
        )
        return planned
    primary = [
        (getattr(old, "inletModelObject", None) or old.supplyInletModelObject)(),
        (getattr(old, "outletModelObject", None) or old.supplyOutletModelObject)(),
    ]
    if any(
        not x.is_initialized() or not x.get().to_Node().is_initialized()
        for x in primary
    ):
        planned["errors"].append(
            "Source requires connected primary water boundary nodes"
        )
        return planned
    secondary = old.secondaryPlantLoop() if info[0] == "ChillerElectricEIR" else None
    ports = [str(x.get().handle()) for x in primary]
    metadata = next(
        (
            ref(x)
            for x in model.getAdditionalPropertiess()
            if dict(raw_fields(x).values()).get("Object Name") == str(old.handle())
        ),
        None,
    )
    references = outside_references(
        model, {str(old.handle())}, [metadata["handle"]] if metadata else []
    )
    if references:
        planned["errors"].append(
            "Reference policy Reject: external source references, including EMS/costs and name-keyed outputs, require explicit resolution"
        )
        planned["impact"] = dict(
            blocking_reference_count=len(references), blocking_references=references[:8]
        )
        return planned
    planned["parameters"].update(
        {
            k: config[k]
            for k in ("target_class", "nominal_capacity_w", "reference_policy")
        }
    )
    planned["resolved_objects"] = dict(
        equipment=ref(old),
        plant_loop=ref(loop),
        ports=ports,
        metadata=metadata,
        capacity_fraction_schedule=schedule,
    )
    allowed = {h: ["Inlet Port", "Outlet Port"] for h in ports}
    removable = {str(old.handle())}
    for _, handle in raw_fields(old).values():
        if handle.startswith("{"):
            target = model.getModelObject(sdk.toUUID(handle))
            if (
                target.is_initialized()
                and target.get().iddObjectType().valueName().startswith("OS_Curve_")
            ):
                removable.add(handle)
    connection_scope = {str(old.handle()), *ports}
    if metadata:
        allowed[metadata["handle"]] = ["Object Name"]
    condenser = secondary.get() if secondary and secondary.is_initialized() else None
    if condenser:
        boundaries = (old.demandInletModelObject(), old.demandOutletModelObject())
        neighbors = [
            getattr(x.get().to_Node().get(), method)()
            for x, method in zip(boundaries, ("inletModelObject", "outletModelObject"))
        ]
        if any(
            not x.is_initialized() or x.get().handle() != expected.handle()
            for x, expected in zip(
                neighbors, (condenser.demandSplitter(), condenser.demandMixer())
            )
        ):
            planned["errors"].append(
                "Condenser conversion requires a dedicated single-chiller branch; series equipment needs separate topology coverage"
            )
            return planned
        for obj in condenser.demandComponents():
            h, kind = str(obj.handle()), obj.iddObjectType().valueName()
            connection_scope.add(h)
            if kind == "OS_Node":
                # Only the two condenser boundary nodes can be deleted.
                if obj.handle() in (
                    old.demandInletModelObject().get().handle(),
                    old.demandOutletModelObject().get().handle(),
                ):
                    removable.add(h)
                allowed[h] = ["Inlet Port", "Outlet Port"]
            elif kind in ("OS_Connector_Mixer", "OS_Connector_Splitter"):
                allowed[h] = ["Inlet Branch Name", "Outlet Branch Name"]
    preview = model.clone(True).to_Model()
    result = replace_source(preview, sdk, planned)
    new = object_by_ref(
        preview, sdk, result["replacement_equipment"], config["target_class"]
    )
    planned["after_controls"] = controls(preview, sdk)
    if any(
        kind == "PlantEquipmentOperation:ComponentSetpoint"
        and old.nameString() in fields
        for kind, fields in planned["after_controls"]
    ):
        planned["errors"].append(
            "District conversion does not support component-setpoint dispatch; review plant control redesign separately"
        )
        return planned
    planned.update(
        freeze(
            model,
            preview,
            sdk,
            allowed=allowed,
            removable=removable,
            connection_scope=connection_scope,
            tokens={str(new.handle()): "@district-source"},
            new_types=(new.iddObjectType().valueName(), "OS_Connection"),
        )
    )
    planned["replacement_signature"] = source_signature(new)
    planned["translated_source"] = translated_state(preview, sdk, new)
    planned["impact"] = dict(
        source=ref(old),
        target_class=config["target_class"],
        nominal_capacity_w=config["nominal_capacity_w"],
        capacity_fraction_schedule=schedule,
        boundary_nodes_retained=ports,
        metadata_retained=metadata,
        new_equipment_identity=True,
        removed_by_type=dict(
            Counter(planned["before_objects"][h] for h in planned["removed_objects"])
        ),
        condenser_plant=ref(condenser) if condenser else None,
    )
    if condenser:
        remaining = demand(object_by_ref(preview, sdk, ref(condenser), "PlantLoop"))
        planned["impact"]["condenser_remaining_demand_equipment_count"] = len(remaining)
        planned["warnings"].append(
            "Condenser branch removed; condenser plant/pumps/towers remain. If no loads remain, review separate unused-plant cleanup with openstudio-hvac-remover"
        )
        if not remaining:
            planned["warnings"].append(
                "No condenser demand remains: fixed-flow pumps/towers may consume idle energy, while autosized equipment may size to zero. Convert-and-stop is not native-validated; review controls or explicit cleanup before trusting results"
            )
    planned["warnings"].append(
        "District conversion changes utility accounting, capacity dispatch limits and requested flow. Boiler fuel/efficiency/parasitics or chiller electricity/curves no longer apply; district production and distribution losses are not modeled. Pumps, loop setpoints and sizing inputs remain; autosized results may change. Review sizing, dispatch and unmet load; reduced electricity/fuel is not a plant efficiency saving"
    )
    planned["warnings"].append(
        "Capacity fraction scales delivery, not nominal dispatch capacity. Temperature protection can still deliver heat at a zero schedule. Review purchased thermal energy and source load allocation"
    )
    planned["simulation_ready"] = True
    if (
        not any(
            x.iddObjectType().valueName().startswith(("OS_Pump_", "OS_HeaderedPumps_"))
            for x in loop.supplyComponents()
        )
        or not loop.supplyOutletNode().setpointManagers()
    ):
        planned["simulation_ready"] = False
        planned["warnings"].append(
            "Selected plant lacks a supply pump or outlet setpoint manager; conversion does not repair plant controls"
        )
    if config["nominal_capacity_w"] == "Autosize":
        require_plant_sizing(planned, planned["translated_source"]["plant_sizing"])
    planned["assumptions"] = [
        "Explicit district capacity and existing fraction schedule; no prototype defaults, no automatic plant cleanup"
    ]
    planned["ready"] = True
    return planned


def validate_replacement(model, sdk, planned, result):
    new = object_by_ref(
        model,
        sdk,
        result["replacement_equipment"],
        planned["parameters"]["target_class"],
    )
    checks = verify_graph(model, sdk, planned, {str(new.handle()): "@district-source"})
    checks["Replacement fields differ"] = (
        source_signature(new) == planned["replacement_signature"]
    )
    metadata = planned["resolved_objects"]["metadata"]
    if metadata:
        checks["Metadata ownership differs"] = dict(
            raw_fields(
                object_by_ref(model, sdk, metadata, "AdditionalProperties")
            ).values()
        )["Object Name"] == str(new.handle())
    checks["Translated district capacity/schedule/service differs"] = (
        translated_state(model, sdk, new) == planned["translated_source"]
    )
    checks["Translated plant control differs"] = (
        controls(model, sdk) == planned["after_controls"]
    )
    checks["Primary boundary nodes differ"] = [
        str(new.inletModelObject().get().handle()),
        str(new.outletModelObject().get().handle()),
    ] == planned["resolved_objects"]["ports"]
    checks["Replacement identity/report differs"] = str(new.handle()) not in planned[
        "before_objects"
    ] and result == dict(
        removed_equipment=planned["resolved_objects"]["equipment"],
        replacement_equipment=ref(new),
        plant_loop=planned["resolved_objects"]["plant_loop"],
        water_nodes=planned["resolved_objects"]["ports"],
    )
    return validation(checks)
