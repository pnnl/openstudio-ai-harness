"""In-place water district-source nominal capacity; no efficiency conversion."""

import json
import math
from pathlib import Path

from common.coil_topology import protected_state
from common.hvac_equipment import call
from common.hvac_inventory import resolve
from common.input_validation import validate
from common.model_preservation import fingerprint, snapshot
from common.temperature_control import translated_workspace, optional_string
from common.water_coil import original_types, raw_fields
from common.plant_sizing import sizing_context, require_plant_sizing

FIELD = "Nominal Capacity"
CLASSES = {
    "OS_DistrictHeating_Water": "DistrictHeatingWater",
    "OS_DistrictCooling": "DistrictCooling",
}


def ref(obj):
    return dict(
        handle=str(obj.handle()),
        name=obj.nameString(),
        type=obj.iddObjectType().valueName(),
    )


def inventory(model):
    return dict(
        plant_loops=sorted(
            [
                dict(
                    ref(loop),
                    loop_type=loop.sizingPlant().loopType(),
                    equipment=sorted(
                        [
                            dict(
                                ref(obj),
                                supported=obj.iddObjectType().valueName() in CLASSES,
                            )
                            for obj in loop.supplyComponents()
                            if obj.iddObjectType().valueName().startswith("OS_District")
                        ],
                        key=lambda x: (x["name"], x["handle"]),
                    ),
                )
                for loop in model.getPlantLoops()
            ],
            key=lambda x: (x["name"], x["handle"]),
        )
    )


def equipment(model, sdk, selected):
    obj = model.getModelObject(sdk.toUUID(selected["handle"]))
    if not obj.is_initialized() or obj.get().iddObjectType().valueName() not in CLASSES:
        raise ValueError(
            "Selected water district source is missing or its class changed"
        )
    return getattr(
        obj.get(), "to_" + CLASSES[obj.get().iddObjectType().valueName()]
    )().get()


def values(obj):
    capacity = obj.nominalCapacity()
    return dict(
        nominal_capacity_w=(
            "Autosize"
            if obj.isNominalCapacityAutosized()
            else capacity.get() if capacity.is_initialized() else None
        )
    )


def matches(actual, expected):
    a, b = actual["nominal_capacity_w"], expected["nominal_capacity_w"]
    return (
        a == b
        if isinstance(b, str)
        else type(a) in (int, float) and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    )


def ports(obj):
    nodes = [obj.inletModelObject(), obj.outletModelObject()]
    if any(
        not n.is_initialized() or not n.get().to_Node().is_initialized() for n in nodes
    ):
        raise ValueError(
            "District equipment requires connected inlet and outlet water nodes"
        )
    return [str(n.get().handle()) for n in nodes]


def translated_state(model, sdk, obj):
    workspace = translated_workspace(
        model, sdk, "Cannot verify translated district equipment"
    )
    kind = (
        "DistrictHeating_Water"
        if obj.iddObjectType().valueName() == "OS_DistrictHeating_Water"
        else "DistrictCooling"
    )
    found = [
        x
        for x in workspace.getObjectsByType(sdk.IddObjectType(kind))
        if x.nameString() == obj.nameString()
    ]
    if len(found) != 1:
        raise ValueError("Cannot identify one translated district source")
    translated = found[0]
    index = translated.iddObject().getFieldIndex(FIELD)
    if not index.is_initialized():
        raise ValueError("Translated district source is missing nominal capacity")
    raw = optional_string(translated, index.get())
    number = translated.getDouble(index.get())
    if raw.lower() != "autosize" and not number.is_initialized():
        raise ValueError("Translated district capacity is neither numeric nor Autosize")
    return dict(
        plant_sizing=sizing_context(model, sdk, workspace),
        settings=dict(
            nominal_capacity_w="Autosize" if raw.lower() == "autosize" else number.get()
        ),
        preserved_fields=[
            [
                translated.iddObject().getField(i).get().name(),
                optional_string(translated, i),
            ]
            for i in range(translated.numFields())
            if i != index.get()
        ],
    )


