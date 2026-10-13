"""In-place direct supply-fan performance editing with independent preservation checks."""

from __future__ import annotations
from collections import Counter
import json
import math
from pathlib import Path
from common.input_validation import validate
from common.hvac_inventory import resolve
from common.fan_equipment import pressure_pa, set_performance
from common.model_preservation import fingerprint, snapshot

SUPPORTED = {
    "OS_Fan_VariableVolume": "FanVariableVolume",
    "OS_Fan_ConstantVolume": "FanConstantVolume",
}
EDITABLE_FIELDS = {
    "total_efficiency": "Fan Total Efficiency",
    "motor_efficiency": "Motor Efficiency",
    "pressure_rise_pa": "Pressure Rise",
}


def ref(obj):
    return dict(
        handle=str(obj.handle()),
        name=obj.nameString(),
        type=obj.iddObjectType().valueName(),
    )


def inventory(model):
    return dict(
        air_loops=sorted(
            [
                dict(
                    ref(loop),
                    zone_count=len(loop.thermalZones()),
                    fans=[
                        ref(x)
                        for x in loop.supplyComponents()
                        if x.iddObjectType().valueName().startswith("OS_Fan_")
                    ],
                    split_supply=loop.supplySplitter().is_initialized()
                    or len(loop.supplyOutletNodes()) != 1,
                )
                for loop in model.getAirLoopHVACs()
            ],
            key=lambda x: (x["name"], x["handle"]),
        )
    )


def fan_object(model, sdk, reference):
    obj = model.getModelObject(sdk.toUUID(reference["handle"]))
    if (
        not obj.is_initialized()
        or obj.get().iddObjectType().valueName() != reference["type"]
    ):
        raise ValueError("Selected fan is missing or has a different class")
    return getattr(obj.get(), "to_" + SUPPORTED[reference["type"]])().get()


def values(fan):
    return dict(
        total_efficiency=fan.fanEfficiency(),
        motor_efficiency=fan.motorEfficiency(),
        pressure_rise_pa=fan.pressureRise(),
    )


def ports(fan):
    result = []
    for obj in (fan.inletModelObject(), fan.outletModelObject()):
        if not obj.is_initialized() or not obj.get().to_Node().is_initialized():
            raise ValueError("Fan must connect directly between two supply nodes")
        result.append(str(obj.get().handle()))
    return result


def protected(model, fan):
    return snapshot(model, excluded={str(fan.handle())})


def fan_counts(model):
    return dict(
        sorted(
            Counter(
                x.iddObjectType().valueName()
                for x in model.modelObjects()
                if x.iddObjectType().valueName().startswith("OS_Fan_")
            ).items()
        )
    )


def fan_signature(fan, changes):
    return fingerprint(
        fan,
        {},
        tuple(EDITABLE_FIELDS[key] for key in changes),
    )


