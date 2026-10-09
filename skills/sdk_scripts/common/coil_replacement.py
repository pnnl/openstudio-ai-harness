"""Deferred same-class coil clone/reconnect primitive; never exported.

In-place edits do not call this code. Plant migration uses existing objects in
coil_migration. Class conversion and location changes need a new
topology/controller/reference contract before using this clone primitive.
The caller must establish reference migration and saved-model validation.
"""

from common.water_coil import object_by_ref, raw_fields, ref
from common.coil_equipment import CLASSES, set_ratings, finalize_controller
from common.hvac_equipment import call, schedule


def clone_and_reconnect(model, sdk, planned):
    p = planned["parameters"]
    r = planned["resolved_objects"]
    kind = p["kind"]
    old = object_by_ref(model, sdk, r["coil"], CLASSES[kind])
    controller = (
        old.controllerWaterCoil().get().clone(model).to_ControllerWaterCoil().get()
    )
    coil = getattr(old.clone(model), "to_" + CLASSES[kind])().get()
    # Retarget the cloned owned controller using the pinned IDD field name.
    fields = raw_fields(controller)
    index = next(i for i, (name, _) in fields.items() if name == "Water Coil Name")
    call(controller, "setPointer", index, coil.handle())
    nodes = [object_by_ref(model, sdk, {"handle": h}, "Node") for h in r["ports"]]
    for port in [
        old.airInletPort(),
        old.airOutletPort(),
        old.waterInletPort(),
        old.waterOutletPort(),
    ]:
        model.disconnect(old, port)
    old.remove()
    for a, b, i, o in [
        (nodes[0], nodes[1], coil.airInletPort(), coil.airOutletPort()),
        (nodes[2], nodes[3], coil.waterInletPort(), coil.waterOutletPort()),
    ]:
        model.connect(a, a.outletPort(), coil, i)
        model.connect(coil, o, b, b.inletPort())
    set_ratings(coil, kind, p["ratings"])
    call(coil, "setName", p["coil_name"])
    call(
        coil,
        "setAvailabilitySchedule",
        schedule(model, sdk, p["availability_schedule"]),
    )
    finalize_controller(coil, model, sdk, kind, p["controller"])
    return dict(coil=ref(coil), controller=ref(coil.controllerWaterCoil().get()))
