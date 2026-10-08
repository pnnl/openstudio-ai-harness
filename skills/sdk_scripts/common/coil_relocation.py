"""Move a water coil on main air supply while retaining its complete plant branch."""

from copy import deepcopy
from common.coil_equipment import CLASSES, node_ports, set_ratings, optional_value
from common.coil_topology import freeze, connection_graph, control_context
from common.hvac_equipment import call
from common.hvac_inventory import resolve
from common.water_coil import (
    ref,
    inventory,
    object_by_ref,
    raw_fields,
    plan as settings_plan,
    ratings,
    settings,
    validate_model as validate_settings,
    heating_rating_usage,
)


def plan_relocation(model, sdk, config):
    missing = [
        key for key in ("coil", "air_loop", "air_node", "sizing") if key not in config
    ]
    if missing:
        return dict(
            ready=False,
            parameters=dict(output_model_path=config["output_model_path"]),
            missing_inputs=missing,
            errors=[],
            warnings=[],
        )
    base = settings_plan(
        model,
        sdk,
        dict(
            output_model_path=config["output_model_path"],
            coil=config["coil"],
            sizing="Autosize",
        ),
        "edit",
        topology_change=True,
    )
    if not base["ready"]:
        return base
    r = base["resolved_objects"]
    catalog = inventory(model)
    destination = resolve(
        config["air_loop"], catalog["air_loops"], "air_loop", base["errors"]
    )
    if destination is None:
        base["ready"] = False
        return base
    node_ref = resolve(
        config["air_node"],
        [
            x
            for x in catalog["supply_nodes"]
            if x["air_loop_handle"] == destination["handle"]
        ],
        "air_node",
        base["errors"],
    )
    if node_ref is None:
        base["ready"] = False
        return base
    target = object_by_ref(model, sdk, destination, "AirLoopHVAC")
    node = object_by_ref(model, sdk, node_ref, "Node")
    source = object_by_ref(model, sdk, r["air_loop"], "AirLoopHVAC")
    coil = object_by_ref(model, sdk, r["coil"], CLASSES[base["parameters"]["kind"]])
    controller = coil.controllerWaterCoil().get()
    if r["ports"][0] == str(source.supplyInletNode().handle()) and r["ports"][1] == str(
        source.supplyOutletNode().handle()
    ):
        base["errors"].append(
            "Relocation of the only source supply component requires separate empty-loop coverage"
        )
    if destination["split_supply"]:
        base["errors"].append(
            "Split destination supply paths are outside this contract"
        )
    if node.handle() != target.supplyOutletNode().handle():
        base["errors"].append(
            "Air relocation requires the destination main supply outlet node"
        )
    if str(node.handle()) == r["ports"][1]:
        base["errors"].append(
            "Coil is already immediately upstream of the selected outlet; use the in-place editor"
        )
    if not any(
        optional_value(x.controlVariable()) == "Temperature"
        for x in node.setpointManagers()
    ):
        base["errors"].append(
            "Destination outlet requires an existing Temperature setpoint manager"
        )
    controls = base["before_settings"]["controller"]
    if (
        controls["control_variable"] != "Temperature"
        or controls["actuator_variable"] != "Flow"
        or controls["minimum_flow_m3_s"] != 0
        or controls["action"]
        != ("Normal" if base["parameters"]["kind"] == "Heating" else "Reverse")
    ):
        base["errors"].append(
            "Relocation requires Temperature/Flow control, matching action and zero minimum flow"
        )
    for accessor, handle in (
        (controller.sensorNode, r["ports"][1]),
        (controller.actuatorNode, r["ports"][2]),
    ):
        actual = accessor()
        if actual.is_initialized() and str(actual.get().handle()) != handle:
            base["errors"].append(
                "Custom controller sensor/actuator locations require separate coverage"
            )
    # Existing source loop boundary control stays on its loop. Dependencies on
    # interior air nodes would still point at the bypassed location after a move.
    interior = set(r["ports"][:2]) - {
        str(source.supplyInletNode().handle()),
        str(source.supplyOutletNode().handle()),
    }
    interior_names = {
        object_by_ref(model, sdk, {"handle": handle}, "Node").nameString().casefold()
        for handle in interior
    }
    for obj in model.modelObjects():
        if obj.iddObjectType().valueName() == "OS_Connection" or str(obj.handle()) in (
            r["coil"]["handle"],
            r["controller"]["handle"],
        ):
            continue
        if any(
            name != "Handle"
            and not (str(obj.handle()) in interior and name == "Name")
            and (value in interior or value.casefold() in interior_names)
            for name, value in raw_fields(obj).values()
        ):
            base["errors"].append(
                "Source interior air node has an external reference: "
                + obj.nameString()
            )
        if any(
            name in ("Fan Inlet Node Name", "Fan Outlet Node Name")
            and value == str(node.handle())
            for name, value in raw_fields(obj).values()
        ):
            base["errors"].append(
                "Destination outlet is referenced as a fan control node; retargeting this control needs separate coverage: "
                + obj.nameString()
            )
    if not node.getTarget(node.inletPort()).is_initialized():
        base["errors"].append("Destination outlet has no incoming connection")
    else:
        edge = dict(raw_fields(node.getTarget(node.inletPort()).get()).values())
        previous = model.getModelObject(sdk.toUUID(edge["Source Object"])).get()
        if previous.iddObjectType().valueName() == "OS_Node":
            base["errors"].append(
                "Empty destination supply path needs separate coverage; select an outlet fed by existing equipment"
            )
    if base["errors"]:
        base["ready"] = False
        return base
    r["source_air_loop"] = r["air_loop"]
    r["air_loop"] = ref(target)
    r["air_node"] = ref(node)
    r["removed_air_node"] = (
        r["ports"][0]
        if r["ports"][1] == str(source.supplyOutletNode().handle())
        else r["ports"][1]
    )
    base["parameters"]["operation"] = "relocate_air"
    before_source_order = base["supply_order"]
    before_target_order = [str(x.handle()) for x in target.supplyComponents()]
    before_control = control_context(model, sdk, coil, source)
    preview = sdk.model.Model(model.clone(True))
    moved = relocate(preview, sdk, base)
    after_control = control_context(
        preview,
        sdk,
        object_by_ref(preview, sdk, r["coil"], CLASSES[base["parameters"]["kind"]]),
        object_by_ref(preview, sdk, r["air_loop"], "AirLoopHVAC"),
    )
    base["before_control"] = before_control
    base["after_control"] = after_control
    allowed = deepcopy(base["protection"].get("ignored", {}))
    allowed[r["coil"]["handle"]] += ["Air Inlet Node Name", "Air Outlet Node Name"]
    allowed[r["controller"]["handle"]] += ["Sensor Node Name", "Actuator Node Name"]
    # Old-location removal merges one interior node into its neighbor; permit
    # only port pointer changes on the two adjacent components and boundaries.
    for handle in r["ports"][:2] + [str(node.handle())]:
        allowed[handle] = ["Inlet Port", "Outlet Port"]
    edge = dict(raw_fields(node.getTarget(node.inletPort()).get()).values())
    scope = set(
        r["ports"][:2]
        + [str(node.handle()), edge["Source Object"], r["coil"]["handle"]]
    )
    old_node = object_by_ref(model, sdk, {"handle": r["removed_air_node"]}, "Node")
    boundary = (
        old_node.inletPort()
        if r["removed_air_node"] == r["ports"][0]
        else old_node.outletPort()
    )
    neighbor_edge = dict(raw_fields(old_node.getTarget(boundary).get()).values())
    endpoint, endpoint_port = (
        ("Source Object", "Outlet Port")
        if boundary == old_node.inletPort()
        else ("Target Object", "Inlet Port")
    )
    neighbor = model.getModelObject(sdk.toUUID(neighbor_edge[endpoint])).get()
    scope.add(str(neighbor.handle()))
    allowed.setdefault(str(neighbor.handle()), []).append(
        raw_fields(neighbor)[int(neighbor_edge[endpoint_port])][0]
    )
    # A component feeding the selected outlet has a connection pointer field;
    # the graph independently pins its unchanged endpoint/port and new destination.
    previous = model.getModelObject(sdk.toUUID(edge["Source Object"])).get()
    allowed.setdefault(str(previous.handle()), []).append(
        raw_fields(previous)[int(edge["Outlet Port"])][0]
    )
    base.update(
        freeze(
            model,
            preview,
            sdk,
            allowed=allowed,
            removable={r["removed_air_node"]},
            connection_scope=scope,
            tokens={moved["after_air_nodes"][0]: "@relocated-air-inlet"},
            new_types=("OS_Node", "OS_Connection"),
        )
    )
    base["source_supply_order"] = before_source_order
    base["destination_supply_order"] = before_target_order
    base["supply_order"] = [
        (
            "@relocated-air-inlet"
            if str(x.handle()) == moved["after_air_nodes"][0]
            else str(x.handle())
        )
        for x in object_by_ref(
            preview, sdk, r["air_loop"], "AirLoopHVAC"
        ).supplyComponents()
    ]
    base["expected_source_supply_order"] = [
        (
            "@relocated-air-inlet"
            if str(x.handle()) == moved["after_air_nodes"][0]
            else str(x.handle())
        )
        for x in object_by_ref(
            preview, sdk, r["source_air_loop"], "AirLoopHVAC"
        ).supplyComponents()
    ]
    zones = {
        str(x.handle()): ref(x)
        for loop in (source, target)
        for x in loop.thermalZones()
    }
    base["impact"].update(
        operation="relocate_air",
        source_air_loop=source.nameString(),
        air_loop=target.nameString(),
        destination_outlet=node.nameString(),
        affected_zone_count=len(zones),
        source_zone_count=len(source.thermalZones()),
        destination_zone_count=len(target.thermalZones()),
        identity="Coil/controller/plant branch retained; one old interior air node removed; air connections rebuilt and one new inlet node",
        sizing="Coil sizing and controller maximum flow reset to Autosize; rating metadata retained",
        before_air_nodes=r["ports"][:2],
        after_air_nodes=["@relocated-air-inlet", str(node.handle())],
        controller_sensor="Destination outlet; water actuator node unchanged",
        removed_air_node=r["removed_air_node"],
        before_control=before_control,
        after_control=after_control,
    )
    base["affected_zones"] = sorted(zones.values(), key=lambda x: x["handle"])
    if base["parameters"]["kind"] == "Heating":
        plant = next(
            x
            for x in catalog["plant_loops"]
            if x["handle"] == r["plant_loop"]["handle"]
        )
        usage = heating_rating_usage(base["after_values"], target, plant, set())
        base["rating_usage"] = base["impact"]["rating_usage"] = usage
        base["assumption_review"] = dict(status="informational", items=[usage])
    base["warnings"].append(
        "Moving the coil changes air-side equipment order and may change source/destination heating or cooling availability. System sizing, zones, terminals and plant settings are retained; run sizing and review both air systems separately."
    )
    base["warnings"].append(
        "Fan position: "
        + before_control["position_relative_to_fan"]
        + " -> "
        + after_control["position_relative_to_fan"]
        + ". Outlet temperature control: "
        + before_control["control_reference"]
        + " -> "
        + after_control["control_reference"]
        + ". Review fan heat compensation and the destination supply-air setpoint; relocation can change sizing and operation."
    )
    base["assumptions"] = [
        "Move only the selected main-supply coil immediately upstream of the selected supply outlet",
        "Preserve coil/controller, water nodes/branch, references, schedules, metadata and rating inputs; reset sizing and controller maximum flow to Autosize",
        "Merge the old location into a single shared air node; one interior air node is removed, new inlet node and rebuilt air connections have new handles",
        "Controller sensor follows the new coil outlet; no zone reassignment or automatic system resizing",
    ]
    return base


