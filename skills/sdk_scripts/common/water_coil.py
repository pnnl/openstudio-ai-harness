"""Reviewed main-supply water-coil rating edits, attachment and replacement."""

from collections import Counter
import json
import math
from pathlib import Path
from common.coil_equipment import (
    CLASSES,
    RATINGS,
    kind_of,
    ratings,
    set_ratings,
    node_ports,
    finalize_controller,
    optional_value,
)
from common.hvac_equipment import call, schedule
from common.hvac_inventory import inventory as hvac_inventory, resolve
from common.model_preservation import fingerprint, snapshot


def ref(obj):
    return dict(
        handle=str(obj.handle()),
        name=obj.nameString(),
        type=obj.iddObjectType().valueName(),
    )


def object_by_ref(model, sdk, reference, cls):
    value = getattr(model, "get" + cls)(sdk.toUUID(reference["handle"]))
    if not value.is_initialized():
        raise ValueError(f"Selected {cls} is missing")
    return value.get()


def inventory(model):
    return dict(
        air_loops=[
            dict(
                ref(loop),
                split_supply=loop.supplySplitter().is_initialized()
                or len(loop.supplyOutletNodes()) != 1,
                supply_node_count=sum(
                    x.to_Node().is_initialized() for x in loop.supplyComponents()
                ),
            )
            for loop in sorted(
                model.getAirLoopHVACs(), key=lambda x: (x.nameString(), str(x.handle()))
            )
        ],
        supply_nodes=[
            dict(
                ref(x),
                air_loop_handle=str(loop.handle()),
                air_loop_name=loop.nameString(),
            )
            for loop in sorted(
                model.getAirLoopHVACs(), key=lambda x: (x.nameString(), str(x.handle()))
            )
            for x in loop.supplyComponents()
            if x.to_Node().is_initialized()
        ],
        water_coils=[
            dict(
                ref(c),
                kind=kind_of(c),
                ratings=ratings(c, kind_of(c)),
                direct_air_loop=(
                    ref(c.airLoopHVAC().get())
                    if c.airLoopHVAC().is_initialized()
                    else None
                ),
                plant_loop=(
                    ref(c.plantLoop().get()) if c.plantLoop().is_initialized() else None
                ),
            )
            for c in sorted(
                list(model.getCoilHeatingWaters()) + list(model.getCoilCoolingWaters()),
                key=lambda x: (x.nameString(), str(x.handle())),
            )
        ],
        plant_loops=hvac_inventory(model)["plant_loops"],
    )


def validate_config(config, mode):
    from common.input_validation import validate

    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "references"
            / (
                "water_coil_ratings.schema.json"
                if mode == "edit"
                else "water_coil_connection.schema.json"
            )
        ).read_text()
    )
    errors = validate(config, schema)
    if errors:
        raise ValueError(f"Invalid water-coil configuration: {errors}")


