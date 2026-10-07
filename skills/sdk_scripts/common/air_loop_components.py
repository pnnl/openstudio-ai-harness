"""Shared air-loop equipment and controls with explicit recipe parameters."""

from __future__ import annotations
from common.hvac_equipment import call, schedule
from common.air_system_recipe import VAV


def configure_sizing(model, sdk, loop, p, r, c):
    t = p["design_temperatures_c"]
    sizing = loop.sizingSystem()
    settings = {
        "TypeofLoadtoSizeOn": c["sizing_load_type"],
        "PreheatDesignTemperature": t["preheat"],
        "PrecoolDesignTemperature": t["precool"],
        "CentralCoolingDesignSupplyAirTemperature": t["central_cooling"],
        "CentralHeatingDesignSupplyAirTemperature": t["central_heating"],
        "PreheatDesignHumidityRatio": c["preheat_humidity_ratio"],
        "PrecoolDesignHumidityRatio": c["precool_humidity_ratio"],
        "CentralCoolingDesignSupplyAirHumidityRatio": c[
            "central_cooling_humidity_ratio"
        ],
        "CentralHeatingDesignSupplyAirHumidityRatio": c[
            "central_heating_humidity_ratio"
        ],
        "CentralHeatingMaximumSystemAirFlowRatio": p["minimum_system_airflow_ratio"],
        "SizingOption": p["sizing_option"],
        "AllOutdoorAirinCooling": c["all_outdoor_air_cooling"],
        "AllOutdoorAirinHeating": c["all_outdoor_air_heating"],
        "SystemOutdoorAirMethod": c["outdoor_air_method"],
        "CoolingDesignAirFlowMethod": c["system_cooling_airflow_method"],
        "HeatingDesignAirFlowMethod": c["system_heating_airflow_method"],
    }
    for field, value in settings.items():
        call(sizing, f"set{field}", value)
    call(sizing, "autosizeDesignOutdoorAirFlowRate")


def attach_supply_setpoint(model, sdk, loop, p, r, c):
    t = p["design_temperatures_c"]
    sat = sdk.model.ScheduleRuleset(model)
    call(sat, "setName", f"{p['system_name']} Supply Air Temperature")
    limits = sdk.model.ScheduleTypeLimits(model)
    call(limits, "setUnitType", c["sat_unit_type"])
    call(limits, "setLowerLimitValue", c["sat_schedule_type_limits_c"][0])
    call(limits, "setUpperLimitValue", c["sat_schedule_type_limits_c"][1])
    call(limits, "setNumericType", c["sat_numeric_type"])
    call(sat, "setScheduleTypeLimits", limits)
    call(
        sat.defaultDaySchedule(),
        "addValue",
        sdk.Time(0, 24, 0, 0),
        t["central_cooling"],
    )
    spm = sdk.model.SetpointManagerScheduled(model, sat)
    call(spm, "setName", f"{p['system_name']} Supply Air Setpoint Manager")
    call(spm, "addToNode", loop.supplyOutletNode())


def attach_fan(model, sdk, loop, p, r, c, *, recipe=VAV):
    fan = getattr(sdk.model, recipe.fan_class)(model)
    call(fan, "setName", f"{p['system_name']} Fan")
    fields = {
        "FanEfficiency": p["fan"]["total_efficiency"],
        "MotorEfficiency": p["fan"]["motor_efficiency"],
        "PressureRise": p["fan"]["pressure_rise_pa"],
        "MotorInAirstreamFraction": c["fan_motor_in_airstream_fraction"],
        "EndUseSubcategory": c["fan_end_use_subcategory"],
    }
    if recipe.fan_kind == "VariableVolume":
        fields.update(
            FanPowerMinimumFlowRateInputMethod=c["fan_power_minimum_flow_input_method"],
            FanPowerMinimumFlowFraction=c["fan_power_minimum_flow_fraction"],
        )
    for field, value in fields.items():
        call(fan, f"set{field}", value)
    if recipe.fan_kind == "VariableVolume":
        for i, coefficient in enumerate(c["fan_power_coefficients"], 1):
            call(fan, f"setFanPowerCoefficient{i}", coefficient)
    call(
        fan,
        "setAvailabilitySchedule",
        schedule(model, sdk, {"builtin": c["component_availability"]}),
    )
    call(fan, "addToNode", loop.supplyInletNode())


def attach_outdoor_air(model, sdk, loop, p, r, c, *, recipe=VAV):
    oa = sdk.model.ControllerOutdoorAir(model)
    call(oa, "setName", f"{p['system_name']} OA Controller")
    call(oa, "setMinimumLimitType", c["oa_minimum_limit_type"])
    call(oa, "autosizeMinimumOutdoorAirFlowRate")
    call(oa, "resetMaximumFractionofOutdoorAirSchedule")
    call(oa, "resetEconomizerMinimumLimitDryBulbTemperature")
    call(oa, "setEconomizerControlType", p["economizer"])
    if "outdoor_air_schedule" in r["schedules"]:
        call(
            oa,
            recipe.oa_schedule_setter,
            schedule(model, sdk, r["schedules"]["outdoor_air_schedule"]),
        )
    call(
        oa.controllerMechanicalVentilation(),
        "setName",
        f"{p['system_name']} Vent Controller",
    )
    call(
        oa.controllerMechanicalVentilation(),
        "setSystemOutdoorAirMethod",
        c["outdoor_air_method"],
    )
    oa_system = sdk.model.AirLoopHVACOutdoorAirSystem(model, oa)
    call(oa_system, "setName", f"{p['system_name']} OA System")
    call(oa_system, "addToNode", loop.supplyInletNode())


def configure_availability(model, sdk, loop, p, r, c):
    call(
        loop,
        "setAvailabilitySchedule",
        schedule(model, sdk, r["schedules"]["availability_schedule"]),
    )
    call(loop, "setNightCycleControlType", c["night_cycle"])
    managers = [
        x.to_AvailabilityManagerNightCycle() for x in loop.availabilityManagers()
    ]
    night = [x.get() for x in managers if x.is_initialized()]
    if len(night) != 1:
        raise RuntimeError("Expected one night-cycle manager")
    call(night[0], "setCyclingRunTime", c["night_cycle_runtime_seconds"])
