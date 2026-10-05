"""Resolve a bounded VAV plan; no SDK imports, model writes, or implicit choices."""

from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path

from common.vav_inventory import resolve

PROFILE = {
    "availability_schedule": {"builtin": "AlwaysOnDiscrete"},
    "outdoor_air_schedule": None,
    "return_plenum": None,
    "fan": {
        "total_efficiency": 0.62,
        "motor_efficiency": 0.9,
        "pressure_rise": 4.0,
        "pressure_units": "inH2O",
    },
    "minimum_system_airflow_ratio": 0.3,
    "minimum_terminal_airflow_fraction": 0.3,
    "sizing_option": "Coincident",
    "economizer": "NoEconomizer",
    "design_temperatures_c": dict(
        zip(
            (
                "preheat",
                "precool",
                "central_heating",
                "central_cooling",
                "zone_heating",
                "zone_cooling",
            ),
            (
                (45 - 32) * 5 / 9,
                (55 - 32) * 5 / 9,
                (55 - 32) * 5 / 9,
                (55 - 32) * 5 / 9,
                40.0,
                (55 - 32) * 5 / 9,
            ),
        )
    ),
}
CONTROLS = {
    "sizing_load_type": "Sensible",
    "outdoor_air_method": "ZoneSum",
    "oa_minimum_limit_type": "FixedMinimum",
    "night_cycle": "CycleOnAny",
    "night_cycle_runtime_seconds": 1800,
    "terminal_minimum_airflow_method": "Constant",
    "damper_heating_action": "Normal",
    "zone_heating_maximum_airflow_fraction": 1.0,
    "fan_end_use_subcategory": "VAV System Fans",
    "preheat_humidity_ratio": 0.008,
    "precool_humidity_ratio": 0.008,
    "central_cooling_humidity_ratio": 0.0085,
    "central_heating_humidity_ratio": 0.008,
    "fan_motor_in_airstream_fraction": 1.0,
    "fan_power_minimum_flow_fraction": 0.25,
    "fan_power_minimum_flow_input_method": "Fraction",
    "fan_power_coefficients": [0.040759894, 0.08804497, -0.07292612, 0.943739823, 0.0],
    "gas_burner_efficiency": 0.8,
    "electric_coil_efficiency": 1.0,
    "heating_water_controller_convergence": 0.1,
    "cooling_water_heat_exchanger": "CrossFlow",
    "water_controller_minimum_flow": 0.0,
    "component_availability": "AlwaysOnDiscrete",
    "cooling_controller_action": "Reverse",
    "gas_on_cycle_parasitic_electric_w": 0.0,
    "gas_off_cycle_parasitic_gas_w": 0.0,
    "all_outdoor_air_cooling": False,
    "all_outdoor_air_heating": False,
    "system_cooling_airflow_method": "DesignDay",
    "system_heating_airflow_method": "DesignDay",
    "zone_cooling_airflow_method": "DesignDayWithLimit",
    "zone_heating_airflow_method": "DesignDay",
    "sat_numeric_type": "Continuous",
    "sat_unit_type": "Temperature",
    "sat_schedule_type_limits_c": [0.0, 100.0],
}

PROFILE_NOTES = {
    "dx_curve_profile": "package-pinned SDK OS default",
    "plant_creation": "excluded; use explicit existing loops",
    "capacity_and_flow_sizing": "pinned SDK autosize defaults",
    "damper_profile": "generic constant; no template or ventilation correction",
    "economizer_limits": "unset; no template-specific limits",
}


