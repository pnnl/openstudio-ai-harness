"""Real main-supply heating water -> electric conversion, not same-class cloning."""

from collections import Counter
from copy import deepcopy
import json
import math
from pathlib import Path

from common.input_validation import validate
from common.coil_topology import (
    freeze,
    connection_graph,
    protected_state,
    remaining_demand,
    control_context,
)
from common.hvac_equipment import call
from common.water_coil import (
    ref,
    object_by_ref,
    raw_fields,
    original_types,
    plan as settings_plan,
)


def plan(model, sdk, config):
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "references/coil_conversion.schema.json"
        ).read_text()
    )
    errors = validate(config, schema)
    if errors:
        raise ValueError("Invalid config: " + "; ".join(errors))
    missing = [
        key
        for key in (
            "coil",
            "efficiency",
            "temperature_control",
            "sizing",
            "reference_policy",
        )
        if key not in config
    ]
    if missing:
        return dict(
            ready=False,
            parameters=dict(output_model_path=config["output_model_path"]),
            missing_inputs=missing,
            errors=[],
            warnings=[],
        )
    # Reuse selection, main-supply context and source-plant readiness warnings.
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
    if base["parameters"]["kind"] != "Heating":
        base["errors"].append(
            "Initial class conversion supports CoilHeatingWater -> CoilHeatingElectric only"
        )
        base["ready"] = False
        return base
    coil = object_by_ref(model, sdk, r["coil"], "CoilHeatingWater")
    plant = object_by_ref(model, sdk, r["plant_loop"], "PlantLoop")
    inlet, outlet = [
        object_by_ref(model, sdk, {"handle": h}, "Node") for h in r["ports"][2:]
    ]
    if (
        inlet.inletModelObject().get().handle() != plant.demandSplitter().handle()
        or outlet.outletModelObject().get().handle() != plant.demandMixer().handle()
    ):
        base["errors"].append(
            "Conversion requires a dedicated single-coil plant demand branch"
        )
    controller = coil.controllerWaterCoil().get()
    controls = base["before_settings"]["controller"]
    sensor = controller.sensorNode()
    actuator = controller.actuatorNode()
    if (
        controls["control_variable"] != "Temperature"
        or controls["actuator_variable"] != "Flow"
        or controls["action"] != "Normal"
        or controls["minimum_flow_m3_s"] != 0
        or sensor.is_initialized()
        and str(sensor.get().handle()) != r["ports"][1]
        or actuator.is_initialized()
        and str(actuator.get().handle()) != r["ports"][2]
    ):
        base["errors"].append(
            "Preserve control requires Normal Temperature/Flow control, zero minimum flow, outlet sensor and water-inlet actuator (or native defaults); custom control needs separate coverage"
        )
    if base["errors"]:
        base["ready"] = False
        return base
    loop = object_by_ref(model, sdk, r["air_loop"], "AirLoopHVAC")
    before_control = control_context(model, sdk, coil, loop)
    if not before_control["managers"]:
        base["errors"].append("Cannot establish original outlet temperature control")
    metadata = next(
        (
            ref(x)
            for x in model.modelObjects()
            if x.iddObjectType().valueName() == "OS_AdditionalProperties"
            and dict(raw_fields(x).values()).get("Object Name") == r["coil"]["handle"]
        ),
        None,
    )
    controller_metadata = [
        str(x.handle())
        for x in model.modelObjects()
        if x.iddObjectType().valueName() == "OS_AdditionalProperties"
        and dict(raw_fields(x).values()).get("Object Name") == r["controller"]["handle"]
    ]
    removed = {
        r["coil"]["handle"],
        r["controller"]["handle"],
        *r["ports"][2:],
        *controller_metadata,
    }
    scope = {str(x.handle()) for x in plant.demandComponents()}
    scope.update(r["ports"] + [r["coil"]["handle"]])
    for obj in model.modelObjects():
        handle, kind = str(obj.handle()), obj.iddObjectType().valueName()
        if (
            handle in removed
            or kind == "OS_Connection"
            or handle in scope
            and kind in ("OS_Connector_Mixer", "OS_Connector_Splitter")
        ):
            continue
        if any(
            name != "Handle"
            and not (
                metadata and handle == metadata["handle"] and name == "Object Name"
            )
            and (value in removed or value.casefold() == coil.nameString().casefold())
            for name, value in raw_fields(obj).values()
        ):
            base["errors"].append(
                "Reference policy Reject: external reference to removed equipment/node: "
                + obj.nameString()
            )
    if base["errors"]:
        base["ready"] = False
        return base
    r["metadata"] = metadata
    base["parameters"] = dict(
        output_model_path=config["output_model_path"],
        operation="water_to_electric",
        efficiency=config["efficiency"],
        temperature_control=config["temperature_control"],
        sizing="Autosize",
        reference_policy="Reject",
    )
    base["after_values"] = dict(
        efficiency=config["efficiency"],
        temperature_control=config["temperature_control"],
        nominal_capacity_w="Autosize",
        coil_name=coil.nameString(),
        availability_schedule=ref(coil.availabilitySchedule()),
    )
    preview = sdk.model.Model(model.clone(True))
    result = convert(preview, sdk, base)
    replacement = object_by_ref(preview, sdk, result["coil"], "CoilHeatingElectric")
    after_control = control_context(
        preview,
        sdk,
        replacement,
        object_by_ref(preview, sdk, r["air_loop"], "AirLoopHVAC"),
    )
    if after_control != before_control:
        base["ready"] = False
        base["errors"].append(
            "Conversion cannot preserve translated outlet temperature control"
        )
        return base
    base["before_control"] = before_control
    base["after_control"] = after_control
    allowed = {h: ["Inlet Port", "Outlet Port"] for h in r["ports"]}
    for obj in plant.demandComponents():
        if obj.iddObjectType().valueName() == "OS_Node":
            allowed[str(obj.handle())] = ["Inlet Port", "Outlet Port"]
        elif obj.iddObjectType().valueName() in (
            "OS_Connector_Mixer",
            "OS_Connector_Splitter",
        ):
            allowed[str(obj.handle())] = ["Inlet Branch Name", "Outlet Branch Name"]
    if metadata:
        allowed[metadata["handle"]] = ["Object Name"]
    base.update(
        freeze(
            model,
            preview,
            sdk,
            allowed=allowed,
            removable=removed,
            connection_scope=scope,
            tokens={result["coil"]["handle"]: "@electric-coil"},
            new_types=(
                "OS_Coil_Heating_Electric",
                "OS_Connection",
            ),
        )
    )
    base["impact"] = dict(
        operation="water_to_electric",
        temperature_control="Preserve",
        before_control=before_control,
        after_control=after_control,
        source_type="CoilHeatingWater",
        destination_type="CoilHeatingElectric",
        coil=coil.nameString(),
        air_loop=r["air_loop"]["name"],
        source_plant=plant.nameString(),
        affected_zone_count=len(
            object_by_ref(model, sdk, r["air_loop"], "AirLoopHVAC").thermalZones()
        ),
        before=base["before_values"],
        after=base["after_values"],
        identity="New electric coil; existing air nodes and coil metadata retained; water coil/controller/branch nodes removed",
        reference_policy="Reject external references to removed equipment/nodes; metadata is reparented",
        removed_object_counts=dict(
            Counter(base["before_objects"][h] for h in base["removed_objects"])
        ),
        controller_metadata_removed=controller_metadata,
        **remaining_demand(plant, coil),
    )
    base["warnings"].append(
        "Heating energy changes from plant-supplied hot water to electricity. Plant supply equipment/pumps remain; run sizing and review energy/fuel impacts separately."
    )
    if base["impact"]["source_plant_remaining_coil_count"] == 0:
        base["warnings"].append(
            "Source plant will serve 0 coils; existing supply equipment and sizing settings remain. Review retention/cleanup; openstudio-hvac-remover currently excludes plant deletion."
        )
    if controller_metadata:
        base["warnings"].append(
            "Owned water-controller metadata is removed with the controller; its handles are listed in impact."
        )
    base["assumptions"] = [
        "Preserve coil name, availability, air boundary nodes and coil metadata; new coil identity",
        "Explicit electric efficiency; preserve existing/translator-generated outlet control without adding a manager or schedule; nominal capacity reset to Autosize",
        "Remove only the selected dedicated demand branch and owned controller; retain the source plant",
        "Reject unsupported incoming references; no automatic EMS or LifeCycleCost transfer",
    ]
    for key in ("rating_usage", "assumption_review"):
        base.pop(key, None)
    return base


