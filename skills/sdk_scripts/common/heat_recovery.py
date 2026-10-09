"""Explicit direct OA heat recovery: bounded attachment or identity-preserving edits."""

import json
from pathlib import Path
from common.input_validation import validate
from common.hvac_inventory import resolve
from common.hvac_equipment import by_handle, call
from common.outdoor_air import (
    ref,
    inventory as air_inventory,
    select_controller,
    context,
    mixed_air_control,
)
from common.model_preservation import snapshot
from common.water_coil import raw_fields
from common.outdoor_air_topology import preview_guard, verify_guard, schedule
from common.temperature_control import translated_workspace, node_temperature_managers
from common.economizer_edit import settings_match
from common.ventilation_context import schedule_bounds

KIND = "OS_HeatExchanger_AirToAir_SensibleAndLatent"
PAIRS = {
    "sensible_heating": "Sensible",
    "latent_heating": "Latent",
    "sensible_cooling": "Sensible",
    "latent_cooling": "Latent",
}
FIELDS = {
    "nominal_power_w": ("nominalElectricPower", "Nominal Electric Power"),
    "heat_exchanger_type": ("heatExchangerType", "Heat Exchanger Type"),
    "frost_control": ("frostControlType", "Frost Control Type"),
    "frost_threshold_c": ("thresholdTemperature", "Threshold Temperature"),
    "initial_defrost_fraction": (
        "initialDefrostTimeFraction",
        "Initial Defrost Time Fraction",
    ),
    "defrost_fraction_increase_per_k": (
        "rateofDefrostTimeFractionIncrease",
        "Rate of Defrost Time Fraction Increase",
    ),
    "supply_outlet_temperature_control": (
        "supplyAirOutletTemperatureControl",
        "Supply Air Outlet Temperature Control",
    ),
    "economizer_lockout": ("economizerLockout", "Economizer Lockout"),
    "nominal_flow_m3_s": ("nominalSupplyAirFlowRate", "Nominal Supply Air Flow Rate"),
    "availability_schedule": ("availabilitySchedule", "Availability Schedule"),
}
for key, prefix in PAIRS.items():
    mode = "Heating" if key.endswith("heating") else "Cooling"
    FIELDS[key + "_100"] = (
        prefix.lower() + "Effectivenessat100" + mode + "AirFlow",
        prefix + " Effectiveness at 100% " + mode + " Air Flow",
    )


def inventory(model):
    return dict(
        air_inventory(model),
        heat_exchangers=sorted(
            [ref(x) for x in model.getHeatExchangerAirToAirSensibleAndLatents()],
            key=lambda x: (x["name"], x["handle"]),
        ),
        schedules=sorted(
            [ref(x) for x in model.getSchedules()],
            key=lambda x: (x["name"], x["handle"]),
        ),
    )


def values(hx):
    result = {}
    for key, (getter, _) in FIELDS.items():
        value = getattr(hx, getter)()
        if key == "availability_schedule":
            value = ref(value)
        elif key == "nominal_flow_m3_s" and hx.isNominalSupplyAirFlowRateAutosized():
            value = "Autosize"
        elif hasattr(value, "is_initialized"):
            value = value.get() if value.is_initialized() else None
        result[key] = value
    return result


def set_settings(hx, sdk, patch):
    for key, value in patch.items():
        getter = FIELDS[key][0]
        if key == "availability_schedule":
            call(
                hx,
                "setAvailabilitySchedule",
                by_handle(hx.model(), sdk, value, "Schedule"),
            )
        elif key == "nominal_flow_m3_s" and value == "Autosize":
            call(hx, "autosizeNominalSupplyAirFlowRate")
        else:
            call(hx, "set" + getter[0].upper() + getter[1:], value)