def check_ratings(kind, effective, patch, plant, errors, warnings):
    def number(key):
        value = effective.get(key)
        return (
            value
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            else None
        )

    if kind == "Heating":
        wi, wo, ai, ao = [
            number("rated_" + key + "_temperature_c")
            for key in ["inlet_water", "outlet_water", "inlet_air", "outlet_air"]
        ]
        if not (wi > wo and ao > ai and wi > ao and wo > ai):
            errors.append(
                "Heating ratings require inlet water > outlet water, outlet air > inlet air, and positive water/air temperature approaches"
            )
        if plant["design_supply_temperature_c"] <= ao:
            errors.append(
                "Heating plant design supply must exceed rated outlet air temperature"
            )
        if not math.isclose(
            wi, plant["design_supply_temperature_c"], abs_tol=0.05
        ) or not math.isclose(
            wo,
            plant["design_supply_temperature_c"] - plant["design_delta_temperature_k"],
            abs_tol=0.05,
        ):
            warnings.append(
                "Rated water conditions differ from plant design conditions; confirm manufacturer ratings and inspect sizing"
            )
        method = effective["performance_input_method"]
        if "rated_capacity_w" in patch and method != "NominalCapacity":
            errors.append(
                "rated_capacity_w changes require explicit effective performance_input_method=NominalCapacity"
            )
        if (
            "ua_w_per_k" in patch or "maximum_water_flow_m3_s" in patch
        ) and method != "UFactorTimesAreaAndDesignWaterFlowRate":
            errors.append(
                "UA/water-flow rating edits require UFactorTimesAreaAndDesignWaterFlowRate"
            )
    else:
        wi, ai, ao = [
            number("design_" + key + "_temperature_c")
            for key in ["inlet_water", "inlet_air", "outlet_air"]
        ]
        if ai is not None and ao is not None and ai <= ao:
            errors.append("Cooling design inlet air must exceed outlet air temperature")
        if wi is not None and ao is not None and wi >= ao:
            errors.append("Cooling design water must be colder than outlet air")
        if ao is not None and plant["design_supply_temperature_c"] >= ao:
            errors.append("Cooling plant design supply must be colder than outlet air")
        hi, ho = number("design_inlet_air_humidity_ratio"), number(
            "design_outlet_air_humidity_ratio"
        )
        if hi is not None and ho is not None and ho > hi:
            errors.append("Cooling design outlet humidity ratio cannot exceed inlet")
        if wi is not None and not math.isclose(
            wi, plant["design_supply_temperature_c"], abs_tol=0.05
        ):
            warnings.append(
                "Coil design inlet water differs from plant design supply; inspect sizing"
            )


def direct_context(model, sdk, reference, air_reference):
    coil = object_by_ref(model, sdk, reference, CLASSES[reference["kind"]])
    loop = object_by_ref(model, sdk, air_reference, "AirLoopHVAC")
    if loop.supplySplitter().is_initialized() or len(loop.supplyOutletNodes()) != 1:
        raise ValueError("Split main supply paths are outside this contract")
    if (
        str(coil.handle()) not in [str(x.handle()) for x in loop.supplyComponents()]
        or not coil.airLoopHVAC().is_initialized()
        or coil.airLoopHVAC().get().handle() != loop.handle()
    ):
        raise ValueError(
            "Select a direct main-supply coil; OA, unitary and terminal coils need separate coverage"
        )
    ports = node_ports(coil)
    if not coil.controllerWaterCoil().is_initialized():
        raise ValueError("Selected water coil has no controller")
    return coil, loop, ports


def original_types(model):
    return {
        str(x.handle()): x.iddObjectType().valueName()
        for x in model.modelObjects()
        if x.iddObjectType().valueName() != "OS_WeatherFile"
    }


def incoming(model, targets, allowed):
    for obj in model.modelObjects():
        if str(obj.handle()) in allowed:
            continue
        for i in range(obj.numFields()):
            target = obj.getTarget(i)
            if target.is_initialized() and str(target.get().handle()) in targets:
                raise ValueError(
                    f"Replacement needs a reference-migration contract for {obj.nameString()} ({obj.iddObjectType().valueName()})"
                )


def raw_fields(obj):
    raw = obj.idfObject()
    return {
        i: (
            (
                raw.iddObject().getField(i).get().name()
                if raw.iddObject().getField(i).is_initialized()
                else str(i)
            ),
            raw.getString(i).get() if raw.getString(i).is_initialized() else "",
        )
        for i in range(raw.numFields())
    }


def connection_handles(model, coil):
    target = str(coil.handle())
    return [
        str(x.handle())
        for x in model.modelObjects()
        if x.iddObjectType().valueName() == "OS_Connection"
        and any(
            x.getTarget(i).is_initialized()
            and str(x.getTarget(i).get().handle()) == target
            for i in (1, 3)
        )
    ]


