"""Reviewed in-place variable-speed tower design fan power edits."""

import json
import math
from pathlib import Path

from common.coil_topology import protected_state
from common.hvac_equipment import call
from common.hvac_inventory import resolve
from common.input_validation import validate
from common.model_preservation import fingerprint, snapshot
from common.temperature_control import translated_workspace, optional_string
from common.water_coil import original_types
from common.plant_sizing import sizing_context, require_plant_sizing

POWER_FIELD = "Design Fan Power"
CURVE_FIELD = "Fan Power Ratio Function of Air Flow Rate Ratio Curve Name"
MODELS = ("CoolToolsCrossFlow", "YorkCalc")


def ref(obj):
    return dict(
        handle=str(obj.handle()),
        name=obj.nameString(),
        type=obj.iddObjectType().valueName(),
    )


def optional_value(value):
    return value.get() if value.is_initialized() else None


def effective_model_type(tower):
    # A blank model type passes through to the pinned EnergyPlus YorkCalc default.
    return optional_value(tower.modelType()) or "YorkCalc"


def supported(obj, loop):
    typed = obj.to_CoolingTowerVariableSpeed()
    return (
        typed.is_initialized()
        and loop.sizingPlant().loopType() == "Condenser"
        and effective_model_type(typed.get()) in MODELS
    )


def inventory(model):
    return dict(
        plant_loops=sorted(
            [
                dict(
                    ref(loop),
                    loop_type=loop.sizingPlant().loopType(),
                    towers=sorted(
                        [
                            dict(ref(obj), supported=supported(obj, loop))
                            for obj in loop.supplyComponents()
                            if obj.iddObjectType()
                            .valueName()
                            .startswith("OS_CoolingTower_")
                        ],
                        key=lambda x: (x["name"], x["handle"]),
                    ),
                )
                for loop in model.getPlantLoops()
            ],
            key=lambda x: (x["name"], x["handle"]),
        )
    )


def tower_object(model, sdk, reference):
    optional = model.getCoolingTowerVariableSpeed(sdk.toUUID(reference["handle"]))
    if not optional.is_initialized():
        raise ValueError(
            "Selected variable-speed cooling tower is missing or its class changed"
        )
    return optional.get()


def sized(tower, suffix):
    if getattr(tower, "is" + suffix + "Autosized")():
        return "Autosize"
    optional = getattr(tower, suffix[0].lower() + suffix[1:])()
    return optional.get() if optional.is_initialized() else None


def values(tower):
    return dict(design_fan_power_w=sized(tower, "DesignFanPower"))


def matches(actual, expected):
    return actual.keys() == expected.keys() and all(
        (
            actual[key] == value
            if isinstance(value, str)
            else type(actual[key]) in (int, float)
            and math.isclose(actual[key], value, rel_tol=1e-9, abs_tol=1e-9)
        )
        for key, value in expected.items()
    )


def ports(tower):
    result = []
    for optional in (tower.inletModelObject(), tower.outletModelObject()):
        if (
            not optional.is_initialized()
            or not optional.get().to_Node().is_initialized()
        ):
            raise ValueError(
                "Cooling tower requires connected inlet and outlet water nodes"
            )
        result.append(str(optional.get().handle()))
    return result


def signature(tower):
    return fingerprint(tower, ignored=[POWER_FIELD])


def translated_state(model, sdk, tower):
    workspace = translated_workspace(
        model, sdk, "Cannot verify translated cooling tower"
    )
    objects = [
        obj
        for obj in workspace.getObjectsByType(
            sdk.IddObjectType("CoolingTower_VariableSpeed")
        )
        if obj.nameString() == tower.nameString()
    ]
    if len(objects) != 1:
        raise ValueError("Cannot identify one translated variable-speed cooling tower")
    obj = objects[0]
    index = obj.iddObject().getFieldIndex(POWER_FIELD)
    if not index.is_initialized():
        raise ValueError("Translated cooling tower is missing design fan power")
    raw = optional_string(obj, index.get())
    if raw.lower() == "autosize":
        value = "Autosize"
    else:
        number = obj.getDouble(index.get())
        if not number.is_initialized():
            raise ValueError(
                "Translated tower fan power is neither numeric nor Autosize"
            )
        value = number.get()
    return dict(
        plant_sizing=sizing_context(model, sdk, workspace),
        settings=dict(design_fan_power_w=value),
        preserved_fields=[
            [obj.iddObject().getField(i).get().name(), optional_string(obj, i)]
            for i in range(obj.numFields())
            if i != index.get()
        ],
    )


