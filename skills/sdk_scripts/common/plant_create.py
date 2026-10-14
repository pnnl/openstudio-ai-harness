"""Bounded generic plant builders traced from openstudio-standards prototypes."""

from __future__ import annotations
import math
from common.input_validation import finite_number


def set_fields(obj, fields):
    for key, value in fields.items():
        if getattr(obj, "set" + key)(value) is False:
            raise ValueError(f"SDK rejected {obj.nameString()}.set{key}")


def checked(obj, method, *args):
    if getattr(obj, method)(*args) is False:
        raise ValueError(f"SDK rejected {obj.nameString()}.{method}")


def plan(model, sdk, config):
    allowed = {"output_model_path", "defaults_profile", "hot_water", "chilled_water"}
    if (
        config.keys() - allowed
        or config.get("defaults_profile") != "prototype_plants_v1"
    ):
        raise ValueError(
            "Choose explicit prototype_plants_v1 defaults; unknown fields are rejected"
        )
    if not any(config.get(k) for k in ("hot_water", "chilled_water")):
        raise ValueError("Select at least one plant")
    plants = []
    names = {o.nameString() for o in model.modelObjects()}

    def number(p, key, default, low, high):
        value = p.get(key, default)
        if not finite_number(value) or not low <= value <= high:
            raise ValueError(
                f"Invalid {key}: expected finite number in [{low}, {high}]"
            )
        return value

    for role in ("hot_water", "chilled_water"):
        if role not in config:
            continue
        p = config[role]
        if not isinstance(p, dict):
            raise ValueError(f"{role} must be an object")
        heating = role == "hot_water"
        keys = {
            "name",
            "source",
            "supply_temperature_c",
            "delta_temperature_k",
            "pumping",
            "num_chillers",
            "boiler_efficiency",
            "condenser_name",
        }
        if p.keys() - keys:
            raise ValueError(f"Unknown {role} fields")
        name = p.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Every plant requires an explicit name")
        sources = (
            ("NaturalGas", "Electricity", "DistrictHeatingWater")
            if heating
            else ("AirCooled", "WaterCooled", "DistrictCooling")
        )
        source = p.get("source")
        if source not in sources:
            raise ValueError(
                f"{role}.source must be explicitly selected from {sources}"
            )
        if heating and any(k in p for k in ("num_chillers", "condenser_name")):
            raise ValueError("Chiller/condenser choices do not apply to heating")
        if source == "DistrictHeatingWater" and "boiler_efficiency" in p:
            raise ValueError("District heating has no boiler efficiency")
        if not heating and "boiler_efficiency" in p:
            raise ValueError("boiler_efficiency only applies to heating")
        temperature = number(
            p,
            "supply_temperature_c",
            (180 - 32) * 5 / 9 if heating else (44 - 32) * 5 / 9,
            10 if heating else 2.3,
            94 if heating else 20,
        )
        delta = number(
            p, "delta_temperature_k", 20 * 5 / 9 if heating else 10.1 * 5 / 9, 0.1, 30
        )
        if heating and temperature - delta <= 10:
            raise ValueError("Hot-water design return must exceed loop minimum 10 C")
        pumping = p.get("pumping", "Variable" if heating else "const_pri")
        if pumping not in (
            ("Variable", "Constant") if heating else ("const_pri", "const_pri_var_sec")
        ):
            raise ValueError("Unsupported pumping arrangement")
        count = p.get("num_chillers", 1)
        if (
            type(count) is not int
            or not 1 <= count <= 3
            or (source == "DistrictCooling" and count != 1)
        ):
            raise ValueError(
                "num_chillers must be 1–3 (district cooling uses one source)"
            )
        equipment_type = (
            "DistrictHeatingWater"
            if source == "DistrictHeatingWater"
            else (
                "BoilerHotWater"
                if heating
                else (
                    "DistrictCooling"
                    if source == "DistrictCooling"
                    else "ChillerElectricEIR"
                )
            )
        )
        equipment = (
            {}
            if "District" in source
            else (
                {
                    "FuelType": source,
                    "NominalThermalEfficiency": number(
                        p, "boiler_efficiency", 0.78, 0.5, 1
                    ),
                    "EfficiencyCurveTemperatureEvaluationVariable": "LeavingBoiler",
                    "BoilerFlowMode": "LeavingSetpointModulated",
                    "WaterOutletUpperTemperatureLimit": 95.0,
                    "MinimumPartLoadRatio": 0.0,
                    "MaximumPartLoadRatio": 1.2,
                    "OptimumPartLoadRatio": 1.0,
                    "SizingFactor": 1.0,
                }
                if heating
                else {
                    "ReferenceLeavingChilledWaterTemperature": temperature,
                    "LeavingChilledWaterLowerTemperatureLimit": (36 - 32) * 5 / 9,
                    "ReferenceEnteringCondenserFluidTemperature": 35.0,
                    "MinimumPartLoadRatio": 0.15,
                    "MaximumPartLoadRatio": 1.0,
                    "OptimumPartLoadRatio": 1.0,
                    "MinimumUnloadingRatio": 0.25,
                    "ChillerFlowMode": "ConstantFlow",
                    "SizingFactor": round(1 / count, 2),
                    "ReferenceCOP": 3.517 / (1.188 if source == "AirCooled" else 0.66),
                    "CondenserType": source,
                }
            )
        )
        pump_fields = {
            "RatedPumpHead": sdk.convert(60, "ftH_{2}O", "Pa").get(),
            "MotorEfficiency": 0.9,
            "PumpControlType": "Intermittent",
        }
        pumps = [
            {
                "type": (
                    "PumpConstantSpeed"
                    if pumping == "Constant"
                    else "PumpVariableSpeed"
                ),
                "side": "supply",
                "settings": pump_fields,
            }
        ]
        loop_fields = {
            "MinimumLoopTemperature": 10.0 if heating else 1.0,
            "MaximumLoopTemperature": 100.0 if heating else 40.0,
        }
        if not heating:
            if pumping == "const_pri":
                pump_fields.update(
                    FractionofMotorInefficienciestoFluidStream=0.0,
                    Coefficient1ofthePartLoadPerformanceCurve=0.0,
                    Coefficient2ofthePartLoadPerformanceCurve=1.0,
                    Coefficient3ofthePartLoadPerformanceCurve=0.0,
                    Coefficient4ofthePartLoadPerformanceCurve=0.0,
                )
            else:
                pumps = [
                    {
                        "type": "PumpConstantSpeed",
                        "side": "supply",
                        "settings": dict(
                            pump_fields,
                            RatedPumpHead=sdk.convert(15, "ftH_{2}O", "Pa").get(),
                        ),
                    },
                    {
                        "type": "PumpVariableSpeed",
                        "side": "demand",
                        "settings": dict(
                            pump_fields,
                            RatedPumpHead=sdk.convert(45, "ftH_{2}O", "Pa").get(),
                            FractionofMotorInefficienciestoFluidStream=0.0,
                            Coefficient1ofthePartLoadPerformanceCurve=0.0,
                            Coefficient2ofthePartLoadPerformanceCurve=0.0205,
                            Coefficient3ofthePartLoadPerformanceCurve=0.4101,
                            Coefficient4ofthePartLoadPerformanceCurve=0.5753,
                        ),
                    },
                ]
                loop_fields["CommonPipeSimulation"] = "CommonPipe"
        plant = dict(
            name=name,
            role=role,
            source=source,
            sizing={
                "LoopType": "Heating" if heating else "Cooling",
                "DesignLoopExitTemperature": temperature,
                "LoopDesignTemperatureDifference": delta,
            },
            loop=loop_fields,
            pumps=pumps,
            equipment_type=equipment_type,
            equipment=equipment,
            count=1 if heating else count,
            setpoint={
                "type": "Scheduled",
                "temperature_c": temperature,
                "schedule_limits": {
                    "UnitType": "Temperature",
                    "NumericType": "Continuous",
                    "LowerLimitValue": 0.0,
                    "UpperLimitValue": 100.0,
                },
            },
        )
        plants.append(plant)
        if source == "WaterCooled":
            cw_name = p.get("condenser_name", name + " Condenser")
            if not isinstance(cw_name, str) or not cw_name.strip():
                raise ValueError("Invalid condenser_name")
            plant["condenser_name"] = cw_name
            plants.append(
                dict(
                    name=cw_name,
                    role="condenser",
                    source="CoolingTower",
                    sizing={
                        "LoopType": "Condenser",
                        "DesignLoopExitTemperature": (85 - 32) * 5 / 9,
                        "LoopDesignTemperatureDifference": 10 * 5 / 9,
                        "SizingOption": "Coincident",
                        "ZoneTimestepsinAveragingWindow": 6,
                        "CoincidentSizingFactorMode": "GlobalCoolingSizingFactor",
                    },
                    loop={
                        "MinimumLoopTemperature": 5.0,
                        "MaximumLoopTemperature": 80.0,
                    },
                    pumps=[
                        {
                            "type": "PumpConstantSpeed",
                            "side": "supply",
                            "settings": {
                                "RatedPumpHead": sdk.convert(
                                    49.7, "ftH_{2}O", "Pa"
                                ).get(),
                                "MotorEfficiency": 0.9,
                                "PumpControlType": "Intermittent",
                            },
                        }
                    ],
                    equipment_type="CoolingTowerVariableSpeed",
                    equipment={
                        "DesignRangeTemperature": 10 * 5 / 9,
                        "DesignApproachTemperature": 7 * 5 / 9,
                        "FractionofTowerCapacityinFreeConvectionRegime": 0.125,
                        "NumberofCells": 2,
                        "SizingFactor": 1.0,
                    },
                    count=1,
                    setpoint={
                        "type": "FollowOutdoorAirTemperature",
                        "ReferenceTemperatureType": "OutdoorAirWetBulb",
                        "MaximumSetpointTemperature": (85 - 32) * 5 / 9,
                        "MinimumSetpointTemperature": (70 - 32) * 5 / 9,
                        "OffsetTemperatureDifference": 7 * 5 / 9,
                    },
                    curve={
                        "Coefficient1Constant": 0.33162901,
                        "Coefficient2x": -0.88567609,
                        "Coefficient3xPOW2": 0.60556507,
                        "Coefficient4xPOW3": 0.9484823,
                        "MinimumValueofx": 0.0,
                        "MaximumValueofx": 1.0,
                    },
                )
            )
        elif "condenser_name" in p:
            raise ValueError("condenser_name requires WaterCooled")
    proposed = []
    for p in plants:
        proposed += [
            p["name"],
            p["name"] + " Setpoint",
            p["name"] + " Temperature",
            p["name"] + " Fan Curve",
        ]
        proposed += [p["name"] + f" Pump {i+1}" for i in range(len(p["pumps"]))]
        proposed += [p["name"] + f" Equipment {i+1}" for i in range(p["count"])]
    if len(proposed) != len(set(proposed)) or names.intersection(proposed):
        raise ValueError(
            "Plant or generated equipment name already exists/duplicates another selection"
        )
    assumptions = [
        f"{p['name']}.{key}: {value}"
        for p in plants
        for key, value in p.items()
        if key not in ("name", "role")
    ]
    assumptions += [
        "Generic prototype plants; pinned SDK default chiller/boiler/tower performance curves where not explicitly supplied; capacities/flows autosized.",
        "Fixed condenser design 85 F/10 R and 7 R approach; weather-derived/PRM design wet-bulb sizing is not applied.",
    ]
    return dict(
        parameters={"plants": plants},
        resolved_objects={},
        assumptions=assumptions,
        preserved_plants=[str(x.handle()) for x in model.getPlantLoops()],
    )