def convert(model, sdk, planned):
    r = planned["resolved_objects"]
    old = object_by_ref(model, sdk, r["coil"], "CoilHeatingWater")
    new = sdk.model.CoilHeatingElectric(model, old.availabilitySchedule())
    call(new, "setEfficiency", planned["parameters"]["efficiency"])
    new.autosizeNominalCapacity()
    plant = object_by_ref(model, sdk, r["plant_loop"], "PlantLoop")
    call(plant, "removeDemandBranchWithComponent", old)
    model.disconnect(old, old.airInletPort())
    model.disconnect(old, old.airOutletPort())
    inlet, outlet = [
        object_by_ref(model, sdk, {"handle": h}, "Node") for h in r["ports"][:2]
    ]
    model.connect(inlet, inlet.outletPort(), new, new.inletPort())
    model.connect(new, new.outletPort(), outlet, outlet.inletPort())
    if r["metadata"]:
        properties = object_by_ref(model, sdk, r["metadata"], "AdditionalProperties")
        call(properties, "setPointer", 1, new.handle())
    old.remove()
    call(new, "setName", planned["after_values"]["coil_name"])
    return deepcopy(
        dict(
            operation="water_to_electric",
            source_coil=r["coil"],
            coil=ref(new),
            removed_controller=r["controller"],
            air_nodes=r["ports"][:2],
            source_plant=r["plant_loop"],
        )
    )


