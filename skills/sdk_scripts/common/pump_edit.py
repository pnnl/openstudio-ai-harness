"""In-place single-pump edits with explicit power semantics and saved-state checks."""

from __future__ import annotations
import json
import math
from pathlib import Path
from common.input_validation import validate
from common.hvac_inventory import resolve
from common.model_preservation import fingerprint, snapshot

SUPPORTED = {
    "OS_Pump_ConstantSpeed": "PumpConstantSpeed",
    "OS_Pump_VariableSpeed": "PumpVariableSpeed",
}
# Configuration key, SDK getter/setter suffix, raw IDD field. No prototype defaults.
FIELDS = {
    "head_pa": ("ratedPumpHead", "RatedPumpHead", "Rated Pump Head"),
    "motor_efficiency": ("motorEfficiency", "MotorEfficiency", "Motor Efficiency"),
    "motor_loss_fraction_to_fluid": (
        "fractionofMotorInefficienciestoFluidStream",
        "FractionofMotorInefficienciestoFluidStream",
        "Fraction of Motor Inefficiencies to Fluid Stream",
    ),
    "control_type": ("pumpControlType", "PumpControlType", "Pump Control Type"),
    "power_sizing_method": (
        "designPowerSizingMethod",
        "DesignPowerSizingMethod",
        "Design Power Sizing Method",
    ),
    "electric_power_per_flow": (
        "designElectricPowerPerUnitFlowRate",
        "DesignElectricPowerPerUnitFlowRate",
        "Design Electric Power per Unit Flow Rate",
    ),
    "shaft_power_per_flow_per_head": (
        "designShaftPowerPerUnitFlowRatePerUnitHead",
        "DesignShaftPowerPerUnitFlowRatePerUnitHead",
        "Design Shaft Power per Unit Flow Rate per Unit Head",
    ),
}
CURVE_FIELDS = [
    f"Coefficient {i} of the Part Load Performance Curve" for i in range(1, 5)
]


def ref(obj):
    return dict(
        handle=str(obj.handle()),
        name=obj.nameString(),
        type=obj.iddObjectType().valueName(),
    )


def inventory(model):
    return dict(
        plant_loops=sorted(
            [
                dict(
                    ref(loop),
                    loop_type=loop.sizingPlant().loopType(),
                    pumps=[
                        dict(ref(x), side=side)
                        for side in ("supply", "demand")
                        for x in getattr(loop, side + "Components")()
                        if x.iddObjectType()
                        .valueName()
                        .startswith(("OS_Pump_", "OS_HeaderedPumps_"))
                    ],
                )
                for loop in model.getPlantLoops()
            ],
            key=lambda x: (x["name"], x["handle"]),
        )
    )


def pump_object(model, sdk, reference):
    obj = model.getModelObject(sdk.toUUID(reference["handle"]))
    if (
        not obj.is_initialized()
        or obj.get().iddObjectType().valueName() != reference["type"]
    ):
        raise ValueError("Selected pump missing or class changed")
    return getattr(obj.get(), "to_" + SUPPORTED[reference["type"]])().get()


def sized(pump, key):
    if getattr(pump, "is" + key[0].upper() + key[1:] + "Autosized")():
        return "Autosize"
    val = getattr(pump, key)()
    return val.get() if val.is_initialized() else None


def values(pump):
    result = {key: getattr(pump, getter)() for key, (getter, _, _) in FIELDS.items()}
    result["rated_power_w"] = sized(pump, "ratedPowerConsumption")
    if pump.iddObjectType().valueName() == "OS_Pump_VariableSpeed":
        result["part_load_coefficients"] = [
            getattr(pump, f"coefficient{i}ofthePartLoadPerformanceCurve")()
            for i in range(1, 5)
        ]
    return result


def ports(pump):
    result = []
    for port in (pump.inletModelObject(), pump.outletModelObject()):
        if not port.is_initialized() or not port.get().to_Node().is_initialized():
            raise ValueError("Pump must connect directly between two plant nodes")
        result.append(str(port.get().handle()))
    return result


def signature(pump, patch):
    ignored = [FIELDS[key][2] for key in patch if key in FIELDS]
    if "rated_power_w" in patch:
        ignored.append("Rated Power Consumption")
    if "part_load_coefficients" in patch:
        ignored.extend(CURVE_FIELDS)
    return fingerprint(pump, ignored=ignored)


def curve_minimum(c):
    # Evaluate endpoints and all stationary points of the cubic, not a sampled grid.
    a, b, cc, d = c
    points = [0.0, 1.0]
    if d == 0:
        if cc != 0:
            points.append(-b / (2 * cc))
    else:
        disc = 4 * cc * cc - 12 * d * b
        if disc >= 0:
            points.extend(
                [(-2 * cc + sign * math.sqrt(disc)) / (6 * d) for sign in (-1, 1)]
            )
    return min(a + x * (b + x * (cc + x * d)) for x in points if 0 <= x <= 1)


