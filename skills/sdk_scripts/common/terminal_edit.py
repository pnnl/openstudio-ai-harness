"""In-place single-zone VAV terminal controls; no equipment or branch rewiring."""

from __future__ import annotations
import json
import math
from pathlib import Path
from common.input_validation import validate
from common.hvac_inventory import resolve
from common.model_preservation import fingerprint, snapshot
from common.ventilation_context import (
    schedule_bounds,
    stable_evidence,
    zone_requirements,
)

SUPPORTED = {
    "OS_AirTerminal_SingleDuct_VAV_Reheat": "AirTerminalSingleDuctVAVReheat",
    "OS_AirTerminal_SingleDuct_VAV_NoReheat": "AirTerminalSingleDuctVAVNoReheat",
}
# Input key -> SDK getter/setter suffix and raw IDD field. Explicit settings only.
FIELDS = {
    "minimum_airflow_fraction": (
        "constantMinimumAirFlowFraction",
        "ConstantMinimumAirFlowFraction",
        "Constant Minimum Air Flow Fraction",
    ),
    "damper_heating_action": (
        "damperHeatingAction",
        "DamperHeatingAction",
        "Damper Heating Action",
    ),
    "maximum_reheat_temperature_c": (
        "maximumReheatAirTemperature",
        "MaximumReheatAirTemperature",
        "Maximum Reheat Air Temperature",
    ),
    "maximum_reheat_flow_fraction": (
        "maximumFlowFractionDuringReheat",
        "MaximumFlowFractionDuringReheat",
        "Maximum Flow Fraction During Reheat",
    ),
    "maximum_reheat_flow_per_area_m3_s_m2": (
        "maximumFlowPerZoneFloorAreaDuringReheat",
        "MaximumFlowPerZoneFloorAreaDuringReheat",
        "Maximum Flow per Zone Floor Area During Reheat",
    ),
}
REHEAT = set(FIELDS) - {"minimum_airflow_fraction"}
FLOW_LIMITS = {"maximum_reheat_flow_fraction", "maximum_reheat_flow_per_area_m3_s_m2"}


def ref(obj):
    return dict(
        handle=str(obj.handle()),
        name=obj.nameString(),
        type=obj.iddObjectType().valueName(),
    )


def optional(value):
    if hasattr(value, "is_initialized"):
        return value.get() if value.is_initialized() else None
    return value


def sized(obj, getter):
    method = "is" + getter[0].upper() + getter[1:] + "Autosized"
    if hasattr(obj, method) and getattr(obj, method)():
        return "Autosize"
    return optional(getattr(obj, getter)())


def typed(model, sdk, reference):
    obj = model.getModelObject(sdk.toUUID(reference["handle"]))
    if (
        not obj.is_initialized()
        or obj.get().iddObjectType().valueName() != reference["type"]
    ):
        raise ValueError("Selected terminal is missing or its class changed")
    return getattr(obj.get(), "to_" + SUPPORTED[reference["type"]])().get()


def inventory(model):
    rows = []
    for zone in model.getThermalZones():
        for item in zone.airLoopHVACTerminals():
            loop = item.airLoopHVAC()
            if loop.is_initialized():
                rows.append(
                    dict(
                        ref(item),
                        zone=ref(zone),
                        air_loop=ref(loop.get()),
                        supported=item.iddObjectType().valueName() in SUPPORTED,
                    )
                )
    return dict(
        terminals=sorted(
            rows,
            key=lambda x: (
                x["air_loop"]["name"],
                x["zone"]["name"],
                x["name"],
                x["handle"],
            ),
        )
    )


def values(terminal):
    return {
        key: sized(terminal, getter)
        for key, (getter, _, _) in FIELDS.items()
        if hasattr(terminal, getter)
    }


def ports(terminal):
    result = []
    for port in (terminal.inletModelObject(), terminal.outletModelObject()):
        if not port.is_initialized() or not port.get().to_Node().is_initialized():
            raise ValueError(
                "Selected terminal must have connected inlet and outlet nodes"
            )
        result.append(str(port.get().handle()))
    return result


def signature(terminal, patch):
    return fingerprint(terminal, ignored=[FIELDS[key][2] for key in patch])