def attachment_projection(model, sdk, kind, plant_ref, node_ref):
    """Preview only SDK topology on an isolated handle-preserving model copy.

    Existing graph changes must be node/port links or connector extensions. The
    saved validator separately checks original identities, exact supply order,
    demand ownership, preserved branches, object deltas and controller nodes.
    """
    before = original_types(model)
    preview = sdk.model.Model(model.clone(True))
    coil = getattr(sdk.model, CLASSES[kind])(preview)
    call(
        object_by_ref(preview, sdk, plant_ref, "PlantLoop"),
        "addDemandBranchForComponent",
        coil,
    )
    call(coil, "addToNode", object_by_ref(preview, sdk, node_ref, "Node"))
    after = original_types(preview)
    removed = sorted(before.keys() - after.keys())
    if any(before[h] != "OS_Connection" for h in removed):
        raise ValueError(
            "SDK attachment would remove an existing non-connection object"
        )
    ignored = {}
    limits = {}
    for handle in before.keys() & after.keys():
        old = model.getModelObject(sdk.toUUID(handle)).get()
        new = preview.getModelObject(sdk.toUUID(handle)).get()
        old_fields, new_fields = raw_fields(old), raw_fields(new)
        changed = [
            name
            for i, (name, value) in old_fields.items()
            if new_fields.get(i) != (name, value)
        ]
        added = set(new_fields) - set(old_fields)
        if not changed and not added:
            continue
        typ = before[handle]
        valid = all(
            name
            in (
                "Inlet Port",
                "Outlet Port",
                "Air Inlet Node Name",
                "Air Outlet Node Name",
            )
            or (
                typ in ("OS_Connector_Mixer", "OS_Connector_Splitter")
                and name in ("Inlet Branch Name", "Outlet Branch Name")
            )
            for name in changed
        )
        if not valid or (
            added and typ not in ("OS_Connector_Mixer", "OS_Connector_Splitter")
        ):
            raise ValueError(
                f"Unexpected SDK attachment side effect on {old.nameString()}"
            )
        ignored[handle] = changed
        if added:
            limits[handle] = len(old_fields)
    return dict(
        removed=removed,
        ignored=ignored,
        field_limits=limits,
        added_counts=dict(Counter(after[h] for h in after.keys() - before.keys())),
    )