def power_check(after, flow):
    """Shared rated-power feasibility and active-sizing messages, without sizing."""
    errors, warnings = [], []
    if after["rated_power_w"] != "Autosize":
        warnings.append(
            "Rated electric power is fixed: head/motor efficiency and sizing-factor changes do not recalculate it. Request rated_power_w: Autosize explicitly if recalculation is intended"
        )
        if flow == "Autosize":
            maximum_flow = (
                after["rated_power_w"] * after["motor_efficiency"] / after["head_pa"]
                if after["head_pa"] > 0
                else None
            )
            warnings.append(
                "Motor-output feasibility cannot be checked before sizing: rated flow is autosized "
                "while electric power is fixed. After sizing, verify implied hydraulic efficiency "
                "flow × head / (rated power × motor efficiency) <= 1."
                + (
                    f" Maximum feasible design flow is {maximum_flow:.9g} m³/s."
                    if maximum_flow is not None
                    else ""
                )
            )
        if (
            isinstance(flow, (float, int))
            and flow * after["head_pa"]
            > after["rated_power_w"] * after["motor_efficiency"] + 1e-9
        ):
            errors.append(
                "Fixed flow/head require more hydraulic power than the rated motor can deliver"
            )
    elif after["power_sizing_method"] == "PowerPerFlow":
        warnings.append(
            "Autosized electric power uses flow times electric_power_per_flow; head and motor efficiency do not change that sizing calculation"
        )
    else:
        warnings.append(
            "Autosized electric power uses flow × head × shaft_power_per_flow_per_head / motor_efficiency; re-run sizing"
        )
    return errors, warnings


def plan(model, sdk, config):
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "references/pump_performance.schema.json"
        ).read_text()
    )
    errors = validate(config, schema)
    if errors:
        raise ValueError(f"Invalid pump performance configuration: {errors}")
    planned = dict(
        ready=False,
        parameters=dict(output_model_path=config["output_model_path"]),
        missing_inputs=[
            k for k in ("plant_loop", "pump", "settings") if not config.get(k)
        ],
        errors=[],
        warnings=[],
        assumptions=[],
    )
    if planned["missing_inputs"]:
        return planned
    loop_ref = resolve(
        config["plant_loop"],
        inventory(model)["plant_loops"],
        "plant_loop",
        planned["errors"],
    )
    if loop_ref is None:
        return planned
    selected = resolve(config["pump"], loop_ref["pumps"], "pump", planned["errors"])
    if selected is None:
        return planned
    if selected["type"] not in SUPPORTED:
        planned["errors"].append(
            "Only single PumpConstantSpeed and PumpVariableSpeed are supported; headered/condensate pumps require separate coverage"
        )
        return planned
    pump = pump_object(model, sdk, selected)
    patch = dict(config["settings"])
    if ("head" in patch) != ("head_units" in patch):
        planned["missing_inputs"].append(
            "settings.head and head_units must be specified together"
        )
        return planned
    if "head" in patch:
        unit = patch.pop("head_units")
        patch["head_pa"] = sdk.convert(
            patch.pop("head"), "ftH_{2}O" if unit == "ftH2O" else "Pa", "Pa"
        ).get()
    if "part_load_coefficients" in patch:
        if selected["type"] != "OS_Pump_VariableSpeed":
            planned["errors"].append(
                "Part-load coefficients apply only to a variable-speed pump"
            )
        elif (
            len(patch["part_load_coefficients"]) != 4
            or curve_minimum(patch["part_load_coefficients"]) < -1e-10
            or sum(patch["part_load_coefficients"]) <= 0
        ):
            planned["errors"].append(
                "Supply exactly four coefficients with nonnegative power over flow fraction [0,1] and positive full-flow power"
            )
    before = values(pump)
    after = dict(before, **patch)
    if any(
        isinstance(v, (float, int)) and not math.isfinite(v) for v in after.values()
    ):
        planned["errors"].append("Effective settings must be finite")
    if after == before:
        planned["errors"].append("Edit must change at least one setting")
    if planned["errors"]:
        return planned
    warnings = planned["warnings"]
    power_errors, power_warnings = power_check(after, sized(pump, "ratedFlowRate"))
    planned["errors"].extend(power_errors)
    warnings.extend(power_warnings)
    if planned["errors"]:
        return planned
    if (
        "electric_power_per_flow" in patch
        and after["power_sizing_method"] != "PowerPerFlow"
    ):
        warnings.append(
            "electric_power_per_flow is inactive under the selected power sizing method"
        )
    if (
        "shaft_power_per_flow_per_head" in patch
        and after["power_sizing_method"] != "PowerPerFlowPerPressure"
    ):
        warnings.append(
            "shaft_power_per_flow_per_head is inactive under the selected power sizing method"
        )
    if "part_load_coefficients" in patch:
        warnings.append(
            "Part-load coefficients describe electric power versus flow; they do not install differential-pressure reset controls or force variable plant flow"
        )
        if not math.isclose(sum(patch["part_load_coefficients"]), 1, abs_tol=1e-3):
            warnings.append("Part-load power fraction at full flow differs from 1.0")
    if pump.pumpCurve().is_initialized() or (
        selected["type"] == "OS_Pump_VariableSpeed"
        and pump.vFDControlType().is_initialized()
    ):
        warnings.append(
            "Existing pump pressure curve/VFD controls are retained and may override the simple part-load power model"
        )
    if after["control_type"] == "Continuous":
        warnings.append(
            "Continuous control may circulate water without a load, subject to retained schedules and loop controls"
        )
    loop = model.getPlantLoop(sdk.toUUID(loop_ref["handle"])).get()
    if (
        not pump.plantLoop().is_initialized()
        or pump.plantLoop().get().handle() != loop.handle()
    ):
        raise ValueError("Pump ownership differs from the selected plant")
    planned.update(
        ready=True,
        parameters=dict(output_model_path=config["output_model_path"], settings=patch),
        resolved_objects=dict(
            plant_loop={k: loop_ref[k] for k in ("handle", "name", "type")},
            pump={k: selected[k] for k in ("handle", "name", "type")},
            side=selected["side"],
            ports=ports(pump),
        ),
        before_values=before,
        after_values=after,
        preserved_pump=signature(pump, patch),
        protected_objects=snapshot(model, excluded={str(pump.handle())}),
        component_order={
            side: [str(x.handle()) for x in getattr(loop, side + "Components")()]
            for side in ("supply", "demand")
        },
        impact=dict(
            plant_loop=loop.nameString(),
            pump=pump.nameString(),
            side=selected["side"],
            before=before,
            after=after,
            rated_flow_m3_s=sized(pump, "ratedFlowRate"),
            identities="Pump, connections, metadata and incoming references retained; no plant rewiring",
        ),
        assumptions=[
            "Only requested settings change; name/class, flow/minimum flow, schedules, other pumps, plant sizing and controls remain unchanged"
        ],
    )
    return planned


