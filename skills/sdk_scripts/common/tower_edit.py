"""Reviewed in-place variable-speed tower fan power and low-load control edits."""

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
FIELDS = {
    "design_fan_power_w": ("DesignFanPower", POWER_FIELD),
    "minimum_air_flow_ratio": (
        "MinimumAirFlowRateRatio",
        "Minimum Air Flow Rate Ratio",
    ),
    "free_convection_capacity_fraction": (
        "FractionofTowerCapacityinFreeConvectionRegime",
        "Fraction of Tower Capacity in Free Convection Regime",
    ),
}

# Pinned EnergyPlus 25.2 IDD defaults; OpenStudio's optional getters omit these.
CONTROL_DEFAULTS = {
    "minimum_air_flow_ratio": 0.2,
    "free_convection_capacity_fraction": 0.125,
}


def blank_control(tower, key):
    index = tower.iddObject().getFieldIndex(FIELDS[key][1]).get()
    raw = tower.getString(index)
    return not raw.is_initialized() or not raw.get().strip()


def control_value(tower, key):
    if blank_control(tower, key):
        return CONTROL_DEFAULTS[key]
    suffix = FIELDS[key][0]
    return optional_value(getattr(tower, suffix[0].lower() + suffix[1:])())


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


def values(tower, patch=None):
    result = dict(design_fan_power_w=sized(tower, "DesignFanPower"))
    for key in patch or {}:
        if key != "design_fan_power_w":
            result[key] = control_value(tower, key)
    return result


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


def signature(tower, patch=None):
    return fingerprint(
        tower,
        ignored=[FIELDS[key][1] for key in (patch or {"design_fan_power_w": None})],
    )


