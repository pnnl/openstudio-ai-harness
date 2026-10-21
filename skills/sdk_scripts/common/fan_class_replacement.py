"""Reviewed constant/variable supply-fan class changes with retained air nodes."""

from collections import Counter
from copy import deepcopy
import json
import math
import re
from pathlib import Path

from common.input_validation import validate
from common.hvac_inventory import resolve
from common.fan_edit import inventory, fan_object, ports, ref, values
from common.fan_equipment import pressure_pa, set_performance
from common.hvac_equipment import call
from common.water_coil import raw_fields, original_types, object_by_ref
from common.coil_topology import freeze, connection_graph, protected_state

SHARED_FAN_OUTPUTS = frozenset(
    name.casefold()
    for name in (
        "Fan Electricity Rate",
        "Fan Electricity Energy",
        "Fan Rise in Air Temperature",
        "Fan Heat Gain to Air",
        "Fan Air Mass Flow Rate",
    )
)


def retained_output_fields(obj, fan_ref):
    """Exempt compatible name keys, never pointers to the removed fan object."""
    kind = obj.iddObjectType().valueName()
    fields = raw_fields(obj)
    allowed = {}
    for i, (name, value) in fields.items():
        if value.casefold() != fan_ref["name"].casefold():
            continue
        variable = fields.get(i + 1, ("", ""))[1]
        if (
            kind == "OS_Output_Variable"
            and name == "Key Value"
            and variable.casefold() in SHARED_FAN_OUTPUTS
            or kind in ("OS_Meter_Custom", "OS_Meter_CustomDecrement")
            and name == "Key Name"
            and variable.casefold() == "fan electricity energy"
        ):
            allowed[i] = dict(field_index=i, key=value, variable=variable)
    return allowed


def retained_output_references(model, fan_ref):
    kept = []
    for obj in model.modelObjects():
        fields = retained_output_fields(obj, fan_ref)
        if fields:
            kept.append(dict(object=ref(obj), keys=list(fields.values())))
    meter_names = {
        item["object"]["name"].casefold()
        for item in kept
        if item["object"]["type"] in ("OS_Meter_Custom", "OS_Meter_CustomDecrement")
    }
    for meter in model.getOutputMeters():
        if meter.nameString().casefold() in meter_names:
            kept.append(dict(object=ref(meter), meter_name=meter.nameString()))
    return sorted(kept, key=lambda x: (x["object"]["type"], x["object"]["handle"]))


def polynomial(coefficients, x):
    value = 0.0
    for coefficient in reversed(coefficients):
        value = value * x + coefficient
    return value


def roots_in_unit_interval(coefficients):
    """Isolate real polynomial roots using derivative intervals and bisection."""
    c = list(coefficients)
    while c and c[-1] == 0:
        c.pop()
    if len(c) <= 1:
        return []
    derivative = [i * c[i] for i in range(1, len(c))]
    bounds = [0.0, *roots_in_unit_interval(derivative), 1.0]
    roots = [x for x in bounds if abs(polynomial(c, x)) < 1e-12]
    for left, right in zip(bounds, bounds[1:]):
        if polynomial(c, left) * polynomial(c, right) >= 0:
            continue
        for _ in range(60):
            middle = (left + right) / 2
            if polynomial(c, left) * polynomial(c, middle) <= 0:
                right = middle
            else:
                left = middle
        roots.append((left + right) / 2)
    return sorted(set(roots))


def curve_errors(curve):
    c = curve["power_coefficients"]
    if len(c) != 5:
        return ["Variable-volume power curve requires exactly five coefficients"]
    # Bound coefficients as well as values so evaluation cannot overflow in SDK.
    if any(abs(x) > 1e6 for x in c):
        return ["Power-curve coefficient magnitude must not exceed 1e6"]
    extrema = [0.0, 1.0, *roots_in_unit_interval([i * c[i] for i in range(1, 5)])]
    powers = [polynomial(c, x) for x in extrema]
    if (
        min(powers) < -1e-9
        or max(powers) > 1.01
        or not math.isclose(sum(c), 1, abs_tol=0.01)
    ):
        return [
            "Power curve must stay between zero and 1.01 over flow fractions 0–1 and equal 1 at full flow within 0.01"
        ]
    return []


