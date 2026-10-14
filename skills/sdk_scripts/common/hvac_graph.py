"""Read-only HVAC graph: native connections are distinct from relationships."""

from collections import Counter, defaultdict
import hashlib


def handle(obj):
    return str(obj.handle())


def fields(obj):
    for index in range(obj.numFields()):
        field = obj.iddObject().getField(index)
        if field.is_initialized():
            yield index, field.get().name()


def raw(obj):
    obj = obj.idfObject()  # Workspace getString resolves pointers to names.
    return {
        name: obj.getString(i).get()
        for i, name in fields(obj)
        if obj.getString(i).is_initialized()
    }


def state(model):
    return {handle(obj): str(obj) for obj in model.modelObjects()}


def extract(model, sdk):
    """Never infer a series path from the ordering of component inventories."""
    before = state(model)
    objects = {handle(obj): obj for obj in model.modelObjects()}
    nodes, edges, groups, warnings = {}, [], {}, []
    membership = defaultdict(set)
    port_references = {}

    def connection_field(obj, connection):
        key = handle(obj)
        if key not in port_references:
            references = defaultdict(list)
            idf = obj.idfObject()
            for index, name in fields(obj):
                value = idf.getString(index)
                if value.is_initialized():
                    references[value.get()].append((index, name))
            port_references[key] = references
        matches = port_references[key].get(connection, [])
        return (
            matches[0]
            if len(matches) == 1
            else (None, "Unresolved connection reference")
        )

    def add(obj):
        key = handle(obj)
        obj = objects[key]  # getTarget returns WorkspaceObject, not ModelObject.
        if key not in nodes:
            kind = obj.iddObjectType().valueName()
            nodes[key] = dict(
                handle=key,
                name=obj.nameString(),
                type=kind,
                ports=[],
                groups=[],
                provenance="model_object",
            )
        return key

    def relation(source, target, kind, evidence, **extra):
        a, b = add(source), add(target)
        key = hashlib.sha256(f"{a}|{b}|{kind}|{evidence}".encode()).hexdigest()
        edges.append(
            dict(
                id=key,
                kind=kind,
                source=a,
                target=b,
                source_port=None,
                target_port=None,
                provenance=evidence,
                groups=[],
                **extra,
            )
        )

    def group(obj, kind, members, zones=()):
        key = kind + "_" + handle(obj).strip("{}").replace("-", "")
        items = {add(x) for x in members} | {add(obj)}
        groups[key] = dict(
            id=key,
            kind=kind,
            root=handle(obj),
            name=obj.nameString(),
            members=items,
            served_zones=sorted(handle(z) for z in zones),
        )
        return key

    # All native HVAC connection endpoints are retained, including unknown types.
    for connection in objects.values():
        if connection.iddObjectType().valueName() != "OS_Connection":
            continue
        values = raw(connection)
        a, b = values.get("Source Object"), values.get("Target Object")
        if a not in objects or b not in objects:
            warnings.append(dict(code="invalid_connection", handle=handle(connection)))
            continue
        source, target = objects[a], objects[b]
        add(source)
        add(target)
        try:
            out_port, in_port = int(values["Outlet Port"]), int(values["Inlet Port"])
        except (ValueError, KeyError):
            warnings.append(
                dict(code="invalid_connection_port", handle=handle(connection))
            )
            continue
        names, indices = [], []
        for obj, port, direction in (
            (source, out_port, "out"),
            (target, in_port, "in"),
        ):
            # Translated legacy connections can retain old numeric ports. Keep
            # those exact values, but identify the current field by its explicit
            # reference to this connection, never by an obsolete field offset.
            index, name = connection_field(obj, handle(connection))
            names.append(name)
            indices.append(index)
            if index != port:
                warnings.append(
                    dict(
                        code=(
                            "connection_port_discrepancy"
                            if index is not None
                            else "unresolved_connection_reference"
                        ),
                        handle=handle(connection),
                        endpoint=handle(obj),
                        direction=direction,
                        stored_port=port,
                        field_index=index,
                    )
                )
            nodes[handle(obj)]["ports"].append(
                dict(
                    index=port,
                    field_index=index,
                    field=name,
                    direction=direction,
                    connection=handle(connection),
                )
            )
        edges.append(
            dict(
                id=handle(connection),
                kind="flow",
                source=a,
                target=b,
                source_port=out_port,
                target_port=in_port,
                source_field=names[0],
                target_field=names[1],
                source_field_index=indices[0],
                target_field_index=indices[1],
                medium="unknown",
                groups=[],
                provenance="OS_Connection",
            )
        )

    for loop in model.getAirLoopHVACs():
        members = [loop, *loop.supplyComponents(), *loop.demandComponents()]
        oa = loop.airLoopHVACOutdoorAirSystem()
        if oa.is_initialized():
            members += list(oa.get().components())
            # Controllers are not HVAC components. Follow only stored owning
            # references, avoiding lazy getters that could create model objects.
            for index, name in fields(oa.get()):
                if name != "Controller Name":
                    continue
                reference = oa.get().getTarget(index)
                if reference.is_initialized():
                    controller = objects[handle(reference.get())]
                    members.append(controller)
                    for child_index, child_name in fields(controller):
                        if child_name != "Controller Mechanical Ventilation":
                            continue
                        child = controller.getTarget(child_index)
                        if child.is_initialized():
                            members.append(objects[handle(child.get())])
        group(loop, "air_loop", members, loop.thermalZones())
    for loop in model.getPlantLoops():
        group(
            loop,
            "plant_loop",
            [loop, *loop.supplyComponents(), *loop.demandComponents()],
        )

    vrf_zones = defaultdict(set)
    for vrf in model.getAirConditionerVariableRefrigerantFlows():
        terminals, zones = list(vrf.terminals()), []
        for terminal in terminals:
            relation(
                vrf,
                terminal,
                "vrf_membership",
                "AirConditionerVariableRefrigerantFlow.terminals",
            )
            if terminal.thermalZone().is_initialized():
                zone = terminal.thermalZone().get()
                zones.append(zone)
                vrf_zones[handle(zone)].add(handle(vrf))
        group(vrf, "vrf_system", [vrf, *terminals, *zones], zones)

    zone_records = []
    for zone in model.getThermalZones():
        add(zone)
        equipment = list(zone.equipment())
        air = list(zone.airLoopHVACs())
        zone_records.append(
            dict(
                handle=handle(zone),
                name=zone.nameString(),
                air_loops=sorted(handle(x) for x in air),
                vrf_systems=sorted(vrf_zones[handle(zone)]),
                equipment=sorted(handle(x) for x in equipment),
                ideal_loads=zone.useIdealAirLoads(),
                plenum=zone.isPlenum(),
                unserved=not (
                    air or equipment or zone.useIdealAirLoads() or zone.isPlenum()
                ),
            )
        )
        key = group(zone, "zone", [zone, *equipment])
        for component in equipment:
            relation(component, zone, "serves_zone", "ThermalZone.equipment")
        # Read stored references, rather than lazy getters which can create nodes.
        for i, name in fields(zone):
            if name not in {
                "Zone Air Inlet Port List",
                "Zone Return Air Port List",
                "Zone Air Exhaust Port List",
                "Zone Air Node Name",
            }:
                continue
            reference = zone.getTarget(i)
            if not reference.is_initialized():
                continue
            obj = reference.get()
            groups[key]["members"].add(add(obj))
            for current in groups.values():
                if (
                    current["kind"] == "air_loop"
                    and handle(zone) in current["served_zones"]
                ):
                    current["members"].update((handle(zone), handle(obj)))
            if name.endswith("Port List"):
                a, b = (obj, zone) if "Inlet" in name else (zone, obj)
                relation(a, b, "zone_boundary", "ThermalZone." + name, medium="air")

    # Keep isolated equipment visible too, without claiming it serves a zone.
    for obj in objects.values():
        if obj.to_HVACComponent().is_initialized():
            add(obj)
        elif (
            obj.iddObjectType()
            .valueName()
            .startswith(("OS_SetpointManager_", "OS_Controller_"))
        ):
            add(obj)

    for obj in objects.values():
        if "Plenum" in obj.iddObjectType().valueName():
            for i, name in fields(obj):
                target = obj.getTarget(i)
                if target.is_initialized() and handle(target.get()) in objects:
                    zone = objects[handle(target.get())]
                    if zone.iddObjectType().valueName() == "OS_ThermalZone":
                        relation(obj, zone, "plenum_zone", name)

    # Embedded equipment is visible, but field order is not internal flow order.
    pending = list(nodes)
    visited = set()
    while pending:
        key = pending.pop()
        if key in visited:
            continue
        visited.add(key)
        obj = objects[key]
        kind = nodes[key]["type"]
        if not kind.startswith(
            (
                "OS_AirTerminal_",
                "OS_ZoneHVAC_",
                "OS_AirLoopHVAC_Unitary",
                "OS_CoilSystem_",
            )
        ):
            continue
        children = []
        for i, name in fields(obj):
            reference = obj.getTarget(i)
            if not reference.is_initialized():
                continue
            child = objects[handle(reference.get())]
            if (
                child.iddObjectType()
                .valueName()
                .startswith(("OS_Coil_", "OS_Fan_", "OS_HeatExchanger_"))
            ):
                children.append(add(child))
                relation(obj, child, "contains", kind + "." + name)
                pending.append(handle(child))
        warnings.append(
            dict(
                code="embedded_air_path_unexpanded",
                handle=key,
                children=sorted(children),
            )
        )
        for current in groups.values():
            if key in current["members"]:
                current["members"].update(children)

    # Stored setpoint/controller references are control relationships, not ducts.
    for obj in objects.values():
        kind = obj.iddObjectType().valueName()
        if not kind.startswith(("OS_SetpointManager_", "OS_Controller_")):
            continue
        for i, name in fields(obj):
            reference = obj.getTarget(i)
            if reference.is_initialized() and handle(reference.get()) in nodes:
                relation(obj, reference.get(), "control", kind + "." + name)
    for key in list(nodes):
        obj = objects[key]
        if nodes[key]["type"] == "OS_AirLoopHVAC_OutdoorAirSystem":
            for i, name in fields(obj):
                if name == "Controller Name" and obj.getTarget(i).is_initialized():
                    relation(
                        obj.getTarget(i).get(),
                        obj,
                        "control",
                        "OutdoorAirSystem.Controller Name",
                    )

    for current in groups.values():
        for key in current["members"]:
            membership[key].add(current["id"])
    for edge in edges:
        a, b = edge["source"], edge["target"]
        common = membership[a] & membership[b]
        if edge["kind"] == "flow":
            names = (edge["source_field"] + " " + edge["target_field"]).lower()
            medium = "water" if "water" in names else "air" if "air" in names else None
            candidates = common or membership[a] | membership[b]
            loop_groups = {
                k
                for k in candidates
                if groups[k]["kind"] in {"air_loop", "plant_loop", "zone"}
            }
            if medium is None:
                kinds = {groups[k]["kind"] for k in loop_groups}
                medium = (
                    "water"
                    if kinds == {"plant_loop"}
                    else "air" if kinds and kinds <= {"air_loop", "zone"} else "unknown"
                )
            edge["medium"] = medium
            wanted = {"plant_loop"} if medium == "water" else {"air_loop", "zone"}
            edge["groups"] = sorted(
                k for k in loop_groups if groups[k]["kind"] in wanted
            )
        else:
            edge["groups"] = sorted(common or membership[a] | membership[b])
        for key in edge["groups"]:
            groups[key]["members"].update((a, b))

    unassigned = (
        set(nodes) - set().union(*(g["members"] for g in groups.values()))
        if groups
        else set(nodes)
    )
    orphan_edges = [edge for edge in edges if not edge["groups"]]
    unassigned.update(
        h for edge in orphan_edges for h in (edge["source"], edge["target"])
    )
    if unassigned:
        groups["unassigned"] = dict(
            id="unassigned",
            kind="unassigned",
            root=None,
            name="Unassigned connected or isolated HVAC",
            members=unassigned,
            served_zones=[],
        )
        for edge in orphan_edges:
            edge["groups"] = ["unassigned"]

    for current in groups.values():
        current["members"] = sorted(current["members"])
        for key in current["members"]:
            nodes[key]["groups"].append(current["id"])
    for node in nodes.values():
        node["groups"].sort()
        node["ports"].sort(key=lambda p: (p["index"], p["direction"], p["connection"]))
    if state(model) != before:
        raise RuntimeError("HVAC inspection changed in-memory model objects")
    return dict(
        nodes=sorted(nodes.values(), key=lambda n: n["handle"]),
        edges=sorted(edges, key=lambda e: (e["kind"], e["id"])),
        groups=sorted(groups.values(), key=lambda g: g["id"]),
        zones=sorted(zone_records, key=lambda z: z["handle"]),
        warnings=sorted(warnings, key=lambda w: (w["code"], w["handle"])),
        coverage=dict(
            native_connection_count=sum(
                x.iddObjectType().valueName() == "OS_Connection"
                for x in objects.values()
            ),
            represented_connection_count=sum(e["kind"] == "flow" for e in edges),
            embedded_air_paths="not_expanded",
            controls="stored_OSM_references_only; translator-generated controls not inferred",
            vrf="membership_only; refrigerant piping not inferred",
            sizing_or_operation_validated=False,
            warning_counts=dict(sorted(Counter(w["code"] for w in warnings).items())),
        ),
    )