def plan(model, sdk, config, mode):
    validate_config(config, mode)
    planned = dict(
        ready=False,
        parameters=dict(output_model_path=config["output_model_path"]),
        missing_inputs=[],
        errors=[],
        warnings=[],
        assumptions=[],
    )
    required = (
        ["coil", "ratings"]
        if mode == "edit"
        else [
            "air_loop",
            "plant_loop",
            "coil_name",
            "availability_schedule",
            "sizing",
            "controller",
        ]
        + (["coil"] if config.get("operation") == "replace" else ["kind", "air_node"])
    )
    if mode != "edit":
        required += ["design"] if config.get("operation") != "replace" else []
    for key in required:
        if key not in config or config[key] == {}:
            planned["missing_inputs"].append(key)
    if planned["missing_inputs"]:
        return planned
    catalog = inventory(model)
    selected = None
    loop = None
    operation = "edit" if mode == "edit" else config.get("operation", "attach")
    if operation in ("edit", "replace"):
        selected = resolve(
            config["coil"], catalog["water_coils"], "coil", planned["errors"]
        )
        if selected is None:
            return planned
        if not selected["direct_air_loop"] or not selected["plant_loop"]:
            planned["errors"].append(
                "Select a water coil connected to both main air supply and plant demand"
            )
            return planned
        coil, loop, ports = direct_context(
            model, sdk, selected, selected["direct_air_loop"]
        )
        kind = selected["kind"]
        before = ratings(coil, kind)
    else:
        kind = config["kind"]
        before = None
    plant_selector = (
        selected["plant_loop"] if operation == "edit" else config["plant_loop"]
    )
    plant = resolve(
        {
            k: v
            for k, v in plant_selector.items()
            if k in ("handle", "name")
            and (k == "handle" or "handle" not in plant_selector)
        },
        catalog["plant_loops"],
        "plant_loop",
        planned["errors"],
    )
    if plant is None:
        return planned
    if selected is not None and selected["handle"] not in {
        str(x.handle())
        for x in object_by_ref(model, sdk, plant, "PlantLoop").demandComponents()
    }:
        planned["errors"].append("Selected coil must be on plant demand, not supply")
    if plant["loop_type"] != kind or not all(
        plant[key]
        for key in ["supply_equipment", "supply_pumps", "supply_setpoint_managers"]
    ):
        planned["errors"].append(
            "Plant requires matching Heating/Cooling type, supply equipment, actual pump and outlet setpoint manager"
        )
    if (
        not math.isfinite(plant["design_supply_temperature_c"])
        or not math.isfinite(plant["design_delta_temperature_k"])
        or plant["design_delta_temperature_k"] <= 0
    ):
        planned["errors"].append(
            "Plant design conditions must be finite with positive delta temperature"
        )
    if operation == "edit":
        patch = config["ratings"]
        unknown = patch.keys() - RATINGS[kind].keys()
        if unknown:
            planned["errors"].append(
                f"Ratings do not apply to {kind}: {sorted(unknown)}"
            )
            return planned
        after = dict(before, **patch)
        if after == before:
            planned["errors"].append("Rating edit must change at least one value")
    else:
        loop_ref = resolve(
            config["air_loop"], catalog["air_loops"], "air_loop", planned["errors"]
        )
        if loop_ref is None:
            return planned
        loop = object_by_ref(model, sdk, loop_ref, "AirLoopHVAC")
        if loop_ref["split_supply"]:
            planned["errors"].append("Split supply paths are outside this contract")
        if any(
            x.nameString() == config["coil_name"]
            for x in list(model.getCoilHeatingWaters())
            + list(model.getCoilCoolingWaters())
            if selected is None or str(x.handle()) != selected["handle"]
        ):
            planned["errors"].append("New coil name already exists")
        # Schedule resolution uses existing candidates/builtins; it never drafts a schedule.
        selector = config["availability_schedule"]
        if "builtin" in selector:
            availability = selector
        else:
            availability = resolve(
                selector,
                hvac_inventory(model)["schedules"],
                "availability_schedule",
                planned["errors"],
            )
            if availability is None:
                return planned
            limits = availability.get("type_limits")
            if not limits or limits["unit_type"] != "Availability":
                planned["errors"].append(
                    "Availability schedule requires Availability type limits"
                )
        if operation == "replace":
            if (
                loop.handle() != coil.airLoopHVAC().get().handle()
                or plant["handle"] != selected["plant_loop"]["handle"]
            ):
                planned["errors"].append(
                    "Replacement is limited to the same air loop, water-coil class and plant"
                )
            after = dict(before, **config.get("design", {}))
            unknown = config.get("design", {}).keys() - RATINGS[kind].keys()
            if unknown:
                planned["errors"].append(
                    f"Design fields do not apply to {kind}: {sorted(unknown)}"
                )
                return planned
        else:
            design = config["design"]
            if kind == "Heating":
                fields = [
                    "rated_inlet_water_temperature_c",
                    "rated_outlet_water_temperature_c",
                    "rated_inlet_air_temperature_c",
                    "rated_outlet_air_temperature_c",
                ]
                extra = {
                    "performance_input_method": "UFactorTimesAreaAndDesignWaterFlowRate",
                    "rated_capacity_w": "Autosize",
                    "ua_w_per_k": "Autosize",
                    "maximum_water_flow_m3_s": "Autosize",
                }
            else:
                fields = [
                    "design_inlet_water_temperature_c",
                    "design_inlet_air_temperature_c",
                    "design_outlet_air_temperature_c",
                    "design_inlet_air_humidity_ratio",
                    "design_outlet_air_humidity_ratio",
                    "heat_exchanger_configuration",
                    "type_of_analysis",
                ]
                extra = {
                    "design_water_flow_m3_s": "Autosize",
                    "design_air_flow_m3_s": "Autosize",
                }
            planned["missing_inputs"] += [
                "design." + key for key in fields if key not in design
            ]
            if design.keys() - set(fields):
                planned["errors"].append(f"Attachment design fields must be {fields}")
            if planned["missing_inputs"] or planned["errors"]:
                return planned
            after = dict(design, **extra)
            node_ref = resolve(
                config["air_node"],
                [
                    x
                    for x in catalog["supply_nodes"]
                    if x["air_loop_handle"] == loop_ref["handle"]
                ],
                "air_node",
                planned["errors"],
            )
            if node_ref is None:
                return planned
            node = object_by_ref(model, sdk, node_ref, "Node")
            if node.handle() == loop.supplyInletNode().handle():
                planned["errors"].append(
                    "Choose a downstream main-supply node; the supply inlet has different insertion semantics"
                )
            # Each new Temperature controller needs a defined setpoint at its outlet.
            if not any(
                optional_value(x.controlVariable()) == "Temperature"
                for x in node.setpointManagers()
            ):
                planned["errors"].append(
                    "Attachment outlet node requires an existing Temperature setpoint manager"
                )
            if not node.getTarget(2).is_initialized():
                planned["errors"].append(
                    "Attachment node has no incoming supply connection"
                )
        if config["controller"]["minimum_flow_m3_s"] != 0:
            planned["errors"].append(
                "Initial autosized controller contract requires minimum_flow_m3_s=0"
            )
        if operation == "replace":
            after.update(
                {
                    key: "Autosize"
                    for key, (_, _, autosizable) in RATINGS[kind].items()
                    if autosizable
                    and (
                        key.endswith("_flow_m3_s")
                        or key in ("rated_capacity_w", "ua_w_per_k")
                    )
                }
            )
    # Autosizing all heating sizing fields is one explicit construction decision;
    # method-specific edit restrictions only apply to partial scalar edits.
    check_ratings(
        kind,
        after,
        config["ratings"] if operation == "edit" else {},
        plant,
        planned["errors"],
        planned["warnings"],
    )
    if planned["errors"]:
        return planned
    model.getWeatherFile()
    weather_was_empty = not any(
        value
        for name, value in raw_fields(model.getWeatherFile()).values()
        if name not in ("Handle", "Url", "Checksum")
    )
    original = original_types(model)
    params = dict(
        output_model_path=config["output_model_path"],
        operation=operation,
        kind=kind,
        ratings=after if operation != "edit" else patch,
    )
    resolved = dict(
        air_loop=ref(loop), plant_loop={k: plant[k] for k in ("name", "handle")}
    )
    protected_args = {}
    removed = []
    added_counts = {}
    if operation == "edit":
        resolved.update(coil=ref(coil), ports=ports)
        ignored = {str(coil.handle()): [RATINGS[kind][key][1] for key in patch]}
        protected_args = dict(ignored=ignored)
    else:
        params.update(
            coil_name=config["coil_name"],
            availability_schedule=availability,
            sizing=config["sizing"],
            controller=config["controller"],
        )
        if operation == "attach":
            resolved["air_node"] = node_ref
            projection = attachment_projection(
                model, sdk, kind, resolved["plant_loop"], node_ref
            )
            removed = projection.pop("removed")
            added_counts = projection.pop("added_counts")
            protected_args = dict(excluded=removed, **projection)
        else:
            controller = coil.controllerWaterCoil().get()
            connections = connection_handles(model, coil)
            metadata = [
                str(x.handle())
                for x in model.modelObjects()
                if x.iddObjectType().valueName() == "OS_AdditionalProperties"
                and x.getTarget(1).is_initialized()
                and x.getTarget(1).get().handle() == coil.handle()
            ]
            removed = [
                str(coil.handle()),
                str(controller.handle()),
                *connections,
                *metadata,
            ]
            incoming(
                model, {str(coil.handle()), str(controller.handle())}, set(removed)
            )
            resolved.update(coil=ref(coil), controller=ref(controller), ports=ports)
            ignored = {
                ports[i]: ["Outlet Port" if i in (0, 2) else "Inlet Port"]
                for i in range(4)
            }
            protected_args = dict(excluded=removed, ignored=ignored)
            added_counts = dict(Counter(original[h] for h in removed))
            params["metadata_signature"] = (
                fingerprint(
                    coil.additionalProperties(), ignored=("Handle", "Object Name")
                )
                if metadata
                else None
            )
    planned.update(
        ready=True,
        weather_was_empty=weather_was_empty,
        parameters=params,
        resolved_objects=resolved,
        before_values=before,
        after_values=after,
        protected_objects=snapshot(model, **protected_args),
        protection=protected_args,
        before_objects=original,
        removed_objects=removed,
        added_counts=added_counts,
        supply_order=[str(x.handle()) for x in loop.supplyComponents()],
        plant_supply_order=[
            str(x.handle())
            for x in object_by_ref(
                model, sdk, resolved["plant_loop"], "PlantLoop"
            ).supplyComponents()
        ],
        plant_demand_components=[
            str(x.handle())
            for x in object_by_ref(
                model, sdk, resolved["plant_loop"], "PlantLoop"
            ).demandComponents()
            if x.iddObjectType().valueName()
            not in ("OS_Node", "OS_Connector_Mixer", "OS_Connector_Splitter")
        ],
        impact=dict(
            operation=operation,
            air_loop=loop.nameString(),
            coil=selected["name"] if selected else config["coil_name"],
            plant=plant["name"],
            affected_zone_count=len(loop.thermalZones()),
            before=before,
            after=after,
            identity=(
                "retained" if operation == "edit" else "new coil/controller identity"
            ),
        ),
        assumptions=(
            [
                "Only requested ratings change; all connections/controllers/references retain identity"
            ]
            if operation == "edit"
            else [
                "Main supply only; Temperature controller; Flow actuator; autosized water/air flow and capacity; controller finalized after both connections"
            ]
        ),
    )
    return planned