def translated_controls(model, sdk):
    """Freeze all translated temperature control fields, including MixedAir."""
    translator = sdk.energyplus.ForwardTranslator()
    workspace = translator.translateModel(model)
    if translator.errors():
        raise ValueError(
            "Cannot verify translated controls: "
            + "; ".join(x.logMessage() for x in translator.errors())
        )
    return sorted(
        [
            obj.iddObject().name(),
            [
                obj.getString(i).get() if obj.getString(i).is_initialized() else ""
                for i in range(1, obj.numFields())
            ],
        ]
        for obj in workspace.objects()
        if obj.iddObject().name().startswith(("SetpointManager:", "NodeList"))
    )


def fan_settings(fan):
    result = dict(
        values(fan),
        motor_in_airstream_fraction=fan.motorInAirstreamFraction(),
        end_use_subcategory=fan.endUseSubcategory(),
        maximum_flow_m3_s=(
            "Autosize"
            if fan.isMaximumFlowRateAutosized()
            else fan.maximumFlowRate().get()
        ),
    )
    if fan.iddObjectType().valueName() == "OS_Fan_VariableVolume":
        result["variable_volume"] = dict(
            minimum_power_flow_fraction=fan.fanPowerMinimumFlowFraction(),
            power_coefficients=[
                getattr(fan, "fanPowerCoefficient" + str(i))().get()
                for i in range(1, 6)
            ],
            input_method=fan.fanPowerMinimumFlowRateInputMethod(),
            minimum_power_air_flow_m3_s=fan.fanPowerMinimumAirFlowRate().get(),
        )
    return result


def settings_match(actual, expected):
    """Permit only insignificant numeric changes from OSM serialization."""
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and actual.keys() == expected.keys()
            and all(settings_match(actual[k], v) for k, v in expected.items())
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(settings_match(a, b) for a, b in zip(actual, expected))
        )
    if type(expected) in (int, float):
        return type(actual) in (int, float) and math.isclose(
            actual, expected, rel_tol=1e-9, abs_tol=1e-9
        )
    return actual == expected


