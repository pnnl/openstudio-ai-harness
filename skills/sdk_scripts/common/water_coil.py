"""Reviewed main-supply water-coil edits, attachment and plant migration."""

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
    CONTROLLER_FIELDS,
    controller_values,
    set_controller_settings,
)
from common.hvac_equipment import call, schedule
from common.hvac_inventory import inventory as hvac_inventory, resolve
from common.model_preservation import fingerprint, snapshot

HEATING_TEMPERATURE_FIELDS = tuple(
    key for key in RATINGS["Heating"] if key.endswith("_temperature_c")
)


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
                supply_outlet_node=ref(loop.supplyOutletNode()),
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
                attachment_supported=x.handle() == loop.supplyOutletNode().handle(),
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
                "water_coil_edit.schema.json"
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
        method = effective["performance_input_method"]
        # EnergyPlus validates these input relationships even under the UA method.
        if not (wi > wo and ao > ai and wi > ai):
            errors.append(
                "Heating ratings require inlet water > outlet water, outlet air > inlet air, and inlet water > inlet air"
            )
        if method == "NominalCapacity":
            if not (wi > ao and wo > ai):
                errors.append(
                    "Nominal heating ratings require positive water/air temperature approaches"
                )
            if plant["design_supply_temperature_c"] <= ao:
                errors.append(
                    "Heating plant design supply must exceed rated outlet air temperature"
                )
            if not math.isclose(
                wi, plant["design_supply_temperature_c"], abs_tol=0.05
            ) or not math.isclose(
                wo,
                plant["design_supply_temperature_c"]
                - plant["design_delta_temperature_k"],
                abs_tol=0.05,
            ):
                warnings.append(
                    "Rated water conditions differ from plant design conditions; confirm manufacturer ratings and inspect sizing"
                )
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


def settings(coil):
    controller = coil.controllerWaterCoil().get()
    return dict(
        coil_name=coil.nameString(),
        availability_schedule=ref(coil.availabilitySchedule()),
        controller_name=controller.nameString(),
        controller=controller_values(controller),
    )


def autosized_sizes(kind):
    return {
        key: "Autosize"
        for key, (_, _, autosizable) in RATINGS[kind].items()
        if autosizable
        and (key.endswith("_flow_m3_s") or key in ("rated_capacity_w", "ua_w_per_k"))
    }


def resolve_availability(model, selector, errors):
    if "builtin" in selector:
        return selector
    availability = resolve(
        selector, hvac_inventory(model)["schedules"], "availability_schedule", errors
    )
    if availability is not None:
        limits = availability.get("type_limits")
        if not limits or limits["unit_type"] != "Availability":
            errors.append("Availability schedule requires Availability type limits")
    return availability


def heating_rating_usage(values, loop, plant, default_fields):
    ua = values["performance_input_method"] == "UFactorTimesAreaAndDesignWaterFlowRate"
    return dict(
        performance_input_method=values["performance_input_method"],
        rated_temperatures_set_ua_design_point=False,
        rated_temperature_role="informational" if ua else "nominal_capacity_rating",
        defaulted_rating_fields=sorted(default_fields),
        message=(
            "Rated temperatures are informational under the UA method; they do not set the coil design point. "
            "Autosizing uses plant and air-system sizing conditions. EnergyPlus still checks input temperature relationships."
            if ua
            else "Rated temperatures describe NominalCapacity rating inputs; an autosized nominal capacity may use system sizing conditions instead."
        ),
        sizing_context=dict(
            plant_supply_temperature_c=plant["design_supply_temperature_c"],
            plant_delta_temperature_k=plant["design_delta_temperature_k"],
            system_heating_supply_air_temperature_c=loop.sizingSystem().centralHeatingDesignSupplyAirTemperature(),
            system_preheat_air_temperature_c=loop.sizingSystem().preheatDesignTemperature(),
        ),
    )


