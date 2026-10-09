"""Reviewed single-pump class changes, retaining plant boundaries and controls."""

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

from common.input_validation import validate
from common.hvac_inventory import resolve
from common.pump_edit import (
    SUPPORTED,
    FIELDS,
    inventory,
    pump_object,
    ports,
    ref,
    values,
    sized,
    matches,
    curve_minimum,
    power_check,
)
from common.hvac_equipment import call
from common.water_coil import raw_fields, original_types, object_by_ref
from common.coil_topology import freeze, connection_graph, protected_state
from common.model_preservation import fingerprint

SHARED_OUTPUTS = frozenset(
    x.casefold()
    for x in (
        "Pump Electricity Rate",
        "Pump Electricity Energy",
        "Pump Shaft Power",
        "Pump Fluid Heat Gain Rate",
        "Pump Fluid Heat Gain Energy",
        "Pump Outlet Temperature",
        "Pump Mass Flow Rate",
    )
)


def optional_ref(value):
    return ref(value.get()) if value.is_initialized() else None


def settings(pump):
    result = values(pump)
    result["rated_flow_m3_s"] = sized(pump, "ratedFlowRate")
    result["end_use_subcategory"] = pump.endUseSubcategory()
    result["flow_schedule"] = optional_ref(pump.pumpFlowRateSchedule())
    result["zone"] = optional_ref(pump.zone())
    rad = pump.skinLossRadiativeFraction()
    # ConstantSpeed's blank is zero radiation in EnergyPlus; VariableSpeed defaults 0.5.
    result["skin_loss_radiative_fraction"] = (
        (rad.get() if rad.is_initialized() else 0.0)
        if hasattr(rad, "is_initialized")
        else rad
    )
    if pump.iddObjectType().valueName() == "OS_Pump_VariableSpeed":
        result["minimum_flow_m3_s"] = pump.minimumFlowRate()
        result["design_minimum_flow_fraction"] = pump.designMinimumFlowRateFraction()
    return result


def unsupported(pump):
    fields = dict(raw_fields(pump).values())
    names = (
        "Pump Curve",
        "Pump Curve Name",
        "Impeller Diameter",
        "Rotational Speed",
        "VFD Control Type",
        "Pump RPM Schedule Name",
        "Minimum Pressure Schedule",
        "Maximum Pressure Schedule",
        "Minimum RPM Schedule",
        "Maximum RPM Schedule",
    )
    return [name for name in names if fields.get(name)]


def retained_keys(obj, old):
    kind, fields = obj.iddObjectType().valueName(), raw_fields(obj)
    return {
        i: dict(field_index=i, variable=fields.get(i + 1, ("", ""))[1], key=value)
        for i, (name, value) in fields.items()
        if value.casefold() == old["name"].casefold()
        and (
            kind == "OS_Output_Variable"
            and name == "Key Value"
            and fields.get(i + 1, ("", ""))[1].casefold() in SHARED_OUTPUTS
            or kind in ("OS_Meter_Custom", "OS_Meter_CustomDecrement")
            and name == "Key Name"
            and fields.get(i + 1, ("", ""))[1].casefold() == "pump electricity energy"
        )
    }


def retained_references(model, old):
    kept = [
        dict(object=ref(obj), keys=list(keys.values()))
        for obj in model.modelObjects()
        if (keys := retained_keys(obj, old))
    ]
    meter_names = {
        x["object"]["name"].casefold()
        for x in kept
        if x["object"]["type"] in ("OS_Meter_Custom", "OS_Meter_CustomDecrement")
    }
    kept.extend(
        dict(object=ref(meter), meter_name=meter.nameString())
        for meter in model.getOutputMeters()
        if meter.nameString().casefold() in meter_names
    )
    return sorted(kept, key=lambda x: (x["object"]["type"], x["object"]["handle"]))


