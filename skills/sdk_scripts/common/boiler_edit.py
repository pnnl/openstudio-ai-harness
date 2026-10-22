"""In-place hot-water boiler efficiency/parasitic edits with exact preservation."""

import json
import math
from pathlib import Path

from common.coil_topology import protected_state
from common.hvac_equipment import call
from common.hvac_inventory import resolve
from common.input_validation import validate
from common.model_preservation import fingerprint, snapshot
from common.temperature_control import translated_workspace, optional_string
from common.water_coil import original_types

# Configuration key -> SDK suffix / IDD field. No prototype defaults or resets.
FIELDS = {
    "nominal_thermal_efficiency": (
        "NominalThermalEfficiency",
        "Nominal Thermal Efficiency",
    ),
    "on_cycle_parasitic_electric_load_w": (
        "OnCycleParasiticElectricLoad",
        "On Cycle Parasitic Electric Load",
    ),
    "off_cycle_parasitic_fuel_load_w": (
        "OffCycleParasiticFuelLoad",
        "Off Cycle Parasitic Fuel Load",
    ),
}


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
                    boilers=sorted(
                        [
                            dict(
                                ref(x),
                                supported=x.iddObjectType().valueName()
                                == "OS_Boiler_HotWater"
                                and loop.sizingPlant().loopType() == "Heating",
                            )
                            for x in loop.supplyComponents()
                            if x.iddObjectType().valueName().startswith("OS_Boiler_")
                        ],
                        key=lambda x: (x["name"], x["handle"]),
                    ),
                )
                for loop in model.getPlantLoops()
            ],
            key=lambda x: (x["name"], x["handle"]),
        )
    )


def boiler_object(model, sdk, reference):
    boiler = model.getBoilerHotWater(sdk.toUUID(reference["handle"]))
    if not boiler.is_initialized():
        raise ValueError("Selected hot-water boiler is missing or its class changed")
    return boiler.get()


def values(boiler):
    return {
        key: getattr(boiler, suffix[0].lower() + suffix[1:])()
        for key, (suffix, _) in FIELDS.items()
    }


def sized(boiler, suffix):
    if getattr(boiler, "is" + suffix + "Autosized")():
        return "Autosize"
    value = getattr(boiler, suffix[0].lower() + suffix[1:])()
    return value.get() if value.is_initialized() else None


def ports(boiler):
    result = []
    for port in (boiler.inletModelObject(), boiler.outletModelObject()):
        if not port.is_initialized() or not port.get().to_Node().is_initialized():
            raise ValueError("Boiler requires connected plant inlet and outlet nodes")
        result.append(str(port.get().handle()))
    return result


def signature(boiler, patch):
    return fingerprint(boiler, ignored=[FIELDS[key][1] for key in patch])


def translated_state(model, sdk, boiler):
    workspace = translated_workspace(model, sdk, "Cannot verify translated boiler")
    objects = [
        x
        for x in workspace.getObjectsByType(sdk.IddObjectType("Boiler_HotWater"))
        if x.nameString() == boiler.nameString()
    ]
    if len(objects) != 1:
        raise ValueError("Cannot identify one translated hot-water boiler")
    obj = objects[0]
    settings = {}
    for key, (_, name) in FIELDS.items():
        index = obj.iddObject().getFieldIndex(name)
        if not index.is_initialized():
            raise ValueError(
                "Translated boiler is missing a required performance field"
            )
        value = obj.getDouble(index.get())
        if not value.is_initialized():
            raise ValueError("Translated boiler performance field is not numeric")
        settings[key] = value.get()
    names = {name for _, name in FIELDS.values()}
    preserved = [
        [obj.iddObject().getField(i).get().name(), optional_string(obj, i)]
        for i in range(obj.numFields())
        if obj.iddObject().getField(i).get().name() not in names
    ]
    return dict(settings=settings, preserved_fields=preserved)


def matches(actual, expected):
    return actual.keys() == expected.keys() and all(
        type(actual[key]) in (int, float)
        and math.isclose(actual[key], value, rel_tol=1e-9, abs_tol=1e-9)
        for key, value in expected.items()
    )