def plan(model, sdk, config):
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "references/fan_replacement.schema.json"
        ).read_text()
    )
    errors = validate(config, schema)
    if errors:
        raise ValueError("Invalid fan replacement configuration: " + "; ".join(errors))
    missing = [
        x
        for x in (
            "air_loop",
            "target_class",
            "fan",
            "sizing",
            "terminal_policy",
            "system_sizing_policy",
            "reference_policy",
        )
        if x not in config
    ]
    parameters = dict(output_model_path=config["output_model_path"])
    planned = dict(
        ready=False,
        parameters=parameters,
        missing_inputs=missing,
        errors=[],
        warnings=[],
        assumptions=[],
    )
    if missing:
        return planned
    missing.extend(
        "fan." + x
        for x in (
            "total_efficiency",
            "motor_efficiency",
            "pressure_rise",
            "pressure_units",
        )
        if x not in config["fan"]
    )
    if config["target_class"] == "VariableVolume":
        missing.extend(
            "variable_volume." + x
            for x in ("minimum_power_flow_fraction", "power_coefficients")
            if x not in config.get("variable_volume", {})
        )
    elif "variable_volume" in config:
        planned["errors"].append(
            "Constant-volume target must not include a variable-volume curve"
        )
    if missing or planned["errors"]:
        return planned
    selected = resolve(
        config["air_loop"], inventory(model)["air_loops"], "air_loop", planned["errors"]
    )
    if selected is None:
        return planned
    supported = {"OS_Fan_ConstantVolume", "OS_Fan_VariableVolume"}
    if (
        selected["split_supply"]
        or len(selected["fans"]) != 1
        or selected["fans"][0]["type"] not in supported
    ):
        planned["errors"].append(
            "Select an unsplit air loop with exactly one direct constant- or variable-volume supply fan"
        )
        return planned
    old_ref = selected["fans"][0]
    target_type = "OS_Fan_" + config["target_class"]
    if old_ref["type"] == target_type:
        planned["errors"].append(
            "Same-class changes use openstudio-supply-fan-performance-editor"
        )
        return planned
    fan = fan_object(model, sdk, old_ref)
    loop = object_by_ref(model, sdk, selected, "AirLoopHVAC")
    if (
        not fan.airLoopHVAC().is_initialized()
        or fan.airLoopHVAC().get().handle() != loop.handle()
    ):
        raise ValueError("Selected fan is not directly owned by the air loop")
    patch = dict(config["fan"])
    patch["pressure_rise_pa"] = pressure_pa(
        patch.pop("pressure_rise"), patch.pop("pressure_units")
    )
    if not 0 < patch["total_efficiency"] <= patch["motor_efficiency"] <= 1:
        planned["errors"].append(
            "Fan total efficiency must not exceed motor efficiency"
        )
    curve = deepcopy(config.get("variable_volume"))
    if curve:
        planned["errors"].extend(curve_errors(curve))
    if planned["errors"]:
        return planned
    boundary = ports(fan)
    metadata = next(
        (
            ref(x)
            for x in model.modelObjects()
            if x.iddObjectType().valueName() == "OS_AdditionalProperties"
            and dict(raw_fields(x).values()).get("Object Name") == old_ref["handle"]
        ),
        None,
    )
    for obj in model.modelObjects():
        handle, kind = str(obj.handle()), obj.iddObjectType().valueName()
        if handle == old_ref["handle"] or kind == "OS_Connection":
            continue
        allowed_keys = retained_output_fields(obj, old_ref)
        if any(
            name != "Handle"
            and not (
                metadata and handle == metadata["handle"] and name == "Object Name"
            )
            and (
                value == old_ref["handle"]
                or name != "Name"
                and i not in allowed_keys
                and value.casefold() == old_ref["name"].casefold()
            )
            for i, (name, value) in raw_fields(obj).items()
        ):
            planned["errors"].append(
                "Reference policy Reject: external reference to removed fan: "
                + obj.nameString()
            )
    if planned["errors"]:
        return planned
    before = fan_settings(fan)
    after = dict(
        patch,
        motor_in_airstream_fraction=before["motor_in_airstream_fraction"],
        end_use_subcategory=config.get(
            "end_use_subcategory", before["end_use_subcategory"]
        ),
        maximum_flow_m3_s="Autosize",
    )
    if curve:
        after["variable_volume"] = dict(
            curve, input_method="Fraction", minimum_power_air_flow_m3_s=0.0
        )
    terminals = [
        ref(x)
        for x in loop.demandComponents()
        if x.iddObjectType().valueName().startswith("OS_AirTerminal_")
    ]
    planned.update(
        parameters=dict(
            parameters,
            target_class=config["target_class"],
            fan=patch,
            variable_volume=curve,
            sizing="Autosize",
            terminal_policy="Preserve",
            system_sizing_policy="Preserve",
            reference_policy="Reject",
        ),
        resolved_objects=dict(
            air_loop=ref(loop), fan=old_ref, ports=boundary, metadata=metadata
        ),
        before_values=before,
        after_values=after,
        supply_order=[str(x.handle()) for x in loop.supplyComponents()],
        before_controls=translated_controls(model, sdk),
        preserved_terminals=terminals,
        retained_output_references=retained_output_references(model, old_ref),
    )
    preview = sdk.model.Model(model.clone(True))
    result = replace(preview, sdk, planned)
    planned["after_controls"] = translated_controls(preview, sdk)
    if planned["after_controls"] != planned["before_controls"]:
        planned["errors"].append(
            "Replacement changes translated setpoint control; separate coverage required"
        )
        return planned
    allowed = {h: ["Inlet Port", "Outlet Port"] for h in boundary}
    if metadata:
        allowed[metadata["handle"]] = ["Object Name"]
    planned.update(
        freeze(
            model,
            preview,
            sdk,
            allowed=allowed,
            removable={old_ref["handle"]},
            connection_scope={old_ref["handle"], *boundary},
            tokens={result["replacement_fan"]["handle"]: "@replacement-fan"},
            new_types=(target_type, "OS_Connection"),
        )
    )
    planned["impact"] = dict(
        air_loop=ref(loop),
        affected_zone_count=selected["zone_count"],
        old_fan=old_ref,
        target_class=config["target_class"],
        new_fan_identity=True,
        before=before,
        after=after,
        air_nodes_retained=boundary,
        availability_schedule=ref(fan.availabilitySchedule()),
        terminal_policy="Preserve",
        terminal_count=len(terminals),
        terminal_types=dict(Counter(x["type"] for x in terminals)),
        terminal_details="plan.preserved_terminals",
        system_sizing_policy="Preserve",
        temperature_control="Preserve translated setpoint control and fan boundary nodes",
        metadata_retained=metadata,
        retained_output_reference_count=len(planned["retained_output_references"]),
        retained_output_references=planned["retained_output_references"][:8],
        output_reference_details="plan.retained_output_references",
        end_use_subcategory_policy=(
            "Explicit" if "end_use_subcategory" in config else "Preserve"
        ),
        airflow_behavior=dict(
            control="Retained terminal and air-system airflow controls",
            enforces_constant_airflow=False,
            fan_power_model=(
                "Linear with terminal-driven flow at fixed pressure/efficiency"
                if config["target_class"] == "ConstantVolume"
                else "Polynomial with the chosen minimum-power flow floor"
            ),
            description=(
                "Changing fan class does not enforce constant airflow. Existing terminals can continue to vary flow; the constant-volume fan follows that requested flow with proportional power."
                if config["target_class"] == "ConstantVolume"
                else "Existing terminal airflow controls remain; the selected fan power curve changes power behavior, not terminal minimum airflow."
            ),
        ),
    )
    planned["warnings"] = [
        "Replacing the fan changes its identity and part-load power behavior. Existing terminals, minimum flows, outdoor-air controls, system sizing and zone assignments are retained; this is not a whole-system VAV/CAV conversion. Run sizing and simulation separately.",
        "Fan maximum flow is reset to Autosize; review existing system/terminal sizing before simulation.",
    ]
    if before.get("variable_volume") and curve is None:
        planned["warnings"].append(
            "The variable-volume part-load power curve is removed; constant-volume fan power behavior applies even though terminal airflow controls are retained."
        )
    if "end_use_subcategory" not in config:
        pattern = (
            r"\b(?:CAV|constant[- ]volume)\b"
            if old_ref["type"] == "OS_Fan_ConstantVolume"
            else r"\b(?:VAV|variable[- ]volume)\b"
        )
        if re.search(pattern, before["end_use_subcategory"], re.IGNORECASE):
            planned["warnings"].append(
                f"Retained end-use subcategory '{before['end_use_subcategory']}' names the old fan/system type; use explicit end_use_subcategory to choose a new reporting label."
            )
    if after["end_use_subcategory"] != before["end_use_subcategory"]:
        planned["warnings"].append(
            "Changing the end-use subcategory changes subcategory meter names; review any corresponding meter requests separately. Fan-name keyed outputs and custom meters remain intact."
        )
    planned["ready"] = True
    return planned