def controls(model, sdk):
    ft = sdk.energyplus.ForwardTranslator()
    workspace = ft.translateModel(model)
    if ft.errors():
        raise ValueError(
            "Cannot verify translated plant controls: "
            + "; ".join(x.logMessage() for x in ft.errors())
        )
    return sorted(
        [
            obj.iddObject().name(),
            [
                obj.getString(i).get() if obj.getString(i).is_initialized() else ""
                for i in range(obj.numFields())
            ],
        ]
        for obj in workspace.objects()
        if obj.iddObject()
        .name()
        .startswith(
            (
                "SetpointManager:",
                "NodeList",
                "PlantEquipmentOperation:",
                "AvailabilityManager:",
            )
        )
    )


def target_signature(pump):
    return fingerprint(pump, ignored=("Handle", "Inlet Node Name", "Outlet Node Name"))


def expected_controls(planned):
    """Update only a selected pump's class in component-setpoint references."""
    result = deepcopy(planned["before_controls"])
    old = planned["resolved_objects"]["pump"]
    old_type = old["type"].replace("OS_Pump_", "Pump:")
    new_type = "Pump:" + planned["parameters"]["target_class"]
    for kind, fields in result:
        if kind == "PlantEquipmentOperation:ComponentSetpoint":
            for i in range(len(fields) - 1):
                if fields[i] == old_type and fields[i + 1] == old["name"]:
                    fields[i] = new_type
    return sorted(result)


def demand_bypass(loop, sdk):
    """Identify complete, uncontrolled pipe-only splitter-to-mixer paths."""
    passive_pipes = {
        "OS_Pipe_Adiabatic",
        "OS_Pipe_Indoor",
        "OS_Pipe_Outdoor",
        "OS_Pipe_Underground",
    }
    mixer = loop.demandMixer()
    paths = []
    for start in loop.demandSplitter().outletModelObjects():
        components = list(loop.demandComponents(start.to_HVACComponent().get(), mixer))
        equipment = [
            x
            for x in components
            if x.iddObjectType().valueName() not in ("OS_Node", "OS_Connector_Mixer")
        ]
        if (
            components
            and components[-1].handle() == mixer.handle()
            and all(x.iddObjectType().valueName() in passive_pipes for x in equipment)
        ):
            paths.append(ref(start))
    # The pinned translator can synthesize a bypass absent from the OSM.
    translator = sdk.energyplus.ForwardTranslator()
    workspace = translator.translateModel(loop.model())
    if translator.errors():
        raise ValueError("Cannot verify translated demand bypass")

    def lookup(kind, name):
        obj = next(
            (
                obj
                for obj in workspace.getObjectsByType(sdk.IddObjectType(kind))
                if obj.nameString() == name
            ),
            None,
        )
        if obj is None:
            raise ValueError(
                f"Cannot verify translated demand bypass: missing {kind} '{name}'"
            )
        return obj

    plant = lookup("PlantLoop", loop.nameString())
    field_name = "Demand Side Connector List Name"
    index = plant.iddObject().getFieldIndex(field_name)
    if not index.is_initialized():
        raise ValueError(
            f"Cannot verify translated demand bypass: missing PlantLoop field '{field_name}'"
        )
    connector_name = plant.getString(index.get())
    if not connector_name.is_initialized() or not connector_name.get().strip():
        raise ValueError(
            f"Cannot verify translated demand bypass: empty PlantLoop field '{field_name}'"
        )
    # Extensible groups contain connector type/name, splitter branch names and
    # branch components.
    connectors = lookup("ConnectorList", connector_name.get())
    splitter_name = next(
        (
            group.getString(1).get()
            for group in connectors.extensibleGroups()
            if group.getString(0).get() == "Connector:Splitter"
        ),
        None,
    )
    if splitter_name is None:
        raise ValueError(
            "Cannot verify translated demand bypass: missing Connector:Splitter entry"
        )
    translated = []
    for group in lookup("Connector:Splitter", splitter_name).extensibleGroups():
        name = group.getString(0).get()
        equipment = lookup("Branch", name).extensibleGroups()
        if equipment and all(
            group.getString(0).get()
            in {"Pipe:Adiabatic", "Pipe:Indoor", "Pipe:Outdoor", "Pipe:Underground"}
            for group in equipment
        ):
            translated.append(name)
    return dict(
        status="present" if paths else "not_found",
        uncontrolled_branch_count=len(paths),
        uncontrolled_branch_inlets=sorted(paths, key=lambda x: x["handle"]),
        detection="Complete pipe-only or empty demand splitter-to-mixer paths; other passive equipment is not classified",
        common_pipe_simulation=loop.commonPipeSimulation(),
        translated_uncontrolled_branch_count=len(translated),
        translated_uncontrolled_branch_names=sorted(translated),
    )


