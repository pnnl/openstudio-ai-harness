"""Scoped plant-demand migration, retaining coil/controller and air identities."""

from collections import Counter
from copy import deepcopy
import math

from common.coil_equipment import (
    CLASSES,
    kind_of,
    node_ports,
    ratings,
    set_ratings,
    set_controller_settings,
)
from common.hvac_equipment import call
from common.hvac_inventory import resolve
from common.model_preservation import snapshot
from common.water_coil import (
    ref,
    inventory,
    object_by_ref,
    original_types,
    raw_fields,
    settings,
    plan as plan_settings,
    check_ratings,
    validate_model,
)


def move_branch(model, sdk, coil, source, destination):
    """Protect controller ownership while the native branch API rebuilds water links.

    removeDemandBranchWithComponent removes the owned controller. A temporary
    unattached coil holds its pointer until attachment creates a disposable
    controller. Restore the original owner and both control nodes last.
    """
    controller = coil.controllerWaterCoil().get()
    holding = getattr(sdk.model, CLASSES[kind_of(coil)])(model)
    index = next(
        i
        for i, (name, _) in raw_fields(controller).items()
        if name == "Water Coil Name"
    )
    call(controller, "setPointer", index, holding.handle())
    call(source, "removeDemandBranchWithComponent", coil)
    call(destination, "addDemandBranchForComponent", coil)
    temporary_controller = coil.controllerWaterCoil().get()
    temporary_controller.remove()
    call(controller, "setPointer", index, coil.handle())
    holding.remove()
    set_controller_settings(controller, {"maximum_flow_m3_s": "Autosize"})
    ports = node_ports(coil)
    call(
        controller,
        "setSensorNode",
        object_by_ref(model, sdk, {"handle": ports[1]}, "Node"),
    )
    call(
        controller,
        "setActuatorNode",
        object_by_ref(model, sdk, {"handle": ports[2]}, "Node"),
    )


def graph(model, coil, before):
    """Independent whole-model connection graph, normalizing only new water nodes."""
    tokens = {
        h: "@migrated-water-" + str(index)
        for index, h in enumerate(node_ports(coil)[2:])
        if h not in before
    }
    edges = []
    for obj in model.modelObjects():
        if obj.iddObjectType().valueName() != "OS_Connection":
            continue
        fields = dict(raw_fields(obj).values())
        edges.append(
            list(
                tokens.get(fields[key], fields[key])
                for key in (
                    "Source Object",
                    "Outlet Port",
                    "Target Object",
                    "Inlet Port",
                )
            )
        )
    return sorted(edges)


def projection(model, preview, sdk, planned):
    """Restrict preview differences to the selected coil and two demand graphs."""
    r = planned["resolved_objects"]
    before, after = original_types(model), original_types(preview)
    scope = {r["coil"]["handle"]}
    for plant in (r["source_plant_loop"], r["plant_loop"]):
        scope.update(
            str(x.handle())
            for x in object_by_ref(model, sdk, plant, "PlantLoop").demandComponents()
        )
    removed = sorted(before.keys() - after.keys())
    for h in removed:
        obj = model.getModelObject(sdk.toUUID(h)).get()
        fields = dict(raw_fields(obj).values())
        allowed = (before[h] == "OS_Node" and h in r["ports"][2:]) or (
            before[h] == "OS_Connection"
            and fields["Source Object"] in scope
            and fields["Target Object"] in scope
        )
        if not allowed:
            raise ValueError(
                "Migration would remove an object outside the selected demand branch"
            )
    ignored = deepcopy(planned["protection"].get("ignored", {}))
    limits = {}
    for h in before.keys() & after.keys():
        old = model.getModelObject(sdk.toUUID(h)).get()
        new = preview.getModelObject(sdk.toUUID(h)).get()
        a, b = raw_fields(old), raw_fields(new)
        changed = {name for i, (name, value) in a.items() if b.get(i) != (name, value)}
        added = b.keys() - a.keys()
        allowed = set(ignored.get(h, []))
        if h == r["coil"]["handle"]:
            allowed.update(("Water Inlet Node Name", "Water Outlet Node Name"))
        elif h == r["controller"]["handle"]:
            allowed.update(("Sensor Node Name", "Actuator Node Name"))
        elif h in scope and before[h] == "OS_Node":
            allowed.update(("Inlet Port", "Outlet Port"))
        elif h in scope and before[h] in (
            "OS_Connector_Mixer",
            "OS_Connector_Splitter",
        ):
            allowed.update(("Inlet Branch Name", "Outlet Branch Name"))
        if changed - allowed or (
            added and before[h] not in ("OS_Connector_Mixer", "OS_Connector_Splitter")
        ):
            raise ValueError(
                f"Unexpected migration side effect on {old.nameString()}: {sorted(changed - allowed)}"
            )
        if added:
            if h not in scope or any(b[i][0] not in allowed for i in added):
                raise ValueError("Migration changed unrelated connector fields")
            limits[h] = len(a)
        if allowed:
            ignored[h] = sorted(allowed)
    added_counts = dict(Counter(after[h] for h in after.keys() - before.keys()))
    if set(added_counts) - {"OS_Node", "OS_Connection"}:
        raise ValueError("Migration unexpectedly creates equipment or controls")
    protection = dict(excluded=removed, ignored=ignored, field_limits=limits)
    return protection, removed, added_counts


