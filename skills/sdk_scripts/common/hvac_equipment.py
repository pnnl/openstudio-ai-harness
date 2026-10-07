"""Shared multizone equipment factories; parent recipes own connection order."""

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


def attach_zones(model, sdk, loop, p, r, c):
    t = p["design_temperatures_c"]
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
            for key, setter in (
                (
                    "terminal_maximum_reheat_flow_per_area",
                    "setMaximumFlowPerZoneFloorAreaDuringReheat",
                ),
                (
                    "terminal_maximum_reheat_flow_fraction",
                    "setMaximumFlowFractionDuringReheat",
                ),
            ):
                if key in c:
                    call(terminal, setter, c[key])
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