def validate_model(model, sdk, planned, result):
    errors, checks = [], 0

    def check(ok, message):
        nonlocal checks
        checks += 1
        if not ok:
            errors.append(message)

    r = planned["resolved_objects"]
    coil = object_by_ref(model, sdk, result["coil"], "CoilHeatingElectric")
    after = planned["after_values"]
    check(
        ref(coil) == result["coil"]
        and str(coil.handle()) not in planned["before_objects"],
        "Replacement coil identity differs",
    )
    check(
        math.isclose(coil.efficiency(), after["efficiency"], abs_tol=1e-9)
        and coil.isNominalCapacityAutosized(),
        "Electric performance differs from approved settings",
    )
    check(
        coil.nameString() == after["coil_name"]
        and ref(coil.availabilitySchedule()) == after["availability_schedule"],
        "Replacement name/schedule differs",
    )
    check(
        [
            str(coil.inletModelObject().get().handle()),
            str(coil.outletModelObject().get().handle()),
        ]
        == r["ports"][:2],
        "Air boundary nodes changed",
    )
    check(
        coil.airLoopHVAC().is_initialized()
        and str(coil.airLoopHVAC().get().handle()) == r["air_loop"]["handle"],
        "Wrong air-loop ownership",
    )
    current = original_types(model)
    before = planned["before_objects"]
    check(
        sorted(before.keys() - current.keys()) == planned["removed_objects"],
        "Unexpected removed objects",
    )
    check(
        dict(Counter(current[h] for h in current.keys() - before.keys()))
        == planned["added_counts"],
        "Unexpected added objects",
    )
    check(protected_state(model, sdk, planned), "Protected model objects changed")
    check(
        connection_graph(model, {str(coil.handle()): "@electric-coil"})
        == planned["connection_graph"],
        "Connection graph differs from approved replacement",
    )
    loop = object_by_ref(model, sdk, r["air_loop"], "AirLoopHVAC")
    check(
        [str(x.handle()) for x in loop.supplyComponents()]
        == [
            str(coil.handle()) if h == r["coil"]["handle"] else h
            for h in planned["supply_order"]
        ],
        "Air supply order changed",
    )
    plant = object_by_ref(model, sdk, r["plant_loop"], "PlantLoop")
    check(
        [str(x.handle()) for x in plant.supplyComponents()]
        == planned["plant_supply_order"],
        "Plant supply order changed",
    )
    check(
        control_context(model, sdk, coil, loop)
        == planned["before_control"]
        == planned["after_control"],
        "Translated outlet temperature control differs from preserved control",
    )
    if r["metadata"]:
        check(
            dict(
                raw_fields(
                    object_by_ref(model, sdk, r["metadata"], "AdditionalProperties")
                ).values()
            )["Object Name"]
            == str(coil.handle()),
            "Metadata targets the wrong object",
        )
    check(
        result
        == dict(
            operation="water_to_electric",
            source_coil=r["coil"],
            coil=ref(coil),
            removed_controller=r["controller"],
            air_nodes=r["ports"][:2],
            source_plant=r["plant_loop"],
        ),
        "Reported replacement mapping differs",
    )
    return dict(ok=not errors, checks=checks, errors=errors)