def plan(model, sdk, config):
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "references/tower_performance.schema.json"
        ).read_text()
    )
    errors = validate(config, schema)
    if errors:
        raise ValueError(
            "Invalid cooling tower performance configuration: " + "; ".join(errors)
        )
    planned = dict(
        ready=False,
        simulation_ready=False,
        simulation_readiness_scope="operation_and_companions",
        parameters=dict(output_model_path=config["output_model_path"]),
        missing_inputs=[
            key for key in ("plant_loop", "tower", "settings") if not config.get(key)
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
    selected = resolve(config["tower"], loop_ref["towers"], "tower", planned["errors"])
    if selected is None:
        return planned
    if not selected["supported"]:
        planned["errors"].append(
            "Select a CoolingTowerVariableSpeed on a Condenser plant supply side using built-in CoolToolsCrossFlow or YorkCalc; other tower classes and user-defined thermal models require separate coverage"
        )
        return planned
    tower = tower_object(model, sdk, selected)
    loop = model.getPlantLoop(sdk.toUUID(loop_ref["handle"])).get()
    if (
        not tower.plantLoop().is_initialized()
        or tower.plantLoop().get().handle() != loop.handle()
    ):
        raise ValueError("Selected cooling tower plant ownership differs")
    before, after = values(tower), dict(config["settings"])
    if before["design_fan_power_w"] is None:
        planned["errors"].append(
            "Source tower design fan power is unset; diagnose the incomplete source model before editing"
        )
        return planned
    if matches(before, after):
        planned["errors"].append(
            "Edit must change design fan power or its sizing policy"
        )
        return planned
    translated = translated_state(model, sdk, tower)
    if not matches(translated["settings"], before):
        planned["errors"].append(
            "Source tower fan power disagrees with EnergyPlus translation; diagnose the source model before editing"
        )
        return planned
    curve = tower.fanPowerRatioFunctionofAirFlowRateRatioCurve()
    curve = curve.get() if curve.is_initialized() else None
    if (
        curve
        and dict(translated["preserved_fields"]).get(CURVE_FIELD) != curve.nameString()
    ):
        planned["errors"].append(
            "Configured tower fan curve does not survive translation; diagnose the source model before editing"
        )
        return planned
    protection = dict(excluded=[str(tower.handle())], ignored={}, field_limits={})
    protected = snapshot(model, **protection)
    ems = []
    for actuator in model.getEnergyManagementSystemActuators():
        component = actuator.actuatedComponent()
        if component.is_initialized() and component.get().handle() == tower.handle():
            ems.append(ref(actuator))
    planned.update(
        ready=True,
        simulation_ready=True,
        parameters=dict(output_model_path=config["output_model_path"], settings=after),
        resolved_objects=dict(
            plant_loop=ref(loop), tower=ref(tower), ports=ports(tower)
        ),
        before_values=before,
        after_values=after,
        preserved_tower=signature(tower),
        before_objects=original_types(model),
        protection=protection,
        protected_objects=protected,
        translated_preserved_fields=translated["preserved_fields"],
        impact=dict(
            tower=ref(tower),
            plant_loop=ref(loop),
            before=before,
            after=after,
            design_air_flow_m3_s=sized(tower, "DesignAirFlowRate"),
            design_water_flow_m3_s=sized(tower, "DesignWaterFlowRate"),
            autosized_airflow_depends_on_fan_power=tower.isDesignAirFlowRateAutosized(),
            thermal_model=effective_model_type(tower),
            fan_curve=ref(curve) if curve else None,
            minimum_air_flow_ratio=optional_value(tower.minimumAirFlowRateRatio()),
            free_convection_capacity_fraction=optional_value(
                tower.fractionofTowerCapacityinFreeConvectionRegime()
            ),
            design_wet_bulb_c=optional_value(tower.designInletAirWetBulbTemperature()),
            design_approach_k=optional_value(tower.designApproachTemperature()),
            design_range_k=optional_value(tower.designRangeTemperature()),
            condenser_design_delta_t_k=loop.sizingPlant().loopDesignTemperatureDifference(),
            evaporation_loss_mode=tower.evaporationLossMode(),
            sizing_factor=optional_value(tower.sizingFactor()),
            supply_tower_count=len(loop_ref["towers"]),
            ems_actuator_count=len(ems),
            ems_actuators=sorted(ems, key=lambda x: x["handle"])[:8],
            preservation_policy="Retain tower identity, graph, curves, thermal/control and sizing inputs; only design fan power and its explicit Autosize flag change",
        ),
    )
    planned["warnings"].append(
        "Design fan power is total electrical watts for the complete tower at design airflow, not per-cell watts, motor horsepower or whole-plant efficiency. Retained fan curve, staging, free convection and controls determine runtime power; compare pumps and chillers separately"
    )
    if tower.isDesignAirFlowRateAutosized():
        planned["warnings"].append(
            "Design tower airflow is autosized from design fan power. Changing power changes reported design/free-convection airflow; recompute airflow-based metrics. The supported thermal models use airflow ratios, so this edit alone does not imply changed cooling, condenser temperatures or chiller/pump energy. In SaturatedExit mode, absolute airflow affects evaporation and make-up water; review water use and tower fan electricity"
        )
    if after["design_fan_power_w"] == "Autosize":
        require_plant_sizing(planned, translated["plant_sizing"])
        planned["warnings"].append(
            "Explicit Autosize sets design fan power to 0.0105 times water density times water specific heat times tower design water volume flow times condenser-loop design delta T, using sizing-condition fluid properties. A chiller COP change affects this sizing chain when tower design water flow is autosized; with fixed tower water flow and unchanged fluid properties/delta T, it does not change the sized fan power"
        )
    if ems:
        planned["warnings"].append(
            "Retained tower EMS can override operation; verify results before claiming energy savings"
        )
    if len(loop_ref["towers"]) > 1:
        planned["warnings"].append(
            "Other towers and plant dispatch remain unchanged; selected equipment may not run or carry the full load"
        )
    has_pump = any(
        obj.iddObjectType().valueName().startswith(("OS_Pump_", "OS_HeaderedPumps_"))
        for obj in loop.supplyComponents()
    )
    if not has_pump or not loop.supplyOutletNode().setpointManagers():
        planned["warnings"].append(
            "Existing condenser plant lacks an identified supply pump or outlet setpoint manager; a fan-power edit does not repair flow or temperature controls"
        )
        planned["simulation_ready"] = False
    return planned


def edit(model, sdk, planned):
    tower = tower_object(model, sdk, planned["resolved_objects"]["tower"])
    before = values(tower)
    value = planned["after_values"]["design_fan_power_w"]
    if value == "Autosize":
        call(tower, "autosizeDesignFanPower")
    else:
        call(tower, "setDesignFanPower", value)
    return dict(tower=ref(tower), before=before, after=values(tower))


def validate_model(model, sdk, planned, result):
    r = planned["resolved_objects"]
    tower = tower_object(model, sdk, r["tower"])
    checks = {
        "Tower identity/name/class changed": ref(tower)
        == r["tower"]
        == result["tower"],
        "Reported tower values differ": matches(
            result["before"], planned["before_values"]
        )
        and matches(result["after"], planned["after_values"]),
        "Saved tower power or sizing flag differs": matches(
            values(tower), planned["after_values"]
        ),
        "Unrequested tower fields changed": signature(tower)
        == planned["preserved_tower"],
        "Tower boundary nodes changed": ports(tower) == r["ports"],
        "Tower plant ownership changed": tower.plantLoop().is_initialized()
        and str(tower.plantLoop().get().handle()) == r["plant_loop"]["handle"],
        "Model objects/handles changed": original_types(model)
        == planned["before_objects"],
        "Protected model objects/references changed": protected_state(
            model, sdk, planned
        ),
    }
    if all(checks.values()):
        translated = translated_state(model, sdk, tower)
        checks["Translated tower fan power differs"] = matches(
            translated["settings"], planned["after_values"]
        )
        checks["Unrequested translated tower fields changed"] = (
            translated["preserved_fields"] == planned["translated_preserved_fields"]
        )
    return dict(
        ok=all(checks.values()),
        checks=len(checks),
        errors=[message for message, ok in checks.items() if not ok],
    )