def plan(model, sdk, config):
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "references/district_capacity.schema.json"
        ).read_text()
    )
    errors = validate(config, schema)
    if errors:
        raise ValueError(
            "Invalid district capacity configuration: " + "; ".join(errors)
        )
    planned = dict(
        ready=False,
        simulation_ready=False,
        simulation_readiness_scope="operation_and_companions",
        parameters=dict(output_model_path=config["output_model_path"]),
        missing_inputs=[
            key
            for key in ("plant_loop", "district_equipment", "settings")
            if not config.get(key)
        ],
        errors=[],
        warnings=[],
        assumptions=[],
    )
    if planned["missing_inputs"]:
        return planned
    loop_ref = resolve(
        config["plant_loop"],
        inventory(model)["plant_loops"],
        "plant_loop",
        planned["errors"],
    )
    if loop_ref is None:
        return planned
    selected = resolve(
        config["district_equipment"],
        loop_ref["equipment"],
        "district_equipment",
        planned["errors"],
    )
    if selected is None:
        return planned
    if not selected["supported"]:
        planned["errors"].append(
            "Select supply-side DistrictHeatingWater or DistrictCooling; steam requires separate coverage"
        )
        return planned
    obj = equipment(model, sdk, selected)
    loop = model.getPlantLoop(sdk.toUUID(loop_ref["handle"])).get()
    before, after = values(obj), dict(config["settings"])
    if before["nominal_capacity_w"] is None:
        planned["errors"].append(
            "Source district nominal capacity is unset; diagnose the source model"
        )
        return planned
    if matches(before, after):
        planned["errors"].append(
            "Edit must change nominal capacity or its sizing policy"
        )
        return planned
    try:
        boundary = ports(obj)
        translated = translated_state(model, sdk, obj)
    except ValueError as exc:
        planned["errors"].append(str(exc))
        return planned
    if not matches(translated["settings"], before):
        planned["errors"].append(
            "Source district capacity disagrees with EnergyPlus translation; diagnose the source model"
        )
        return planned
    schedule = obj.capacityFractionSchedule()
    constant = schedule.to_ScheduleConstant()
    fraction = constant.get().value() if constant.is_initialized() else None
    actuators = sorted(
        [
            ref(a)
            for a in model.getEnergyManagementSystemActuators()
            if a.actuatedComponent().is_initialized()
            and a.actuatedComponent().get().handle() == obj.handle()
        ],
        key=lambda x: x["handle"],
    )
    protection = dict(excluded=[str(obj.handle())], ignored={}, field_limits={})
    protected = snapshot(model, **protection)
    planned.update(
        weather_was_empty=not any(
            value
            for name, value in raw_fields(model.getWeatherFile()).values()
            if name not in ("Handle", "Url", "Checksum")
        ),
        ready=True,
        simulation_ready=True,
        parameters=dict(output_model_path=config["output_model_path"], settings=after),
        resolved_objects=dict(
            plant_loop=ref(loop), district_equipment=ref(obj), ports=boundary
        ),
        before_values=before,
        after_values=after,
        preserved_equipment=fingerprint(obj, ignored=[FIELD]),
        before_objects=original_types(model),
        protection=protection,
        protected_objects=protected,
        translated_preserved_fields=translated["preserved_fields"],
        impact=dict(
            district_equipment=ref(obj),
            plant_loop=ref(loop),
            loop_type=loop_ref["loop_type"],
            load_distribution_scheme=loop.loadDistributionScheme(),
            dispatch_design_capacity_w=after["nominal_capacity_w"],
            dispatch_design_capacity_includes_schedule_fraction=False,
            before=before,
            after=after,
            capacity_fraction_schedule=ref(schedule),
            constant_capacity_fraction=fraction,
            effective_constant_limit_w=(
                after["nominal_capacity_w"] * max(0, fraction)
                if fraction is not None
                and isinstance(after["nominal_capacity_w"], (int, float))
                else None
            ),
            design_exit_temperature_c=loop.sizingPlant().designLoopExitTemperature(),
            design_delta_t_k=loop.sizingPlant().loopDesignTemperatureDifference(),
            ems_actuator_count=len(actuators),
            ems_actuators=actuators[:8],
            preservation_policy="Retain identity, schedule, ports, dispatch inputs, pump and sizing inputs; change only nominal capacity/Autosize",
        ),
    )
    planned["warnings"].append(
        "District capacity is purchased thermal watts, not electric watts, COP or efficiency. Available capacity is nominal capacity times the retained nonnegative capacity-fraction schedule (which can exceed 1); loads, dispatch, flow and temperature limits determine delivered energy. A smaller capacity can cause unmet loads, not efficiency savings"
    )
    planned["warnings"].append(
        "EnergyPlus applies loop temperature protection after capacity limiting; a temperature bound can override the nominal-times-schedule limit in reported heat even when the limited load is zero or the capacity-fraction schedule is 0. A zero schedule is not a guaranteed off switch. Inspect delivered heat, outlet temperatures and unmet loads"
    )
    if fraction is None:
        planned["warnings"].append(
            "Retained capacity-fraction schedule is time-varying; no single effective watt limit is inferred"
        )
    elif fraction != 1:
        planned["warnings"].append(
            "Retained constant capacity-fraction schedule modifies the nominal limit; inspect effective_constant_limit_w"
        )
    if after["nominal_capacity_w"] == "Autosize":
        require_plant_sizing(planned, translated["plant_sizing"])
        planned["warnings"].append(
            "Autosize uses plant design water volume flow times fluid density times specific heat times plant design delta T; design sizing and dispatch must be reviewed. Other sizing inputs are retained, not calculated sizes"
        )
    if actuators:
        planned["warnings"].append(
            "Retained EMS may override district operation; verify runtime results"
        )
    planned["warnings"].append(
        "Load-based plant dispatch uses nominal capacity as this source's maximum/optimal load without the capacity-fraction schedule. Editing capacity can redistribute load between sources even though operation schemes are retained. With a fraction below 1, assigned load can exceed delivery and the shortfall may remain unmet instead of being reassigned to other equipment; review all source loads and plant unmet demand"
    )
    planned["warnings"].append(
        "For nonzero assigned load, this district source requests the loop's full design water flow before capacity limiting. Reducing capacity alone does not proportionally reduce requested flow or guarantee pump-energy savings; actual flow remains subject to plant flow constraints and controls"
    )
    typical = "Heating" if selected["type"] == "OS_DistrictHeating_Water" else "Cooling"
    if loop_ref["loop_type"] != typical:
        planned["warnings"].append(
            "District source is on a loop with a different sizing role; heating adds heat and cooling removes it regardless of that role. Review dispatch and setpoints"
        )
    if (
        not any(
            x.iddObjectType().valueName().startswith(("OS_Pump_", "OS_HeaderedPumps_"))
            for x in loop.supplyComponents()
        )
        or not loop.supplyOutletNode().setpointManagers()
    ):
        planned["simulation_ready"] = False
        planned["warnings"].append(
            "Existing plant lacks an identified supply pump or outlet setpoint manager; this capacity edit does not repair plant controls"
        )
    return planned