def plan_migration(model, sdk, config):
    missing = [key for key in ("coil", "plant_loop", "sizing") if key not in config]
    if missing:
        return dict(
            ready=False,
            parameters=dict(output_model_path=config["output_model_path"]),
            missing_inputs=missing,
            errors=[],
            warnings=[],
        )
    catalog = inventory(model)
    errors = []
    selected = resolve(config["coil"], catalog["water_coils"], "coil", errors)
    destination = resolve(
        config["plant_loop"], catalog["plant_loops"], "plant_loop", errors
    )
    if errors:
        return dict(
            ready=False,
            parameters=dict(output_model_path=config["output_model_path"]),
            missing_inputs=[],
            errors=errors,
            warnings=[],
        )
    base = plan_settings(
        model,
        sdk,
        dict(
            output_model_path=config["output_model_path"],
            coil=config["coil"],
            sizing=config["sizing"],
        ),
        "edit",
        topology_change=True,
    )
    if not base["ready"]:
        return base
    r = base["resolved_objects"]
    kind = base["parameters"]["kind"]
    r["source_plant_loop"] = r["plant_loop"]
    r["plant_loop"] = {k: destination[k] for k in ("name", "handle")}
    coil = object_by_ref(model, sdk, r["coil"], CLASSES[kind])
    source = object_by_ref(model, sdk, r["source_plant_loop"], "PlantLoop")
    target = object_by_ref(model, sdk, r["plant_loop"], "PlantLoop")
    if source.handle() == target.handle():
        base["errors"].append(
            "Migration requires a different destination plant; use the editor for settings"
        )
    if destination["loop_type"] != kind:
        base["errors"].append("Destination plant must match Heating/Cooling type")
    for key in ("supply_equipment", "supply_pumps", "supply_setpoint_managers"):
        if not destination[key]:
            base["errors"].append("Destination plant is missing " + key)
    if (
        not math.isfinite(destination["design_supply_temperature_c"])
        or not math.isfinite(destination["design_delta_temperature_k"])
        or destination["design_delta_temperature_k"] <= 0
    ):
        base["errors"].append(
            "Destination plant design conditions must be finite with positive delta temperature"
        )
    if any(
        x.fluidType() != "Water" or x.glycolConcentration() != 0
        for x in (source, target)
    ):
        base["errors"].append(
            "Initial migration supports water-only source and destination plants"
        )
    # Branch removal removes the whole branch; serial equipment must never be lost.
    inlet = object_by_ref(model, sdk, {"handle": r["ports"][2]}, "Node")
    outlet = object_by_ref(model, sdk, {"handle": r["ports"][3]}, "Node")
    if (
        not inlet.inletModelObject().is_initialized()
        or inlet.inletModelObject().get().handle() != source.demandSplitter().handle()
        or not outlet.outletModelObject().is_initialized()
        or outlet.outletModelObject().get().handle() != source.demandMixer().handle()
    ):
        base["errors"].append(
            "Migration requires a dedicated single-coil demand branch; serial components need separate coverage"
        )
    controller = coil.controllerWaterCoil().get()
    controls = base["before_settings"]["controller"]
    if (
        controls["control_variable"] != "Temperature"
        or controls["actuator_variable"] != "Flow"
        or controls["action"] != ("Normal" if kind == "Heating" else "Reverse")
        or controls["minimum_flow_m3_s"] != 0
    ):
        base["errors"].append(
            "Migration requires Temperature/Flow control, matching action and zero minimum flow"
        )
    for accessor, handle in (
        (controller.sensorNode, r["ports"][1]),
        (controller.actuatorNode, r["ports"][2]),
    ):
        node = accessor()
        if node.is_initialized() and str(node.get().handle()) != handle:
            base["errors"].append(
                "Custom controller sensor/actuator locations require separate coverage"
            )
    # Removed water-node references cannot be safely retargeted without user intent.
    for obj in model.modelObjects():
        if (
            obj.iddObjectType().valueName() == "OS_Connection"
            or str(obj.handle()) == r["controller"]["handle"]
        ):
            continue
        if any(
            name != "Handle" and value in r["ports"][2:]
            for name, value in raw_fields(obj).values()
        ):
            base["errors"].append(
                "Selected water nodes have external references: " + obj.nameString()
            )
    check_ratings(
        kind, base["after_values"], {}, destination, base["errors"], base["warnings"]
    )
    if base["errors"]:
        base["ready"] = False
        return base
    base["parameters"]["operation"] = "migrate_plant"
    base["source_plant_supply_order"] = base["plant_supply_order"]
    base["source_plant_demand_components"] = base["plant_demand_components"]
    base["plant_supply_order"] = [str(x.handle()) for x in target.supplyComponents()]
    base["plant_demand_components"] = [
        str(x.handle())
        for x in target.demandComponents()
        if x.iddObjectType().valueName()
        not in ("OS_Node", "OS_Connector_Mixer", "OS_Connector_Splitter")
    ]
    preview = sdk.model.Model(model.clone(True))
    migrate(preview, sdk, base)
    protection, removed, added = projection(model, preview, sdk, base)
    base.update(
        protection=protection,
        protected_objects=snapshot(model, **protection),
        removed_objects=removed,
        added_counts=added,
    )
    moved = object_by_ref(preview, sdk, r["coil"], CLASSES[kind])
    base["connection_graph"] = graph(preview, moved, base["before_objects"])
    remaining_demand = {
        str(x.handle()): x
        for x in source.demandComponents()
        if x.handle() != coil.handle()
        and x.iddObjectType().valueName()
        not in ("OS_Node", "OS_Connector_Mixer", "OS_Connector_Splitter")
        and not x.iddObjectType()
        .valueName()
        .startswith(("OS_Pipe_", "OS_Pump_", "OS_HeaderedPumps_"))
    }
    remaining_coils = sum(
        x.iddObjectType().valueName().startswith("OS_Coil_")
        for x in remaining_demand.values()
    )
    if remaining_coils == 0:
        other = len(remaining_demand)
        service = (
            f"It still has {other} other demand equipment object(s). "
            if other
            else "It will have no remaining demand equipment. "
        )
        base["warnings"].append(
            f"Source plant '{source.nameString()}' will serve 0 coils after migration. "
            + service
            + "Its supply equipment and pumps remain, including their existing sizing/Autosize settings. "
            + "Review whether to retain this plant. openstudio-hvac-remover covers supported HVAC cleanup "
            + "but currently excludes plant deletion; deleting the plant needs separate supported coverage."
        )
    retained = base["after_values"]
    fixed_water = {}
    if kind == "Cooling" and isinstance(
        retained["design_inlet_water_temperature_c"], (int, float)
    ):
        fixed_water = {
            "design_inlet_water_temperature_c": (
                retained["design_inlet_water_temperature_c"],
                destination["design_supply_temperature_c"],
            )
        }
    elif (
        kind == "Heating" and retained["performance_input_method"] == "NominalCapacity"
    ):
        fixed_water = {
            "rated_inlet_water_temperature_c": (
                retained["rated_inlet_water_temperature_c"],
                destination["design_supply_temperature_c"],
            ),
            "rated_outlet_water_temperature_c": (
                retained["rated_outlet_water_temperature_c"],
                destination["design_supply_temperature_c"]
                - destination["design_delta_temperature_k"],
            ),
        }
    mismatches = {
        key: dict(retained_temperature_c=value, destination_temperature_c=expected)
        for key, (value, expected) in fixed_water.items()
        if not math.isclose(value, expected, abs_tol=0.05)
    }
    if mismatches:
        base["warnings"].append(
            "Migration retains fixed water rating/design values that differ from the destination: "
            + ", ".join(sorted(mismatches))
            + ". Review these inputs; use openstudio-water-coil-editor on the copied output "
            + "for explicitly selected rating changes before sizing/simulation when needed. "
            + "Migration does not automatically change manufacturer ratings or design conditions."
        )
    base["impact"].update(
        operation="migrate_plant",
        source_plant=source.nameString(),
        plant=target.nameString(),
        identity="coil/controller/air nodes retained; water nodes and demand connection handles may change",
        removed_object_counts=dict(Counter(base["before_objects"][h] for h in removed)),
        sizing="Coil sizing and controller maximum flow reset to Autosize; other ratings/settings retained",
        source_design=dict(
            supply_temperature_c=source.sizingPlant().designLoopExitTemperature(),
            delta_temperature_k=source.sizingPlant().loopDesignTemperatureDifference(),
        ),
        destination_design=dict(
            supply_temperature_c=destination["design_supply_temperature_c"],
            delta_temperature_k=destination["design_delta_temperature_k"],
        ),
        source_plant_remaining_coil_count=remaining_coils,
        source_plant_remaining_demand_equipment_count=len(remaining_demand),
        source_plant_will_be_unserved=not remaining_demand,
        retained_water_rating_mismatches=mismatches,
    )
    base["assumptions"] = [
        "Move only the selected dedicated demand branch; source plant remains even when unused",
        "Retain coil/controller/air connections and incoming references; reset coil sizing and controller maximum flow to Autosize",
        "Plant demand connection handles may be rebuilt; do not reuse removed water-node/connection handles",
        "Existing air-system sizing, terminals, schedules and source equipment are unchanged; run sizing separately",
    ]
    if kind == "Heating":
        from common.water_coil import heating_rating_usage

        usage = heating_rating_usage(
            base["after_values"],
            object_by_ref(model, sdk, r["air_loop"], "AirLoopHVAC"),
            destination,
            set(),
        )
        base["rating_usage"] = base["impact"]["rating_usage"] = usage
        base["assumption_review"] = dict(status="informational", items=[usage])
    return base


