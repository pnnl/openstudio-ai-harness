"""Read actual SDK topology/settings independently of construction helpers."""

from __future__ import annotations
import math


def unwrap(value):
    if hasattr(value, "is_initialized"):
        if not value.is_initialized():
            raise ValueError("Required SDK optional is empty")
        return value.get()
    return value


def handle(value):
    return str(unwrap(value).handle())


def counts(model):
    return {
        key: len(getattr(model, getter)())
        for key, getter in {
            "air_loops": "getAirLoopHVACs",
            "plant_loops": "getPlantLoops",
            "terminals": "getAirTerminalSingleDuctVAVReheats",
            "no_reheat_terminals": "getAirTerminalSingleDuctVAVNoReheats",
            "fans": "getFanVariableVolumes",
            "water_heating_coils": "getCoilHeatingWaters",
            "water_cooling_coils": "getCoilCoolingWaters",
            "electric_coils": "getCoilHeatingElectrics",
            "gas_coils": "getCoilHeatingGass",
            "dx_coils": "getCoilCoolingDXTwoSpeeds",
        }.items()
    }


def validate_model(model, sdk, planned, loop_handle, before):
    errors = []
    checked = 0
    p, r = planned["parameters"], planned["resolved_objects"]

    def equal(label, actual, expected):
        nonlocal checked
        checked += 1
        actual = unwrap(actual)
        match = (
            math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9)
            if isinstance(expected, float)
            else actual == expected
        )
        if not match:
            errors.append(f"{label}: expected {expected}, got {actual}")

    def object_at(reference, kind):
        return unwrap(getattr(model, f"get{kind}")(sdk.toUUID(reference["handle"])))

    def scheduled(reference):
        return (
            model.alwaysOnDiscreteSchedule()
            if reference.get("builtin")
            else object_at(reference, "Schedule")
        )

    loop = unwrap(model.getAirLoopHVAC(sdk.toUUID(loop_handle)))
    equal("system name", loop.nameString(), p["system_name"])
    equal(
        "served zones",
        sorted(str(x.handle()) for x in loop.thermalZones()),
        sorted(x["handle"] for x in r["target_zones"]),
    )
    equal(
        "availability schedule",
        handle(loop.availabilitySchedule()),
        handle(scheduled(r["schedules"]["availability_schedule"])),
    )
    equal("night cycle", loop.nightCycleControlType(), "CycleOnAny")
    nights = [x.to_AvailabilityManagerNightCycle() for x in loop.availabilityManagers()]
    nights = [x.get() for x in nights if x.is_initialized()]
    equal("night managers", len(nights), 1)
    if nights:
        equal("night runtime", nights[0].cyclingRunTime(), 1800.0)
    sizing = loop.sizingSystem()
    t = p["design_temperatures_c"]
    for getter, expected in {
        "typeofLoadtoSizeOn": "Sensible",
        "systemOutdoorAirMethod": "ZoneSum",
        "sizingOption": p["sizing_option"],
        "centralHeatingMaximumSystemAirFlowRatio": p["minimum_system_airflow_ratio"],
        "preheatDesignTemperature": t["preheat"],
        "precoolDesignTemperature": t["precool"],
        "centralHeatingDesignSupplyAirTemperature": t["central_heating"],
        "centralCoolingDesignSupplyAirTemperature": t["central_cooling"],
        "preheatDesignHumidityRatio": 0.008,
        "precoolDesignHumidityRatio": 0.008,
        "centralCoolingDesignSupplyAirHumidityRatio": 0.0085,
        "centralHeatingDesignSupplyAirHumidityRatio": 0.008,
        "allOutdoorAirinCooling": False,
        "allOutdoorAirinHeating": False,
        "coolingDesignAirFlowMethod": "DesignDay",
        "heatingDesignAirFlowMethod": "DesignDay",
        "isDesignOutdoorAirFlowRateAutosized": True,
    }.items():
        equal(f"sizing.{getter}", getattr(sizing, getter)(), expected)

    def typed(component, kind):
        return unwrap(getattr(component, f"to_{kind}")())

    def coil(component, role):
        kind = p[role]["type"]
        cls = {
            "Water": (
                "CoilCoolingWater" if role == "central_cooling" else "CoilHeatingWater"
            ),
            "NaturalGas": "CoilHeatingGas",
            "Electricity": "CoilHeatingElectric",
            "DXTwoSpeed": "CoilCoolingDXTwoSpeed",
        }[kind]
        c = typed(component, cls)
        equal(
            f"{role}.availability",
            handle(c.availabilitySchedule()),
            handle(model.alwaysOnDiscreteSchedule()),
        )
        if kind == "Water":
            plant = object_at(r["plant_loops"][role], "PlantLoop")
            equal(f"{role}.plant", handle(c.plantLoop()), handle(plant))
            equal(
                f"{role}.plant demand branch",
                handle(c) in {handle(x) for x in plant.demandComponents()},
                True,
            )
            ctl = unwrap(c.controllerWaterCoil())
            equal(f"{role}.controller coil", handle(ctl.waterCoil()), handle(c))
            equal(f"{role}.minimum water flow", ctl.minimumActuatedFlow(), 0.0)
            if role == "central_cooling":
                equal("cooling.controller action", ctl.action(), "Reverse")
                equal(
                    "cooling.heat exchanger",
                    c.heatExchangerConfiguration(),
                    "CrossFlow",
                )
                equal(
                    "cooling.inlet water autosize",
                    c.isDesignInletWaterTemperatureAutosized(),
                    True,
                )
            else:
                equal(f"{role}.convergence", ctl.controllerConvergenceTolerance(), 0.1)
                for getter, expected in {
                    "ratedInletWaterTemperature": plant.sizingPlant().designLoopExitTemperature(),
                    "ratedOutletWaterTemperature": plant.sizingPlant().designLoopExitTemperature()
                    - plant.sizingPlant().loopDesignTemperatureDifference(),
                    "ratedInletAirTemperature": (
                        t["central_heating"] if role == "reheat" else t["preheat"]
                    ),
                    "ratedOutletAirTemperature": (
                        t["zone_heating"] if role == "reheat" else t["central_heating"]
                    ),
                }.items():
                    equal(f"{role}.{getter}", getattr(c, getter)(), expected)
        elif kind == "NaturalGas":
            equal(f"{role}.gas efficiency", c.gasBurnerEfficiency(), 0.8)
            equal(f"{role}.electric parasitic", c.onCycleParasiticElectricLoad(), 0.0)
            equal(f"{role}.gas parasitic", c.offCycleParasiticGasLoad(), 0.0)
        elif kind == "Electricity":
            equal(f"{role}.electric efficiency", c.efficiency(), 1.0)

    components = [
        x for x in loop.supplyComponents() if not x.to_Node().is_initialized()
    ]
    expected_types = [
        "OS_AirLoopHVAC_OutdoorAirSystem",
        (
            "OS_Coil_Cooling_Water"
            if p["central_cooling"]["type"] == "Water"
            else "OS_Coil_Cooling_DX_TwoSpeed"
        ),
    ]
    heating_types = {
        "Water": "OS_Coil_Heating_Water",
        "Electricity": "OS_Coil_Heating_Electric",
        "NaturalGas": "OS_Coil_Heating_Gas",
    }
    if p["central_heating"]["type"] != "None":
        expected_types.append(heating_types[p["central_heating"]["type"]])
    expected_types.append("OS_Fan_VariableVolume")
    equal(
        "supply order OA/cooling/heating/fan",
        [x.iddObjectType().valueName() for x in components],
        expected_types,
    )
    if len(components) == len(expected_types):
        oa = typed(
            components[0], "AirLoopHVACOutdoorAirSystem"
        ).getControllerOutdoorAir()
        equal("OA minimum", oa.getMinimumLimitType(), "FixedMinimum")
        equal("OA autosize", oa.isMinimumOutdoorAirFlowRateAutosized(), True)
        equal("economizer", oa.getEconomizerControlType(), p["economizer"])
        equal(
            "OA maximum fraction unset",
            oa.maximumFractionofOutdoorAirSchedule().is_initialized(),
            False,
        )
        equal(
            "OA minimum economizer temperature unset",
            oa.getEconomizerMinimumLimitDryBulbTemperature().is_initialized(),
            False,
        )
        equal(
            "ventilation",
            oa.controllerMechanicalVentilation().systemOutdoorAirMethod(),
            "ZoneSum",
        )
        if "outdoor_air_schedule" in r["schedules"]:
            equal(
                "OA schedule",
                handle(oa.minimumOutdoorAirSchedule()),
                handle(scheduled(r["schedules"]["outdoor_air_schedule"])),
            )
        else:
            equal(
                "OA schedule unset",
                oa.minimumOutdoorAirSchedule().is_initialized(),
                False,
            )
        coil(components[1], "central_cooling")
        if p["central_heating"]["type"] != "None":
            coil(components[2], "central_heating")
        fan = typed(components[-1], "FanVariableVolume")
        for getter, expected in {
            "fanEfficiency": p["fan"]["total_efficiency"],
            "motorEfficiency": p["fan"]["motor_efficiency"],
            "pressureRise": p["fan"]["pressure_rise_pa"],
            "motorInAirstreamFraction": 1.0,
            "fanPowerMinimumFlowRateInputMethod": "Fraction",
            "fanPowerMinimumFlowFraction": 0.25,
            "endUseSubcategory": "VAV System Fans",
            "fanPowerCoefficient1": 0.040759894,
            "fanPowerCoefficient2": 0.08804497,
            "fanPowerCoefficient3": -0.07292612,
            "fanPowerCoefficient4": 0.943739823,
            "fanPowerCoefficient5": 0.0,
        }.items():
            equal(f"fan.{getter}", getattr(fan, getter)(), expected)
        equal(
            "fan schedule",
            handle(fan.availabilitySchedule()),
            handle(model.alwaysOnDiscreteSchedule()),
        )
    managers = [
        x.to_SetpointManagerScheduled()
        for x in loop.supplyOutletNode().setpointManagers()
    ]
    managers = [x.get() for x in managers if x.is_initialized()]
    equal("SAT manager count", len(managers), 1)
    if managers:
        sat = typed(managers[0].schedule(), "ScheduleRuleset")
        values = list(sat.defaultDaySchedule().values())
        equal("SAT value count", len(values), 1)
        if values:
            equal("SAT temperature", values[0], t["central_cooling"])
        equal("SAT units", unwrap(sat.scheduleTypeLimits()).unitType(), "Temperature")
        equal(
            "SAT lower limit", unwrap(sat.scheduleTypeLimits()).lowerLimitValue(), 0.0
        )
        equal(
            "SAT upper limit", unwrap(sat.scheduleTypeLimits()).upperLimitValue(), 100.0
        )
    for ref in r["target_zones"]:
        zone = object_at(ref, "ThermalZone")
        equal(
            f"{ref['name']}.air loops",
            [handle(x) for x in zone.airLoopHVACs()],
            [loop_handle],
        )
        terms = zone.airLoopHVACTerminals()
        equal(f"{ref['name']}.terminal count", len(terms), 1)
        if not terms:
            continue
        reheated = p["reheat"]["type"] != "None"
        term = typed(
            terms[0],
            (
                "AirTerminalSingleDuctVAVReheat"
                if reheated
                else "AirTerminalSingleDuctVAVNoReheat"
            ),
        )
        equal(
            "terminal minimum method", term.zoneMinimumAirFlowInputMethod(), "Constant"
        )
        equal(
            "terminal minimum fraction",
            term.constantMinimumAirFlowFraction(),
            p["minimum_terminal_airflow_fraction"],
        )
        equal(
            "terminal schedule",
            handle(term.availabilitySchedule()),
            handle(model.alwaysOnDiscreteSchedule()),
        )
        equal("terminal air loop", handle(term.airLoopHVAC()), loop_handle)
        if reheated:
            equal("damper action", term.damperHeatingAction(), "Normal")
            equal(
                "reheat maximum temperature",
                term.maximumReheatAirTemperature(),
                t["zone_heating"],
            )
            coil(term.reheatCoil(), "reheat")
        zs = zone.sizingZone()
        equal(
            "zone cooling method", zs.coolingDesignAirFlowMethod(), "DesignDayWithLimit"
        )
        equal(
            "zone cooling temperature",
            zs.zoneCoolingDesignSupplyAirTemperature(),
            t["zone_cooling"],
        )
        equal("zone heating fraction", zs.heatingMaximumAirFlowFraction(), 1.0)
        if reheated:
            equal("zone heating method", zs.heatingDesignAirFlowMethod(), "DesignDay")
            equal(
                "zone heating temperature",
                zs.zoneHeatingDesignSupplyAirTemperature(),
                t["zone_heating"],
            )
    if "return_plenum" in r:
        plenums = [
            x
            for x in model.getAirLoopHVACReturnPlenums()
            if x.airLoopHVAC().is_initialized()
            and handle(x.airLoopHVAC()) == loop_handle
        ]
        equal("return plenum count", len(plenums), 1)
        if plenums:
            equal(
                "return plenum zone",
                handle(plenums[0].thermalZone()),
                r["return_plenum"]["handle"],
            )
            equal(
                "return plenum branch count",
                len(plenums[0].inletModelObjects()),
                len(r["target_zones"]),
            )
    after = counts(model)
    expected = dict.fromkeys(before, 0)
    expected.update(air_loops=1, fans=1)
    n = len(r["target_zones"])
    expected[
        "terminals" if p["reheat"]["type"] != "None" else "no_reheat_terminals"
    ] = n
    for role, num in (("central_heating", 1), ("central_cooling", 1), ("reheat", n)):
        kind = p[role]["type"]
        if kind != "None":
            key = {
                "Water": (
                    "water_cooling_coils"
                    if role == "central_cooling"
                    else "water_heating_coils"
                ),
                "NaturalGas": "gas_coils",
                "Electricity": "electric_coils",
                "DXTwoSpeed": "dx_coils",
            }[kind]
            expected[key] += num
    for key in before:
        equal(f"count delta.{key}", after[key] - before[key], expected[key])
    return {
        "ok": not errors,
        "checks": checked,
        "errors": errors,
        "counts": after,
        "supply_order": [x.iddObjectType().valueName() for x in components],
    }