def matches(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(matches(a[k], b[k]) for k in a)
    if type(a) in (int, float) and type(b) in (int, float):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return a == b


def context(model, terminal, loop, zone):
    schedules = {}
    for name in (
        "availabilitySchedule",
        "minimumAirFlowFractionSchedule",
        "minimumAirFlowTurndownSchedule",
    ):
        schedule = optional(getattr(terminal, name)())
        schedules[name] = schedule_bounds(schedule) if schedule else None
    coil = terminal.to_AirTerminalSingleDuctVAVReheat()
    coil = coil.get().reheatCoil() if coil.is_initialized() else None
    oa = loop.airLoopHVACOutdoorAirSystem()
    controller = oa.get().getControllerOutdoorAir() if oa.is_initialized() else None
    zone_oa = next(
        x
        for x in zone_requirements(loop)["zones"]
        if x["zone"]["handle"] == str(zone.handle())
    )
    targets = {str(terminal.handle())} | ({str(coil.handle())} if coil else set())
    ems = []
    for actuator in model.getEnergyManagementSystemActuators():
        component = actuator.actuatedComponent()
        if component.is_initialized() and str(component.get().handle()) in targets:
            ems.append(ref(actuator))
    return stable_evidence(
        dict(
            minimum_method=optional(terminal.zoneMinimumAirFlowInputMethod()),
            maximum_airflow_m3_s=sized(terminal, "maximumAirFlowRate"),
            fixed_minimum_airflow_m3_s=sized(terminal, "fixedMinimumAirFlowRate"),
            control_for_outdoor_air=terminal.controlForOutdoorAir(),
            schedules=schedules,
            reheat_coil=ref(coil) if coil else None,
            zone_ventilation=zone_oa,
            oa_controller=(
                dict(
                    ref(controller),
                    minimum_flow_m3_s=sized(controller, "minimumOutdoorAirFlowRate"),
                    maximum_flow_m3_s=sized(controller, "maximumOutdoorAirFlowRate"),
                    dcv=controller.controllerMechanicalVentilation().demandControlledVentilation(),
                )
                if controller
                else None
            ),
            ems_actuators=sorted(ems, key=lambda x: x["handle"]),
            served_air_loop_count=len(zone.airLoopHVACs()),
            zone_multiplier=zone.multiplier(),
            floor_area_per_copy_m2=zone.floorArea(),
            multiplied_floor_area_m2=zone.floorArea() * zone.multiplier(),
        )
    )


def reheat_limit_effect(values, info):
    """Pinned E+ 25.2 SizeSys behavior, not the intended two-input maximum."""
    action = values.get("damper_heating_action")
    area = values.get("maximum_reheat_flow_per_area_m3_s_m2")
    fraction = values.get("maximum_reheat_flow_fraction")
    maximum = info["maximum_airflow_m3_s"]
    floor = values["minimum_airflow_fraction"]
    result = dict(
        mode="inactive",
        nominal_cap_m3_s=None,
        nominal_cap_fraction=None,
        requested_per_area_flow_m3_s=(
            area * info["multiplied_floor_area_m2"]
            if type(area) in (int, float)
            else None
        ),
        flow_basis="Terminal flow and zone OA include zone multiplier once; area includes the same multiplier",
        cap_basis="Nominal sizing bound before retained schedule, outdoor-air and operating overrides",
    )
    if action != "ReverseWithLimits":
        return result
    if area != "Autosize":
        result["mode"] = "user_limits_ignored_by_pinned_engine"
    elif type(fraction) in (int, float):
        result["mode"] = "fraction_only"
        if info["minimum_method"] == "Constant" and type(floor) in (int, float):
            result["nominal_cap_fraction"] = max(fraction, floor)
            if type(maximum) in (int, float):
                result["nominal_cap_m3_s"] = maximum * result["nominal_cap_fraction"]
    else:
        result["mode"] = "design_calculated"
    return result


def plan(model, sdk, config):
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1] / "references/terminal_edit.schema.json"
        ).read_text()
    )
    errors = validate(config, schema)
    if errors:
        raise ValueError(f"Invalid terminal edit configuration: {errors}")
    planned = dict(
        ready=False,
        parameters=dict(output_model_path=config["output_model_path"]),
        missing_inputs=[
            k for k in ("air_loop", "zone", "terminal", "settings") if not config.get(k)
        ],
        errors=[],
        warnings=[],
        assumptions=[],
    )
    if planned["missing_inputs"]:
        return planned
    rows = inventory(model)["terminals"]
    for selector, key in (
        ("air_loop", "air_loop"),
        ("zone", "zone"),
        ("terminal", None),
    ):
        candidates = (
            {x[key]["handle"]: x[key] for x in rows}
            if key
            else {x["handle"]: x for x in rows}
        )
        selected = resolve(
            config[selector], list(candidates.values()), selector, planned["errors"]
        )
        if selected is None:
            return planned
        rows = [
            x
            for x in rows
            if (x[key]["handle"] if key else x["handle"]) == selected["handle"]
        ]
    if len(rows) != 1 or not rows[0]["supported"]:
        planned["errors"].append(
            "Select one connected VAVReheat or VAVNoReheat terminal on the specified zone and air loop"
        )
        return planned
    row = rows[0]
    terminal = typed(model, sdk, row)
    loop = model.getAirLoopHVAC(sdk.toUUID(row["air_loop"]["handle"])).get()
    zone = model.getThermalZone(sdk.toUUID(row["zone"]["handle"])).get()
    patch = dict(config["settings"])
    before = values(terminal)
    after = dict(before, **patch)
    info = context(model, terminal, loop, zone)
    errors, warnings = planned["errors"], planned["warnings"]
    if "minimum_airflow_fraction" in patch and info["minimum_method"] != "Constant":
        errors.append(
            "Minimum-fraction editing requires existing Constant method; FixedFlowRate/Scheduled method changes need separate coverage"
        )
    if REHEAT & patch.keys() and info["reheat_coil"] is None:
        errors.append("Reheat controls do not apply to a no-reheat terminal")
    coil_kind = (info["reheat_coil"] or {}).get("type")
    if REHEAT & patch.keys() and coil_kind not in {
        "OS_Coil_Heating_Water",
        "OS_Coil_Heating_Electric",
        "OS_Coil_Heating_Gas",
    }:
        errors.append(
            "Reheat control edits support existing water, electric or gas heating coils only"
        )
    action = after.get("damper_heating_action")
    if (
        "damper_heating_action" in patch
        and action != "Normal"
        and coil_kind != "OS_Coil_Heating_Water"
    ):
        errors.append(
            "Reverse damper action is supported here only with water reheat; it is not a fuel conversion"
        )
    if FLOW_LIMITS & patch.keys() and (
        action != "ReverseWithLimits" or coil_kind != "OS_Coil_Heating_Water"
    ):
        errors.append(
            "Reheat airflow-limit edits require water reheat with effective ReverseWithLimits damper action"
        )
    limits = dict(
        before=reheat_limit_effect(before, info), after=reheat_limit_effect(after, info)
    )
    planned["impact"] = dict(
        terminal=terminal.nameString(),
        zone=zone.nameString(),
        air_loop=loop.nameString(),
        reheat_flow_limits=limits,
    )
    if FLOW_LIMITS & patch.keys() and limits["after"]["mode"] != "fraction_only":
        errors.append(
            'EnergyPlus 25.2 ignores numeric per-area reheat limits, including 0, and the fraction when per-area is numeric. An effective fraction edit requires maximum_reheat_flow_per_area_m3_s_m2: "Autosize" and a numeric maximum_reheat_flow_fraction. Request the reset explicitly; it is never inferred'
        )
    if matches(before, after):
        errors.append("Edit must change at least one setting")
    if errors:
        return planned
    maximum = info["maximum_airflow_m3_s"]
    fraction = after["minimum_airflow_fraction"]
    minimum = (
        maximum * fraction
        if type(maximum) in (float, int)
        and type(fraction) in (float, int)
        and info["minimum_method"] == "Constant"
        else None
    )
    if info["minimum_method"] != "Constant":
        warnings.append(
            "Existing minimum-flow method is retained; constant fraction is inactive"
        )
    if info["schedules"]["minimumAirFlowTurndownSchedule"]:
        warnings.append(
            "Retained turndown schedule scales minimum airflow; requested fraction alone is not the effective operating floor"
        )
    if info["schedules"]["minimumAirFlowFractionSchedule"]:
        warnings.append(
            "Retained minimum fraction schedule applies only under Scheduled method; this edit does not change the method or schedule"
        )
    if info["ems_actuators"]:
        warnings.append(
            "Retained terminal/reheat EMS actuators can override operation; their handles and programs are preserved"
        )
    if info["served_air_loop_count"] > 1:
        warnings.append(
            "Zone has multiple serving air loops; the selected terminal alone does not establish combined ventilation or conditioning"
        )
    if minimum is None:
        warnings.append(
            "Design/minimum terminal flow cannot be established before sizing or for this retained method; re-run sizing and check ventilation"
        )
    nominal = info["zone_ventilation"]["nominal_oa_m3_s"]
    if minimum is not None and minimum < nominal - 1e-9:
        warnings.append(
            "Nominal minimum supply floor is below nominal zone outdoor-air demand; actual airflow may be raised by OA/load controls. Verify ventilation rather than treating this floor as the delivered flow"
        )
    if type(maximum) in (int, float) and maximum < nominal - 1e-9:
        warnings.append(
            "Selected terminal maximum supply flow is below nominal zone outdoor-air demand even at 100% OA. This path alone cannot supply that demand; review sizing and any alternate ventilation sources before simulation"
        )
        planned["simulation_ready"] = False
    warnings.append(
        "Minimum terminal supply-air fraction is not outdoor-air fraction. Retained OA/DCV, zone OA schedules, occupancy, system minimums and sizing can alter required flow; no ventilation or energy-saving claim is made"
    )
    if info["oa_controller"]:
        if info["oa_controller"]["dcv"] or info["control_for_outdoor_air"]:
            warnings.append(
                "Retained outdoor-air/DCV controls may raise terminal airflow above the requested minimum"
            )
    elif nominal > 0:
        warnings.append(
            "No direct air-loop OA system is present; nominal zone ventilation must be provided and checked separately"
        )
    if info["reheat_coil"]:
        if action != "ReverseWithLimits":
            warnings.append(
                "Reheat flow-fraction/per-area limits are inactive unless damper action is ReverseWithLimits; retained values are not removed"
            )
        else:
            effect = limits["after"]
            if effect["mode"] == "user_limits_ignored_by_pinned_engine":
                warnings.append(
                    'Pre-existing numeric per-area reheat input (including 0) makes EnergyPlus 25.2 ignore the user reheat-flow limits and use its design-calculated value. Retained values are not an effective cap. Choose an explicit per-area "Autosize" reset with a numeric fraction to activate fraction-only control'
                )
            elif effect["mode"] == "fraction_only":
                if (
                    info["minimum_method"] == "Constant"
                    and type(fraction) in (int, float)
                    and after["maximum_reheat_flow_fraction"] < fraction
                ):
                    warnings.append(
                        "Requested reheat maximum is below terminal minimum; EnergyPlus raises it to the minimum, so the requested cap cannot be achieved"
                    )
                if maximum == "Autosize" or effect["nominal_cap_fraction"] is None:
                    warnings.append(
                        "Fraction-only reheat limit is active, but effective flow/minimum bounds require sizing and the retained minimum-flow controls"
                    )
            else:
                warnings.append(
                    "Both reheat limits are Autocalculate; effective reheat flow is design-calculated and requires sizing"
                )
        warnings.append(
            "Reheat discharge limit is not a supply-air setpoint. Existing coil capacities, water limits and zone/system sizing are retained; run sizing and check loads/unmet hours"
        )
        thermostat = zone.thermostatSetpointDualSetpoint()
        if thermostat.is_initialized():
            schedule = thermostat.get().heatingSetpointTemperatureSchedule()
            if schedule.is_initialized():
                bounds = schedule_bounds(schedule.get())
                if (
                    bounds["verified"]
                    and after["maximum_reheat_temperature_c"] <= bounds["maximum"]
                ):
                    warnings.append(
                        "Reheat temperature limit is at or below a retained zone heating setpoint; heating load may not be met"
                    )
    planned.update(
        ready=True,
        parameters=dict(output_model_path=config["output_model_path"], settings=patch),
        resolved_objects=dict(
            terminal=ref(terminal),
            air_loop=row["air_loop"],
            zone=row["zone"],
            ports=ports(terminal),
        ),
        before_values=before,
        after_values=after,
        context=info,
        preserved_terminal=signature(terminal, patch),
        protected_objects=snapshot(model, excluded={str(terminal.handle())}),
        impact=dict(
            terminal=terminal.nameString(),
            zone=zone.nameString(),
            air_loop=loop.nameString(),
            before=before,
            after=after,
            minimum_method=info["minimum_method"],
            maximum_airflow_m3_s=maximum,
            nominal_minimum_supply_m3_s=minimum,
            nominal_zone_oa_m3_s=nominal,
            zone_multiplier=info["zone_multiplier"],
            multiplied_floor_area_m2=info["multiplied_floor_area_m2"],
            reheat_flow_limits=limits,
            reheat_coil=info["reheat_coil"],
            retained_schedules={k: v for k, v in info["schedules"].items() if v},
            retained_oa_controls=info["oa_controller"],
            ems_actuator_count=len(info["ems_actuators"]),
            identities="Terminal, coil, metadata, references, zone service and connections retained; no rewiring",
            sizing_policy="Only requested terminal controls change, including an explicitly chosen per-area Autosize reset; preserve maximum air/water flows and coil/zone/system sizing fields; no other sizing resets or applySizingValues",
        ),
        assumptions=[
            "Only explicit terminal settings change; no prototype defaults, coil edits, schedule changes, plant/zone reassignment or topology replacement"
        ],
    )
    return planned


