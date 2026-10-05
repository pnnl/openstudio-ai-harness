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
    if reference.get("builtin") == "AlwaysOnDiscrete":
        return model.alwaysOnDiscreteSchedule()
    return by_handle(model, sdk, reference, "Schedule")


def water_controller(coil, heating):
    controller = coil.controllerWaterCoil()
    if not controller.is_initialized():
        raise RuntimeError(f"Missing water controller: {coil.nameString()}")
    controller = controller.get()
    call(controller, "setName", f"{coil.nameString()} Controller")
    call(controller, "setMinimumActuatedFlow", 0.0)
    if heating:
        call(controller, "setControllerConvergenceTolerance", 0.1)
    else:
        call(controller, "setAction", "Reverse")


def make_coil(model, sdk, resolved, parameters, role, name, node=None):
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
    call(coil, "setAvailabilitySchedule", model.alwaysOnDiscreteSchedule())
    if kind == "Water":
        if heating:
            supply = plant.sizingPlant().designLoopExitTemperature()
            delta = plant.sizingPlant().loopDesignTemperatureDifference()
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
            call(coil, "setHeatExchangerConfiguration", "CrossFlow")
        water_controller(coil, heating)
    elif kind == "NaturalGas":
        call(coil, "setGasBurnerEfficiency", 0.8)
        call(coil, "setOnCycleParasiticElectricLoad", 0.0)
        call(coil, "setOffCycleParasiticGasLoad", 0.0)
    elif kind == "Electricity":
        call(coil, "setEfficiency", 1.0)
    # DXTwoSpeed intentionally retains pinned SDK curves: Ruby's 'OS default'.
    return coil


def create(model, sdk, planned):
    p, r = planned["parameters"], planned["resolved_objects"]
    t = p["design_temperatures_c"]
    loop = sdk.model.AirLoopHVAC(model)
    call(loop, "setName", p["system_name"])
    sizing = loop.sizingSystem()
    settings = {
        "TypeofLoadtoSizeOn": "Sensible",
        "PreheatDesignTemperature": t["preheat"],
        "PrecoolDesignTemperature": t["precool"],
        "CentralCoolingDesignSupplyAirTemperature": t["central_cooling"],
        "CentralHeatingDesignSupplyAirTemperature": t["central_heating"],
        "PreheatDesignHumidityRatio": 0.008,
        "PrecoolDesignHumidityRatio": 0.008,
        "CentralCoolingDesignSupplyAirHumidityRatio": 0.0085,
        "CentralHeatingDesignSupplyAirHumidityRatio": 0.008,
        "CentralHeatingMaximumSystemAirFlowRatio": p["minimum_system_airflow_ratio"],
        "SizingOption": p["sizing_option"],
        "AllOutdoorAirinCooling": False,
        "AllOutdoorAirinHeating": False,
        "SystemOutdoorAirMethod": "ZoneSum",
        "CoolingDesignAirFlowMethod": "DesignDay",
        "HeatingDesignAirFlowMethod": "DesignDay",
    }
    for field, value in settings.items():
        call(sizing, f"set{field}", value)
    call(sizing, "autosizeDesignOutdoorAirFlowRate")
    sat = sdk.model.ScheduleRuleset(model)
    call(sat, "setName", f"{p['system_name']} Supply Air Temperature")
    limits = sdk.model.ScheduleTypeLimits(model)
    call(limits, "setUnitType", "Temperature")
    call(limits, "setLowerLimitValue", 0.0)
    call(limits, "setUpperLimitValue", 100.0)
    call(limits, "setNumericType", "Continuous")
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
        "MotorInAirstreamFraction": 1.0,
        "FanPowerMinimumFlowRateInputMethod": "Fraction",
        "FanPowerMinimumFlowFraction": 0.25,
        "EndUseSubcategory": "VAV System Fans",
    }.items():
        call(fan, f"set{field}", value)
    for i, coefficient in enumerate(
        (0.040759894, 0.08804497, -0.07292612, 0.943739823), 1
    ):
        call(fan, f"setFanPowerCoefficient{i}", coefficient)
    # JSON coefficient 5 is null; preserve the pinned SDK default (0).
    call(fan, "setAvailabilitySchedule", model.alwaysOnDiscreteSchedule())
    call(fan, "addToNode", loop.supplyInletNode())
    make_coil(
        model,
        sdk,
        r,
        p,
        "central_heating",
        f"{p['system_name']} Main Heating Coil",
        loop.supplyInletNode(),
    )
    make_coil(
        model,
        sdk,
        r,
        p,
        "central_cooling",
        f"{p['system_name']} Cooling Coil",
        loop.supplyInletNode(),
    )
    oa = sdk.model.ControllerOutdoorAir(model)
    call(oa, "setName", f"{p['system_name']} OA Controller")
    call(oa, "setMinimumLimitType", "FixedMinimum")
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
    call(oa.controllerMechanicalVentilation(), "setSystemOutdoorAirMethod", "ZoneSum")
    oa_system = sdk.model.AirLoopHVACOutdoorAirSystem(model, oa)
    call(oa_system, "setName", f"{p['system_name']} OA System")
    call(oa_system, "addToNode", loop.supplyInletNode())
    call(
        loop,
        "setAvailabilitySchedule",
        schedule(model, sdk, r["schedules"]["availability_schedule"]),
    )
    call(loop, "setNightCycleControlType", "CycleOnAny")
    managers = [
        x.to_AvailabilityManagerNightCycle() for x in loop.availabilityManagers()
    ]
    night = [x.get() for x in managers if x.is_initialized()]
    if len(night) != 1:
        raise RuntimeError("Expected one night-cycle manager")
    call(night[0], "setCyclingRunTime", 1800)
    for reference in r["target_zones"]:
        zone = by_handle(model, sdk, reference, "ThermalZone")
        reheat = make_coil(
            model, sdk, r, p, "reheat", f"{zone.nameString()} Reheat Coil"
        )
        if reheat:
            terminal = sdk.model.AirTerminalSingleDuctVAVReheat(
                model, model.alwaysOnDiscreteSchedule(), reheat
            )
            call(terminal, "setDamperHeatingAction", "Normal")
            call(terminal, "setMaximumReheatAirTemperature", t["zone_heating"])
        else:
            terminal = sdk.model.AirTerminalSingleDuctVAVNoReheat(
                model, model.alwaysOnDiscreteSchedule()
            )
        call(terminal, "setName", f"{zone.nameString()} VAV Terminal")
        call(terminal, "setZoneMinimumAirFlowInputMethod", "Constant")
        call(
            terminal,
            "setConstantMinimumAirFlowFraction",
            p["minimum_terminal_airflow_fraction"],
        )
        call(loop, "multiAddBranchForZone", zone, terminal)
        if reheat and p["reheat"]["type"] == "Water":
            # Attachments can reset the controller; set and validate after the final connection.
            water_controller(reheat, True)
        zone_sizing = zone.sizingZone()
        call(zone_sizing, "setCoolingDesignAirFlowMethod", "DesignDayWithLimit")
        call(zone_sizing, "setHeatingMaximumAirFlowFraction", 1.0)
        call(zone_sizing, "setZoneCoolingDesignSupplyAirTemperature", t["zone_cooling"])
        if reheat:
            call(zone_sizing, "setHeatingDesignAirFlowMethod", "DesignDay")
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
