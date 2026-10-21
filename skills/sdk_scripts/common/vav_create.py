"""VAV recipe backed by shared equipment and multizone assembly."""

from common.hvac_equipment import call, by_handle, schedule, water_controller, make_coil
from common.multizone_assembly import assemble


def create(model, sdk, planned):
    return assemble(model, sdk, planned)
