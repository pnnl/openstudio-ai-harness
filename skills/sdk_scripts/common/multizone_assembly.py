"""Multizone assembly: one transaction assembles reusable equipment modules."""

from __future__ import annotations
from common.air_system_recipe import VAV
from common.hvac_equipment import (
    call,
    by_handle,
    schedule,
    water_controller,
    make_coil,
    attach_zones,
)
from common.air_loop_components import (
    configure_sizing,
    attach_supply_setpoint,
    attach_fan,
    attach_outdoor_air,
    configure_availability,
)


def assemble(model, sdk, planned, *, recipe=VAV):
    recipe.check_plan(planned)
    p, r = planned["parameters"], planned["resolved_objects"]
    c = planned["controls"]
    loop = sdk.model.AirLoopHVAC(model)
    call(loop, "setName", p["system_name"])
    configure_sizing(model, sdk, loop, p, r, c)
    attach_supply_setpoint(model, sdk, loop, p, r, c)
    attach_fan(model, sdk, loop, p, r, c, recipe=recipe)
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
    attach_outdoor_air(model, sdk, loop, p, r, c, recipe=recipe)
    configure_availability(model, sdk, loop, p, r, c)
    attach_zones(model, sdk, loop, p, r, c)
    return str(loop.handle())