def plan(config: dict, catalog: dict, input_path: Path) -> dict:
    parameters = deepcopy(config)
    errors, missing, assumptions, warnings = [], [], [], []
    name = config.get("system_name", "<system>")
    supplied_fan = config.get("fan", {})
    pressure_pair = ("pressure_rise", "pressure_units")
    incomplete_pressure = any(k in supplied_fan for k in pressure_pair) and not all(
        k in supplied_fan for k in pressure_pair
    )

    def assume(path, value):
        assumptions.append(f"Object:{name}.{path}: assumed to be {value}")

    if config.get("defaults_profile") == "prototype_vav_v1":
        for key, default in PROFILE.items():
            if key in ("fan", "design_temperatures_c"):
                target = parameters.setdefault(key, {})
                for field, value in default.items():
                    if key == "fan" and field in pressure_pair and incomplete_pressure:
                        continue
                    if field not in target:
                        target[field] = deepcopy(value)
                        assume(f"{key}.{field}", value)
            elif key not in parameters:
                parameters[key] = deepcopy(default)
                assume(key, default)
        for key, value in {**CONTROLS, **PROFILE_NOTES}.items():
            assume(f"controls.{key}", value)
        warnings.append(
            "prototype_vav_v1 uses generic prototype defaults; it does not establish code compliance or template-specific damper logic."
        )

    required = (
        "defaults_profile",
        "system_name",
        "output_model_path",
        "target_zones",
        "central_heating",
        "central_cooling",
        "reheat",
        *PROFILE.keys(),
    )
    for key in required:
        if key not in parameters:
            missing.append(key)
    for key in ("fan", "design_temperatures_c"):
        if key in parameters:
            missing.extend(
                f"{key}.{field}"
                for field in PROFILE[key]
                if field not in parameters[key]
            )
    resolved = {"target_zones": [], "plant_loops": {}, "schedules": {}}
    if "system_name" in config and any(
        loop["name"] == name for loop in catalog["air_loops"]
    ):
        errors.append("system_name: an air loop already has this name")
    if "output_model_path" in config:
        output = Path(config["output_model_path"])
        if not output.is_absolute():
            errors.append("output_model_path: use an absolute path")
        if output.is_symlink():
            errors.append("output_model_path: an existing symlink is not a new output")
        output = output.resolve()
        parameters["output_model_path"] = str(output)
        if output == input_path.resolve() or output.exists():
            errors.append(
                "output_model_path: must be a new path that preserves the input and any existing output"
            )
        if output.suffix.lower() != ".osm":
            errors.append("output_model_path: must end with .osm")
        parent = output.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        if not parent.exists():
            errors.append("output_model_path: output drive/root does not exist")
        elif not parent.is_dir():
            errors.append("output_model_path: parent path is not a directory")
    selected = set()
    for i, selector in enumerate(config.get("target_zones", [])):
        zone = resolve(selector, catalog["zones"], f"target_zones[{i}]", errors)
        if zone is None:
            continue
        if zone["handle"] in selected:
            errors.append("target_zones: multiple selectors resolve to the same zone")
        selected.add(zone["handle"])
        if zone["is_plenum"] or not zone["spaces"] or not zone["has_thermostat"]:
            errors.append(
                f"target_zones: {zone['name']} needs occupied spaces and an existing thermostat and must not be a plenum"
            )
        if not zone.get("has_dual_setpoint_schedules"):
            errors.append(
                f"target_zones: {zone['name']} requires a dual-setpoint thermostat with heating and cooling schedules"
            )
        if zone["air_loops"] or zone["equipment"]:
            errors.append(
                f"target_zones: {zone['name']} already has HVAC; replacement is outside this operation"
            )
        resolved["target_zones"].append(
            {"name": zone["name"], "handle": zone["handle"]}
        )
    for key in ("central_heating", "central_cooling", "reheat"):
        coil = config.get(key)
        if coil is None:
            continue
        kind = coil.get("type")
        if kind is None:
            missing.append(f"{key}.type")
        if kind == "Water":
            if "plant_loop" not in coil:
                missing.append(f"{key}.plant_loop")
            else:
                loop = resolve(
                    coil["plant_loop"],
                    catalog["plant_loops"],
                    f"{key}.plant_loop",
                    errors,
                )
                if loop:
                    expected = "Cooling" if key == "central_cooling" else "Heating"
                    if loop["loop_type"] != expected:
                        errors.append(f"{key}.plant_loop: requires a {expected} loop")
                    if not loop.get("supply_equipment"):
                        errors.append(
                            f"{key}.plant_loop: requires existing supply equipment"
                        )
                    if not loop.get("supply_pumps"):
                        errors.append(
                            f"{key}.plant_loop: requires an existing supply pump"
                        )
                    if not loop.get("supply_setpoint_managers"):
                        errors.append(
                            f"{key}.plant_loop: requires a supply-outlet setpoint manager"
                        )
                    supply = loop.get("design_supply_temperature_c")
                    delta = loop.get("design_delta_temperature_k")
                    t = parameters.get("design_temperatures_c", {})
                    if (
                        supply is None
                        or delta is None
                        or not math.isfinite(supply)
                        or not math.isfinite(delta)
                        or delta <= 0
                    ):
                        errors.append(
                            f"{key}.plant_loop: requires finite design temperature and positive delta"
                        )
                    elif key == "central_cooling":
                        if supply >= t.get("central_cooling", float("inf")):
                            errors.append(
                                f"{key}.plant_loop: chilled water must be colder than cooling supply air"
                            )
                    elif supply - delta <= t.get(
                        "zone_heating" if key == "reheat" else "central_heating",
                        float("-inf"),
                    ):
                        errors.append(
                            f"{key}.plant_loop: hot-water return must be warmer than rated outlet air"
                        )
                    resolved["plant_loops"][key] = {
                        "name": loop["name"],
                        "handle": loop["handle"],
                        "design_supply_temperature_c": supply,
                        "design_delta_temperature_k": delta,
                    }
        elif "plant_loop" in coil:
            errors.append(f"{key}.plant_loop: only valid for Water")
        if kind == "DXTwoSpeed" and coil.get("dx_approved") is not True:
            missing.append(f"{key}.dx_approved=true")
        if "dx_approved" in coil and (key != "central_cooling" or kind != "DXTwoSpeed"):
            errors.append(f"{key}.dx_approved: only valid for DXTwoSpeed cooling")
    for key in ("availability_schedule", "outdoor_air_schedule"):
        selector = parameters.get(key)
        if selector is None:
            continue
        if "builtin" in selector:
            resolved["schedules"][key] = selector
            continue
        schedule = resolve(selector, catalog["schedules"], key, errors)
        if schedule:
            limits = schedule["type_limits"]
            if not limits or limits["unit_type"] not in (
                "Availability",
                "Dimensionless",
            ):
                errors.append(
                    f"{key}: select a schedule with availability/fraction type limits"
                )
            elif (
                limits["lower"] is None
                or limits["upper"] is None
                or limits["lower"] < 0
                or limits["upper"] > 1
            ):
                errors.append(
                    f"{key}: schedule type limits must be bounded within [0,1]"
                )
            resolved["schedules"][key] = {
                "name": schedule["name"],
                "handle": schedule["handle"],
            }
    if parameters.get("return_plenum"):
        zone = resolve(
            parameters["return_plenum"], catalog["zones"], "return_plenum", errors
        )
        if zone:
            if (
                zone["handle"] in selected
                or not zone["spaces"]
                or not zone.get("can_be_plenum", False)
                or zone.get("plenum_air_loops")
                or zone["air_loops"]
                or zone["equipment"]
            ):
                errors.append(
                    "return_plenum: select a distinct eligible zone with spaces and no HVAC or plenum association to another loop"
                )
            resolved["return_plenum"] = {"name": zone["name"], "handle": zone["handle"]}
    if parameters.get("design_temperatures_c", {}).get("central_cooling", 0) < 0:
        errors.append(
            "design_temperatures_c.central_cooling: SAT must be within the prototype Temperature schedule limits [0,100]"
        )
    t = parameters.get("design_temperatures_c", {})
    for lower, upper, enabled in (
        ("central_cooling", "precool", True),
        ("central_cooling", "zone_cooling", True),
        (
            "preheat",
            "central_heating",
            config.get("central_heating", {}).get("type") not in (None, "None"),
        ),
        (
            "central_heating",
            "zone_heating",
            config.get("reheat", {}).get("type") not in (None, "None"),
        ),
        ("zone_cooling", "zone_heating", True),
    ):
        if enabled and lower in t and upper in t and t[lower] > t[upper]:
            errors.append(f"design_temperatures_c: {lower} must not exceed {upper}")
    if parameters.get("minimum_terminal_airflow_fraction", 0) > parameters.get(
        "minimum_system_airflow_ratio", 1
    ):
        errors.append(
            "minimum_terminal_airflow_fraction: cannot exceed minimum_system_airflow_ratio in this generic constant-flow profile"
        )
    conversions = []
    fan = parameters.get("fan", {})
    if fan.get("total_efficiency", 0) > fan.get("motor_efficiency", 1):
        errors.append("fan.total_efficiency: cannot exceed motor_efficiency")
    if all(key in fan for key in PROFILE["fan"]):
        pressure = fan["pressure_rise"]
        if fan["pressure_units"] == "inH2O":
            pressure *= 249.08891  # Verified with OpenStudio 3.11.0 convert().
            if not math.isfinite(pressure):
                errors.append("fan.pressure_rise: SI conversion is not finite")
                pressure = None
            else:
                conversions.append(
                    {
                        "field": "fan.pressure_rise",
                        "from": fan["pressure_rise"],
                        "from_units": "inH2O",
                        "to": pressure,
                        "to_units": "Pa",
                    }
                )
        fan["pressure_rise_pa"] = pressure
    return {
        "ready": not errors and not missing,
        "missing_inputs": sorted(set(missing)),
        "errors": errors,
        "assumptions": assumptions,
        "warnings": warnings,
        "parameters": parameters,
        "resolved_objects": resolved,
        "controls": deepcopy(CONTROLS) if config.get("defaults_profile") else {},
        "conversions": conversions,
        "expected_changes": {
            "air_loops": 1,
            "terminals": len(selected),
            "zone_reheat_coils": (
                len(selected)
                if config.get("reheat", {}).get("type") not in (None, "None")
                else 0
            ),
        },
    }