def plan_edit(model, sdk, config):
    return plan(model, sdk, config, "edit")


def plan_connection(model, sdk, config):
    return plan(model, sdk, config, "connection")


def change(model, sdk, planned):
    p = planned["parameters"]
    r = planned["resolved_objects"]
    kind = p["kind"]
    mode = p["operation"]
    if mode == "edit":
        coil = object_by_ref(model, sdk, r["coil"], CLASSES[kind])
    elif mode == "attach":
        coil = getattr(sdk.model, CLASSES[kind])(model)
        call(
            object_by_ref(model, sdk, r["plant_loop"], "PlantLoop"),
            "addDemandBranchForComponent",
            coil,
        )
        call(coil, "addToNode", object_by_ref(model, sdk, r["air_node"], "Node"))
    else:
        old = object_by_ref(model, sdk, r["coil"], CLASSES[kind])
        controller = (
            old.controllerWaterCoil().get().clone(model).to_ControllerWaterCoil().get()
        )
        coil = getattr(old.clone(model), "to_" + CLASSES[kind])().get()
        # Retarget the cloned owned controller using the pinned IDD field name.
        fields = raw_fields(controller)
        index = next(i for i, (name, _) in fields.items() if name == "Water Coil Name")
        call(controller, "setPointer", index, coil.handle())
        nodes = [object_by_ref(model, sdk, {"handle": h}, "Node") for h in r["ports"]]
        for port in [
            old.airInletPort(),
            old.airOutletPort(),
            old.waterInletPort(),
            old.waterOutletPort(),
        ]:
            model.disconnect(old, port)
        old.remove()
        for a, b, i, o in [
            (nodes[0], nodes[1], coil.airInletPort(), coil.airOutletPort()),
            (nodes[2], nodes[3], coil.waterInletPort(), coil.waterOutletPort()),
        ]:
            model.connect(a, a.outletPort(), coil, i)
            model.connect(coil, o, b, b.inletPort())
    set_ratings(coil, kind, p["ratings"])
    if mode != "edit":
        call(coil, "setName", p["coil_name"])
        call(
            coil,
            "setAvailabilitySchedule",
            schedule(model, sdk, p["availability_schedule"]),
        )
        finalize_controller(coil, model, sdk, kind, p["controller"])
    return dict(
        operation=mode,
        coil=ref(coil),
        controller=ref(coil.controllerWaterCoil().get()),
        before=planned["before_values"],
        after=ratings(coil, kind),
    )


