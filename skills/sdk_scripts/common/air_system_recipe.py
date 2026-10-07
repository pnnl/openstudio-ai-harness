"""Immutable system metadata shared by assembly and independent validation."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AirSystemRecipe:
    system_kind: str
    fan_kind: str
    oa_schedule_mode: str

    def __post_init__(self):
        if self.fan_kind not in ("VariableVolume", "ConstantVolume"):
            raise ValueError("Unsupported air-system fan kind")
        if self.oa_schedule_mode not in ("minimum_flow", "minimum_fraction"):
            raise ValueError("Unsupported outdoor-air schedule role")

    @property
    def fan_class(self):
        return "Fan" + self.fan_kind

    @property
    def fan_count_key(self):
        return "fan_" + self.fan_kind

    @property
    def oa_schedule_setter(self):
        return "set" + self.oa_schedule_getter[0].upper() + self.oa_schedule_getter[1:]

    @property
    def oa_schedule_getter(self):
        return (
            "minimumOutdoorAirSchedule"
            if self.oa_schedule_mode == "minimum_flow"
            else "minimumFractionofOutdoorAirSchedule"
        )

    @property
    def unused_oa_schedule_getter(self):
        return (
            "minimumFractionofOutdoorAirSchedule"
            if self.oa_schedule_mode == "minimum_flow"
            else "minimumOutdoorAirSchedule"
        )

    def check_plan(self, planned):
        if planned.get("system_kind", self.system_kind) != self.system_kind:
            raise ValueError("Plan does not match the air-system recipe")


VAV = AirSystemRecipe("vav_reheat", "VariableVolume", "minimum_flow")
PROTOTYPE_CAV = AirSystemRecipe("prototype_cav", "ConstantVolume", "minimum_fraction")