def curve_context(hx):
    result = {}
    for key, prefix in PAIRS.items():
        mode = "Heating" if key.endswith("heating") else "Cooling"
        curve = getattr(
            hx, prefix.lower() + "Effectivenessof" + mode + "AirFlowCurve"
        )()
        item = ref(curve.get()) if curve.is_initialized() else None
        if item:
            table = curve.get().to_TableLookup()
            if table.is_initialized():
                t = table.get()
                item.update(
                    normalization_method=t.normalizationMethod(),
                    normalization_divisor=t.normalizationDivisor(),
                    output_values=list(t.outputValues()),
                    independent_variables=[
                        dict(
                            values=list(iv.values()),
                            interpolation=iv.interpolationMethod(),
                            extrapolation=iv.extrapolationMethod(),
                        )
                        for iv in t.independentVariables()
                    ],
                )
        result[key] = item
    return result


def cooling_context(system):
    """Screen for heat-then-cool risk without claiming coincident operation."""
    loop = system.airLoopHVAC().get()
    components = list(loop.supplyComponents())
    position = next(
        i for i, x in enumerate(components) if x.handle() == system.handle()
    )
    cooling = [
        ref(x)
        for x in components[position + 1 :]
        if x.iddObjectType().valueName().startswith("OS_Coil_Cooling_")
    ]
    supply = []
    for manager in loop.supplyOutletNode().setpointManagers():
        scheduled = manager.to_SetpointManagerScheduled()
        if (
            scheduled.is_initialized()
            and scheduled.get().controlVariable() == "Temperature"
        ):
            bounds = schedule_bounds(scheduled.get().schedule())
            if bounds["verified"] and bounds["unit_type"] == "Temperature":
                supply.append(bounds)
    heating = []
    for zone in loop.thermalZones():
        thermostat = zone.thermostatSetpointDualSetpoint()
        if thermostat.is_initialized():
            schedule = thermostat.get().heatingSetpointTemperatureSchedule()
            if schedule.is_initialized():
                bounds = schedule_bounds(schedule.get())
                if bounds["verified"] and bounds["unit_type"] == "Temperature":
                    heating.append(bounds["minimum"])
    # Comparing ranges is only a risk screen, not proof that the hours coincide.
    below_zone_heating = bool(heating) and any(
        x["minimum"] < min(heating) for x in supply
    )
    return dict(
        downstream_cooling_components=cooling,
        supply_temperature_schedules=supply,
        minimum_zone_heating_setpoint_c=min(heating) if heating else None,
        supply_can_be_below_zone_heating_setpoints=below_zone_heating,
        cooling_risk=bool(cooling) or below_zone_heating,
    )


def controls(model, sdk, hx, system):
    workspace = translated_workspace(
        model, sdk, "Cannot verify heat-recovery temperature controls"
    )
    outlet = hx.primaryAirOutletModelObject().get().nameString()
    mixed = system.mixedAirModelObject().get().nameString()
    managers = node_temperature_managers(workspace, sdk, outlet)
    reference = node_temperature_managers(workspace, sdk, mixed)
    single = lambda items: [
        x for x in items if x["type"] != "SetpointManager:Scheduled:DualSetpoint"
    ]
    managers, reference = single(managers), single(reference)
    pretreat = any(x["type"] == "SetpointManager:OutdoorAirPretreat" for x in managers)
    return dict(
        outlet_node=outlet,
        outlet_managers=managers,
        mixed_air_node=mixed,
        reference_managers=reference,
        temperature_setpoint_verified=bool(managers)
        and (not pretreat or bool(reference)),
        cooling_context=cooling_context(system),
    )