def create(model, sdk, planned):
    results = []
    loops = {}
    for p in planned["parameters"]["plants"]:
        loop = sdk.model.PlantLoop(model)
        checked(loop, "setName", p["name"])
        loops[p["name"]] = loop
        set_fields(loop, p["loop"])
        set_fields(loop.sizingPlant(), p["sizing"])
        if p["setpoint"]["type"] == "Scheduled":
            sch = sdk.model.ScheduleConstant(model)
            checked(sch, "setName", p["name"] + " Temperature")
            checked(sch, "setValue", p["setpoint"]["temperature_c"])
            limits = sdk.model.ScheduleTypeLimits(model)
            set_fields(
                limits,
                p["setpoint"]["schedule_limits"],
            )
            checked(sch, "setScheduleTypeLimits", limits)
            spm = sdk.model.SetpointManagerScheduled(model, sch)
        else:
            spm = sdk.model.SetpointManagerFollowOutdoorAirTemperature(model)
            set_fields(spm, {k: v for k, v in p["setpoint"].items() if k != "type"})
        checked(spm, "setName", p["name"] + " Setpoint")
        checked(spm, "addToNode", loop.supplyOutletNode())
        pumps = []
        equipment = []
        curve = None
        for i, pump in enumerate(p["pumps"]):
            obj = getattr(sdk.model, pump["type"])(model)
            checked(obj, "setName", p["name"] + f" Pump {i+1}")
            set_fields(obj, pump["settings"])
            checked(
                obj,
                "addToNode",
                (
                    loop.supplyInletNode()
                    if pump["side"] == "supply"
                    else loop.demandInletNode()
                ),
            )
            pumps.append(str(obj.handle()))
        for i in range(p["count"]):
            obj = getattr(sdk.model, p["equipment_type"])(model)
            checked(obj, "setName", p["name"] + f" Equipment {i+1}")
            set_fields(
                obj,
                {
                    k: v
                    for k, v in p["equipment"].items()
                    if not (k == "CondenserType" and v == "WaterCooled")
                },
            )
            checked(loop, "addSupplyBranchForComponent", obj)
            if p["equipment_type"] in (
                "BoilerHotWater",
                "DistrictHeatingWater",
                "DistrictCooling",
            ):
                checked(obj, "autosizeNominalCapacity")
            if p["equipment_type"] == "ChillerElectricEIR":
                checked(obj, "autosizeReferenceCapacity")
            if "curve" in p:
                curve = sdk.model.CurveCubic(model)
                checked(curve, "setName", p["name"] + " Fan Curve")
                set_fields(curve, p["curve"])
                checked(obj, "setFanPowerRatioFunctionofAirFlowRateRatioCurve", curve)
            equipment.append(str(obj.handle()))
        for side in ("Supply", "Demand"):
            checked(
                loop,
                "add" + side + "BranchForComponent",
                sdk.model.PipeAdiabatic(model),
            )
        for node in (
            loop.supplyOutletNode(),
            loop.demandInletNode(),
            loop.demandOutletNode(),
        ):
            checked(sdk.model.PipeAdiabatic(model), "addToNode", node)
        results.append(
            dict(
                name=p["name"],
                handle=str(loop.handle()),
                pumps=pumps,
                equipment=equipment,
                setpoint=str(spm.handle()),
                curve=str(curve.handle()) if curve else None,
            )
        )
    for p, result in zip(planned["parameters"]["plants"], results):
        if "condenser_name" in p:
            for handle in result["equipment"]:
                obj = model.getChillerElectricEIR(sdk.toUUID(handle)).get()
                checked(loops[p["condenser_name"]], "addDemandBranchForComponent", obj)
                checked(obj, "setCondenserType", "WaterCooled")
    return results


