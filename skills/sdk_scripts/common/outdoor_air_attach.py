"""Attach one explicitly configured direct OA system at a main supply inlet."""

import json
from pathlib import Path
from common.input_validation import validate
from common.hvac_inventory import resolve
from common.hvac_equipment import by_handle, call
from common.outdoor_air import ref, inventory as air_inventory
from common.outdoor_air_topology import schedule
from common.model_preservation import snapshot
from common.water_coil import raw_fields
from common.outdoor_air_topology import preview_guard, verify_guard, normalized_new
from common.ventilation_equipment import FIELDS, set_settings, values
from common.ventilation_edit import retained_context, review, matches, dcv_floor_review
from common.ventilation_context import stable_evidence


def inventory(model):
    return dict(
        air_inventory(model),
        schedules=sorted(
            [ref(x) for x in model.getSchedules()],
            key=lambda x: (x["name"], x["handle"]),
        ),
    )


def normalize(value, tokens):
    if isinstance(value, dict):
        return {k: normalize(v, tokens) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v, tokens) for v in value]
    return tokens.get(value, value) if isinstance(value, str) else value


def attach(model, sdk, planned):
    loop = by_handle(model, sdk, planned["resolved_objects"]["air_loop"], "AirLoopHVAC")
    p = planned["parameters"]
    controller = sdk.model.ControllerOutdoorAir(model)
    call(controller, "setName", p["name"] + " Controller")
    mv = controller.controllerMechanicalVentilation()
    call(mv, "setName", p["name"] + " Ventilation")
    call(mv, "setSystemOutdoorAirMethod", p["ventilation_method"])
    call(
        mv,
        "setAvailabilitySchedule",
        by_handle(model, sdk, p["mechanical_availability_schedule"], "Schedule"),
    )
    set_settings(model, sdk, controller, mv, p["ventilation"])
    call(controller, "setEconomizerControlType", p["economizer_control"])
    call(controller, "setEconomizerControlActionType", "ModulateFlow")
    call(controller, "setLockoutType", "NoLockout")
    call(controller, "setHeatRecoveryBypassControlType", p["bypass_control"])
    system = sdk.model.AirLoopHVACOutdoorAirSystem(model, controller)
    call(system, "setName", p["name"])
    call(system, "addToNode", loop.supplyInletNode())
    for node, suffix in (
        (system.outboardOANode().get(), " Intake"),
        (system.outboardReliefNode().get(), " Relief"),
        (system.mixedAirModelObject().get(), " Mixed Air"),
    ):
        call(node, "setName", p["name"] + suffix)
    return system, controller, mv