def plan(model, sdk, config):
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "references/pump_replacement.schema.json"
        ).read_text()
    )
    errors = validate(config, schema)
    if errors:
        raise ValueError("Invalid pump replacement configuration: " + "; ".join(errors))
    required = (
        "plant_loop",
        "pump",
        "target_class",
        "flow_policy",
        "power_policy",
        "plant_policy",
        "reference_policy",
    )
    planned = dict(
        ready=False,
        parameters=dict(output_model_path=config["output_model_path"]),
        missing_inputs=[key for key in required if key not in config],
        errors=[],
        warnings=[],
        assumptions=[],
    )
    if planned["missing_inputs"]:
        return planned
    if config["target_class"] == "VariableSpeed":
        if "variable_speed" not in config:
            planned["missing_inputs"].append("variable_speed")
        else:
            planned["missing_inputs"].extend(
                "variable_speed." + key
                for key in ("minimum_flow_m3_s", "power_coefficients")
                if key not in config["variable_speed"]
            )
    elif "variable_speed" in config:
        planned["errors"].append(
            "Constant-speed target cannot include variable-speed settings"
        )
    if planned["missing_inputs"] or planned["errors"]:
        return planned
    loop_ref = resolve(
        config["plant_loop"],
        inventory(model)["plant_loops"],
        "plant_loop",
        planned["errors"],
    )
    if loop_ref is None:
        return planned
    selected = resolve(config["pump"], loop_ref["pumps"], "pump", planned["errors"])
    if selected is None:
        return planned
    if selected["type"] not in SUPPORTED:
        planned["errors"].append(
            "Only single constant/variable-speed pumps are supported; banks/condensate pumps require separate coverage"
        )
        return planned
    if selected["type"] == "OS_Pump_" + config["target_class"]:
        planned["errors"].append(
            "Same-class changes use openstudio-pump-performance-editor"
        )
        return planned
    pump = pump_object(model, sdk, selected)
    loop = object_by_ref(model, sdk, loop_ref, "PlantLoop")
    if (
        not pump.plantLoop().is_initialized()
        or pump.plantLoop().get().handle() != loop.handle()
    ):
        raise ValueError("Pump is not owned by the selected plant")
    advanced = unsupported(pump)
    pressure = dict(raw_fields(loop).values()).get("Pressure Simulation Type", "")
    if advanced or pressure.casefold() not in ("", "none"):
        planned["errors"].append(
            "Pressure/VFD/impeller/RPM controls require a separate replacement contract: "
            + ", ".join(
                advanced
                + (
                    ["plant pressure simulation"]
                    if pressure.casefold() not in ("", "none")
                    else []
                )
            )
        )
        return planned
    boundary = ports(pump)
    old = ref(pump)
    metadata = next(
        (
            ref(x)
            for x in model.modelObjects()
            if x.iddObjectType().valueName() == "OS_AdditionalProperties"
            and dict(raw_fields(x).values()).get("Object Name") == old["handle"]
        ),
        None,
    )
    for obj in model.modelObjects():
        handle, kind = str(obj.handle()), obj.iddObjectType().valueName()
        if handle == old["handle"] or kind == "OS_Connection":
            continue
        kept = retained_keys(obj, old)
        if any(
            name != "Handle"
            and not (
                metadata and handle == metadata["handle"] and name == "Object Name"
            )
            and (
                value == old["handle"]
                or name != "Name"
                and i not in kept
                and value.casefold() == old["name"].casefold()
            )
            for i, (name, value) in raw_fields(obj).items()
        ):
            planned["errors"].append(
                "Reference policy Reject: external reference to removed pump: "
                + obj.nameString()
            )
    if planned["errors"]:
        return planned
    before = settings(pump)
    after = {
        k: deepcopy(v)
        for k, v in before.items()
        if k
        not in (
            "part_load_coefficients",
            "minimum_flow_m3_s",
            "design_minimum_flow_fraction",
        )
    }
    if config["flow_policy"] == "Autosize":
        after["rated_flow_m3_s"] = "Autosize"
    if config["power_policy"] == "Autosize":
        after["rated_power_w"] = "Autosize"
    if "end_use_subcategory" in config:
        after["end_use_subcategory"] = config["end_use_subcategory"]
    if config["target_class"] == "VariableSpeed":
        v = config["variable_speed"]
        coefficients = v["power_coefficients"]
        if curve_minimum(coefficients) < -1e-10 or sum(coefficients) <= 0:
            planned["errors"].append(
                "Power coefficients must be nonnegative over flow fraction [0,1] and positive at full flow"
            )
        after.update(
            part_load_coefficients=coefficients,
            minimum_flow_m3_s=v["minimum_flow_m3_s"],
            design_minimum_flow_fraction=0.0,
        )
        if (
            isinstance(after["rated_flow_m3_s"], (int, float))
            and v["minimum_flow_m3_s"] >= after["rated_flow_m3_s"]
        ):
            planned["errors"].append(
                "Variable-speed minimum flow must be below rated flow"
            )
        elif after["rated_flow_m3_s"] == "Autosize" and v["minimum_flow_m3_s"] > 0:
            planned["warnings"].append(
                "Minimum pump flow cannot be checked against autosized rated flow before sizing; verify minimum flow is below the sized design flow"
            )
    power_errors, power_warnings = power_check(after, after["rated_flow_m3_s"])
    planned["errors"].extend(power_errors)
    planned["warnings"].extend(power_warnings)
    if planned["errors"]:
        return planned
    planned.update(
        parameters=dict(
            planned["parameters"],
            target_class=config["target_class"],
            flow_policy=config["flow_policy"],
            power_policy=config["power_policy"],
            plant_policy="Preserve",
            reference_policy="Reject",
        ),
        resolved_objects=dict(
            plant_loop=ref(loop),
            pump=old,
            ports=boundary,
            metadata=metadata,
            side=selected["side"],
        ),
        before_values=before,
        after_values=after,
        component_order={
            side: [str(x.handle()) for x in getattr(loop, side + "Components")()]
            for side in ("supply", "demand")
        },
        before_controls=controls(model, sdk),
        retained_output_references=retained_references(model, old),
        demand_bypass=demand_bypass(loop, sdk),
    )
    preview = sdk.model.Model(model.clone(True))
    result = replace(preview, sdk, planned)
    planned["after_controls"] = controls(preview, sdk)
    if planned["after_controls"] != expected_controls(planned):
        planned["errors"].append(
            "Replacement changes translated plant controls; separate coverage required"
        )
        return planned
    new = pump_object(preview, sdk, result["replacement_pump"])
    planned["replacement_signature"] = target_signature(new)
    allowed = {h: ["Inlet Port", "Outlet Port"] for h in boundary}
    if metadata:
        allowed[metadata["handle"]] = ["Object Name"]
    planned.update(
        freeze(
            model,
            preview,
            sdk,
            allowed=allowed,
            removable={old["handle"]},
            connection_scope={old["handle"], *boundary},
            tokens={result["replacement_pump"]["handle"]: "@replacement-pump"},
            new_types=("OS_Pump_" + config["target_class"], "OS_Connection"),
        )
    )
    planned["impact"] = dict(
        plant_loop=ref(loop),
        old_pump=old,
        target_class=config["target_class"],
        side=selected["side"],
        new_pump_identity=True,
        boundary_nodes_retained=boundary,
        before=before,
        after=after,
        flow_policy=config["flow_policy"],
        power_policy=config["power_policy"],
        plant_policy="Preserve",
        demand_bypass=dict(
            planned["demand_bypass"],
            uncontrolled_branch_inlets=planned["demand_bypass"][
                "uncontrolled_branch_inlets"
            ][:8],
            translated_uncontrolled_branch_names=planned["demand_bypass"][
                "translated_uncontrolled_branch_names"
            ][:8],
            details="plan.demand_bypass",
            constant_speed_supply_review=config["target_class"] == "ConstantSpeed"
            and selected["side"] == "supply",
        ),
        metadata_retained=metadata,
        retained_output_reference_count=len(planned["retained_output_references"]),
        retained_output_references=planned["retained_output_references"][:8],
        output_reference_details="plan.retained_output_references",
        flow_behavior="Existing plant, coil, valve and pump-flow schedule controls remain; changing pump class does not redesign the loop or guarantee variable flow",
        power_behavior=(
            "Full rated electric power whenever running (simple constant-speed model)"
            if config["target_class"] == "ConstantSpeed"
            else "Chosen polynomial electric power versus flow fraction; no differential-pressure reset installed"
        ),
    )
    planned["warnings"].append(
        "Pump identity and its two connection identities change; boundary nodes and other plant objects remain. Run sizing/simulation separately; this is a single-equipment replacement, not a constant/variable-flow plant conversion"
    )
    if config["target_class"] == "ConstantSpeed":
        planned["warnings"].append(
            "Variable-speed power curve and minimum-flow settings are removed; constant-speed rated-power behavior applies while retained plant demand/schedule controls still determine flow"
        )
        if (
            selected["side"] == "supply"
            and planned["demand_bypass"]["status"] == "not_found"
        ):
            planned["warnings"].append(
                "No explicit uncontrolled demand bypass branch in the OSM: the constant-speed supply pump requests design flow while running. "
                + (
                    "OpenStudio translation currently provides an uncontrolled demand path (see impact.demand_bypass); if downstream measures remove it, excess flow may be forced through controlled coils. "
                    if planned["demand_bypass"]["translated_uncontrolled_branch_count"]
                    else "No translated uncontrolled demand path was found; excess flow may be forced through controlled coils. "
                )
                + "Review bypass/flow adequacy before simulation; plant_policy Preserve does not add an OSM bypass. Common-pipe arrangements can decouple primary/secondary flow and require separate flow review"
            )
    elif abs(sum(after["part_load_coefficients"]) - 1) > 1e-3:
        planned["warnings"].append(
            "Part-load power fraction at full flow differs from 1.0"
        )
    if after["end_use_subcategory"] != before["end_use_subcategory"]:
        planned["warnings"].append(
            "End-use subcategory change affects subcategory meter names; review corresponding requests separately"
        )
    planned["assumptions"] = [
        "Common head/motor/control/sizing factors, flow schedule and zone heat-loss split retained; no prototype defaults applied",
        "All other plant equipment, controls, setpoints, fluid, sizing and connections retained",
    ]
    planned["ready"] = True
    return planned


