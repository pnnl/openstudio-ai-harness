"""Bounded generic prototype VAV construction for OpenStudio 3.11.0."""

from __future__ import annotations


def call(obj, method, *args):
    """SDK setters may return bool, void, or an optional; reject explicit failure."""
    result = getattr(obj, method)(*args)
    if result is False:
        raise RuntimeError(f"SDK rejected {obj.nameString()}.{method}")
    return result


def by_handle(model, sdk, reference, kind):
    result = getattr(model, f"get{kind}")(sdk.toUUID(reference["handle"]))
    if not result.is_initialized():
        raise ValueError(f"Resolved {kind} no longer exists: {reference['handle']}")
    return result.get()


def schedule(model, sdk, reference):
    if reference.get("builtin"):
        methods = {
            "AlwaysOnDiscrete": "alwaysOnDiscreteSchedule",
            "AlwaysOffDiscrete": "alwaysOffDiscreteSchedule",
        }
        return getattr(model, methods[reference["builtin"]])()
    return by_handle(model, sdk, reference, "Schedule")


def water_controller(coil, heating, controls):
    controller = coil.controllerWaterCoil()
    if not controller.is_initialized():
        raise RuntimeError(f"Missing water controller: {coil.nameString()}")
    controller = controller.get()
    call(controller, "setName", f"{coil.nameString()} Controller")
    call(
        controller, "setMinimumActuatedFlow", controls["water_controller_minimum_flow"]
    )
    if heating:
        call(
            controller,
            "setControllerConvergenceTolerance",
            controls["heating_water_controller_convergence"],
        )
    else:
        call(controller, "setAction", controls["cooling_controller_action"])


def make_coil(model, sdk, resolved, parameters, controls, role, name, node=None):
    config = parameters[role]
    kind = config["type"]
    if kind == "None":
        return None
    heating = role != "central_cooling"
    classes = {
        "NaturalGas": "CoilHeatingGas",
        "Electricity": "CoilHeatingElectric",
        "DXTwoSpeed": "CoilCoolingDXTwoSpeed",
        "Water": "CoilHeatingWater" if heating else "CoilCoolingWater",
    }
    coil = getattr(sdk.model, classes[kind])(model)
    call(coil, "setName", name)
    if kind == "Water":
        plant = by_handle(model, sdk, resolved["plant_loops"][role], "PlantLoop")
        call(plant, "addDemandBranchForComponent", coil)
    if node is not None:
        call(coil, "addToNode", node)
    call(
        coil,
        "setAvailabilitySchedule",
        schedule(model, sdk, {"builtin": controls["component_availability"]}),
    )
    if kind == "Water":
        if heating:
            supply = resolved["plant_loops"][role]["design_supply_temperature_c"]
            delta = resolved["plant_loops"][role]["design_delta_temperature_k"]
            t = parameters["design_temperatures_c"]
            call(coil, "setRatedInletWaterTemperature", supply)
            call(coil, "setRatedOutletWaterTemperature", supply - delta)
            call(
                coil,
                "setRatedInletAirTemperature",
                t["central_heating"] if role == "reheat" else t["preheat"],
            )
            call(
                coil,
                "setRatedOutletAirTemperature",
                t["zone_heating"] if role == "reheat" else t["central_heating"],
            )
        else:
            call(coil, "autosizeDesignInletWaterTemperature")
            call(
                coil,
                "setHeatExchangerConfiguration",
                controls["cooling_water_heat_exchanger"],
            )
        water_controller(coil, heating, controls)
    elif kind == "NaturalGas":
        call(coil, "setGasBurnerEfficiency", controls["gas_burner_efficiency"])
        call(
            coil,
            "setOnCycleParasiticElectricLoad",
            controls["gas_on_cycle_parasitic_electric_w"],
        )
        call(
            coil,
            "setOffCycleParasiticGasLoad",
            controls["gas_off_cycle_parasitic_gas_w"],
        )
    elif kind == "Electricity":
        call(coil, "setEfficiency", controls["electric_coil_efficiency"])
    # DXTwoSpeed intentionally retains pinned SDK curves: Ruby's 'OS default'.
    return coil