def replace(model, sdk, planned):
    r, p = planned["resolved_objects"], planned["parameters"]
    old = fan_object(model, sdk, r["fan"])
    new = getattr(sdk.model, "Fan" + p["target_class"])(
        model, old.availabilitySchedule()
    )
    set_performance(new, p["fan"])
    call(
        new,
        "setMotorInAirstreamFraction",
        planned["after_values"]["motor_in_airstream_fraction"],
    )
    call(new, "setEndUseSubcategory", planned["after_values"]["end_use_subcategory"])
    new.autosizeMaximumFlowRate()
    if p["variable_volume"]:
        curve = p["variable_volume"]
        call(new, "setFanPowerMinimumFlowRateInputMethod", "Fraction")
        call(
            new, "setFanPowerMinimumFlowFraction", curve["minimum_power_flow_fraction"]
        )
        call(new, "setFanPowerMinimumAirFlowRate", 0.0)
        for i, value in enumerate(curve["power_coefficients"], 1):
            call(new, "setFanPowerCoefficient" + str(i), value)
    inlet, outlet = [
        object_by_ref(model, sdk, {"handle": h}, "Node") for h in r["ports"]
    ]
    model.disconnect(old, old.inletPort())
    model.disconnect(old, old.outletPort())
    model.connect(inlet, inlet.outletPort(), new, new.inletPort())
    model.connect(new, new.outletPort(), outlet, outlet.inletPort())
    if r["metadata"]:
        call(
            object_by_ref(model, sdk, r["metadata"], "AdditionalProperties"),
            "setPointer",
            1,
            new.handle(),
        )
    old.remove()
    call(new, "setName", r["fan"]["name"])
    return deepcopy(
        dict(
            air_loop=r["air_loop"],
            removed_fan=r["fan"],
            replacement_fan=ref(new),
            air_nodes=r["ports"],
        )
    )


