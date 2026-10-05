"""Read-only OpenStudio 3.11.0 VAV object inventory and exact selector resolution."""

from __future__ import annotations


def identity(obj) -> dict:
    return {"handle": str(obj.handle()), "name": obj.nameString()}


def ordered(objects) -> list[dict]:
    return sorted(objects, key=lambda item: (item["name"], item["handle"]))


def inventory(model) -> dict:
    zones = []
    for zone in model.getThermalZones():
        zones.append(
            {
                **identity(zone),
                "is_plenum": zone.isPlenum(),
                "can_be_plenum": zone.canBePlenum(),
                "plenum_air_loops": ordered(
                    identity(obj.airLoopHVAC().get())
                    for obj in list(model.getAirLoopHVACReturnPlenums())
                    + list(model.getAirLoopHVACSupplyPlenums())
                    if obj.thermalZone().is_initialized()
                    and obj.thermalZone().get().handle() == zone.handle()
                    and obj.airLoopHVAC().is_initialized()
                ),
                "has_thermostat": zone.thermostat().is_initialized(),
                "has_dual_setpoint_schedules": (
                    zone.thermostatSetpointDualSetpoint().is_initialized()
                    and zone.thermostatSetpointDualSetpoint()
                    .get()
                    .heatingSetpointTemperatureSchedule()
                    .is_initialized()
                    and zone.thermostatSetpointDualSetpoint()
                    .get()
                    .coolingSetpointTemperatureSchedule()
                    .is_initialized()
                ),
                "spaces": ordered(identity(space) for space in zone.spaces()),
                "air_loops": ordered(identity(loop) for loop in zone.airLoopHVACs()),
                "equipment": ordered(identity(obj) for obj in zone.equipment()),
            }
        )
    schedules = []
    for schedule in model.getSchedules():
        limits = schedule.scheduleTypeLimits()
        details = None
        if limits.is_initialized():
            limits = limits.get()
            lower, upper = limits.lowerLimitValue(), limits.upperLimitValue()
            details = {
                "unit_type": limits.unitType(),
                "lower": lower.get() if lower.is_initialized() else None,
                "upper": upper.get() if upper.is_initialized() else None,
            }
        schedules.append({**identity(schedule), "type_limits": details})
    return {
        "zones": ordered(zones),
        "air_loops": ordered(
            {
                **identity(loop),
                "served_zones": ordered(identity(z) for z in loop.thermalZones()),
            }
            for loop in model.getAirLoopHVACs()
        ),
        "plant_loops": ordered(
            {
                **identity(loop),
                "loop_type": loop.sizingPlant().loopType(),
                "design_supply_temperature_c": loop.sizingPlant().designLoopExitTemperature(),
                "design_delta_temperature_k": loop.sizingPlant().loopDesignTemperatureDifference(),
                "supply_equipment": ordered(
                    {**identity(obj), "type": obj.iddObjectType().valueName()}
                    for obj in loop.supplyComponents()
                    if any(
                        token in obj.iddObjectType().valueName()
                        for token in (
                            "Boiler",
                            "Chiller",
                            "DistrictHeating",
                            "DistrictCooling",
                            "HeatPump",
                            "HeatExchanger",
                            "CoolingTower",
                            "FluidCooler",
                            "SolarCollector",
                            "WaterHeater",
                            "PlantComponent_TemperatureSource",
                            "PlantComponent_UserDefined",
                        )
                    )
                ),
                "supply_pumps": ordered(
                    identity(obj)
                    for obj in loop.supplyComponents()
                    if "Pump" in obj.iddObjectType().valueName()
                ),
                "supply_setpoint_managers": ordered(
                    identity(obj) for obj in loop.supplyOutletNode().setpointManagers()
                ),
            }
            for loop in model.getPlantLoops()
        ),
        "schedules": ordered(schedules),
    }


def resolve(selector: dict, candidates: list[dict], label: str, errors: list[str]):
    key = "handle" if "handle" in selector else "name"
    matches = [item for item in candidates if item[key] == selector[key]]
    if len(matches) != 1:
        errors.append(
            f"{label}: selector matched {len(matches)} objects; choose an exact candidate handle"
        )
        return None
    return matches[0]