def edit(model, sdk, planned):
    terminal = typed(model, sdk, planned["resolved_objects"]["terminal"])
    before = values(terminal)
    for key, value in planned["parameters"]["settings"].items():
        ok = (
            terminal.autosizeMaximumFlowPerZoneFloorAreaDuringReheat()
            if key == "maximum_reheat_flow_per_area_m3_s_m2" and value == "Autosize"
            else getattr(terminal, "set" + FIELDS[key][1])(value)
        )
        if ok is False:
            raise ValueError("SDK rejected requested terminal setting")
    return dict(terminal=ref(terminal), before=before, after=values(terminal))


def translated_settings(model, sdk, terminal, patch):
    translator = sdk.energyplus.ForwardTranslator()
    workspace = translator.translateModel(model)
    kind = terminal.iddObjectType().valueName().removeprefix("OS_")
    found = [
        x
        for x in workspace.objects()
        if x.iddObject().type().valueName() == kind
        and x.nameString().casefold() == terminal.nameString().casefold()
    ]
    if translator.errors() or len(found) != 1:
        return False
    obj = found[0]
    for key, expected in patch.items():
        index = obj.iddObject().getFieldIndex(FIELDS[key][2])
        if not index.is_initialized():
            return False
        if key == "maximum_reheat_flow_per_area_m3_s_m2" and expected == "Autosize":
            expected = "Autocalculate"
        value = (
            obj.getDouble(index.get())
            if type(expected) in (int, float)
            else obj.getString(index.get())
        )
        if not value.is_initialized() or not matches(value.get(), expected):
            return False
    return True