def attach(model, sdk, planned):
    r, p = planned["resolved_objects"], planned["parameters"]
    system = by_handle(model, sdk, r["oa_system"], "AirLoopHVACOutdoorAirSystem")
    controller = system.getControllerOutdoorAir()
    hx = sdk.model.HeatExchangerAirToAirSensibleAndLatent(model)
    call(hx, "setName", p["name"])
    set_settings(hx, sdk, p["settings"])
    call(hx, "addToNode", system.outboardOANode().get())
    call(hx.primaryAirOutletModelObject().get(), "setName", p["name"] + " OA Outlet")
    call(
        hx.secondaryAirInletModelObject().get(), "setName", p["name"] + " Relief Inlet"
    )
    iv = sdk.model.TableIndependentVariable(model)
    call(iv, "setName", p["name"] + " Flow Fraction")
    for method, value in (
        ("setInterpolationMethod", "Linear"),
        ("setExtrapolationMethod", "Constant"),
        ("setMinimumValue", 0),
        ("setMaximumValue", 10),
        ("setUnitType", "Dimensionless"),
    ):
        call(iv, method, value)
    call(iv, "addValue", 0.75)
    call(iv, "addValue", 1.0)
    for key, prefix in PAIRS.items():
        curve = sdk.model.TableLookup(model)
        call(curve, "setName", p["name"] + " " + key)
        e100 = p["settings"][key + "_100"]
        for method, value in (
            ("setNormalizationMethod", "DivisorOnly"),
            ("setNormalizationDivisor", e100 or 1),
            ("setMinimumOutput", 0),
            ("setMaximumOutput", 10),
            ("setOutputUnitType", "Dimensionless"),
        ):
            call(curve, method, value)
        call(curve, "addIndependentVariable", iv)
        call(
            curve.getTarget(
                curve.iddObject().getFieldIndex("Independent Variable List Name").get()
            ).get(),
            "setName",
            p["name"] + " " + key + " Variables",
        )
        call(curve, "addOutputValue", p["part_load_effectiveness"][key])
        call(curve, "addOutputValue", e100)
        mode = "Heating" if key.endswith("heating") else "Cooling"
        call(hx, "set" + prefix + "Effectivenessof" + mode + "AirFlowCurve", curve)
    call(controller, "setHeatRecoveryBypassControlType", p["bypass_control"])
    if p["settings"]["supply_outlet_temperature_control"]:
        spm = sdk.model.SetpointManagerOutdoorAirPretreat(model)
        call(spm, "setName", p["name"] + " Pretreat")
        call(spm, "setControlVariable", "Temperature")
        for key, setter in (
            ("minimum_temperature_c", "setMinimumSetpointTemperature"),
            ("maximum_temperature_c", "setMaximumSetpointTemperature"),
            ("minimum_humidity_ratio", "setMinimumSetpointHumidityRatio"),
            ("maximum_humidity_ratio", "setMaximumSetpointHumidityRatio"),
        ):
            call(spm, setter, p["pretreat_limits"][key])
        mixed = system.mixedAirModelObject().get().to_Node().get()
        for setter, node in (
            ("setReferenceSetpointNode", mixed),
            ("setMixedAirStreamNode", mixed),
            ("setOutdoorAirStreamNode", system.outboardOANode().get()),
            (
                "setReturnAirStreamNode",
                system.returnAirModelObject().get().to_Node().get(),
            ),
        ):
            call(spm, setter, node)
        call(spm, "addToNode", hx.primaryAirOutletModelObject().get().to_Node().get())
    return hx


