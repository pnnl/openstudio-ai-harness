"""Deferred fan replacement primitive; deliberately not exported as a skill.

The tested same-class clone/reconnect algorithm retains boundary nodes. A future
class-changing replacement contract must specify new fan curves, terminal/sizing
changes and reference migration before adapting or exposing this primitive.
Performance edits use fan_edit.edit and never call this function.
"""

from common.fan_edit import SUPPORTED, fan_object, ref, values
from common.fan_equipment import set_performance
from common.hvac_equipment import call


def clone_and_reconnect(model, sdk, planned):
    fan = fan_object(model, sdk, planned["resolved_objects"]["fan"])
    before = values(fan)
    inlet = model.getNode(sdk.toUUID(planned["resolved_objects"]["ports"][0])).get()
    outlet = model.getNode(sdk.toUUID(planned["resolved_objects"]["ports"][1])).get()
    replacement = getattr(
        fan.clone(model), "to_" + SUPPORTED[planned["resolved_objects"]["fan"]["type"]]
    )().get()
    set_performance(replacement, planned["parameters"]["fan"], partial=True)
    # addToNode/remove may delete an interior node. Native port operations are
    # void in 3.11.0; saved getters verify both connections and node identities.
    model.disconnect(fan, fan.inletPort())
    model.disconnect(fan, fan.outletPort())
    fan.remove()
    model.connect(inlet, inlet.outletPort(), replacement, replacement.inletPort())
    model.connect(replacement, replacement.outletPort(), outlet, outlet.inletPort())
    call(replacement, "setName", planned["resolved_objects"]["fan"]["name"])
    return dict(
        air_loop=planned["resolved_objects"]["air_loop"],
        removed_fan=planned["resolved_objects"]["fan"],
        replacement_fan=ref(replacement),
        before=before,
        after=values(replacement),
    )
