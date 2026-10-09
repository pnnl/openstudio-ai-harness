"""Economizer field setters shared by complete-system and in-place operations."""

from common.hvac_equipment import call

# Input key: SDK suffix, raw IDD field, optional/resettable.
FIELDS = {
    "control_type": ("EconomizerControlType", "Economizer Control Type", False),
    "lockout_type": ("LockoutType", "Lockout Type", False),
    "maximum_dry_bulb_c": (
        "EconomizerMaximumLimitDryBulbTemperature",
        "Economizer Maximum Limit Dry-Bulb Temperature",
        True,
    ),
    "maximum_enthalpy_j_kg": (
        "EconomizerMaximumLimitEnthalpy",
        "Economizer Maximum Limit Enthalpy",
        True,
    ),
    "maximum_dewpoint_c": (
        "EconomizerMaximumLimitDewpointTemperature",
        "Economizer Maximum Limit Dewpoint Temperature",
        True,
    ),
    "minimum_dry_bulb_c": (
        "EconomizerMinimumLimitDryBulbTemperature",
        "Economizer Minimum Limit Dry-Bulb Temperature",
        True,
    ),
}


def set_settings(controller, patch):
    for key, value in patch.items():
        suffix, _, resettable = FIELDS[key]
        if value is None:
            if not resettable:
                raise ValueError(f"Cannot reset economizer {key}")
            call(controller, "reset" + suffix)
        else:
            call(controller, "set" + suffix, value)
