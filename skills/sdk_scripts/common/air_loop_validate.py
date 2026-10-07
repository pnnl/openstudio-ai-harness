"""Read actual SDK topology/settings independently of construction helpers."""

from __future__ import annotations
import math
from common.air_system_recipe import VAV


def unwrap(value):
    if hasattr(value, "is_initialized"):
        if not value.is_initialized():
            raise ValueError("Required SDK optional is empty")
        return value.get()
    return value


def handle(value):
    return str(unwrap(value).handle())


FAN_KINDS = (
    "ComponentModel",
    "ConstantVolume",
    "OnOff",
    "SystemModel",
    "VariableVolume",
    "ZoneExhaust",
)


def counts(model, *, recipe=VAV):
    return {
        key: len(getattr(model, getter)())
        for key, getter in {
            "air_loops": "getAirLoopHVACs",
            "plant_loops": "getPlantLoops",
            "terminals": "getAirTerminalSingleDuctVAVReheats",
            "no_reheat_terminals": "getAirTerminalSingleDuctVAVNoReheats",
            "fans": "get" + recipe.fan_class + "s",
            **{"fan_" + kind: "getFan" + kind + "s" for kind in FAN_KINDS},
            "water_heating_coils": "getCoilHeatingWaters",
            "water_cooling_coils": "getCoilCoolingWaters",
            "electric_coils": "getCoilHeatingElectrics",
            "gas_coils": "getCoilHeatingGass",
            "dx_coils": "getCoilCoolingDXTwoSpeeds",
        }.items()
    }