def plan(model, sdk, config):
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1] / "references/heat_recovery.schema.json"
        ).read_text()
    )
    errors = validate(config, schema)
    if errors:
        raise ValueError("Invalid heat recovery configuration: " + "; ".join(errors))
    mode = config.get("mode")
    required = ["mode", "air_loop", "settings"] + (
        ["name", "part_load_effectiveness", "part_load_policy", "bypass_control"]
        if mode == "attach"
        else ["heat_exchanger"] if mode == "edit" else []
    )
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
    irrelevant = (
        {"heat_exchanger"}
        if mode == "attach"
        else {
            "name",
            "part_load_effectiveness",
            "part_load_policy",
            "bypass_control",
            "pretreat_limits",
        }
    ) & config.keys()
    if irrelevant:
        p["errors"].append(
            "Fields outside selected mode: " + ", ".join(sorted(irrelevant))
        )
        return p
    if (
        mode == "attach"
        and not config["settings"].get("supply_outlet_temperature_control", True)
        and "pretreat_limits" in config
    ):
        p["errors"].append(
            "pretreat_limits require supply_outlet_temperature_control: true"
        )
        return p
    selection = select_controller(model, sdk, config["air_loop"], p["errors"])
    if selection is None:
        return p
    loop, system, controller = selection
    settings = dict(config["settings"])
    if not settings:
        p["missing_inputs"].append("settings: at least one explicit field")
        return p
    if "availability_schedule" in settings:
        settings["availability_schedule"] = schedule(
            model, sdk, settings["availability_schedule"], p["errors"]
        )
    streams = list(system.oaComponents()) + list(system.reliefComponents())
    hxs = {
        str(x.handle()): x.to_HeatExchangerAirToAirSensibleAndLatent().get()
        for x in streams
        if x.iddObjectType().valueName() == KIND
    }
    p["resolved_objects"] = dict(
        air_loop=ref(loop), oa_system=ref(system), controller=ref(controller)
    )
    params = dict(p["parameters"], mode=mode, settings=settings)
    p["parameters"] = params
    if mode == "attach":
        p["missing_inputs"].extend("settings." + k for k in FIELDS if k not in settings)
        if (
            settings.get("supply_outlet_temperature_control")
            and "pretreat_limits" not in config
        ):
            p["missing_inputs"].append("pretreat_limits")
        if any(x.iddObjectType().valueName() != "OS_Node" for x in streams):
            p["errors"].append(
                "Attachment requires empty direct OA/relief streams containing nodes only; existing recovery/equipment needs separate coverage"
            )
        if any(
            x.nameString().casefold().startswith(config["name"].casefold())
            for x in model.modelObjects()
        ):
            p["errors"].append("Choose an unused attachment name/prefix")
        for key, e75 in config["part_load_effectiveness"].items():
            if settings.get(key + "_100") == 0 and e75 != 0:
                p["errors"].append(
                    "Zero 100% effectiveness requires zero 75% effectiveness: " + key
                )
        params.update(
            {
                k: config[k]
                for k in (
                    "name",
                    "part_load_effectiveness",
                    "part_load_policy",
                    "bypass_control",
                    "pretreat_limits",
                )
                if k in config
            }
        )
        if "pretreat_limits" in params:
            limits = params["pretreat_limits"]
            if (
                limits["minimum_temperature_c"] >= limits["maximum_temperature_c"]
                or limits["minimum_humidity_ratio"] >= limits["maximum_humidity_ratio"]
            ):
                p["errors"].append(
                    "Pretreat minimum limits must be below maximum limits"
                )
    else:
        selected = resolve(
            config["heat_exchanger"],
            [ref(x) for x in hxs.values()],
            "heat_exchanger",
            p["errors"],
        )
        if selected:
            hx = hxs[selected["handle"]]
            if not all(
                any(x.handle() == hx.handle() for x in side)
                for side in (system.oaComponents(), system.reliefComponents())
            ):
                p["errors"].append(
                    "Exchanger must serve both direct OA and relief streams"
                )
            p["resolved_objects"]["heat_exchanger"] = ref(hx)
            p["before_values"] = values(hx)
            if settings_match(dict(p["before_values"], **settings), p["before_values"]):
                p["errors"].append("Edit must change at least one setting")
    if p["errors"] or p["missing_inputs"]:
        return p
    effective = settings if mode == "attach" else dict(p["before_values"], **settings)
    if effective["frost_control"] != "None" and any(
        effective[k] is None
        for k in (
            "frost_threshold_c",
            "initial_defrost_fraction",
            "defrost_fraction_increase_per_k",
        )
    ):
        p["missing_inputs"].append(
            "Active frost control requires explicit threshold and defrost fraction/rate"
        )
        return p
    snapshot(model)
    p["weather_was_empty"] = not any(
        value
        for name, value in raw_fields(model.getWeatherFile()).values()
        if name not in ("Handle", "Url", "Checksum")
    )
    preview = sdk.model.Model(model.clone(True))
    if mode == "attach":
        hx = attach(preview, sdk, p)
        intake, relief = (
            system.outboardOANode().get(),
            system.outboardReliefNode().get(),
        )
        allowed = {
            str(system.handle()): [
                "Outdoor Air Stream Node Name",
                "Relief Air Stream Node Name",
            ],
            str(controller.handle()): ["Heat Recovery Bypass Control Type"],
            str(intake.handle()): ["Outlet Port"],
            str(relief.handle()): ["Inlet Port"],
        }
        p["topology"] = preview_guard(
            model,
            preview,
            sdk,
            allowed,
            {str(x.handle()) for x in (system, intake, relief)},
            {
                KIND,
                "OS_Node",
                "OS_Connection",
                "OS_Table_Lookup",
                "OS_Table_IndependentVariable",
                "OS_ModelObjectList",
                "OS_SetpointManager_OutdoorAirPretreat",
            },
        )
        p["before_values"] = None
    else:
        hx = by_handle(
            preview,
            sdk,
            p["resolved_objects"]["heat_exchanger"],
            "HeatExchangerAirToAirSensibleAndLatent",
        )
        set_settings(hx, sdk, settings)
        p["topology"] = preview_guard(
            model,
            preview,
            sdk,
            {str(hx.handle()): [FIELDS[k][1] for k in settings]},
            set(),
            set(),
        )
    if mode == "edit":
        for key, prefix in PAIRS.items():
            if key + "_100" not in settings:
                continue
            mode_name = "Heating" if key.endswith("heating") else "Cooling"
            curve = getattr(
                hx, prefix.lower() + "Effectivenessof" + mode_name + "AirFlowCurve"
            )()
            if not curve.is_initialized():
                continue
            table = curve.get().to_TableLookup()
            if (
                table.is_initialized()
                and table.get().normalizationMethod() == "DivisorOnly"
            ):
                divisor = table.get().normalizationDivisor()
                if divisor <= 0 or any(
                    not -1e-9 <= v / divisor * settings[key + "_100"] <= 1 + 1e-9
                    for v in table.get().outputValues()
                ):
                    p["errors"].append(
                        "Requested 100% value makes retained part-load table effectiveness exceed [0,1]: "
                        + key
                    )
                    return p
    p["after_values"] = values(hx)
    if not settings_match(p["after_values"], effective):
        raise ValueError("SDK did not retain requested heat-recovery settings")
    ps = by_handle(preview, sdk, ref(system), "AirLoopHVACOutdoorAirSystem")
    control = controls(preview, sdk, hx, ps)
    control["economizer"] = mixed_air_control(
        preview, sdk, ps.getControllerOutdoorAir()
    )
    warnings = [
        "Sizing and annual performance remain unverified; fan pressure/energy is retained. Explicit nominal electric power must account for the intended wheel and pressure-loss energy without double counting.",
        "Recovery is limited by actual relief flow; zone exhaust can reduce recovered energy. No air balancing, leakage or ventilation compliance is inferred.",
    ]
    if (
        not effective["supply_outlet_temperature_control"]
        and control["cooling_context"]["cooling_risk"]
    ):
        warnings.append(
            "Uncontrolled heat-recovery outlet temperature on a loop with downstream cooling equipment or a cool supply-air target: recovery is not modulated to the mixed-air temperature need. When otherwise active, winter/shoulder-season recovery can overheat mixed air above its setpoint and add downstream cooling load (heat-then-cool). Review explicit OutdoorAirPretreat outlet control and economizer/bypass choices; more recovered heat is not evidence of energy savings."
        )
    if mode == "edit" and any(k.endswith("_100") for k in settings):
        warnings.append(
            "Retained part-load curve multipliers are unchanged: changing 100% effectiveness scales the existing part-load effectiveness too; review manufacturer data."
        )
    if effective["frost_control"] == "ExhaustAirRecirculation":
        warnings.append(
            "ExhaustAirRecirculation frost control interrupts outdoor ventilation during defrost; review minimum ventilation separately."
        )
    if effective["frost_control"] == "None":
        warnings.append(
            "No frost protection is modeled; cold-climate operation needs review."
        )
    sim_ready = (
        not effective["supply_outlet_temperature_control"]
        or control["temperature_setpoint_verified"]
    )
    if (
        control["economizer"] is not None
        and not control["economizer"]["temperature_setpoint_verified"]
    ):
        warnings.append(
            "Enabled retained economizer lacks a verified mixed-air temperature setpoint; simulation is not ready"
        )
        sim_ready = False
    if (
        effective["supply_outlet_temperature_control"]
        and not control["temperature_setpoint_verified"]
    ):
        warnings.append(
            "Enabled heat-exchanger outlet temperature control has no verified translated setpoint/reference; simulation is not ready. Provide a manager or separately verify EMS control."
        )
    if (
        mode == "attach"
        and effective["supply_outlet_temperature_control"]
        and not control["temperature_setpoint_verified"]
    ):
        p["errors"].append(
            "Pretreat attachment requires a verified mixed-air reference temperature setpoint"
        )
        return p
    p.update(
        ready=True,
        simulation_ready=sim_ready,
        warnings=warnings,
        control=control,
        curves=(
            {
                k: (
                    {field: value for field, value in v.items() if field != "handle"}
                    if v
                    else None
                )
                for k, v in curve_context(hx).items()
            }
            if mode == "attach"
            else curve_context(hx)
        ),
        assumptions=[
            "Only explicit equipment/control choices; no template effectiveness, power, frost or bypass defaults"
        ],
        impact=dict(
            mode=mode,
            air_loop=ref(loop),
            affected_zone_count=len(loop.thermalZones()),
            before=p["before_values"],
            after=p["after_values"],
            part_load_policy=params.get(
                "part_load_policy", "Retain existing curves and multipliers"
            ),
            part_load_effectiveness=params.get("part_load_effectiveness"),
            controls=control,
            uncontrolled_recovery_cooling_risk=(
                not effective["supply_outlet_temperature_control"]
                and control["cooling_context"]["cooling_risk"]
            ),
            retained_curves=curve_context(hx) if mode == "edit" else None,
            bypass_control=params.get(
                "bypass_control", context(loop, controller, sdk)["heat_recovery_bypass"]
            ),
            identity_policy=(
                "Preserve all existing equipment handles; attachment changes only intake/relief wiring and explicit bypass field"
                if mode == "attach"
                else "Preserve exchanger, curves, controls, nodes, connections and references"
            ),
            added_object_counts=p.get("topology", {}).get("added_counts", {}),
        ),
    )
    return p


