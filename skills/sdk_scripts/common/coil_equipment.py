"""Water-coil rating setters and controller finalization for pinned SDK bundles."""

from common.hvac_equipment import call

CLASSES = {"Heating": "CoilHeatingWater", "Cooling": "CoilCoolingWater"}
# public key: SDK suffix, raw IDD field, accepts Autosize
RATINGS = {
    "Heating": {
        "rated_inlet_water_temperature_c": (
            "RatedInletWaterTemperature",
            "Rated Inlet Water Temperature",
            False,
        ),
        "rated_outlet_water_temperature_c": (
            "RatedOutletWaterTemperature",
            "Rated Outlet Water Temperature",
            False,
        ),
        "rated_inlet_air_temperature_c": (
            "RatedInletAirTemperature",
            "Rated Inlet Air Temperature",
            False,
        ),
        "rated_outlet_air_temperature_c": (
            "RatedOutletAirTemperature",
            "Rated Outlet Air Temperature",
            False,
        ),
        "rated_capacity_w": ("RatedCapacity", "Rated Capacity", True),
        "ua_w_per_k": ("UFactorTimesAreaValue", "U-Factor Times Area Value", True),
        "maximum_water_flow_m3_s": (
            "MaximumWaterFlowRate",
            "Maximum Water Flow Rate",
            True,
        ),
        "performance_input_method": (
            "PerformanceInputMethod",
            "Performance Input Method",
            False,
        ),
    },
    "Cooling": {
        "design_water_flow_m3_s": (
            "DesignWaterFlowRate",
            "Design Water Flow Rate",
            True,
        ),
        "design_air_flow_m3_s": ("DesignAirFlowRate", "Design Air Flow Rate", True),
        "design_inlet_water_temperature_c": (
            "DesignInletWaterTemperature",
            "Design Inlet Water Temperature",
            True,
        ),
        "design_inlet_air_temperature_c": (
            "DesignInletAirTemperature",
            "Design Inlet Air Temperature",
            True,
        ),
        "design_outlet_air_temperature_c": (
            "DesignOutletAirTemperature",
            "Design Outlet Air Temperature",
            True,
        ),
        "design_inlet_air_humidity_ratio": (
            "DesignInletAirHumidityRatio",
            "Design Inlet Air Humidity Ratio",
            True,
        ),
        "design_outlet_air_humidity_ratio": (
            "DesignOutletAirHumidityRatio",
            "Design Outlet Air Humidity Ratio",
            True,
        ),
        "heat_exchanger_configuration": (
            "HeatExchangerConfiguration",
            "Heat Exchanger Configuration",
            False,
        ),
        "type_of_analysis": ("TypeOfAnalysis", "Type of Analysis", False),
    },
}


def kind_of(coil):
    kinds = {"OS_Coil_Heating_Water": "Heating", "OS_Coil_Cooling_Water": "Cooling"}
    try:
        return kinds[coil.iddObjectType().valueName()]
    except KeyError:
        raise ValueError(
            "Only CoilHeatingWater and CoilCoolingWater are supported"
        ) from None


def optional_value(value):
    if hasattr(value, "is_initialized"):
        return value.get() if value.is_initialized() else None
    return value


def ratings(coil, kind):
    result = {}
    for key, (suffix, _, autosizable) in RATINGS[kind].items():
        if autosizable and getattr(coil, "is" + suffix + "Autosized")():
            result[key] = "Autosize"
            continue
        value = getattr(coil, suffix[0].lower() + suffix[1:])()
        result[key] = optional_value(value)
    return result


def set_ratings(coil, kind, values):
    unknown = values.keys() - RATINGS[kind].keys()
    if unknown:
        raise ValueError(f"Unsupported {kind} ratings: {sorted(unknown)}")
    for key, value in values.items():
        suffix, _, autosizable = RATINGS[kind][key]
        if value == "Autosize":
            if not autosizable:
                raise ValueError(f"{key} cannot be autosized")
            call(coil, "autosize" + suffix)
        else:
            call(coil, "set" + suffix, value)


def node_ports(coil):
    ports = []
    for side in ("airInlet", "airOutlet", "waterInlet", "waterOutlet"):
        obj = getattr(coil, side + "ModelObject")()
        if not obj.is_initialized() or not obj.get().to_Node().is_initialized():
            raise ValueError("Coil requires direct air and plant node connections")
        ports.append(str(obj.get().handle()))
    return ports


CONTROLLER_FIELDS = {
    "control_variable": ("ControlVariable", "Control Variable", False),
    "action": ("Action", "Action", False),
    "actuator_variable": ("ActuatorVariable", "Actuator Variable", False),
    "minimum_flow_m3_s": ("MinimumActuatedFlow", "Minimum Actuated Flow", False),
    "convergence_tolerance_k": (
        "ControllerConvergenceTolerance",
        "Controller Convergence Tolerance",
        True,
    ),
    "maximum_flow_m3_s": ("MaximumActuatedFlow", "Maximum Actuated Flow", True),
}


def controller_values(controller):
    result = {}
    for key, (suffix, _, autosizable) in CONTROLLER_FIELDS.items():
        if autosizable and getattr(controller, "is" + suffix + "Autosized")():
            result[key] = "Autosize"
        else:
            result[key] = optional_value(
                getattr(controller, suffix[0].lower() + suffix[1:])()
            )
    return result


def set_controller_settings(controller, settings):
    unknown = settings.keys() - CONTROLLER_FIELDS.keys()
    if unknown:
        raise ValueError(f"Unsupported controller settings: {sorted(unknown)}")
    for key, (suffix, _, autosizable) in CONTROLLER_FIELDS.items():
        if key not in settings:
            continue
        value = settings[key]
        if value == "Autosize":
            if not autosizable:
                raise ValueError(f"{key} cannot be autosized")
            call(controller, "autosize" + suffix)
        else:
            call(controller, "set" + suffix, value)


def finalize_controller(coil, model, sdk, kind, settings):
    # The SDK creates/resets this owned object during attachment. Finalize last.
    ports = node_ports(coil)
    controller = coil.controllerWaterCoil()
    if not controller.is_initialized():
        raise ValueError("Water coil has no controller after attachment")
    controller = controller.get()
    call(controller, "setName", coil.nameString() + " Controller")
    set_controller_settings(
        controller,
        dict(
            settings,
            action="Normal" if kind == "Heating" else "Reverse",
            actuator_variable="Flow",
            maximum_flow_m3_s="Autosize",
        ),
    )
    call(controller, "setSensorNode", model.getNode(sdk.toUUID(ports[1])).get())
    call(controller, "setActuatorNode", model.getNode(sdk.toUUID(ports[2])).get())
    return controller
