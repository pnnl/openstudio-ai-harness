"""Shared fan units and performance setters for assembly and partial edits."""

import math
from common.hvac_equipment import call

PERFORMANCE_SETTERS = {
    "total_efficiency": "setFanEfficiency",
    "motor_efficiency": "setMotorEfficiency",
    "pressure_rise_pa": "setPressureRise",
}


def pressure_pa(value, units):
    # OpenStudio 3.11.0 convert(value, "inH_{2}O", "Pa") verified this factor.
    factors = {"Pa": 1.0, "inH2O": 249.08891}
    if units not in factors:
        raise ValueError(f"Unsupported pressure units: {units}")
    converted = value * factors[units]
    if not math.isfinite(converted):
        raise ValueError("SI conversion is not finite")
    return converted


def require_performance(values):
    missing = sorted(PERFORMANCE_SETTERS.keys() - values.keys())
    if missing:
        raise ValueError(f"Missing fan performance values: {', '.join(missing)}")


def set_performance(fan, values, *, partial=False):
    if not partial:
        require_performance(values)
    for key, method in PERFORMANCE_SETTERS.items():
        if key in values:
            call(fan, method, values[key])