def plan(model, sdk, config):
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "references/outdoor_air_attach.schema.json"
        ).read_text()
    )
    errors = validate(config, schema)
    if errors:
        raise ValueError(
            "Invalid outdoor-air attachment configuration: " + "; ".join(errors)
        )
    required = [
        "air_loop",
        "name",
        "ventilation",
        "ventilation_method",
        "mechanical_availability_schedule",
        "economizer_control",
        "bypass_control",
    ]
    p = dict(
        ready=False,
        parameters=dict(output_model_path=config["output_model_path"]),
        missing_inputs=[k for k in required if k not in config],
        errors=[],
        warnings=[],
        assumptions=[],
    )
    if p["missing_inputs"]:
        return p
    p["missing_inputs"].extend(
        "ventilation." + k for k in (*FIELDS, "dcv") if k not in config["ventilation"]
    )
    selected = resolve(
        config["air_loop"], air_inventory(model)["air_loops"], "air_loop", p["errors"]
    )
    if selected is None:
        return p
    loop = by_handle(model, sdk, selected, "AirLoopHVAC")
    if selected["split_supply"] or selected["controller"] is not None:
        p["errors"].append("Select an unsplit loop with no existing outdoor-air system")
    if not loop.thermalZones():
        p["errors"].append(
            "Attach requires a served air loop; create/connect the parent and terminals first"
        )
    if any(
        x.nameString().casefold().startswith(config["name"].casefold())
        for x in model.modelObjects()
    ):
        p["errors"].append("Choose an unused attachment name/prefix")
    ventilation = dict(config["ventilation"])
    for k, (_, _, kind) in FIELDS.items():
        if kind == "schedule" and ventilation.get(k) is not None:
            ventilation[k] = schedule(model, sdk, ventilation[k], p["errors"])
    availability = schedule(
        model, sdk, config["mechanical_availability_schedule"], p["errors"]
    )
    if p["missing_inputs"] or p["errors"]:
        return p
    low, high = ventilation["minimum_flow_m3_s"], ventilation["maximum_flow_m3_s"]
    if high == 0 or (
        type(low) in (int, float) and type(high) in (int, float) and low > high
    ):
        p["errors"].append("OA maximum must be positive and not below minimum")
        return p
    inlet = loop.supplyInletNode()
    fields = dict(raw_fields(inlet).values())
    connection = model.getModelObject(sdk.toUUID(fields["Outlet Port"])).get()
    boundary = dict(raw_fields(connection).values())
    downstream = model.getModelObject(sdk.toUUID(boundary["Target Object"])).get()
    port = int(boundary["Inlet Port"])
    field = downstream.iddObject().getField(port)
    if (
        not field.is_initialized()
        or not downstream.iddObjectType()
        .valueName()
        .startswith(("OS_Fan_", "OS_Coil_"))
    ):
        p["errors"].append(
            "Attachment supports a direct fan/coil immediately after the main supply inlet; unitary/complex topology needs separate coverage"
        )
        return p
    p["resolved_objects"] = dict(
        air_loop=ref(loop), inlet=ref(inlet), downstream=ref(downstream)
    )
    p["parameters"].update(
        {
            k: config[k]
            for k in (
                "name",
                "ventilation_method",
                "economizer_control",
                "bypass_control",
            )
        }
    )
    p["parameters"].update(
        ventilation=ventilation, mechanical_availability_schedule=availability
    )
    snapshot(model)
    p["weather_was_empty"] = not any(
        value
        for name, value in raw_fields(model.getWeatherFile()).values()
        if name not in ("Handle", "Url", "Checksum")
    )
    preview = sdk.model.Model(model.clone(True))
    system, controller, mv = attach(preview, sdk, p)
    p["topology"] = preview_guard(
        model,
        preview,
        sdk,
        {
            str(inlet.handle()): ["Outlet Port"],
            str(downstream.handle()): [field.get().name()],
        },
        {str(inlet.handle()), str(downstream.handle())},
        {
            "OS_AirLoopHVAC_OutdoorAirSystem",
            "OS_Controller_OutdoorAir",
            "OS_Controller_MechanicalVentilation",
            "OS_Node",
            "OS_Connection",
        },
    )
    tokens, _ = normalized_new(preview, p["topology"]["before_objects"])
    pl = by_handle(preview, sdk, ref(loop), "AirLoopHVAC")
    current = retained_context(preview, sdk, pl, controller, mv)
    after = values(controller, mv)
    warnings, sim_ready = review(after, current)
    warnings = warnings[1:] + [
        "New OA intake changes mixing and coil loads; sizing and ventilation compliance require a separate assessment. Existing zone OA, People, schedules and system sizing are retained. No economizer, heat recovery or template policy is inferred."
    ]
    p.update(
        ready=True,
        simulation_ready=sim_ready,
        warnings=warnings,
        after_values=after,
        context=normalize(stable_evidence(current), tokens),
        assumptions=[
            "Attach at main supply inlet, ahead of the retained fan/coil; ZoneSum and NoEconomizer are explicit initial choices; enable economizer with its editor afterward"
        ],
        impact=dict(
            air_loop=ref(loop),
            affected_zone_count=len(loop.thermalZones()),
            location="Main supply inlet, upstream of " + downstream.nameString(),
            before="No outdoor-air system",
            after=after,
            ventilation_method=config["ventilation_method"],
            economizer_control=config["economizer_control"],
            nominal_design_oa_m3_s=current["zone_requirements"][
                "nominal_design_oa_m3_s"
            ],
            **dcv_floor_review(after, current),
            added_object_counts=p["topology"]["added_counts"],
            identity_policy="Retain original fan/coil, loop, terminals, nodes and their handles; change only two boundary connection fields",
        ),
    )
    return p


def execute(model, sdk, planned):
    system, controller, mv = attach(model, sdk, planned)
    return dict(
        oa_system=ref(system),
        controller=ref(controller),
        mechanical_ventilation=ref(mv),
        after=values(controller, mv),
    )


def validate_model(model, sdk, planned, result):
    loop = by_handle(model, sdk, planned["resolved_objects"]["air_loop"], "AirLoopHVAC")
    system = by_handle(model, sdk, result["oa_system"], "AirLoopHVACOutdoorAirSystem")
    controller = system.getControllerOutdoorAir()
    mv = controller.controllerMechanicalVentilation()
    tokens, _ = normalized_new(model, planned["topology"]["before_objects"])
    checks = verify_guard(model, sdk, planned)
    checks.update(
        {
            "OA ownership changed": loop.airLoopHVACOutdoorAirSystem().is_initialized()
            and loop.airLoopHVACOutdoorAirSystem().get().handle() == system.handle(),
            "Saved ventilation settings differ": matches(
                values(controller, mv), planned["after_values"]
            )
            and matches(result["after"], planned["after_values"]),
            "Ventilation context differs": matches(
                normalize(
                    stable_evidence(retained_context(model, sdk, loop, controller, mv)),
                    tokens,
                ),
                planned["context"],
            ),
        }
    )
    return dict(
        ok=all(checks.values()),
        checks=len(checks),
        errors=[k for k, v in checks.items() if not v],
    )