def create(model, sdk, planned):
    p, r = planned["parameters"], planned["resolved_objects"]
    t = p["design_temperatures_c"]
    c = planned["controls"]
    loop = sdk.model.AirLoopHVAC(model)
    call(loop, "setName", p["system_name"])
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
    fan = sdk.model.FanVariableVolume(model)
    call(fan, "setName", f"{p['system_name']} Fan")
    for field, value in {
        "FanEfficiency": p["fan"]["total_efficiency"],
        "MotorEfficiency": p["fan"]["motor_efficiency"],
        "PressureRise": p["fan"]["pressure_rise_pa"],
        "MotorInAirstreamFraction": c["fan_motor_in_airstream_fraction"],
        "FanPowerMinimumFlowRateInputMethod": c["fan_power_minimum_flow_input_method"],
        "FanPowerMinimumFlowFraction": c["fan_power_minimum_flow_fraction"],
        "EndUseSubcategory": c["fan_end_use_subcategory"],
    }.items():
        call(fan, f"set{field}", value)
    for i, coefficient in enumerate(c["fan_power_coefficients"], 1):
        call(fan, f"setFanPowerCoefficient{i}", coefficient)
    call(
        fan,
        "setAvailabilitySchedule",
        schedule(model, sdk, {"builtin": c["component_availability"]}),
    )
    call(fan, "addToNode", loop.supplyInletNode())
    make_coil(
        model,
        sdk,
        r,
        p,
        c,
        "central_heating",
        f"{p['system_name']} Main Heating Coil",
        loop.supplyInletNode(),
    )
    make_coil(
        model,
        sdk,
        r,
        p,
        c,
        "central_cooling",
        f"{p['system_name']} Cooling Coil",
        loop.supplyInletNode(),
    )
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
            "setMinimumOutdoorAirSchedule",
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
    for reference in r["target_zones"]:
        zone = by_handle(model, sdk, reference, "ThermalZone")
        reheat = make_coil(
            model, sdk, r, p, c, "reheat", f"{zone.nameString()} Reheat Coil"
        )
        if reheat:
            terminal = sdk.model.AirTerminalSingleDuctVAVReheat(
                model,
                schedule(model, sdk, {"builtin": c["component_availability"]}),
                reheat,
            )
            call(terminal, "setDamperHeatingAction", c["damper_heating_action"])
            call(terminal, "setMaximumReheatAirTemperature", t["zone_heating"])
        else:
            terminal = sdk.model.AirTerminalSingleDuctVAVNoReheat(
                model, schedule(model, sdk, {"builtin": c["component_availability"]})
            )
        call(terminal, "setName", f"{zone.nameString()} VAV Terminal")
        call(
            terminal,
            "setZoneMinimumAirFlowInputMethod",
            c["terminal_minimum_airflow_method"],
        )
        call(
            terminal,
            "setConstantMinimumAirFlowFraction",
            p["minimum_terminal_airflow_fraction"],
        )
        call(loop, "multiAddBranchForZone", zone, terminal)
        if reheat and p["reheat"]["type"] == "Water":
            # Attachments can reset the controller; set and validate after the final connection.
            water_controller(reheat, True, c)
        zone_sizing = zone.sizingZone()
        call(
            zone_sizing,
            "setCoolingDesignAirFlowMethod",
            c["zone_cooling_airflow_method"],
        )
        call(
            zone_sizing,
            "setHeatingMaximumAirFlowFraction",
            c["zone_heating_maximum_airflow_fraction"],
        )
        call(zone_sizing, "setZoneCoolingDesignSupplyAirTemperature", t["zone_cooling"])
        if reheat:
            call(
                zone_sizing,
                "setHeatingDesignAirFlowMethod",
                c["zone_heating_airflow_method"],
            )
            call(
                zone_sizing,
                "setZoneHeatingDesignSupplyAirTemperature",
                t["zone_heating"],
            )
        if "return_plenum" in r:
            call(
                zone,
                "setReturnPlenum",
                by_handle(model, sdk, r["return_plenum"], "ThermalZone"),
            )
    return str(loop.handle())