def validate_model(model, sdk, planned, result):
    terminal = typed(model, sdk, planned["resolved_objects"]["terminal"])
    reference = planned["resolved_objects"]
    rows = [
        x
        for x in inventory(model)["terminals"]
        if x["handle"] == str(terminal.handle())
    ]
    checks = {
        "Terminal identity/name/class changed": ref(terminal)
        == reference["terminal"]
        == result["terminal"],
        "Reported values differ from plan": matches(
            result["before"], planned["before_values"]
        )
        and matches(result["after"], planned["after_values"]),
        "Saved settings differ from plan": matches(
            values(terminal), planned["after_values"]
        ),
        "Terminal boundary nodes changed": ports(terminal) == reference["ports"],
        "Terminal ownership or zone service changed": len(rows) == 1
        and rows[0]["zone"] == reference["zone"]
        and rows[0]["air_loop"] == reference["air_loop"],
        "Unrequested terminal fields changed": signature(
            terminal, planned["parameters"]["settings"]
        )
        == planned["preserved_terminal"],
        "Protected objects/references changed": snapshot(
            model, excluded={str(terminal.handle())}
        )
        == planned["protected_objects"],
    }
    if all(checks.values()):
        checks["Translated terminal settings differ from plan"] = translated_settings(
            model, sdk, terminal, planned["parameters"]["settings"]
        )
    return dict(
        ok=all(checks.values()),
        checks=len(checks),
        errors=[key for key, ok in checks.items() if not ok],
    )