def validate_model(
    model,
    sdk,
    planned,
    loop_handle,
    before,
    *,
    recipe=VAV,
):
    recipe.check_plan(planned)
    errors = []
    checked = 0
    p, r = planned["parameters"], planned["resolved_objects"]
    controls = planned["controls"]

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
        if reference.get("builtin"):
            methods = {
                "AlwaysOnDiscrete": "alwaysOnDiscreteSchedule",
                "AlwaysOffDiscrete": "alwaysOffDiscreteSchedule",
            }
            return getattr(model, methods[reference["builtin"]])()
        return object_at(reference, "Schedule")

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
    equal("night cycle", loop.nightCycleControlType(), controls["night_cycle"])
    nights = [x.to_AvailabilityManagerNightCycle() for x in loop.availabilityManagers()]
    nights = [x.get() for x in nights if x.is_initialized()]
    equal("night managers", len(nights), 1)
    if nights:
        equal(
            "night runtime",
            nights[0].cyclingRunTime(),
            float(controls["night_cycle_runtime_seconds"]),
        )
    sizing = loop.sizingSystem()
    t = p["design_temperatures_c"]
    for getter, expected in {
        "typeofLoadtoSizeOn": controls["sizing_load_type"],
        "systemOutdoorAirMethod": controls["outdoor_air_method"],
        "sizingOption": p["sizing_option"],
        "centralHeatingMaximumSystemAirFlowRatio": p["minimum_system_airflow_ratio"],
        "preheatDesignTemperature": t["preheat"],
        "precoolDesignTemperature": t["precool"],
        "centralHeatingDesignSupplyAirTemperature": t["central_heating"],
        "centralCoolingDesignSupplyAirTemperature": t["central_cooling"],
        "preheatDesignHumidityRatio": controls["preheat_humidity_ratio"],
        "precoolDesignHumidityRatio": controls["precool_humidity_ratio"],
        "centralCoolingDesignSupplyAirHumidityRatio": controls[
            "central_cooling_humidity_ratio"
        ],
        "centralHeatingDesignSupplyAirHumidityRatio": controls[
            "central_heating_humidity_ratio"
        ],
        "allOutdoorAirinCooling": controls["all_outdoor_air_cooling"],
        "allOutdoorAirinHeating": controls["all_outdoor_air_heating"],
        "coolingDesignAirFlowMethod": controls["system_cooling_airflow_method"],
        "heatingDesignAirFlowMethod": controls["system_heating_airflow_method"],
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
            handle(scheduled({"builtin": controls["component_availability"]})),
        )
        if kind == "Water":
            plant = object_at(r["plant_loops"][role], "PlantLoop")
            equal(f"{role}.plant", handle(c.plantLoop()), handle(plant))
            reference = r["plant_loops"][role]
            equal(
                f"{role}.plant temperature",
                plant.sizingPlant().designLoopExitTemperature(),
                reference["design_supply_temperature_c"],
            )
            equal(
                f"{role}.plant delta",
                plant.sizingPlant().loopDesignTemperatureDifference(),
                reference["design_delta_temperature_k"],
            )
            equal(
                f"{role}.plant demand branch",
                handle(c) in {handle(x) for x in plant.demandComponents()},
                True,
            )
            ctl = unwrap(c.controllerWaterCoil())
            equal(f"{role}.controller coil", handle(ctl.waterCoil()), handle(c))
            equal(
                f"{role}.minimum water flow",
                ctl.minimumActuatedFlow(),
                controls["water_controller_minimum_flow"],
            )
            if role == "central_cooling":
                equal(
                    "cooling.controller action",
                    ctl.action(),
                    controls["cooling_controller_action"],
                )
                equal(
                    "cooling.heat exchanger",
                    c.heatExchangerConfiguration(),
                    controls["cooling_water_heat_exchanger"],
                )
                equal(
                    "cooling.inlet water autosize",
                    c.isDesignInletWaterTemperatureAutosized(),
                    True,
                )
            else:
                equal(
                    f"{role}.convergence",
                    ctl.controllerConvergenceTolerance(),
                    controls["heating_water_controller_convergence"],
                )
                for getter, expected in {
                    "ratedInletWaterTemperature": reference[
                        "design_supply_temperature_c"
                    ],
                    "ratedOutletWaterTemperature": reference[
                        "design_supply_temperature_c"
                    ]
                    - reference["design_delta_temperature_k"],
                    "ratedInletAirTemperature": (
                        t["central_heating"] if role == "reheat" else t["preheat"]
                    ),
                    "ratedOutletAirTemperature": (
                        t["zone_heating"] if role == "reheat" else t["central_heating"]
                    ),
                }.items():
                    equal(f"{role}.{getter}", getattr(c, getter)(), expected)
        elif kind == "NaturalGas":
            equal(
                f"{role}.gas efficiency",
                c.gasBurnerEfficiency(),
                controls["gas_burner_efficiency"],
            )
            equal(
                f"{role}.electric parasitic",
                c.onCycleParasiticElectricLoad(),
                controls["gas_on_cycle_parasitic_electric_w"],
            )
            equal(
                f"{role}.gas parasitic",
                c.offCycleParasiticGasLoad(),
                controls["gas_off_cycle_parasitic_gas_w"],
            )
        elif kind == "Electricity":
            equal(
                f"{role}.electric efficiency",
                c.efficiency(),
                controls["electric_coil_efficiency"],
            )

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
    expected_types.append("OS_" + recipe.fan_class.replace("Fan", "Fan_", 1))
    equal(
        "supply order OA/cooling/heating/fan",
        [x.iddObjectType().valueName() for x in components],
        expected_types,
    )
    if len(components) == len(expected_types):
        oa = typed(
            components[0], "AirLoopHVACOutdoorAirSystem"
        ).getControllerOutdoorAir()
        equal("OA minimum", oa.getMinimumLimitType(), controls["oa_minimum_limit_type"])
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
            controls["outdoor_air_method"],
        )
        if "outdoor_air_schedule" in r["schedules"]:
            equal(
                "OA schedule",
                handle(getattr(oa, recipe.oa_schedule_getter)()),
                handle(scheduled(r["schedules"]["outdoor_air_schedule"])),
            )
        else:
            equal(
                "OA schedule unset",
                getattr(oa, recipe.oa_schedule_getter)().is_initialized(),
                False,
            )
        equal(
            "unused OA schedule unset",
            getattr(oa, recipe.unused_oa_schedule_getter)().is_initialized(),
            False,
        )
        coil(components[1], "central_cooling")
        if p["central_heating"]["type"] != "None":
            coil(components[2], "central_heating")
        fan = typed(components[-1], recipe.fan_class)
        fan_fields = {
            "fanEfficiency": p["fan"]["total_efficiency"],
            "motorEfficiency": p["fan"]["motor_efficiency"],
            "pressureRise": p["fan"]["pressure_rise_pa"],
            "motorInAirstreamFraction": controls["fan_motor_in_airstream_fraction"],
            "endUseSubcategory": controls["fan_end_use_subcategory"],
        }
        if recipe.fan_kind == "VariableVolume":
            fan_fields.update(
                fanPowerMinimumFlowRateInputMethod=controls[
                    "fan_power_minimum_flow_input_method"
                ],
                fanPowerMinimumFlowFraction=controls["fan_power_minimum_flow_fraction"],
            )
            fan_fields.update(
                {
                    f"fanPowerCoefficient{i}": value
                    for i, value in enumerate(controls["fan_power_coefficients"], 1)
                }
            )
        for getter, expected in fan_fields.items():
            equal(f"fan.{getter}", getattr(fan, getter)(), expected)
        equal(
            "fan schedule",
            handle(fan.availabilitySchedule()),
            handle(scheduled({"builtin": controls["component_availability"]})),
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
        equal(
            "SAT numeric type",
            unwrap(sat.scheduleTypeLimits()).numericType(),
            controls["sat_numeric_type"],
        )
        equal(
            "SAT units",
            unwrap(sat.scheduleTypeLimits()).unitType(),
            controls["sat_unit_type"],
        )
        equal(
            "SAT lower limit",
            unwrap(sat.scheduleTypeLimits()).lowerLimitValue(),
            controls["sat_schedule_type_limits_c"][0],
        )
        equal(
            "SAT upper limit",
            unwrap(sat.scheduleTypeLimits()).upperLimitValue(),
            controls["sat_schedule_type_limits_c"][1],
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
            "terminal minimum method",
            term.zoneMinimumAirFlowInputMethod(),
            controls["terminal_minimum_airflow_method"],
        )
        equal(
            "terminal minimum fraction",
            term.constantMinimumAirFlowFraction(),
            p["minimum_terminal_airflow_fraction"],
        )
        equal(
            "terminal schedule",
            handle(term.availabilitySchedule()),
            handle(scheduled({"builtin": controls["component_availability"]})),
        )
        equal("terminal air loop", handle(term.airLoopHVAC()), loop_handle)
        if reheated:
            equal(
                "damper action",
                term.damperHeatingAction(),
                controls["damper_heating_action"],
            )
            equal(
                "reheat maximum temperature",
                term.maximumReheatAirTemperature(),
                t["zone_heating"],
            )
            for key, getter in (
                (
                    "terminal_maximum_reheat_flow_per_area",
                    "maximumFlowPerZoneFloorAreaDuringReheat",
                ),
                (
                    "terminal_maximum_reheat_flow_fraction",
                    "maximumFlowFractionDuringReheat",
                ),
            ):
                if key in controls:
                    equal(key, getattr(term, getter)(), controls[key])
            coil(term.reheatCoil(), "reheat")
        zs = zone.sizingZone()
        equal(
            "zone cooling method",
            zs.coolingDesignAirFlowMethod(),
            controls["zone_cooling_airflow_method"],
        )
        equal(
            "zone cooling temperature",
            zs.zoneCoolingDesignSupplyAirTemperature(),
            t["zone_cooling"],
        )
        equal(
            "zone heating fraction",
            zs.heatingMaximumAirFlowFraction(),
            controls["zone_heating_maximum_airflow_fraction"],
        )
        if reheated:
            equal(
                "zone heating method",
                zs.heatingDesignAirFlowMethod(),
                controls["zone_heating_airflow_method"],
            )
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
    after = counts(model, recipe=recipe)
    expected = dict.fromkeys(before, 0)
    expected.update(air_loops=1, fans=1)
    expected[recipe.fan_count_key] = 1
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
