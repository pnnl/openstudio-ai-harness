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
        for key, value in CONTROLS.items():
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
        output = output.resolve()
        parameters["output_model_path"] = str(output)
        if output == input_path.resolve() or output.exists():
            errors.append(
                "output_model_path: must be a new path that preserves the input and any existing output"
            )
        if output.suffix.lower() != ".osm":
            errors.append("output_model_path: must end with .osm")
        parent = output.parent
        while not parent.exists():
            parent = parent.parent
        if not parent.is_dir():
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
                    resolved["plant_loops"][key] = {
                        "name": loop["name"],
                        "handle": loop["handle"],
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
                or not zone["is_plenum"]
            ):
                errors.append(
                    "return_plenum: select a distinct existing plenum zone with spaces"
                )
            resolved["return_plenum"] = {"name": zone["name"], "handle": zone["handle"]}
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