def validate_model(model, sdk, planned, results):
    errors = []
    checks = 0

    def test(ok, text):
        nonlocal checks
        checks += 1
        if not ok:
            errors.append(text)

    def get(kind, handle):
        return getattr(model, "get" + kind)(sdk.toUUID(handle)).get()

    def fields(obj, settings):
        for key, expected in settings.items():
            actual = getattr(obj, key[0].lower() + key[1:])()
            if hasattr(actual, "is_initialized"):
                actual = actual.get() if actual.is_initialized() else None
            equal = (
                math.isclose(actual, expected, rel_tol=1e-8, abs_tol=1e-8)
                if type(expected) in (int, float) and actual is not None
                else actual == expected
            )
            test(equal, f"{obj.nameString()}.{key}: {actual} != {expected}")

    for p, r in zip(planned["parameters"]["plants"], results):
        loop = get("PlantLoop", r["handle"])
        fields(loop, p["loop"])
        fields(loop.sizingPlant(), p["sizing"])
        test(loop.nameString() == p["name"], "Plant name differs")
        supply = {str(x.handle()) for x in loop.supplyComponents()}
        demand = {str(x.handle()) for x in loop.demandComponents()}
        for pump, h in zip(p["pumps"], r["pumps"]):
            obj = get(pump["type"], h)
            fields(obj, pump["settings"])
            test(
                h in (supply if pump["side"] == "supply" else demand),
                "Pump connection differs",
            )
        for h in r["equipment"]:
            obj = get(p["equipment_type"], h)
            fields(obj, p["equipment"])
            test(h in supply, "Equipment disconnected")
            if "condenser_name" in p:
                test(
                    obj.secondaryPlantLoop().is_initialized()
                    and obj.secondaryPlantLoop().get().nameString()
                    == p["condenser_name"],
                    "Chiller condenser connection differs",
                )
            if "curve" in p:
                curve = get("CurveCubic", r["curve"])
                fields(curve, p["curve"])
                test(
                    str(
                        obj.fanPowerRatioFunctionofAirFlowRateRatioCurve()
                        .get()
                        .handle()
                    )
                    == r["curve"],
                    "Tower fan curve disconnected",
                )
        spm = get("SetpointManager" + p["setpoint"]["type"], r["setpoint"])
        test(
            r["setpoint"]
            in {str(x.handle()) for x in loop.supplyOutletNode().setpointManagers()},
            "Setpoint manager disconnected",
        )
        if p["setpoint"]["type"] == "Scheduled":
            test(
                math.isclose(
                    spm.schedule().to_ScheduleConstant().get().value(),
                    p["setpoint"]["temperature_c"],
                ),
                "Plant schedule temperature differs",
            )
            fields(
                spm.schedule().scheduleTypeLimits().get(),
                p["setpoint"]["schedule_limits"],
            )
        else:
            fields(spm, {k: v for k, v in p["setpoint"].items() if k != "type"})
    test(
        len(model.getPlantLoops()) == len(planned["preserved_plants"]) + len(results),
        "Unexpected plant count",
    )
    for h in planned["preserved_plants"]:
        test(
            model.getPlantLoop(sdk.toUUID(h)).is_initialized(), "Existing plant removed"
        )
    return dict(ok=not errors, checks=checks, errors=errors)