def edit(model, sdk, planned):
    obj = equipment(model, sdk, planned["resolved_objects"]["district_equipment"])
    before = values(obj)
    value = planned["after_values"]["nominal_capacity_w"]
    (
        call(obj, "autosizeNominalCapacity")
        if value == "Autosize"
        else call(obj, "setNominalCapacity", value)
    )
    return dict(district_equipment=ref(obj), before=before, after=values(obj))


def validate_model(model, sdk, planned, result):
    r = planned["resolved_objects"]
    obj = equipment(model, sdk, r["district_equipment"])
    checks = {
        "District identity/name/class changed": ref(obj)
        == r["district_equipment"]
        == result["district_equipment"],
        "Reported values differ": matches(result["before"], planned["before_values"])
        and matches(result["after"], planned["after_values"]),
        "Saved district capacity differs": matches(
            values(obj), planned["after_values"]
        ),
        "Unrequested district fields changed": fingerprint(obj, ignored=[FIELD])
        == planned["preserved_equipment"],
        "District boundary nodes changed": ports(obj) == r["ports"],
        "District plant ownership changed": obj.plantLoop().is_initialized()
        and str(obj.plantLoop().get().handle()) == r["plant_loop"]["handle"],
        "Model objects/handles changed": original_types(model)
        == planned["before_objects"],
        "Protected model objects/references changed": protected_state(
            model, sdk, planned
        ),
    }
    if all(checks.values()):
        translated = translated_state(model, sdk, obj)
        checks["Translated district capacity differs"] = matches(
            translated["settings"], planned["after_values"]
        )
        checks["Unrequested translated district fields changed"] = (
            translated["preserved_fields"] == planned["translated_preserved_fields"]
        )
    return dict(
        ok=all(checks.values()),
        checks=len(checks),
        errors=[m for m, ok in checks.items() if not ok],
    )