def validate_model(model, sdk, planned, result):
    p = planned["parameters"]
    r = planned["resolved_objects"]
    mode = p["operation"]
    kind = p["kind"]
    errors = []
    checks = 0

    def check(ok, text):
        nonlocal checks
        checks += 1
        if not ok:
            errors.append(text)

    coil = object_by_ref(model, sdk, result["coil"], CLASSES[kind])
    check(
        result["after"] == planned["after_values"]
        and result["before"] == planned["before_values"],
        "Reported ratings differ from the approved plan",
    )
    actual = ratings(coil, kind)
    for key, value in planned["after_values"].items():
        check(
            (
                math.isclose(actual[key], value, rel_tol=1e-9, abs_tol=1e-9)
                if isinstance(value, (int, float))
                and isinstance(actual[key], (int, float))
                else actual[key] == value
            ),
            f"Coil {key} differs from approved rating",
        )
    check(
        coil.airLoopHVAC().is_initialized()
        and str(coil.airLoopHVAC().get().handle()) == r["air_loop"]["handle"],
        "Wrong air-loop ownership",
    )
    check(
        coil.plantLoop().is_initialized()
        and str(coil.plantLoop().get().handle()) == r["plant_loop"]["handle"],
        "Wrong plant ownership",
    )
    ports = node_ports(coil)
    if mode in ("edit", "replace"):
        check(ports == r["ports"], "Boundary nodes changed")
    if mode == "edit":
        check(result["coil"] == r["coil"], "Rating edit changed coil identity")
    elif mode == "replace":
        check(
            result["coil"]["handle"] != r["coil"]["handle"],
            "Replacement retained old coil identity",
        )
        check(
            not model.getModelObject(
                sdk.toUUID(r["controller"]["handle"])
            ).is_initialized(),
            "Old controller remains",
        )
        if p["metadata_signature"] is not None:
            check(
                fingerprint(
                    coil.additionalProperties(), ignored=("Handle", "Object Name")
                )
                == p["metadata_signature"],
                "Replacement lost metadata",
            )
    else:
        check(
            ports[1] == r["air_node"]["handle"],
            "New coil outlet is not the selected node",
        )
    current = original_types(model)
    before = planned["before_objects"]
    removed = planned["removed_objects"]
    new = set(current) - set(before)
    check(
        sorted(set(before) - set(current)) == sorted(removed),
        "Unexpected removed object identities",
    )
    check(
        dict(Counter(current[h] for h in new)) == planned["added_counts"],
        "Unexpected added object types/counts",
    )
    protected_args = dict(planned["protection"])
    protected_args["excluded"] = list(protected_args.get("excluded", [])) + list(new)
    actual_snapshot = snapshot(model, **protected_args)
    expected_snapshot = dict(planned["protected_objects"])
    weather_target = planned["companions"].get("weather_resource")
    if planned["weather_was_empty"] and weather_target:
        # Workflow weather may fill previously absent OSM climate metadata.
        # Validate that data independently against the hash-bound source EPW.
        resource = next(
            x
            for x in planned["companions"]["resources"]
            if x["target"] == weather_target
        )
        expected_model = sdk.model.Model()
        expected_weather = sdk.model.WeatherFile.setWeatherFile(
            expected_model, sdk.EpwFile(resource["source"])
        )
        if not expected_weather.is_initialized():
            raise ValueError("Could not read companion weather metadata")
        expected_snapshot["@weather"] = fingerprint(
            expected_weather.get(), ignored=("Handle", "Url", "Checksum")
        )
    check(
        actual_snapshot == expected_snapshot,
        "Protected model objects changed",
    )
    loop = object_by_ref(model, sdk, r["air_loop"], "AirLoopHVAC")
    plant = object_by_ref(model, sdk, r["plant_loop"], "PlantLoop")
    order = [str(x.handle()) for x in loop.supplyComponents()]
    expected = list(planned["supply_order"])
    if mode == "replace":
        expected = [
            str(coil.handle()) if h == r["coil"]["handle"] else h for h in expected
        ]
    elif mode == "attach":
        # addToNode introduces exactly one new upstream air node and the new coil.
        idx = expected.index(r["air_node"]["handle"])
        expected[idx:idx] = [ports[0], str(coil.handle())]
    check(
        order == expected,
        "Supply component order changed outside selected insertion/replacement",
    )
    check(
        [str(x.handle()) for x in plant.supplyComponents()]
        == planned["plant_supply_order"],
        "Plant supply topology changed",
    )
    demand = [
        str(x.handle())
        for x in plant.demandComponents()
        if x.iddObjectType().valueName()
        not in ("OS_Node", "OS_Connector_Mixer", "OS_Connector_Splitter")
    ]
    expected_demand = list(planned["plant_demand_components"])
    if mode == "attach":
        expected_demand.append(str(coil.handle()))
    elif mode == "replace":
        expected_demand = [
            str(coil.handle()) if h == r["coil"]["handle"] else h
            for h in expected_demand
        ]
    check(
        sorted(demand) == sorted(expected_demand),
        "Plant demand components changed outside selected coil",
    )
    controller = coil.controllerWaterCoil().get()
    check(
        ref(controller) == result["controller"],
        "Controller identity differs from reported result",
    )
    if mode != "edit":
        check(coil.nameString() == p["coil_name"], "Coil name differs")
        check(
            str(coil.availabilitySchedule().handle())
            == str(schedule(model, sdk, p["availability_schedule"]).handle()),
            "Availability schedule differs",
        )
        check(
            controller.waterCoil().is_initialized()
            and controller.waterCoil().get().handle() == coil.handle(),
            "Controller targets another coil",
        )
        check(
            optional_value(controller.controlVariable())
            == p["controller"]["control_variable"]
            and optional_value(controller.action())
            == ("Normal" if kind == "Heating" else "Reverse")
            and optional_value(controller.actuatorVariable()) == "Flow",
            "Controller mode/action differs",
        )
        check(
            controller.minimumActuatedFlow() == p["controller"]["minimum_flow_m3_s"]
            and controller.isMaximumActuatedFlowAutosized(),
            "Controller flow settings differ",
        )
        tolerance = p["controller"]["convergence_tolerance_k"]
        check(
            (
                controller.isControllerConvergenceToleranceAutosized()
                if tolerance == "Autosize"
                else controller.controllerConvergenceTolerance().is_initialized()
                and math.isclose(
                    controller.controllerConvergenceTolerance().get(), tolerance
                )
            ),
            "Controller convergence differs",
        )
        check(
            controller.sensorNode().is_initialized()
            and str(controller.sensorNode().get().handle()) == ports[1],
            "Controller sensor node differs",
        )
        check(
            controller.actuatorNode().is_initialized()
            and str(controller.actuatorNode().get().handle()) == ports[2],
            "Controller actuator node differs",
        )
    return dict(ok=not errors, checks=checks, errors=errors)
