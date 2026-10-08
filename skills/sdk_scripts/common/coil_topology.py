"""Scoped graph/protected-object checks for genuine coil topology changes."""

from collections import Counter
from common.water_coil import original_types, raw_fields, ref
from common.model_preservation import snapshot, fingerprint


def connection_graph(model, tokens):
    edges = []
    for obj in model.modelObjects():
        if obj.iddObjectType().valueName() != "OS_Connection":
            continue
        fields = dict(raw_fields(obj).values())
        edges.append(
            [
                tokens.get(fields[key], fields[key])
                for key in (
                    "Source Object",
                    "Outlet Port",
                    "Target Object",
                    "Inlet Port",
                )
            ]
        )
    return sorted(edges)


def freeze(
    model, preview, sdk, *, allowed, removable, connection_scope, tokens, new_types
):
    """Reject preview side effects, then freeze the permitted graph and raw fields."""
    before, after = original_types(model), original_types(preview)
    removed = sorted(before.keys() - after.keys())
    for handle in removed:
        obj = model.getModelObject(sdk.toUUID(handle)).get()
        fields = dict(raw_fields(obj).values())
        if handle not in removable and not (
            before[handle] == "OS_Connection"
            and fields["Source Object"] in connection_scope
            and fields["Target Object"] in connection_scope
        ):
            raise ValueError(
                "Topology change would remove an unrelated object: " + obj.nameString()
            )
    ignored, limits = {}, {}
    for handle in before.keys() & after.keys():
        a = raw_fields(model.getModelObject(sdk.toUUID(handle)).get())
        b = raw_fields(preview.getModelObject(sdk.toUUID(handle)).get())
        changed = {name for i, (name, value) in a.items() if b.get(i) != (name, value)}
        fields = set(allowed.get(handle, []))
        added = b.keys() - a.keys()
        if changed - fields or (added and any(b[i][0] not in fields for i in added)):
            obj = model.getModelObject(sdk.toUUID(handle)).get()
            raise ValueError(
                f"Unapproved topology side effect on {obj.iddObjectType().valueName()} '{obj.nameString()}' ({handle}): {sorted(changed - fields)}"
            )
        if added:
            limits[handle] = len(a)
        if fields:
            ignored[handle] = sorted(fields)
    added_counts = dict(Counter(after[h] for h in after.keys() - before.keys()))
    if set(added_counts) - set(new_types):
        raise ValueError("Topology change creates unapproved object types")
    protection = dict(excluded=removed, ignored=ignored, field_limits=limits)
    return dict(
        before_objects=before,
        removed_objects=removed,
        added_counts=added_counts,
        protection=protection,
        protected_objects=snapshot(model, **protection),
        connection_graph=connection_graph(preview, tokens),
    )


def protected_state(model, sdk, planned):
    current = original_types(model)
    new = current.keys() - planned["before_objects"].keys()
    args = dict(planned["protection"])
    args["excluded"] = list(args["excluded"]) + sorted(new)
    expected = dict(planned["protected_objects"])
    companions = planned.get("companions", {})
    weather = companions.get("weather_resource")
    if planned.get("weather_was_empty") and weather:
        source = next(
            x["source"] for x in companions["resources"] if x["target"] == weather
        )
        reference = sdk.model.Model()
        native_weather = sdk.model.WeatherFile.setWeatherFile(
            reference, sdk.EpwFile(source)
        )
        if not native_weather.is_initialized():
            raise ValueError("Could not read companion weather metadata")
        expected["@weather"] = fingerprint(
            native_weather.get(), ignored=("Handle", "Url", "Checksum")
        )
    return snapshot(model, **args) == expected


def remaining_demand(plant, coil):
    equipment = {
        str(x.handle()): x
        for x in plant.demandComponents()
        if x.handle() != coil.handle()
        and x.iddObjectType().valueName()
        not in ("OS_Node", "OS_Connector_Mixer", "OS_Connector_Splitter")
        and not x.iddObjectType()
        .valueName()
        .startswith(("OS_Pipe_", "OS_Pump_", "OS_HeaderedPumps_"))
    }
    return dict(
        source_plant_remaining_coil_count=sum(
            x.iddObjectType().valueName().startswith("OS_Coil_")
            for x in equipment.values()
        ),
        source_plant_remaining_demand_equipment_count=len(equipment),
        source_plant_will_be_unserved=not equipment,
    )


def control_context(model, sdk, coil, loop):
    """Describe translated temperature control, including SDK-generated managers.

    OSM manager inventory alone misses the translator's default MixedAir control.
    Compare these fields independently after saving, not just coil capacity.
    """
    getter = getattr(coil, "airOutletModelObject", None) or coil.outletModelObject
    outlet = getter().get().to_Node().get()
    translator = sdk.energyplus.ForwardTranslator()
    workspace = translator.translateModel(model)
    if translator.errors():
        raise ValueError(
            "Cannot verify translated coil control: "
            + "; ".join(x.logMessage() for x in translator.errors())
        )
    node_lists = {
        x.getString(0).get(): [x.getString(i).get() for i in range(1, x.numFields())]
        for x in workspace.getObjectsByType(sdk.IddObjectType("NodeList"))
    }
    managers = []
    for obj in workspace.objects():
        kind = obj.iddObject().name()
        if not kind.startswith("SetpointManager:"):
            continue
        fields = {
            obj.iddObject().getField(i).get().name(): optional_string(obj, i)
            for i in range(obj.numFields())
        }
        targets = fields.get(
            "Setpoint Node or NodeList Name", fields.get("Setpoint Node Name", "")
        )
        if (
            outlet.nameString() not in node_lists.get(targets, [targets])
            or fields.get("Control Variable", "Temperature") != "Temperature"
        ):
            continue
        fields.pop("Name", None)
        managers.append(dict(type=kind, fields=fields))
    managers.sort(key=lambda x: (x["type"], str(sorted(x["fields"].items()))))
    components = list(loop.supplyComponents())
    index = next(i for i, x in enumerate(components) if x.handle() == coil.handle())
    fans = [
        dict(fan=ref(x), coil_position="upstream" if index < i else "downstream")
        for i, x in enumerate(components)
        if x.iddObjectType().valueName().startswith("OS_Fan_")
    ]
    positions = {x["coil_position"] for x in fans}
    position = (
        "upstream of supply fan(s) (draw-through)"
        if positions == {"upstream"}
        else (
            "downstream of supply fan(s) (blow-through)"
            if positions == {"downstream"}
            else "between supply fans" if positions else "no direct supply fan"
        )
    )
    if outlet.handle() == loop.supplyOutletNode().handle():
        description = "direct supply-outlet temperature setpoint; no downstream-fan heat offset at the coil outlet"
    elif any(x["type"] == "SetpointManager:MixedAir" for x in managers):
        description = (
            "supply-air reference setpoint with fan heat compensation (MixedAir)"
        )
    else:
        description = "existing outlet temperature control: " + ", ".join(
            x["type"] for x in managers
        )
    return dict(
        outlet_node=ref(outlet),
        supply_outlet_node=ref(loop.supplyOutletNode()),
        managers=managers,
        fans=fans,
        position_relative_to_fan=position,
        control_reference=description,
    )


def optional_string(obj, index):
    value = obj.getString(index)
    return value.get() if value.is_initialized() else ""