def plan(model, sdk, config):
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "references/fan_performance.schema.json"
        ).read_text()
    )
    errors = validate(config, schema)
    if errors:
        raise ValueError(f"Invalid fan performance configuration: {errors}")
    missing = [
        key for key in ("air_loop", "fan") if key not in config or not config[key]
    ]
    planned = dict(
        ready=False,
        parameters=dict(output_model_path=config["output_model_path"]),
        missing_inputs=missing,
        errors=[],
        warnings=[],
        assumptions=[],
    )
    if missing:
        return planned
    selected = resolve(
        config["air_loop"], inventory(model)["air_loops"], "air_loop", planned["errors"]
    )
    if selected is None:
        return planned
    if (
        selected["split_supply"]
        or len(selected["fans"]) != 1
        or selected["fans"][0]["type"] not in SUPPORTED
    ):
        planned["errors"].append(
            "Select an unsplit air loop with exactly one direct constant- or variable-volume supply fan"
        )
        return planned
    fan_ref = selected["fans"][0]
    fan = fan_object(model, sdk, fan_ref)
    if (
        not fan.airLoopHVAC().is_initialized()
        or str(fan.airLoopHVAC().get().handle()) != selected["handle"]
    ):
        raise ValueError("Fan is not directly owned by the selected air loop")
    patch = dict(config["fan"])
    if ("pressure_rise" in patch) != ("pressure_units" in patch):
        planned["missing_inputs"].append(
            "fan.pressure_rise and fan.pressure_units must be specified together"
        )
        return planned
    if "pressure_rise" in patch:
        unit = patch.pop("pressure_units")
        try:
            patch["pressure_rise_pa"] = pressure_pa(patch.pop("pressure_rise"), unit)
        except ValueError as exc:
            planned["errors"].append(f"fan.pressure_rise: {exc}")
            return planned
    before = values(fan)
    after = dict(before, **patch)
    if (
        any(not math.isfinite(x) for x in after.values())
        or not 0 < after["total_efficiency"] <= after["motor_efficiency"] <= 1
        or after["pressure_rise_pa"] < 0
    ):
        planned["errors"].append(
            "Effective fan settings require 0 < total efficiency <= motor efficiency <= 1 and finite nonnegative pressure"
        )
        return planned
    if after == before:
        planned["errors"].append("Edit must change at least one performance setting")
        return planned
    boundary_ports = ports(fan)
    planned.update(
        ready=True,
        parameters=dict(output_model_path=config["output_model_path"], fan=patch),
        resolved_objects=dict(
            air_loop={k: selected[k] for k in ("name", "handle", "type")},
            fan=fan_ref,
            ports=boundary_ports,
        ),
        before_values=before,
        after_values=after,
        preserved_fan=fan_signature(fan, patch),
        protected_objects=protected(model, fan),
        before_counts=fan_counts(model),
        supply_order=[
            str(x.handle()) for x in fan.airLoopHVAC().get().supplyComponents()
        ],
        impact=dict(
            air_loop=selected["name"],
            fan=fan_ref["name"],
            affected_zone_count=selected["zone_count"],
            before=before,
            after=after,
        ),
        assumptions=[
            "Fan and reference handles retained; same class/name, unspecified settings, schedule, flow/autosize and metadata retained"
        ],
        warnings=[
            "Re-run sizing/simulation to assess performance after fan performance editing"
        ],
    )
    return planned


def edit(model, sdk, planned):
    fan = fan_object(model, sdk, planned["resolved_objects"]["fan"])
    before = values(fan)
    set_performance(fan, planned["parameters"]["fan"], partial=True)
    return dict(
        air_loop=planned["resolved_objects"]["air_loop"],
        fan=ref(fan),
        before=before,
        after=values(fan),
    )


def validate_model(model, sdk, planned, result):
    fan = fan_object(model, sdk, result["fan"])
    old = planned["resolved_objects"]["fan"]
    errors = []
    checks = 0

    def check(ok, text):
        nonlocal checks
        checks += 1
        if not ok:
            errors.append(text)

    check(
        result["before"] == planned["before_values"]
        and result["after"] == planned["after_values"],
        "Reported before/after values differ from the approved plan",
    )
    check(
        str(fan.handle()) == old["handle"] and result["fan"] == old,
        "Fan identity changed",
    )
    check(
        fan.nameString() == old["name"]
        and fan.iddObjectType().valueName() == old["type"],
        "Fan name/class changed",
    )
    for key, actual in values(fan).items():
        check(
            math.isclose(
                actual, planned["after_values"][key], rel_tol=1e-9, abs_tol=1e-9
            ),
            f"Fan {key} differs from approved value",
        )
    check(
        ports(fan) == planned["resolved_objects"]["ports"],
        "Fan boundary nodes changed",
    )
    check(
        fan_signature(fan, planned["parameters"]["fan"]) == planned["preserved_fan"],
        "Unrequested fan settings changed",
    )
    check(
        protected(model, fan) == planned["protected_objects"],
        "Protected model objects changed",
    )
    check(fan_counts(model) == planned["before_counts"], "Fan class counts changed")
    loop = model.getAirLoopHVAC(
        sdk.toUUID(planned["resolved_objects"]["air_loop"]["handle"])
    )
    check(loop.is_initialized(), "Selected air loop missing")
    if loop.is_initialized():
        expected = planned["supply_order"]
        check(
            [str(x.handle()) for x in loop.get().supplyComponents()] == expected,
            "Supply order changed",
        )
        check(
            fan.airLoopHVAC().is_initialized()
            and fan.airLoopHVAC().get().handle() == loop.get().handle(),
            "Fan has wrong air-loop ownership",
        )
    return dict(ok=not errors, checks=checks, errors=errors, counts=fan_counts(model))