def execute(model, sdk, planned):
    if planned["parameters"]["mode"] == "attach":
        hx = attach(model, sdk, planned)
    else:
        hx = by_handle(
            model,
            sdk,
            planned["resolved_objects"]["heat_exchanger"],
            "HeatExchangerAirToAirSensibleAndLatent",
        )
        set_settings(hx, sdk, planned["parameters"]["settings"])
    return dict(heat_exchanger=ref(hx), after=values(hx))


def validate_model(model, sdk, planned, result):
    hx = by_handle(
        model, sdk, result["heat_exchanger"], "HeatExchangerAirToAirSensibleAndLatent"
    )
    system = by_handle(
        model,
        sdk,
        planned["resolved_objects"]["oa_system"],
        "AirLoopHVACOutdoorAirSystem",
    )
    checks = {
        "Saved heat recovery settings differ": settings_match(
            values(hx), planned["after_values"]
        ),
        "Reported settings differ": settings_match(
            result["after"], planned["after_values"]
        ),
        "Exchanger no longer serves both streams": all(
            any(x.handle() == hx.handle() for x in side)
            for side in (system.oaComponents(), system.reliefComponents())
        ),
        "Translated temperature controls changed": dict(
            controls(model, sdk, hx, system),
            economizer=mixed_air_control(model, sdk, system.getControllerOutdoorAir()),
        )
        == planned["control"],
    }
    checks.update(verify_guard(model, sdk, planned))
    if planned["parameters"]["mode"] == "edit":
        checks["Exchanger identity changed"] = (
            ref(hx) == planned["resolved_objects"]["heat_exchanger"]
        )
        checks["Curve references changed"] = curve_context(hx) == planned["curves"]
    return dict(
        ok=all(checks.values()),
        checks=len(checks),
        errors=[k for k, v in checks.items() if not v],
    )
