"""Hash-bound ventilation edits preserving zone inputs, sizing and air topology."""

import json
import math
from pathlib import Path
from common.input_validation import validate
from common.hvac_inventory import resolve
from common.hvac_equipment import by_handle
from common.model_preservation import snapshot
from common.outdoor_air import (
    ref,
    inventory as air_inventory,
    select_controller,
    mechanical_ventilation,
    context,
    mixed_air_control,
)
from common.ventilation_equipment import FIELDS, values, set_settings
from common.ventilation_context import schedule_bounds, zone_requirements
from common.temperature_control import translated_workspace, optional_string


def inventory(model):
    result = air_inventory(model)
    result["schedules"] = sorted(
        [schedule_bounds(s) for s in model.getSchedules()],
        key=lambda x: (x["name"], x["handle"]),
    )
    return result


def matches(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(matches(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(matches(x, y) for x, y in zip(a, b))
    if type(a) in (int, float) and type(b) in (int, float):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return type(a) is type(b) and a == b


def retained_context(model, sdk, loop, controller, mv):
    sizing = loop.sizingSystem()
    design = sizing.designOutdoorAirFlowRate()
    supply = loop.designSupplyAirFlowRate()
    schedules = {}
    for key, (suffix, _, kind) in FIELDS.items():
        if kind == "schedule":
            item = getattr(controller, suffix[0].lower() + suffix[1:])()
            schedules[key] = (
                schedule_bounds(item.get()) if item.is_initialized() else None
            )
    return dict(
        oa=context(loop, controller, sdk),
        schedules=schedules,
        mechanical_availability=(
            schedule_bounds(mv.availabilitySchedule()) if mv else None
        ),
        mixed_air_control=mixed_air_control(model, sdk, controller),
        translated_minimum_flow_m3_s=(
            translated_minimum_flow(model, sdk, controller)
            if mv and mv.demandControlledVentilation()
            else None
        ),
        ems_actuators=sorted(
            [
                ref(a)
                for a in model.getEnergyManagementSystemActuators()
                if a.actuatedComponent().is_initialized()
                and str(a.actuatedComponent().get().handle())
                in {str(controller.handle()), str(mv.handle()) if mv else ""}
            ],
            key=lambda x: x["handle"],
        ),
        design_oa_m3_s=(
            "Autosize"
            if sizing.isDesignOutdoorAirFlowRateAutosized()
            else design.get() if design.is_initialized() else None
        ),
        design_supply_m3_s=(
            "Autosize"
            if loop.isDesignSupplyAirFlowRateAutosized()
            else supply.get() if supply.is_initialized() else None
        ),
        zone_requirements=zone_requirements(loop),
    )


def translated_minimum_flow(model, sdk, controller):
    label = "Cannot verify translated ventilation floor"
    workspace = translated_workspace(model, sdk, label)
    objects = [
        x
        for x in workspace.getObjectsByType(sdk.IddObjectType("Controller_OutdoorAir"))
        if x.nameString().casefold() == controller.nameString().casefold()
    ]
    if len(objects) != 1:
        raise ValueError(label + ": selected OA controller not found uniquely")
    obj = objects[0]
    index = obj.iddObject().getFieldIndex("Minimum Outdoor Air Flow Rate")
    value = optional_string(obj, index.get()) if index.is_initialized() else ""
    if value.casefold() == "autosize":
        return "Autosize"
    try:
        number = float(value)
    except ValueError as error:
        raise ValueError(label + ": missing or invalid minimum flow") from error
    if not math.isfinite(number) or number < 0:
        raise ValueError(label + ": invalid minimum flow")
    return number


def dcv_floor_review(after, current):
    """Identify a blocking floor; unknown never promises effective DCV."""
    design = current["zone_requirements"]["nominal_design_oa_m3_s"]
    floor = current["translated_minimum_flow_m3_s"]
    schedule = current["schedules"]["minimum_flow_schedule"]
    multiplier = (
        1 if schedule is None else schedule["minimum"] if schedule["verified"] else None
    )
    lower = (
        floor * multiplier
        if type(floor) in (int, float) and multiplier is not None
        else None
    )
    mv = current["oa"]["mechanical_ventilation"]
    blocked = (
        after["dcv"] is True
        and mv is not None
        and mv["method"] == "ZoneSum"
        and after["minimum_limit_type"] == "FixedMinimum"
        and design > 0
        and lower is not None
        and (lower >= design or math.isclose(lower, design, rel_tol=1e-9, abs_tol=0))
    )
    return dict(
        dcv_effective=False if blocked or after["dcv"] is False else None,
        dcv_floor=dict(
            blocks_design_oa_reductions=blocked,
            basis="translated EnergyPlus controller minimum",
            declared_minimum_flow_m3_s=after["minimum_flow_m3_s"],
            translated_minimum_flow_m3_s=floor,
            nominal_design_oa_m3_s=design,
            scheduled_minimum_lower_bound_m3_s=lower,
            minimum_limit_type=after["minimum_limit_type"],
        ),
    )


def review(after, current):
    warnings = [
        "Zone OA/People/occupancy, MV method/availability, terminals, sizing, economizer and topology are preserved; this edit does not establish ventilation compliance or annual savings. Run sizing and ventilation assessment separately"
    ]
    ready = True
    low, high = after["minimum_flow_m3_s"], after["maximum_flow_m3_s"]
    if type(low) in (int, float) and type(high) in (int, float) and low > high:
        warnings.append(
            "Effective minimum OA flow exceeds maximum OA flow; simulation is not ready"
        )
        ready = False
    if high == 0:
        warnings.append("Effective maximum OA flow is zero and prevents ventilation")
        ready = False
    for key, schedule in current["schedules"].items():
        if schedule and (
            not schedule["verified"]
            or schedule["minimum"] < 0
            or schedule["maximum"] > 1
        ):
            warnings.append(
                f"Cannot verify effective {key} within [0,1]; review before simulation"
            )
            ready = False
    minimum = current["schedules"]["minimum_fraction_schedule"]
    maximum = current["schedules"]["maximum_fraction_schedule"]
    if maximum and maximum["verified"] and maximum["minimum"] < 1:
        warnings.append(
            "Maximum OA fraction can override zone ventilation and minimum OA; review time-based caps"
        )
        if maximum["maximum"] == 0 or (
            minimum and minimum["verified"] and minimum["minimum"] > maximum["maximum"]
        ):
            warnings.append(
                "Effective fraction bounds prevent/contradict ventilation; simulation is not ready"
            )
            ready = False
    if minimum and minimum["verified"] and minimum["maximum"] == 1:
        warnings.append(
            "Minimum fraction reaches 1.0 (100% OA); this can suppress DCV modulation and increase coil loads"
        )
        if not (
            current["oa"]["all_outdoor_air_heating"]
            and current["oa"]["all_outdoor_air_cooling"]
        ):
            warnings.append(
                "100% OA operation lacks both all-OA sizing flags; sizing review required"
            )
            ready = False
    requirements = current["zone_requirements"]
    design = requirements["nominal_design_oa_m3_s"]
    for key, value in [
        ("maximum controller OA", high),
        ("system design supply", current["design_supply_m3_s"]),
    ]:
        if type(value) in (int, float) and value < design:
            warnings.append(
                f"Fixed {key} {value:g} m3/s is below nominal zone OA {design:g} m3/s; review ventilation/sizing"
            )
            ready = False
    sized_oa = current["design_oa_m3_s"]
    if type(low) in (int, float) and type(sized_oa) in (int, float) and low > sized_oa:
        warnings.append(
            "Requested controller minimum exceeds retained fixed system design OA; resizing is separate"
        )
        ready = False
    if after["minimum_limit_type"] == "ProportionalMinimum":
        warnings.append(
            "ProportionalMinimum scales the controller floor with system flow; it does not guarantee zone design ventilation at low VAV flow"
        )
    if after["dcv"]:
        floor_review = dcv_floor_review(after, current)
        if low == "Autosize" and current["translated_minimum_flow_m3_s"] == 0:
            warnings.append(
                "Retained OSM minimum is Autosize, but OpenStudio translates the EnergyPlus minimum "
                "to 0 with DCV enabled; this controller floor does not block reductions. "
                "Fraction floors and other controls still apply"
            )
        if floor_review["dcv_floor"]["blocks_design_oa_reductions"]:
            warnings.append(
                "DCV will have no effect on outdoor-air reductions: the controller minimum "
                f"({floor_review['dcv_floor']['basis']}) floors the ZoneSum request at or above design OA. "
                "Set minimum_flow_m3_s explicitly (for example 0) to allow reductions; "
                "retained fraction floors and other controls still apply"
            )
        elif current["translated_minimum_flow_m3_s"] != 0 or (
            minimum and minimum["verified"] and minimum["maximum"] > 0
        ):
            warnings.append(
                "Retained/nonzero controller flow or fraction floor can mask DCV; zero minimum is an explicit separate choice, not an inferred reset"
            )
        responsive = False
        for zone in requirements["zones"]:
            for space in zone["spaces"]:
                oa = space["outdoor_air"]
                if not oa:
                    warnings.append(
                        "Missing zone/space OA definitions; DCV ventilation cannot be verified; see zone details"
                    )
                    ready = False
                    continue
                if oa["per_person_m3_s"] > 0 and space["design_people"] > 0:
                    responsive = True
                    for person in space["people"]:
                        schedule = person["occupancy_schedule"]
                        if (
                            not schedule
                            or not schedule["verified"]
                            or schedule["minimum"] < 0
                        ):
                            warnings.append(
                                "Unverified People occupancy schedules; DCV simulation readiness requires review; see zone details"
                            )
                            ready = False
                        elif schedule["maximum"] > 1:
                            warnings.append(
                                "Occupancy exceeds nominal design counts; sizing review required; see zone details"
                            )
                            ready = False
                        elif schedule["minimum"] == schedule["maximum"]:
                            warnings.append(
                                "Constant occupancy schedules retain no occupancy-driven DCV variation for those sources; see zone details"
                            )
                frac = oa["fraction_schedule"]
                if frac and (
                    not frac["verified"] or frac["minimum"] < 0 or frac["maximum"] > 1
                ):
                    warnings.append(
                        "Unverified zone OA fraction schedules; ventilation readiness requires review; see zone details"
                    )
                    ready = False
        if not responsive:
            warnings.append(
                "No positive per-person OA with design People; enabling DCV does not establish an occupancy-responsive ventilation benefit"
            )
    availability = current["mechanical_availability"]
    if availability and (not availability["verified"] or availability["minimum"] <= 0):
        warnings.append(
            "MV availability is zero at some times or unverified; a minimum-flow schedule reset does not disable/enable that independent request"
        )
    if (
        current["mixed_air_control"]
        and not current["mixed_air_control"]["temperature_setpoint_verified"]
    ):
        warnings.append(
            "Retained enabled economizer lacks a verified mixed-air Temperature setpoint; simulation is not ready"
        )
        ready = False
    if (
        current["oa"]["force_economizer_schedule"]
        or current["oa"]["high_humidity_control"]
    ):
        warnings.append(
            "Retained force-economizer/high-humidity controls can override minimum ventilation behavior"
        )
    if current["ems_actuators"]:
        warnings.append(
            "Existing EMS actuators target OA/MV controls and can override requested ventilation; verify their programs separately"
        )
    return list(dict.fromkeys(warnings)), ready


def plan(model, sdk, config):
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1] / "references/ventilation.schema.json"
        ).read_text()
    )
    errors = validate(config, schema)
    if errors:
        raise ValueError("Invalid ventilation configuration: " + "; ".join(errors))
    planned = dict(
        ready=False,
        parameters={"output_model_path": config["output_model_path"]},
        missing_inputs=[k for k in ("air_loop", "ventilation") if k not in config],
        errors=[],
        warnings=[],
        assumptions=[],
    )
    if planned["missing_inputs"]:
        return planned
    if not config["ventilation"]:
        planned["missing_inputs"].append("ventilation: at least one explicit setting")
        return planned
    chosen = select_controller(model, sdk, config["air_loop"], planned["errors"])
    if chosen is None:
        return planned
    loop, system, controller = chosen
    mv = mechanical_ventilation(controller, sdk)
    if (
        mv
        and len(
            [
                c
                for c in model.getControllerOutdoorAirs()
                if mechanical_ventilation(c, sdk)
                and mechanical_ventilation(c, sdk).handle() == mv.handle()
            ]
        )
        != 1
    ):
        planned["errors"].append(
            "Shared mechanical-ventilation controller requires separate coverage"
        )
        return planned
    patch = dict(config["ventilation"])
    if "dcv" in patch and (not mv or mv.systemOutdoorAirMethod() != "ZoneSum"):
        planned["errors"].append(
            "DCV edits require an existing uniquely owned ZoneSum mechanical-ventilation controller; VRP/IAQ method changes need separate coverage"
        )
        return planned
    for key, value in patch.items():
        if key == "dcv" or FIELDS[key][2] != "schedule" or value is None:
            continue
        selected = resolve(
            value, [ref(s) for s in model.getSchedules()], key, planned["errors"]
        )
        if selected is None:
            continue
        schedule = by_handle(model, sdk, selected, "Schedule")
        bounds = schedule_bounds(schedule)
        if (
            not bounds["verified"]
            or bounds["minimum"] < 0
            or bounds["maximum"] > 1
            or bounds["unit_type"] not in ("Dimensionless", "Availability")
        ):
            planned["errors"].append(
                f"{key} requires an existing Constant/Ruleset schedule with dimensionless type limits and all values in [0,1]; prepare untyped schedules separately"
            )
        patch[key] = selected
    if planned["errors"]:
        return planned
    before = values(controller, mv)
    after = dict(before, **patch)
    if matches(before, after):
        planned["errors"].append("Edit must change at least one ventilation setting")
        return planned
    # Snapshot first: the preservation helper materializes the weather singleton.
    ignored = {str(controller.handle()): [FIELDS[k][1] for k in patch if k != "dcv"]}
    if "dcv" in patch:
        ignored[str(mv.handle())] = ["Demand Controlled Ventilation"]
    protected = snapshot(model, ignored=ignored)
    preview = sdk.model.Model(model.clone(True))
    pc = by_handle(preview, sdk, ref(controller), "ControllerOutdoorAir")
    pmv = mechanical_ventilation(pc, sdk)
    try:
        set_settings(preview, sdk, pc, pmv, patch)
    except ValueError as error:
        planned["errors"].append(str(error))
        return planned
    ploop = by_handle(preview, sdk, ref(loop), "AirLoopHVAC")
    current = retained_context(preview, sdk, ploop, pc, pmv)
    if snapshot(preview, ignored=ignored) != protected or not matches(
        values(pc, pmv), after
    ):
        planned["errors"].append(
            "SDK preview changes protected objects or cannot retain the requested settings; prepare compatible schedules separately"
        )
        return planned
    warnings, simulation_ready = review(after, current)
    planned.update(
        ready=True,
        simulation_ready=simulation_ready,
        parameters=dict(planned["parameters"], ventilation=patch),
        resolved_objects=dict(
            air_loop=ref(loop),
            oa_system=ref(system),
            controller=ref(controller),
            mechanical_ventilation=ref(mv) if mv else None,
        ),
        before_values=before,
        after_values=after,
        retained_context=current,
        protection=ignored,
        protected_objects=protected,
        supply_order=[str(x.handle()) for x in loop.supplyComponents()],
        warnings=warnings,
        assumptions=[
            "Explicit ventilation fields only; preserve zone OA, occupancy, sizing, economizer and all model identities"
        ],
        impact=dict(
            **dcv_floor_review(after, current),
            air_loop=ref(loop),
            controller=ref(controller),
            mechanical_ventilation=ref(mv) if mv else None,
            before=before,
            after=after,
            zone_count=current["zone_requirements"]["zone_count"],
            nominal_design_oa_m3_s=current["zone_requirements"][
                "nominal_design_oa_m3_s"
            ],
            zone_preview=[
                dict(
                    zone=z["zone"],
                    nominal_oa_m3_s=z["nominal_oa_m3_s"],
                    space_count=len(z["spaces"]),
                )
                for z in current["zone_requirements"]["zones"][:6]
            ],
            full_zone_details="plan.retained_context.zone_requirements in report",
            schedules=current["schedules"],
            mechanical_ventilation_context=current["oa"]["mechanical_ventilation"],
            mechanical_availability=current["mechanical_availability"],
            retained_sizing=dict(
                design_oa_m3_s=current["design_oa_m3_s"],
                design_supply_m3_s=current["design_supply_m3_s"],
                all_outdoor_air_heating=current["oa"]["all_outdoor_air_heating"],
                all_outdoor_air_cooling=current["oa"]["all_outdoor_air_cooling"],
            ),
            sizing_policy="Preserve; run sizing/ventilation assessment separately",
            mixed_air_control=current["mixed_air_control"],
            ems_actuator_count=len(current["ems_actuators"]),
            ems_actuator_preview=current["ems_actuators"][:4],
        ),
    )
    return planned


