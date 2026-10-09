"""In-place economizer edits preserving ventilation, schedules and all topology."""

import json
import math
from pathlib import Path
from common.input_validation import validate
from common.hvac_inventory import resolve
from common.hvac_equipment import by_handle
from common.economizer_equipment import FIELDS, set_settings
from common.model_preservation import snapshot
from common.outdoor_air import (
    ref,
    inventory,
    schedule_context,
    context,
    mixed_air_control,
)


def values(controller):
    result = {}
    for key, (suffix, _, optional) in FIELDS.items():
        value = getattr(controller, "get" + suffix)()
        result[key] = (
            (value.get() if value.is_initialized() else None) if optional else value
        )
    return result


def settings_match(actual, expected):
    if actual.keys() != expected.keys():
        return False
    for key, value in actual.items():
        wanted = expected[key]
        if type(value) in (int, float) and type(wanted) in (int, float):
            if not math.isclose(value, wanted, rel_tol=1e-9, abs_tol=1e-9):
                return False
        elif type(value) is not type(wanted) or value != wanted:
            return False
    return True


def check_effective(controller, after):
    errors = []
    kind = after["control_type"]
    if kind == "NoEconomizer":
        return errors
    required = {
        "FixedDryBulb": ("maximum_dry_bulb_c",),
        "FixedEnthalpy": ("maximum_enthalpy_j_kg",),
        "FixedDewPointAndDryBulb": ("maximum_dry_bulb_c", "maximum_dewpoint_c"),
    }.get(kind, ())
    errors.extend(
        f"Effective {kind} requires {key}" for key in required if after[key] is None
    )
    low, high = after["minimum_dry_bulb_c"], after["maximum_dry_bulb_c"]
    if low is not None and high is not None and low >= high:
        errors.append("Effective minimum dry-bulb limit must be below the maximum")
    if kind == "ElectronicEnthalpy":
        curve = controller.electronicEnthalpyLimitCurve()
        if (
            not curve.is_initialized()
            or curve.get().iddObjectType().valueName()
            not in ("OS_Curve_Quadratic", "OS_Curve_Cubic")
        ):
            errors.append(
                "ElectronicEnthalpy requires an existing quadratic/cubic limit curve; curve creation/replacement is separate coverage"
            )
    return errors


def warnings_for(controller, after, current):
    warnings = [
        "Ventilation/DCV, flows, schedules, sizing and economizer action are retained; this edit does not establish ventilation compliance or annual savings"
    ]
    simulation_ready = True
    if after["control_type"] == "NoEconomizer":
        warnings.append(
            "Economizer limits and lockout are retained but inactive under NoEconomizer"
        )
    else:
        warnings.append(
            "Every nonblank retained limit is an additional cutoff for the chosen economizer type; no limits or climate/template settings are reset implicitly"
        )
    if after["lockout_type"] == "LockoutWithCompressor" and any(
        x["type"] == "OS_Coil_Cooling_Water" for x in current["cooling_components"]
    ):
        warnings.append(
            "LockoutWithCompressor does not provide DX compressor lockout for the retained hydronic cooling coil; no supply-temperature limit is inferred"
        )
    if current["action"] == "MinimumFlowWithBypass":
        warnings.append(
            "Retained MinimumFlowWithBypass action keeps OA flow at its minimum and controls heat-recovery bypass instead of modulating OA for free cooling"
        )
    if current["force_economizer_schedule"]:
        warnings.append(
            "Retained time-of-day economizer schedule can force maximum outdoor air when positive; it is not an economizer availability schedule"
        )
    if current["high_humidity_control"]:
        warnings.append(
            "Retained high-humidity control can override normal economizer OA flow"
        )
    if controller.electronicEnthalpyLimitCurve().is_initialized():
        warnings.append(
            "Retained electronic enthalpy limit curve remains an additional cutoff when economizing"
        )

    def constant(key):
        item = current[key]
        return item["constant_value"] if item else None

    minimum = constant("minimum_fraction_schedule")
    maximum = constant("maximum_fraction_schedule")
    if minimum == 1:
        warnings.append(
            "Retained minimum OA fraction is 1.0 (100% outdoor air): economizer selection cannot lower that floor; maximum-flow/fraction constraints can still override it"
        )
        if not (
            current["all_outdoor_air_heating"] and current["all_outdoor_air_cooling"]
        ):
            warnings.append(
                "Retained 100% OA floor is not matched by both all-outdoor-air sizing flags; review coil sizing before simulation"
            )
            simulation_ready = False
    for key in ("minimum_fraction_schedule", "maximum_fraction_schedule"):
        item = current[key]
        if item and item["constant_value"] is None:
            warnings.append(
                f"Retained {key} varies or is not constant; effective OA bounds require schedule/time review"
            )
    if maximum is not None and maximum < 1:
        warnings.append(
            f"Retained maximum OA fraction {maximum:g} caps economizer OA and can override minimum ventilation"
        )
    if maximum == 0 or (
        minimum is not None and maximum is not None and minimum > maximum
    ):
        warnings.append(
            "Retained OA fraction constraints suppress/contradict minimum ventilation; review before simulation"
        )
        simulation_ready = False
    lo, hi = current["minimum_flow_m3_s"], current["maximum_flow_m3_s"]
    if hi == 0 or (type(lo) in (int, float) and type(hi) in (int, float) and lo > hi):
        warnings.append(
            "Retained minimum/maximum OA flow constraints conflict or prohibit OA; review before simulation"
        )
        simulation_ready = False
    return warnings, simulation_ready