def plan(model, sdk, config, mode, *, topology_change=False):
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
        ["coil"]
        if mode == "edit"
        else [
            "air_loop",
            "plant_loop",
            "coil_name",
            "availability_schedule",
            "sizing",
            "controller",
            "kind",
            "air_node",
        ]
    )
    if mode != "edit" and config.get("kind") == "Cooling":
        required.append("design")
    if mode == "edit" and not any(
        config.get(key)
        for key in (
            "ratings",
            "coil_name",
            "availability_schedule",
            "sizing",
            "controller",
            "controller_name",
        )
    ):
        planned["missing_inputs"].append("requested_changes")
    for key in required:
        if key not in config or config[key] == {}:
            planned["missing_inputs"].append(key)
    if planned["missing_inputs"]:
        return planned
    catalog = inventory(model)
    selected = None
    loop = None
    operation = "edit" if mode == "edit" else "attach"
    if operation == "edit":
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
        before_settings = settings(coil)
    else:
        kind = config["kind"]
        before = None
        before_settings = None
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
    if plant["loop_type"] != kind:
        planned["errors"].append("Plant must have matching Heating/Cooling type")
    missing_plant_components = [
        label
        for key, label in (
            ("supply_equipment", "supply equipment"),
            ("supply_pumps", "actual pump"),
            ("supply_setpoint_managers", "outlet setpoint manager"),
        )
        if not plant[key]
    ]
    if missing_plant_components:
        message = "Plant is missing " + ", ".join(missing_plant_components)
        if operation == "edit":
            planned["warnings"].append(
                message
                + "; editing preserves this plant; repair it before sizing/simulation"
            )
            planned["simulation_ready"] = False
        else:
            planned["errors"].append(message + "; required for attachment")
    if (
        not math.isfinite(plant["design_supply_temperature_c"])
        or not math.isfinite(plant["design_delta_temperature_k"])
        or plant["design_delta_temperature_k"] <= 0
    ):
        planned["errors"].append(
            "Plant design conditions must be finite with positive delta temperature"
        )
    if operation == "edit":
        patch = dict(config.get("ratings", {}))
        explicit_patch = dict(patch)
        sizing_patch = autosized_sizes(kind) if config.get("sizing") else {}
        if any(key in patch and patch[key] != "Autosize" for key in sizing_patch):
            planned["errors"].append(
                "Fixed size ratings conflict with sizing: Autosize"
            )
        patch.update(sizing_patch)
        unknown = patch.keys() - RATINGS[kind].keys()
        if unknown:
            planned["errors"].append(
                f"Ratings do not apply to {kind}: {sorted(unknown)}"
            )
            return planned
        after = dict(before, **patch)

    else:
        loop_ref = resolve(
            config["air_loop"], catalog["air_loops"], "air_loop", planned["errors"]
        )
        if loop_ref is None:
            return planned
        loop = object_by_ref(model, sdk, loop_ref, "AirLoopHVAC")
        if loop_ref["split_supply"]:
            planned["errors"].append("Split supply paths are outside this contract")
        design = config.get("design", {})
        if kind == "Heating":
            fields = list(HEATING_TEMPERATURE_FIELDS)
            # Keep omitted nominal-rating metadata at the pinned SDK defaults.
            # This isolated object never enters the input model or its snapshot.
            default_model = sdk.model.Model()
            defaults = ratings(sdk.model.CoilHeatingWater(default_model), kind)
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
        if kind == "Cooling":
            planned["missing_inputs"] += [
                "design." + key for key in fields if key not in design
            ]
        if design.keys() - set(fields):
            planned["errors"].append(f"Attachment design fields must be {fields}")
        if planned["missing_inputs"] or planned["errors"]:
            return planned
        after = (
            dict(defaults, **design, **extra)
            if kind == "Heating"
            else dict(design, **extra)
        )
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
        if node.handle() != loop.supplyOutletNode().handle():
            planned["errors"].append(
                "Attachment requires the main supply outlet node; other nodes insert the coil downstream"
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
    availability = None
    schedule_additions = {}
    if "coil_name" in config and any(
        x.nameString() == config["coil_name"]
        for x in list(model.getCoilHeatingWaters()) + list(model.getCoilCoolingWaters())
        if selected is None or str(x.handle()) != selected["handle"]
    ):
        planned["errors"].append("New coil name already exists")
    if "availability_schedule" in config:
        availability = resolve_availability(
            model, config["availability_schedule"], planned["errors"]
        )
        if availability is None:
            return planned
        preview = sdk.model.Model(model.clone(True))
        expected_schedule = schedule(preview, sdk, availability)
        original_handles = original_types(model)
        schedule_additions = dict(
            Counter(
                t
                for h, t in original_types(preview).items()
                if h not in original_handles
            )
        )
    if operation == "edit":
        after_settings = dict(
            before_settings, controller=dict(before_settings["controller"])
        )
        if "controller_name" in config and any(
            x.nameString() == config["controller_name"]
            and x.handle() != coil.controllerWaterCoil().get().handle()
            for x in model.getControllerWaterCoils()
        ):
            planned["errors"].append("Controller name already exists")
        for key in ("coil_name", "controller_name"):
            if key in config:
                after_settings[key] = config[key]
        if availability is not None:
            after_settings["availability_schedule"] = (
                ref(expected_schedule)
                if str(expected_schedule.handle()) in original_types(model)
                else availability
            )
        controller_patch = dict(config.get("controller", {}))
        if config.get("sizing"):
            if controller_patch.get("maximum_flow_m3_s", "Autosize") != "Autosize":
                planned["errors"].append(
                    "Fixed controller maximum flow conflicts with sizing: Autosize"
                )
            controller_patch["maximum_flow_m3_s"] = "Autosize"
        after_settings["controller"].update(controller_patch)
        expected_action = "Normal" if kind == "Heating" else "Reverse"
        if (
            "action" in controller_patch
            and controller_patch["action"] != expected_action
        ):
            planned["errors"].append(
                f"{kind} water-coil controller action must be {expected_action}"
            )
        minimum = after_settings["controller"]["minimum_flow_m3_s"]
        maximum = after_settings["controller"]["maximum_flow_m3_s"]
        if isinstance(maximum, (int, float)) and minimum > maximum:
            planned["errors"].append("Controller minimum flow exceeds maximum flow")
        if (
            after == before
            and after_settings == before_settings
            and not topology_change
        ):
            planned["errors"].append("Edit must change at least one value")
    else:
        after_settings = dict(
            coil_name=config["coil_name"],
            controller_name=config["coil_name"] + " Controller",
            availability_schedule=availability,
            controller=dict(
                config["controller"],
                action="Normal" if kind == "Heating" else "Reverse",
                actuator_variable="Flow",
                maximum_flow_m3_s="Autosize",
            ),
        )
    # Autosizing all heating sizing fields is one explicit construction decision;
    # method-specific edit restrictions only apply to partial scalar edits.
    check_ratings(
        kind,
        after,
        explicit_patch if operation == "edit" else {},
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
        controller = coil.controllerWaterCoil().get()
        resolved.update(coil=ref(coil), controller=ref(controller), ports=ports)
        ignored = {str(coil.handle()): [RATINGS[kind][key][1] for key in patch]}
        for key, raw_name in (
            ("coil_name", "Name"),
            ("availability_schedule", "Availability Schedule Name"),
        ):
            if key in config:
                ignored[str(coil.handle())].append(raw_name)
        ignored[str(controller.handle())] = [
            CONTROLLER_FIELDS[key][1] for key in controller_patch
        ]
        if "controller_name" in config:
            ignored[str(controller.handle())].append("Name")
        # Reports sort JSON keys; protection lists must be independent of input order.
        ignored = {handle: sorted(fields) for handle, fields in ignored.items()}
        protected_args = dict(ignored=ignored)
        params["controller"] = controller_patch
        for key in ("coil_name", "controller_name", "sizing"):
            if key in config:
                params[key] = config[key]
        if availability is not None:
            params["availability_schedule"] = availability
    else:
        params.update(
            coil_name=config["coil_name"],
            availability_schedule=availability,
            sizing=config["sizing"],
            controller=config["controller"],
        )
        resolved["air_node"] = node_ref
        projection = attachment_projection(
            model, sdk, kind, resolved["plant_loop"], node_ref
        )
        removed = projection.pop("removed")
        added_counts = projection.pop("added_counts")
        protected_args = dict(excluded=removed, **projection)
    added_counts = dict(Counter(added_counts) + Counter(schedule_additions))
    planned.update(
        ready=True,
        weather_was_empty=weather_was_empty,
        parameters=params,
        resolved_objects=resolved,
        before_values=before,
        after_values=after,
        before_settings=before_settings,
        after_settings=after_settings,
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
            before=dict(ratings=before, settings=before_settings),
            after=dict(ratings=after, settings=after_settings),
            identity=(
                "retained" if operation == "edit" else "new coil/controller identity"
            ),
        ),
        assumptions=(
            [
                "Only requested coil/controller settings change; connections, metadata and references retain identity"
            ]
            if operation == "edit"
            else [
                "Main supply only; Temperature controller; Flow actuator; autosized water/air flow and capacity; controller finalized after both connections"
            ]
        ),
    )
    if kind == "Heating":
        default_fields = (
            set(HEATING_TEMPERATURE_FIELDS) - config.get("design", {}).keys()
            if operation == "attach"
            else set()
        )
        usage = heating_rating_usage(after, loop, plant, default_fields)
        planned["rating_usage"] = usage
        planned["impact"]["rating_usage"] = usage
        planned["assumptions"].append(usage["message"])
        planned["assumption_review"] = dict(status="informational", items=[usage])
    return planned


def plan_edit(model, sdk, config):
    return plan(model, sdk, config, "edit")


def plan_connection(model, sdk, config):
    if config.get("operation") == "relocate_air":
        from common.coil_relocation import plan_relocation

        validate_config(config, "connection")
        return plan_relocation(model, sdk, config)
    if config.get("operation") == "migrate_plant":
        from common.coil_migration import plan_migration

        validate_config(config, "connection")
        return plan_migration(model, sdk, config)
    return plan(model, sdk, config, "connection")


def change(model, sdk, planned):
    if planned["parameters"]["operation"] == "relocate_air":
        from common.coil_relocation import relocate

        return relocate(model, sdk, planned)
    if planned["parameters"]["operation"] == "migrate_plant":
        from common.coil_migration import migrate

        return migrate(model, sdk, planned)
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
        raise ValueError(
            "Unsupported water-coil operation; only edit and attach are exported"
        )
    set_ratings(coil, kind, p["ratings"])
    if "coil_name" in p:
        call(coil, "setName", p["coil_name"])
    if "availability_schedule" in p:
        call(
            coil,
            "setAvailabilitySchedule",
            schedule(model, sdk, p["availability_schedule"]),
        )
    if mode == "attach":
        finalize_controller(coil, model, sdk, kind, p["controller"])
    else:
        controller = coil.controllerWaterCoil().get()
        set_controller_settings(controller, p["controller"])
        if "controller_name" in p:
            call(controller, "setName", p["controller_name"])
    return dict(
        operation=mode,
        coil=ref(coil),
        controller=ref(coil.controllerWaterCoil().get()),
        before=planned["before_values"],
        after=ratings(coil, kind),
        before_settings=planned["before_settings"],
        after_settings=settings(coil),
    )


def validate_model(model, sdk, planned, result):
    if planned["parameters"]["operation"] == "relocate_air":
        from common.coil_relocation import validate_relocation

        return validate_relocation(model, sdk, planned, result)
    if planned["parameters"]["operation"] == "migrate_plant":
        from common.coil_migration import validate_migration

        return validate_migration(model, sdk, planned, result)
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
    if mode == "edit":
        check(ports == r["ports"], "Boundary nodes changed")
        check(
            result["coil"]["handle"] == r["coil"]["handle"],
            "Edit changed coil identity",
        )
        check(
            result["controller"]["handle"] == r["controller"]["handle"],
            "Edit changed controller identity",
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
    if mode == "attach":
        # addToNode introduces exactly one new upstream air node and the new coil.
        idx = expected.index(r["air_node"]["handle"])
        expected[idx:idx] = [ports[0], str(coil.handle())]
    check(
        order == expected,
        "Supply component order changed outside selected insertion",
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
    check(
        sorted(demand) == sorted(expected_demand),
        "Plant demand components changed outside selected coil",
    )
    controller = coil.controllerWaterCoil().get()
    check(
        ref(controller) == result["controller"],
        "Controller identity differs from reported result",
    )
    actual_settings = settings(coil)
    check(
        result["before_settings"] == planned["before_settings"],
        "Reported original settings differ",
    )
    check(result["after_settings"] == actual_settings, "Reported saved settings differ")
    expected_settings = dict(planned["after_settings"])
    if "availability_schedule" in p:
        expected_settings["availability_schedule"] = ref(
            schedule(model, sdk, p["availability_schedule"])
        )
    check(
        actual_settings == expected_settings,
        "Coil/controller settings differ from approved settings",
    )
    check(
        controller.waterCoil().is_initialized()
        and controller.waterCoil().get().handle() == coil.handle(),
        "Controller targets another coil",
    )
    if mode == "attach":
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