def relocate(model, sdk, planned):
    r, p = planned["resolved_objects"], planned["parameters"]
    coil = object_by_ref(model, sdk, r["coil"], CLASSES[p["kind"]])
    inlet, outlet = [
        object_by_ref(model, sdk, {"handle": h}, "Node") for h in r["ports"][:2]
    ]
    target = object_by_ref(model, sdk, r["air_node"], "Node")
    # Capture the destination edge before disconnecting; no component API is
    # allowed to perform its implicit removal/reconnection at the old location.
    edge = dict(raw_fields(target.getTarget(target.inletPort()).get()).values())
    previous = model.getModelObject(sdk.toUUID(edge["Source Object"])).get()
    # Adjacent Node -> Node links translate to different EnergyPlus names and
    # fail Branch integrity; remove one interior node at the vacated location.
    removed_node = inlet if r["removed_air_node"] == r["ports"][0] else outlet
    boundary = (
        removed_node.inletPort()
        if removed_node.handle() == inlet.handle()
        else removed_node.outletPort()
    )
    old_edge = dict(raw_fields(removed_node.getTarget(boundary).get()).values())
    old_neighbor = model.getModelObject(
        sdk.toUUID(
            old_edge[
                (
                    "Source Object"
                    if boundary == removed_node.inletPort()
                    else "Target Object"
                )
            ]
        )
    ).get()
    upstream = sdk.model.Node(model)
    model.disconnect(coil, coil.airInletPort())
    model.disconnect(coil, coil.airOutletPort())
    model.disconnect(removed_node, boundary)
    if removed_node.handle() == inlet.handle():
        model.connect(
            old_neighbor, int(old_edge["Outlet Port"]), outlet, outlet.inletPort()
        )
    else:
        model.connect(
            inlet, inlet.outletPort(), old_neighbor, int(old_edge["Inlet Port"])
        )
    removed_node.remove()
    model.disconnect(target, target.inletPort())
    model.connect(previous, int(edge["Outlet Port"]), upstream, upstream.inletPort())
    model.connect(upstream, upstream.outletPort(), coil, coil.airInletPort())
    model.connect(coil, coil.airOutletPort(), target, target.inletPort())
    controller = coil.controllerWaterCoil().get()
    call(controller, "setSensorNode", target)
    call(
        controller,
        "setActuatorNode",
        object_by_ref(model, sdk, {"handle": r["ports"][2]}, "Node"),
    )
    controller.autosizeMaximumActuatedFlow()
    set_ratings(coil, p["kind"], p["ratings"])
    return deepcopy(
        dict(
            operation="relocate_air",
            coil=ref(coil),
            controller=ref(controller),
            source_air_loop=r["source_air_loop"],
            destination_air_loop=r["air_loop"],
            before_air_nodes=r["ports"][:2],
            after_air_nodes=node_ports(coil)[:2],
            removed_air_node=r["removed_air_node"],
            before=planned["before_values"],
            after=ratings(coil, p["kind"]),
            before_settings=planned["before_settings"],
            after_settings=settings(coil),
        )
    )