def validate_model(model, sdk, planned, result):
    errors, checks = [], 0

    def check(ok, message):
        nonlocal checks
        checks += 1
        if not ok:
            errors.append(message)

    r = planned["resolved_objects"]
    fan = fan_object(model, sdk, result["replacement_fan"])
    after = fan_settings(fan)
    check(
        ref(fan) == result["replacement_fan"]
        and str(fan.handle()) not in planned["before_objects"],
        "Replacement fan identity differs",
    )
    check(
        fan.iddObjectType().valueName()
        == "OS_Fan_" + planned["parameters"]["target_class"],
        "Wrong fan class",
    )
    check(
        settings_match(after, planned["after_values"]),
        "Fan performance/flow/curve differs from reviewed values",
    )
    check(fan.nameString() == r["fan"]["name"], "Fan name changed")
    loop = object_by_ref(model, sdk, r["air_loop"], "AirLoopHVAC")
    check(
        fan.airLoopHVAC().is_initialized()
        and fan.airLoopHVAC().get().handle() == loop.handle(),
        "Fan ownership differs",
    )
    check(ports(fan) == r["ports"], "Fan air boundary nodes changed")
    check(
        [str(x.handle()) for x in loop.supplyComponents()]
        == [
            str(fan.handle()) if h == r["fan"]["handle"] else h
            for h in planned["supply_order"]
        ],
        "Supply component order changed",
    )
    current, before = original_types(model), planned["before_objects"]
    check(
        sorted(before.keys() - current.keys()) == planned["removed_objects"],
        "Unexpected removed objects",
    )
    check(
        dict(Counter(current[h] for h in current.keys() - before.keys()))
        == planned["added_counts"],
        "Unexpected added objects",
    )
    check(protected_state(model, sdk, planned), "Protected model objects changed")
    check(
        connection_graph(model, {str(fan.handle()): "@replacement-fan"})
        == planned["connection_graph"],
        "Connection graph differs",
    )
    check(
        translated_controls(model, sdk)
        == planned["before_controls"]
        == planned["after_controls"],
        "Translated controls changed",
    )
    # Availability and metadata owner are intentionally outside the protected set.
    check(
        ref(fan.availabilitySchedule()) == planned["impact"]["availability_schedule"],
        "Fan availability schedule changed",
    )
    check(
        retained_output_references(model, ref(fan))
        == planned["retained_output_references"],
        "Retained output references differ from the reviewed plan",
    )
    if r["metadata"]:
        check(
            dict(
                raw_fields(
                    object_by_ref(model, sdk, r["metadata"], "AdditionalProperties")
                ).values()
            )["Object Name"]
            == str(fan.handle()),
            "Fan metadata owner differs",
        )
    check(
        result
        == dict(
            air_loop=r["air_loop"],
            removed_fan=r["fan"],
            replacement_fan=ref(fan),
            air_nodes=r["ports"],
        ),
        "Reported fan mapping differs",
    )
    return dict(ok=not errors, checks=checks, errors=errors)