def plan(model, sdk, config):
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "references/boiler_performance.schema.json"
        ).read_text()
    )
    errors = validate(config, schema)
    if errors:
        raise ValueError(
            "Invalid boiler performance configuration: " + "; ".join(errors)
        )
    planned = dict(
        ready=False,
        simulation_ready=False,
        simulation_readiness_scope="operation_and_companions",
        parameters=dict(output_model_path=config["output_model_path"]),
        missing_inputs=[
            x for x in ("plant_loop", "boiler", "settings") if not config.get(x)
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
    selected = resolve(
        config["boiler"], loop_ref["boilers"], "boiler", planned["errors"]
    )
    if selected is None:
        return planned
    if not selected["supported"] or loop_ref["loop_type"] != "Heating":
        planned["errors"].append(
            "Select a BoilerHotWater on a heating plant supply side; steam boilers and other equipment require separate coverage"
        )
        return planned
    boiler = boiler_object(model, sdk, selected)
    loop = model.getPlantLoop(sdk.toUUID(loop_ref["handle"])).get()
    if (
        not boiler.plantLoop().is_initialized()
        or boiler.plantLoop().get().handle() != loop.handle()
    ):
        raise ValueError("Selected boiler plant ownership differs")
    patch, before = dict(config["settings"]), values(boiler)
    after = dict(before, **patch)
    electric = boiler.fuelType() == "Electricity"
    ignored_before = electric and before["off_cycle_parasitic_fuel_load_w"] > 0
    ignored_after = electric and after["off_cycle_parasitic_fuel_load_w"] > 0
    off_cycle_effect = dict(
        ignored_by_engine_before=ignored_before,
        ignored_by_engine_after=ignored_after,
        effective_input_w=0 if electric else after["off_cycle_parasitic_fuel_load_w"],
    )
    if ignored_before:
        planned["warnings"].append(
            "Existing nonzero off-cycle parasitic fuel input on an electric boiler is ignored by EnergyPlus 25.2 and treated as zero. The stored value is preserved unless an explicit zero is requested"
        )
    planned["impact"] = dict(
        fuel_type=boiler.fuelType(), off_cycle_parasitic_fuel=off_cycle_effect
    )
    if electric and patch.get("off_cycle_parasitic_fuel_load_w", 0) > 0:
        planned["errors"].append(
            "Electric boilers cannot apply positive off-cycle parasitic fuel: EnergyPlus 25.2 ignores it. Request zero explicitly or omit this setting; no automatic reset is made"
        )
        return planned
    if matches(before, after):
        planned["errors"].append("Edit must change at least one setting")
        return planned
    curve = boiler.normalizedBoilerEfficiencyCurve()
    curve = curve.get() if curve.is_initialized() else None
    ems = []
    for actuator in model.getEnergyManagementSystemActuators():
        component = actuator.actuatedComponent()
        if component.is_initialized() and component.get().handle() == boiler.handle():
            ems.append(ref(actuator))
    source_translation = translated_state(model, sdk, boiler)
    if not matches(source_translation["settings"], before):
        raise ValueError("Source boiler settings disagree with EnergyPlus translation")
    curve_translated = (
        dict(source_translation["preserved_fields"]).get(
            "Normalized Boiler Efficiency Curve Name"
        )
        == curve.nameString()
        if curve
        else None
    )
    protection = dict(excluded=[str(boiler.handle())], ignored={}, field_limits={})
    protected = snapshot(model, **protection)
    planned.update(
        ready=True,
        simulation_ready=True,
        parameters=dict(output_model_path=config["output_model_path"], settings=patch),
        resolved_objects=dict(
            plant_loop=ref(loop), boiler=ref(boiler), ports=ports(boiler)
        ),
        before_values=before,
        after_values=after,
        preserved_boiler=signature(boiler, patch),
        before_objects=original_types(model),
        protection=protection,
        protected_objects=protected,
        component_order={
            side: [str(x.handle()) for x in getattr(loop, side + "Components")()]
            for side in ("supply", "demand")
        },
        translated_preserved_fields=source_translation["preserved_fields"],
        impact=dict(
            boiler=ref(boiler),
            plant_loop=ref(loop),
            before=before,
            after=after,
            fuel_type=boiler.fuelType(),
            off_cycle_parasitic_fuel=off_cycle_effect,
            nominal_capacity_w=sized(boiler, "NominalCapacity"),
            design_water_flow_m3_s=sized(boiler, "DesignWaterFlowRate"),
            normalized_efficiency_curve=ref(curve) if curve else None,
            normalized_efficiency_curve_translated=curve_translated,
            efficiency_curve_temperature_variable=optional_string(
                boiler,
                boiler.iddObject()
                .getFieldIndex("Efficiency Curve Temperature Evaluation Variable")
                .get(),
            ),
            part_load_ratios=dict(
                minimum=boiler.minimumPartLoadRatio(),
                maximum=boiler.maximumPartLoadRatio(),
                optimum=boiler.optimumPartLoadRatio(),
            ),
            flow_mode=boiler.boilerFlowMode(),
            outlet_temperature_limit_c=boiler.waterOutletUpperTemperatureLimit(),
            sizing_factor=boiler.sizingFactor(),
            ems_actuator_count=len(ems),
            ems_actuators=sorted(ems, key=lambda x: x["handle"])[:8],
            supply_boiler_count=len(loop_ref["boilers"]),
            identities="Boiler, metadata, incoming references, water nodes and connections retained in place",
            sizing_policy="Preserve capacity, flow, sizing factor, part-load ratios, plant sizing, dispatch and controls; no autosizing reset",
        ),
    )
    planned["warnings"].extend(
        [
            "Nominal thermal efficiency is an HHV-based rating, not whole-plant efficiency. No fuel, capacity, flow, part-load, curve, sizing, schedule or dispatch changes are inferred; verify operation separately.",
            "On-cycle parasitic electricity and off-cycle parasitic fuel are separate consumption inputs, not useful water heating; runtime/cycling and retained controls determine their energy use.",
        ]
    )
    if not electric and after["off_cycle_parasitic_fuel_load_w"] > 0:
        planned["warnings"].append(
            "EnergyPlus 25.2 updates ancillary fuel as the configured off-cycle load times (1 - PLR) in the active boiler calculation, and retains the last rate while idle, including later summer periods. It is metered under Heating / Boiler Parasitic; do not interpret this input as a constant idle standby load"
        )
        if boiler.maximumPartLoadRatio() > 1:
            planned["warnings"].append(
                "Retained maximum part-load ratio exceeds one. The pinned off-cycle fuel formula has no zero clamp, so PLR above one can produce negative ancillary fuel; review operating results and retained part-load limits"
            )
    if curve and curve_translated:
        planned["warnings"].append(
            "Retained normalized efficiency curve multiplies nominal efficiency and can vary with part load and water temperature. This edit does not certify its operating envelope or effective efficiency; review curve validity and simulation warnings before interpreting fuel savings"
        )
    elif curve:
        planned["warnings"].append(
            "Configured boiler efficiency curve is not passed to EnergyPlus by this SDK translation. Nominal efficiency alone applies there; inspect the retained curve and its temperature-evaluation field before simulation. This rating edit does not repair curve controls"
        )
        planned["simulation_ready"] = False
    if ems:
        planned["warnings"].append(
            "Retained boiler EMS can override operation; performance inputs alone do not establish realized energy use"
        )
    if len(loop_ref["boilers"]) > 1:
        planned["warnings"].append(
            "Other boilers and plant dispatch remain unchanged; the selected boiler may not carry the full plant load or run at all"
        )
    pumps = [
        x
        for x in loop.supplyComponents()
        if x.iddObjectType().valueName().startswith(("OS_Pump_", "OS_HeaderedPumps_"))
    ]
    if not pumps or not loop.supplyOutletNode().setpointManagers():
        planned["warnings"].append(
            "Existing heating plant lacks an identified supply pump or supply-outlet setpoint manager. Rating edits do not repair plant readiness; review controls and flow before simulation"
        )
        planned["simulation_ready"] = False
    return planned


def edit(model, sdk, planned):
    boiler = boiler_object(model, sdk, planned["resolved_objects"]["boiler"])
    before = values(boiler)
    for key, value in planned["parameters"]["settings"].items():
        call(boiler, "set" + FIELDS[key][0], value)
    return dict(boiler=ref(boiler), before=before, after=values(boiler))


def validate_model(model, sdk, planned, result):
    r = planned["resolved_objects"]
    boiler = boiler_object(model, sdk, r["boiler"])
    loop = model.getPlantLoop(sdk.toUUID(r["plant_loop"]["handle"])).get()
    checks = {
        "Boiler identity/name/class changed": ref(boiler)
        == r["boiler"]
        == result["boiler"],
        "Reported boiler values differ": matches(
            result["before"], planned["before_values"]
        )
        and matches(result["after"], planned["after_values"]),
        "Saved boiler values differ": matches(values(boiler), planned["after_values"]),
        "Unrequested boiler fields changed": signature(
            boiler, planned["parameters"]["settings"]
        )
        == planned["preserved_boiler"],
        "Boiler boundary nodes changed": ports(boiler) == r["ports"],
        "Boiler plant ownership changed": boiler.plantLoop().is_initialized()
        and boiler.plantLoop().get().handle() == loop.handle(),
        "Model objects/handles changed": original_types(model)
        == planned["before_objects"],
        "Protected model objects/references changed": protected_state(
            model, sdk, planned
        ),
        "Plant component order changed": all(
            [str(x.handle()) for x in getattr(loop, side + "Components")()] == order
            for side, order in planned["component_order"].items()
        ),
    }
    if all(checks.values()):
        translated = translated_state(model, sdk, boiler)
        checks["Translated boiler settings differ"] = matches(
            translated["settings"], planned["after_values"]
        )
        checks["Unrequested translated boiler fields changed"] = (
            translated["preserved_fields"] == planned["translated_preserved_fields"]
        )
    return dict(
        ok=all(checks.values()),
        checks=len(checks),
        errors=[message for message, ok in checks.items() if not ok],
    )