def validate_relocation(model, sdk, planned, result):
    r = planned["resolved_objects"]
    coil = object_by_ref(model, sdk, r["coil"], CLASSES[planned["parameters"]["kind"]])
    ports = node_ports(coil)
    adapted = deepcopy(planned)
    adapted["parameters"]["operation"] = "edit"
    adapted["resolved_objects"]["ports"][:2] = ports[:2]
    adapted["supply_order"] = [
        ports[0] if h == "@relocated-air-inlet" else h for h in planned["supply_order"]
    ]
    validation = validate_settings(model, sdk, adapted, result)

    def check(ok, message):
        validation["checks"] += 1
        if not ok:
            validation["errors"].append(message)

    check(
        ports[0] not in planned["before_objects"]
        and ports[1] == r["air_node"]["handle"],
        "Relocated coil air nodes differ",
    )
    check(
        ports[2:] == r["ports"][2:],
        "Water boundary nodes changed during air relocation",
    )
    check(
        connection_graph(model, {ports[0]: "@relocated-air-inlet"})
        == planned["connection_graph"],
        "Connection graph differs from reviewed air relocation",
    )
    source = object_by_ref(model, sdk, r["source_air_loop"], "AirLoopHVAC")
    order = [
        "@relocated-air-inlet" if str(x.handle()) == ports[0] else str(x.handle())
        for x in source.supplyComponents()
    ]
    check(
        order == planned["expected_source_supply_order"],
        "Source air supply order differs",
    )
    check(
        control_context(
            model, sdk, coil, object_by_ref(model, sdk, r["air_loop"], "AirLoopHVAC")
        )
        == planned["after_control"],
        "Relocated fan position/translated temperature control differs from preview",
    )
    controller = coil.controllerWaterCoil().get()
    check(
        controller.sensorNode().is_initialized()
        and controller.sensorNode().get().handle()
        == coil.airOutletModelObject().get().handle(),
        "Relocated controller sensor differs",
    )
    check(
        controller.actuatorNode().is_initialized()
        and str(controller.actuatorNode().get().handle()) == r["ports"][2],
        "Plant actuator node changed",
    )
    check(
        result["operation"] == "relocate_air"
        and result["source_air_loop"] == r["source_air_loop"]
        and result["destination_air_loop"] == r["air_loop"]
        and result["before_air_nodes"] == r["ports"][:2]
        and result["after_air_nodes"] == ports[:2]
        and result["removed_air_node"] == r["removed_air_node"],
        "Reported air relocation mapping differs",
    )
    validation["ok"] = not validation["errors"]
    return validation