def edit(model, sdk, planned):
    controller = by_handle(
        model, sdk, planned["resolved_objects"]["controller"], "ControllerOutdoorAir"
    )
    mv = mechanical_ventilation(controller, sdk)
    set_settings(model, sdk, controller, mv, planned["parameters"]["ventilation"])
    return dict(
        controller=ref(controller),
        mechanical_ventilation=ref(mv) if mv else None,
        before=planned["before_values"],
        after=values(controller, mv),
    )


def validate_model(model, sdk, planned, result):
    objects = planned["resolved_objects"]
    controller = by_handle(model, sdk, objects["controller"], "ControllerOutdoorAir")
    loop = by_handle(model, sdk, objects["air_loop"], "AirLoopHVAC")
    mv = mechanical_ventilation(controller, sdk)
    checks = {
        "Saved ventilation settings differ": matches(
            values(controller, mv), planned["after_values"]
        ),
        "Reported settings/identities differ": matches(
            result,
            dict(
                controller=objects["controller"],
                mechanical_ventilation=objects["mechanical_ventilation"],
                before=planned["before_values"],
                after=planned["after_values"],
            ),
        ),
        "Controller/MV identity changed": ref(controller) == objects["controller"]
        and (ref(mv) if mv else None) == objects["mechanical_ventilation"],
        "Protected fields, objects or connections changed": snapshot(
            model, ignored=planned["protection"]
        )
        == planned["protected_objects"],
        "OA ownership changed": loop.airLoopHVACOutdoorAirSystem().is_initialized()
        and ref(loop.airLoopHVACOutdoorAirSystem().get()) == objects["oa_system"]
        and loop.airLoopHVACOutdoorAirSystem().get().getControllerOutdoorAir().handle()
        == controller.handle(),
        "Supply order changed": [str(x.handle()) for x in loop.supplyComponents()]
        == planned["supply_order"],
        "Ventilation inputs, sizing or translated control differ": matches(
            retained_context(model, sdk, loop, controller, mv),
            planned["retained_context"],
        ),
    }
    return dict(
        ok=all(checks.values()),
        checks=len(checks),
        errors=[message for message, ok in checks.items() if not ok],
    )
