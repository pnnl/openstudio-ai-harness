"""Read-only direct outdoor-air selection and translated control context."""

from common.hvac_equipment import by_handle
from common.hvac_inventory import resolve
from common.temperature_control import (
    node_temperature_managers,
    translated_workspace,
    optional_string,
)


def ref(obj):
    return dict(
        handle=str(obj.handle()),
        name=obj.nameString(),
        type=obj.iddObjectType().valueName(),
    )


def mixed_air_control(model, sdk, controller):
    """Inspect the effective translated controller, not only OSM managers."""
    if controller.getEconomizerControlType() == "NoEconomizer":
        return None
    workspace = translated_workspace(
        model, sdk, "Cannot verify translated economizer control"
    )
    controllers = [
        x
        for x in workspace.getObjectsByType(sdk.IddObjectType("Controller_OutdoorAir"))
        if x.nameString().casefold() == controller.nameString().casefold()
    ]
    if len(controllers) != 1:
        raise ValueError(
            "Cannot verify translated economizer control: selected OA controller not found uniquely"
        )
    obj = controllers[0]
    index = obj.iddObject().getFieldIndex("Mixed Air Node Name")
    name = optional_string(obj, index.get()) if index.is_initialized() else ""
    if not name:
        raise ValueError(
            "Cannot verify translated economizer control: missing Mixed Air Node Name"
        )
    managers = node_temperature_managers(workspace, sdk, name)
    # A dual-setpoint manager writes TempSetPointHi/Lo, not the single
    # TempSetPoint read by the economizer (EnergyPlus 25.2 MixedAir.cc).
    managers = [
        x for x in managers if x["type"] != "SetpointManager:Scheduled:DualSetpoint"
    ]
    return dict(
        mixed_air_node=name,
        temperature_managers=managers,
        temperature_setpoint_verified=bool(managers),
    )


def inventory(model):
    return dict(
        air_loops=sorted(
            [
                dict(
                    ref(loop),
                    zone_count=len(loop.thermalZones()),
                    controller=(
                        ref(
                            loop.airLoopHVACOutdoorAirSystem()
                            .get()
                            .getControllerOutdoorAir()
                        )
                        if loop.airLoopHVACOutdoorAirSystem().is_initialized()
                        else None
                    ),
                    split_supply=loop.supplySplitter().is_initialized()
                    or len(loop.supplyOutletNodes()) != 1,
                )
                for loop in model.getAirLoopHVACs()
            ],
            key=lambda x: (x["name"], x["handle"]),
        )
    )


def schedule_context(optional):
    if not optional.is_initialized():
        return None
    schedule = optional.get()
    constant = schedule.to_ScheduleConstant()
    return dict(
        ref(schedule),
        constant_value=constant.get().value() if constant.is_initialized() else None,
    )


def context(loop, controller, sdk):
    def flow(maximum):
        prefix = "Maximum" if maximum else "Minimum"
        if getattr(controller, "is" + prefix + "OutdoorAirFlowRateAutosized")():
            return "Autosize"
        value = getattr(controller, prefix.lower() + "OutdoorAirFlowRate")()
        return value.get() if value.is_initialized() else None

    # Read the MV pointer without a getter that could materialize a missing object.
    index = controller.iddObject().getFieldIndex("Controller Mechanical Ventilation")
    pointer = (
        controller.idfObject().getString(index.get())
        if index.is_initialized()
        else None
    )
    mv = None
    if pointer and pointer.is_initialized() and pointer.get():
        obj = loop.model().getControllerMechanicalVentilation(sdk.toUUID(pointer.get()))
        if obj.is_initialized():
            mv = dict(
                ref(obj.get()),
                dcv=obj.get().demandControlledVentilation(),
                method=obj.get().systemOutdoorAirMethod(),
            )
    return dict(
        minimum_flow_m3_s=flow(False),
        maximum_flow_m3_s=flow(True),
        minimum_flow_schedule=schedule_context(controller.minimumOutdoorAirSchedule()),
        minimum_fraction_schedule=schedule_context(
            controller.minimumFractionofOutdoorAirSchedule()
        ),
        maximum_fraction_schedule=schedule_context(
            controller.maximumFractionofOutdoorAirSchedule()
        ),
        force_economizer_schedule=schedule_context(
            controller.timeofDayEconomizerControlSchedule()
        ),
        mechanical_ventilation=mv,
        action=controller.getEconomizerControlActionType(),
        high_humidity_control=(
            controller.getHighHumidityControl().get()
            if controller.getHighHumidityControl().is_initialized()
            else None
        ),
        electronic_enthalpy_curve=(
            ref(controller.electronicEnthalpyLimitCurve().get())
            if controller.electronicEnthalpyLimitCurve().is_initialized()
            else None
        ),
        heat_recovery_bypass=(
            controller.getHeatRecoveryBypassControlType().get()
            if controller.getHeatRecoveryBypassControlType().is_initialized()
            else None
        ),
        operation_staging=controller.economizerOperationStaging(),
        cooling_components=[
            ref(x)
            for x in loop.supplyComponents()
            if "Cooling" in x.iddObjectType().valueName()
            or "Unitary" in x.iddObjectType().valueName()
        ],
        all_outdoor_air_heating=loop.sizingSystem().allOutdoorAirinHeating(),
        all_outdoor_air_cooling=loop.sizingSystem().allOutdoorAirinCooling(),
    )


def select_controller(model, sdk, selector, errors):
    selected = resolve(selector, inventory(model)["air_loops"], "air_loop", errors)
    if selected is None:
        return None
    if selected["split_supply"] or selected["controller"] is None:
        errors.append(
            "Select an unsplit air loop with an existing direct outdoor-air system"
        )
        return None
    loop = by_handle(model, sdk, selected, "AirLoopHVAC")
    system = loop.airLoopHVACOutdoorAirSystem().get()
    controller = system.getControllerOutdoorAir()
    owners = [
        x
        for x in model.getAirLoopHVACOutdoorAirSystems()
        if x.getControllerOutdoorAir().handle() == controller.handle()
    ]
    if (
        system.airLoopHVACDedicatedOutdoorAirSystem().is_initialized()
        or len(owners) != 1
        or not system.airLoopHVAC().is_initialized()
        or system.airLoopHVAC().get().handle() != loop.handle()
    ):
        errors.append(
            "Shared/dedicated or incorrectly owned OA controllers require separate coverage"
        )
        return None
    return loop, system, controller


def mechanical_ventilation(controller, sdk):
    index = controller.iddObject().getFieldIndex("Controller Mechanical Ventilation")
    pointer = (
        controller.idfObject().getString(index.get())
        if index.is_initialized()
        else None
    )
    if pointer and pointer.is_initialized() and pointer.get():
        result = controller.model().getControllerMechanicalVentilation(
            sdk.toUUID(pointer.get())
        )
        if result.is_initialized():
            return result.get()
    return None