def translated_state(model, sdk, tower, patch=None):
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
    active = {"design_fan_power_w": FIELDS["design_fan_power_w"]}
    active.update({key: FIELDS[key] for key in (patch or {})})
    settings, excluded = {}, []
    for key, (_, field) in active.items():
        index = obj.iddObject().getFieldIndex(field)
        if not index.is_initialized():
            raise ValueError(
                "Translated cooling tower is missing a required performance field"
            )
        excluded.append(index.get())
        raw = optional_string(obj, index.get())
        if key == "design_fan_power_w" and raw.lower() == "autosize":
            settings[key] = "Autosize"
        else:
            # Resolve a genuinely blank control using the pinned EnergyPlus IDD,
            # while malformed nonblank values must still reject.
            number = obj.getDouble(
                index.get(), key in CONTROL_DEFAULTS and not raw.strip()
            )
            if not number.is_initialized() or not math.isfinite(number.get()):
                raise ValueError(
                    "Translated cooling tower performance field is not numeric"
                )
            settings[key] = number.get()
    return dict(
        plant_sizing=sizing_context(model, sdk, workspace),
        settings=settings,
        preserved_fields=[
            [obj.iddObject().getField(i).get().name(), optional_string(obj, i)]
            for i in range(obj.numFields())
            if i not in excluded
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
    patch = dict(config["settings"])
    before = values(tower, patch)
    defaulted = {
        key: CONTROL_DEFAULTS[key]
        for key in patch
        if key in CONTROL_DEFAULTS and blank_control(tower, key)
    }
    if defaulted:
        planned["source_control_defaults"] = defaulted
        planned["warnings"].append(
            "Blank requested controls use the pinned EnergyPlus 25.2 IDD defaults shown in source_control_defaults. Unrequested blank fields remain blank; only explicit requested edits write values"
        )
    after = dict(before, **patch)
    if before["design_fan_power_w"] is None:
        planned["errors"].append(
            "Source tower design fan power is unset; diagnose the incomplete source model before editing"
        )
        return planned
    if matches(before, after):
        planned["errors"].append(
            "Edit must change tower fan power, sizing policy or low-load controls"
        )
        return planned
    if any(value is None for value in before.values()):
        planned["errors"].append(
            "Source tower requested control is unset; diagnose before editing"
        )
        return planned
    try:
        translated = translated_state(model, sdk, tower, patch)
    except ValueError as exc:
        planned["errors"].append(str(exc))
        return planned
    if not matches(translated["settings"], before):
        planned["errors"].append(
            "Source tower fan power disagrees with EnergyPlus translation or requested control differs; diagnose the source model before editing"
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
        parameters=dict(output_model_path=config["output_model_path"], settings=patch),
        resolved_objects=dict(
            plant_loop=ref(loop), tower=ref(tower), ports=ports(tower)
        ),
        before_values=before,
        after_values=after,
        preserved_tower=signature(tower, patch),
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
            minimum_air_flow_ratio=control_value(tower, "minimum_air_flow_ratio"),
            free_convection_capacity_fraction=control_value(
                tower, "free_convection_capacity_fraction"
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
            preservation_policy="Retain tower identity, graph, curves, design conditions, flows, staging and unrequested inputs; only explicitly requested fan power or low-load controls change",
        ),
    )
    planned["warnings"].append(
        "Design fan power is total electrical watts for the complete tower at design airflow, not per-cell watts, motor horsepower or whole-plant efficiency. Fan curve, staging, free convection and controls determine runtime power; compare pumps and chillers separately"
    )
    if "design_fan_power_w" in patch and tower.isDesignAirFlowRateAutosized():
        planned["warnings"].append(
            "Design tower airflow is autosized from design fan power. Changing power changes reported design/free-convection airflow; recompute airflow-based metrics. The supported thermal models use airflow ratios, so this edit alone does not imply changed cooling, condenser temperatures or chiller/pump energy. In SaturatedExit mode, absolute airflow affects evaporation and make-up water; review water use and tower fan electricity"
        )
    if patch.get("design_fan_power_w") == "Autosize":
        require_plant_sizing(planned, translated["plant_sizing"])
        planned["warnings"].append(
            "Explicit Autosize sets design fan power to 0.0105 times water density times water specific heat times tower design water volume flow times condenser-loop design delta T, using sizing-condition fluid properties. A chiller COP change affects this sizing chain when tower design water flow is autosized; with fixed tower water flow and unchanged fluid properties/delta T, it does not change the sized fan power"
        )
    controls = set(patch) - {"design_fan_power_w"}
    if controls:
        planned["impact"]["low_load_controls"] = dict(
            before={key: before[key] for key in sorted(controls)},
            after={key: after[key] for key in sorted(controls)},
            minimum_air_flow_ratio_limits=[0.2, 0.5],
            free_convection_capacity_fraction_limits=[0, 0.2],
            fan_curve_policy="Retain configured curve or implicit cubic; no fan-power floor is inferred",
        )
        planned["warnings"].append(
            "Low-load settings change actual thermal operation and fan electricity, not just rated fan watts. Minimum airflow ratio is the fan-on modulation floor; below it EnergyPlus cycles the fan to meet the water setpoint, so reported average airflow can be lower. Free-convection fraction estimates fan-off heat rejection at current conditions, not guaranteed annual free cooling or a fan speed. It does not switch off the condenser pump; verify cooling delivered, fan cycling, chiller/pump energy and make-up water before claiming savings"
        )
        if "minimum_air_flow_ratio" in controls:
            planned["warnings"].append(
                "Changing minimum airflow can shift cycling and minimum-speed fan power through the retained curve. EnergyPlus also derives reported free-convection design airflow from minimum airflow ratio times design airflow; sizing inputs remain unchanged"
            )
        if "free_convection_capacity_fraction" in controls:
            planned["warnings"].append(
                "The free-convection fraction is a manufacturer/performance assumption; do not infer it from a desired savings percentage. Zero removes the modeled fan-off heat-rejection contribution, while higher fractions can extend fan-off operation and can overcool water below setpoint. Runtime free-convection airflow ratio reporting uses this fraction; design free-convection airflow instead uses minimum airflow ratio"
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
            "Existing condenser plant lacks an identified supply pump or outlet setpoint manager; a tower performance edit does not repair flow or temperature controls"
        )
        planned["simulation_ready"] = False
    return planned


def edit(model, sdk, planned):
    tower = tower_object(model, sdk, planned["resolved_objects"]["tower"])
    patch = planned["parameters"]["settings"]
    before = values(tower, patch)
    for key, value in patch.items():
        suffix = FIELDS[key][0]
        if key == "design_fan_power_w" and value == "Autosize":
            call(tower, "autosizeDesignFanPower")
        else:
            call(tower, "set" + suffix, value)
    return dict(tower=ref(tower), before=before, after=values(tower, patch))


def validate_model(model, sdk, planned, result):
    r = planned["resolved_objects"]
    patch = planned["parameters"]["settings"]
    tower = tower_object(model, sdk, r["tower"])
    checks = {
        "Tower identity/name/class changed": ref(tower)
        == r["tower"]
        == result["tower"],
        "Reported tower values differ": matches(
            result["before"], planned["before_values"]
        )
        and matches(result["after"], planned["after_values"]),
        "Saved tower settings differ": matches(
            values(tower, patch), planned["after_values"]
        ),
        "Unrequested tower fields changed": signature(tower, patch)
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
        translated = translated_state(model, sdk, tower, patch)
        checks["Translated tower settings differ"] = matches(
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
