"""Explicit ventilation setters: no schedule construction or implicit DCV floor reset."""

from common.hvac_equipment import call, by_handle
from common.outdoor_air import ref

FIELDS = {
    "minimum_flow_m3_s": (
        "MinimumOutdoorAirFlowRate",
        "Minimum Outdoor Air Flow Rate",
        "flow",
    ),
    "maximum_flow_m3_s": (
        "MaximumOutdoorAirFlowRate",
        "Maximum Outdoor Air Flow Rate",
        "flow",
    ),
    "minimum_limit_type": ("MinimumLimitType", "Minimum Limit Type", "enum"),
    "minimum_flow_schedule": (
        "MinimumOutdoorAirSchedule",
        "Minimum Outdoor Air Schedule Name",
        "schedule",
    ),
    "minimum_fraction_schedule": (
        "MinimumFractionofOutdoorAirSchedule",
        "Minimum Fraction of Outdoor Air Schedule Name",
        "schedule",
    ),
    "maximum_fraction_schedule": (
        "MaximumFractionofOutdoorAirSchedule",
        "Maximum Fraction of Outdoor Air Schedule Name",
        "schedule",
    ),
}


def values(controller, mv):
    result = {}
    for key, (suffix, _, kind) in FIELDS.items():
        if kind == "enum":
            value = controller.getMinimumLimitType()
        elif kind == "flow" and getattr(controller, "is" + suffix + "Autosized")():
            value = "Autosize"
        else:
            optional = getattr(controller, suffix[0].lower() + suffix[1:])()
            value = (
                (ref(optional.get()) if kind == "schedule" else optional.get())
                if optional.is_initialized()
                else None
            )
        result[key] = value
    result["dcv"] = mv.demandControlledVentilation() if mv else None
    return result


def set_settings(model, sdk, controller, mv, patch):
    for key, value in patch.items():
        if key == "dcv":
            if mv is None:
                raise ValueError(
                    "DCV requires an existing mechanical-ventilation controller"
                )
            call(mv, "setDemandControlledVentilation", value)
            continue
        suffix, _, kind = FIELDS[key]
        if kind == "flow" and value == "Autosize":
            call(controller, "autosize" + suffix)
        elif kind == "schedule":
            if value is None:
                call(controller, "reset" + suffix)
            else:
                call(
                    controller, "set" + suffix, by_handle(model, sdk, value, "Schedule")
                )
        else:
            call(controller, "set" + suffix, value)