def migrate(model, sdk, planned):
    r, p = planned["resolved_objects"], planned["parameters"]
    coil = object_by_ref(model, sdk, r["coil"], CLASSES[p["kind"]])
    move_branch(
        model,
        sdk,
        coil,
        object_by_ref(model, sdk, r["source_plant_loop"], "PlantLoop"),
        object_by_ref(model, sdk, r["plant_loop"], "PlantLoop"),
    )
    set_ratings(coil, p["kind"], p["ratings"])
    return dict(
        operation="migrate_plant",
        coil=ref(coil),
        controller=ref(coil.controllerWaterCoil().get()),
        source_plant=r["source_plant_loop"],
        destination_plant=r["plant_loop"],
        before_water_nodes=r["ports"][2:],
        after_water_nodes=node_ports(coil)[2:],
        removed_handles=planned.get("removed_objects", []),
        before=planned["before_values"],
        after=ratings(coil, p["kind"]),
        before_settings=planned["before_settings"],
        after_settings=settings(coil),
    )


def validate_migration(model, sdk, planned, result):
    # Reuse independent scalar/identity/protected-field checks; adapt only the
    # expected water-node boundary and destination component membership.
    adapted = deepcopy(planned)
    adapted["parameters"]["operation"] = "edit"
    r = planned["resolved_objects"]
    coil = object_by_ref(model, sdk, r["coil"], CLASSES[planned["parameters"]["kind"]])
    adapted["resolved_objects"]["ports"][2:] = node_ports(coil)[2:]
    adapted["plant_demand_components"].append(str(coil.handle()))
    validation = validate_model(model, sdk, adapted, result)

    def check(ok, message):
        validation["checks"] += 1
        if not ok:
            validation["errors"].append(message)

    source = object_by_ref(model, sdk, r["source_plant_loop"], "PlantLoop")
    check(
        [str(x.handle()) for x in source.supplyComponents()]
        == planned["source_plant_supply_order"],
        "Source plant supply topology changed",
    )
    expected = sorted(
        h for h in planned["source_plant_demand_components"] if h != r["coil"]["handle"]
    )
    actual = sorted(
        str(x.handle())
        for x in source.demandComponents()
        if x.iddObjectType().valueName()
        not in ("OS_Node", "OS_Connector_Mixer", "OS_Connector_Splitter")
    )
    check(actual == expected, "Source demand components changed outside selected coil")
    check(
        graph(model, coil, planned["before_objects"]) == planned["connection_graph"],
        "Connection graph differs from reviewed migration",
    )
    controller = coil.controllerWaterCoil().get()
    for accessor, handle, label in (
        (controller.sensorNode, node_ports(coil)[1], "sensor"),
        (controller.actuatorNode, node_ports(coil)[2], "actuator"),
    ):
        node = accessor()
        check(
            node.is_initialized() and str(node.get().handle()) == handle,
            "Migrated controller " + label + " node differs",
        )
    check(
        result["source_plant"] == r["source_plant_loop"]
        and result["destination_plant"] == r["plant_loop"],
        "Reported migration plants differ",
    )
    check(
        result["operation"] == "migrate_plant"
        and result["before_water_nodes"] == r["ports"][2:]
        and result["after_water_nodes"] == node_ports(coil)[2:]
        and result["removed_handles"] == planned["removed_objects"],
        "Reported migration identity changes differ",
    )
    validation["ok"] = not validation["errors"]
    return validation