def edit(model, sdk, planned):
    pump = pump_object(model, sdk, planned["resolved_objects"]["pump"])
    before = values(pump)
    for key, value in planned["parameters"]["settings"].items():
        if key == "rated_power_w":
            ok = (
                pump.autosizeRatedPowerConsumption()
                if value == "Autosize"
                else pump.setRatedPowerConsumption(value)
            )
        elif key == "part_load_coefficients":
            for i, coefficient in enumerate(value, 1):
                if (
                    getattr(pump, f"setCoefficient{i}ofthePartLoadPerformanceCurve")(
                        coefficient
                    )
                    is False
                ):
                    raise ValueError("SDK rejected pump coefficient")
            continue
        else:
            ok = getattr(pump, "set" + FIELDS[key][1])(value)
        if ok is False:
            raise ValueError(f"SDK rejected pump {key}")
    return dict(pump=ref(pump), before=before, after=values(pump))


def matches(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(matches(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(matches(x, y) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return a == b


def validate_model(model, sdk, planned, result):
    pump = pump_object(model, sdk, planned["resolved_objects"]["pump"])
    loop = model.getPlantLoop(
        sdk.toUUID(planned["resolved_objects"]["plant_loop"]["handle"])
    ).get()
    checks = {
        "Pump identity/name/class changed": ref(pump)
        == planned["resolved_objects"]["pump"]
        == result["pump"],
        "Reported values differ from plan": matches(
            result["before"], planned["before_values"]
        )
        and matches(result["after"], planned["after_values"]),
        "Saved settings differ from plan": matches(
            values(pump), planned["after_values"]
        ),
        "Pump boundary nodes changed": ports(pump)
        == planned["resolved_objects"]["ports"],
        "Unrequested pump fields changed": signature(
            pump, planned["parameters"]["settings"]
        )
        == planned["preserved_pump"],
        "Protected objects/references changed": snapshot(
            model, excluded={str(pump.handle())}
        )
        == planned["protected_objects"],
        "Pump plant ownership changed": pump.plantLoop().is_initialized()
        and pump.plantLoop().get().handle() == loop.handle(),
        "Plant supply/demand component order changed": all(
            [str(x.handle()) for x in getattr(loop, side + "Components")()] == expected
            for side, expected in planned["component_order"].items()
        ),
    }
    return dict(
        ok=all(checks.values()),
        checks=len(checks),
        errors=[key for key, ok in checks.items() if not ok],
    )