def replace(model, sdk, planned):
    r, p, after = (
        planned["resolved_objects"],
        planned["parameters"],
        planned["after_values"],
    )
    old = pump_object(model, sdk, r["pump"])
    new = getattr(sdk.model, "Pump" + p["target_class"])(model)
    for key, (_, suffix, _) in FIELDS.items():
        call(new, "set" + suffix, after[key])
    for key, suffix in (
        ("rated_power_w", "RatedPowerConsumption"),
        ("rated_flow_m3_s", "RatedFlowRate"),
    ):
        if after[key] == "Autosize":
            getattr(new, "autosize" + suffix)()
        else:
            call(new, "set" + suffix, after[key])
    call(new, "setEndUseSubcategory", after["end_use_subcategory"])
    call(new, "setSkinLossRadiativeFraction", after["skin_loss_radiative_fraction"])
    if after["flow_schedule"]:
        call(
            new,
            "setPumpFlowRateSchedule",
            object_by_ref(model, sdk, after["flow_schedule"], "Schedule"),
        )
    if after["zone"]:
        call(new, "setZone", object_by_ref(model, sdk, after["zone"], "ThermalZone"))
    if p["target_class"] == "VariableSpeed":
        call(new, "setMinimumFlowRate", after["minimum_flow_m3_s"])
        call(
            new,
            "setDesignMinimumFlowRateFraction",
            after["design_minimum_flow_fraction"],
        )
        for i, coefficient in enumerate(after["part_load_coefficients"], 1):
            call(new, f"setCoefficient{i}ofthePartLoadPerformanceCurve", coefficient)
    inlet, outlet = [
        object_by_ref(model, sdk, {"handle": h}, "Node") for h in r["ports"]
    ]
    model.disconnect(old, old.inletPort())
    model.disconnect(old, old.outletPort())
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
    call(new, "setName", r["pump"]["name"])
    return deepcopy(
        dict(
            plant_loop=r["plant_loop"],
            removed_pump=r["pump"],
            replacement_pump=ref(new),
            water_nodes=r["ports"],
        )
    )