def plan(model, sdk, config):
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1] / "references/economizer.schema.json"
        ).read_text()
    )
    errors = validate(config, schema)
    if errors:
        raise ValueError("Invalid economizer configuration: " + "; ".join(errors))
    planned = dict(
        ready=False,
        parameters=dict(output_model_path=config["output_model_path"]),
        missing_inputs=[k for k in ("air_loop", "economizer") if k not in config],
        errors=[],
        warnings=[],
        assumptions=[],
    )
    if planned["missing_inputs"]:
        return planned
    if not config["economizer"]:
        planned["missing_inputs"].append("economizer: at least one explicit setting")
        return planned
    selected = resolve(
        config["air_loop"], inventory(model)["air_loops"], "air_loop", planned["errors"]
    )
    if selected is None:
        return planned
    if selected["split_supply"] or selected["controller"] is None:
        planned["errors"].append(
            "Select an unsplit air loop with an existing direct outdoor-air system"
        )
        return planned
    loop = by_handle(model, sdk, selected, "AirLoopHVAC")
    system = loop.airLoopHVACOutdoorAirSystem().get()
    controller = system.getControllerOutdoorAir()
    owners = [
        x
        for x in model.getAirLoopHVACOutdoorAirSystems()
        if x.getControllerOutdoorAir().handle() == controller.handle()
    ]
    if (
        system.airLoopHVACDedicatedOutdoorAirSystem().is_initialized()
        or len(owners) != 1
        or not system.airLoopHVAC().is_initialized()
        or system.airLoopHVAC().get().handle() != loop.handle()
    ):
        planned["errors"].append(
            "Shared/dedicated or incorrectly owned OA controllers require separate coverage"
        )
        return planned
    before = values(controller)
    patch = config["economizer"]
    after = dict(before, **patch)
    planned["errors"].extend(check_effective(controller, after))
    if before == after:
        planned["errors"].append("Edit must change at least one economizer setting")
    if planned["errors"]:
        return planned
    current = context(loop, controller, sdk)
    warnings, simulation_ready = warnings_for(controller, after, current)
    preview = sdk.model.Model(model.clone(True))
    preview_controller = by_handle(
        preview, sdk, ref(controller), "ControllerOutdoorAir"
    )
    set_settings(preview_controller, patch)
    current["mixed_air_control"] = mixed_air_control(preview, sdk, preview_controller)
    if (
        current["mixed_air_control"] is not None
        and not current["mixed_air_control"]["temperature_setpoint_verified"]
    ):
        warnings.append(
            "Enabled economizer has no verified translated Temperature setpoint manager on mixed-air node "
            + current["mixed_air_control"]["mixed_air_node"]
            + "; simulation is not ready. Provide a temperature setpoint or separately verify custom/EMS control; this edit adds no managers"
        )
        simulation_ready = False
    fields = [FIELDS[k][1] for k in patch]
    planned.update(
        ready=True,
        simulation_ready=simulation_ready,
        parameters=dict(planned["parameters"], economizer=patch),
        resolved_objects=dict(
            air_loop=ref(loop), oa_system=ref(system), controller=ref(controller)
        ),
        before_values=before,
        after_values=after,
        retained_context=current,
        protected_objects=snapshot(model, ignored={str(controller.handle()): fields}),
        supply_order=[str(x.handle()) for x in loop.supplyComponents()],
        warnings=warnings,
        assumptions=[
            "Only explicitly requested economizer fields change on the existing controller; no default profile or template policy applied"
        ],
        impact=dict(
            air_loop=ref(loop),
            controller=ref(controller),
            affected_zone_count=selected["zone_count"],
            before=before,
            after=after,
            retained_ventilation=dict(
                current,
                cooling_components=current["cooling_components"][:8],
                cooling_component_count=len(current["cooling_components"]),
            ),
            identity_policy="Preserve controller, OA system, MV, nodes, connections, metadata and references",
            sizing_policy="Preserve; run sizing/simulation separately",
        ),
    )
    return planned


def edit(model, sdk, planned):
    controller = by_handle(
        model, sdk, planned["resolved_objects"]["controller"], "ControllerOutdoorAir"
    )
    set_settings(controller, planned["parameters"]["economizer"])
    return dict(
        controller=ref(controller),
        before=planned["before_values"],
        after=values(controller),
    )


def validate_model(model, sdk, planned, result):
    r = planned["resolved_objects"]
    controller = by_handle(model, sdk, r["controller"], "ControllerOutdoorAir")
    loop = by_handle(model, sdk, r["air_loop"], "AirLoopHVAC")
    fields = [FIELDS[k][1] for k in planned["parameters"]["economizer"]]
    retained = context(loop, controller, sdk)
    retained["mixed_air_control"] = mixed_air_control(model, sdk, controller)
    checks = {
        "Controller settings differ": settings_match(
            values(controller), planned["after_values"]
        ),
        "Controller identity/name changed": ref(controller) == r["controller"],
        "Reported result differs": result["controller"] == r["controller"]
        and settings_match(result["before"], planned["before_values"])
        and settings_match(result["after"], planned["after_values"]),
        "Protected objects, fields or connections changed": snapshot(
            model, ignored={str(controller.handle()): fields}
        )
        == planned["protected_objects"],
        "Outdoor-air system/ownership changed": loop.airLoopHVACOutdoorAirSystem().is_initialized()
        and ref(loop.airLoopHVACOutdoorAirSystem().get()) == r["oa_system"]
        and loop.airLoopHVACOutdoorAirSystem().get().getControllerOutdoorAir().handle()
        == controller.handle(),
        "Supply equipment order changed": [
            str(x.handle()) for x in loop.supplyComponents()
        ]
        == planned["supply_order"],
        "Ventilation, schedules, sizing or translated control context changed": retained
        == planned["retained_context"],
    }
    return dict(
        ok=all(checks.values()),
        checks=len(checks),
        errors=[key for key, ok in checks.items() if not ok],
    )