def validate_model(model, sdk, planned, result):
    r = planned["resolved_objects"]
    new = pump_object(model, sdk, result["replacement_pump"])
    loop = object_by_ref(model, sdk, r["plant_loop"], "PlantLoop")
    before, current = planned["before_objects"], original_types(model)
    checks = {
        "Replacement pump class/identity/name differs": ref(new)
        == result["replacement_pump"]
        and str(new.handle()) not in before
        and new.iddObjectType().valueName()
        == "OS_Pump_" + planned["parameters"]["target_class"]
        and new.nameString() == r["pump"]["name"],
        "Pump settings differ from approved plan": matches(
            settings(new), planned["after_values"]
        ),
        "Unapproved replacement pump field changes": target_signature(new)
        == planned["replacement_signature"],
        "Pump water boundaries changed": ports(new) == r["ports"],
        "Pump plant ownership differs": new.plantLoop().is_initialized()
        and new.plantLoop().get().handle() == loop.handle(),
        "Demand bypass status changed": demand_bypass(loop, sdk)
        == planned["demand_bypass"],
        "Plant component order differs": all(
            [str(x.handle()) for x in getattr(loop, side + "Components")()]
            == [str(new.handle()) if h == r["pump"]["handle"] else h for h in expected]
            for side, expected in planned["component_order"].items()
        ),
        "Unexpected removed objects": sorted(before.keys() - current.keys())
        == planned["removed_objects"],
        "Unexpected added objects": dict(
            Counter(current[h] for h in current.keys() - before.keys())
        )
        == planned["added_counts"],
        "Protected plant/model objects changed": protected_state(model, sdk, planned),
        "Connection graph differs": connection_graph(
            model, {str(new.handle()): "@replacement-pump"}
        )
        == planned["connection_graph"],
        "Translated plant controls changed": controls(model, sdk)
        == planned["after_controls"]
        == expected_controls(planned),
        "Retained reporting references changed": retained_references(model, ref(new))
        == planned["retained_output_references"],
        "Reported pump mapping differs": result
        == dict(
            plant_loop=r["plant_loop"],
            removed_pump=r["pump"],
            replacement_pump=ref(new),
            water_nodes=r["ports"],
        ),
    }
    if r["metadata"]:
        checks["Metadata owner differs"] = dict(
            raw_fields(
                object_by_ref(model, sdk, r["metadata"], "AdditionalProperties")
            ).values()
        )["Object Name"] == str(new.handle())
    return dict(
        ok=all(checks.values()),
        checks=len(checks),
        errors=[key for key, ok in checks.items() if not ok],
    )
