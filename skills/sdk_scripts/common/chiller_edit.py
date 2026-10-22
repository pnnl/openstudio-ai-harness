"""Reference-COP edits preserve an EIR chiller and its complete model graph."""

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


def ref(obj):
    return dict(
        handle=str(obj.handle()),
        name=obj.nameString(),
        type=obj.iddObjectType().valueName(),
    )


def supported(obj, loop):
    typed = obj.to_ChillerElectricEIR()
    if not typed.is_initialized() or loop.sizingPlant().loopType() != "Cooling":
        return False
    chiller = typed.get()
    return (
        chiller.condenserType() in ("AirCooled", "WaterCooled")
        and not chiller.heatRecoveryLoop().is_initialized()
        and not chiller.thermosiphonCapacityFractionCurve().is_initialized()
    )


def inventory(model):
    return dict(
        plant_loops=sorted(
            [
                dict(
                    ref(loop),
                    loop_type=loop.sizingPlant().loopType(),
                    chillers=sorted(
                        [
                            dict(ref(obj), supported=supported(obj, loop))
                            for obj in loop.supplyComponents()
                            if obj.iddObjectType().valueName().startswith("OS_Chiller_")
                        ],
                        key=lambda x: (x["name"], x["handle"]),
                    ),
                )
                for loop in model.getPlantLoops()
            ],
            key=lambda x: (x["name"], x["handle"]),
        )
    )


def chiller_object(model, sdk, reference):
    optional = model.getChillerElectricEIR(sdk.toUUID(reference["handle"]))
    if not optional.is_initialized():
        raise ValueError("Selected EIR chiller is missing or its class changed")
    return optional.get()


def values(chiller):
    return dict(reference_cop=chiller.referenceCOP())


def matches(actual, expected):
    return actual.keys() == expected.keys() and all(
        type(actual[key]) in (int, float)
        and math.isclose(actual[key], value, rel_tol=1e-9, abs_tol=1e-9)
        for key, value in expected.items()
    )


def signature(chiller):
    return fingerprint(chiller, ignored=["Reference COP"])


def sized(chiller, suffix):
    if getattr(chiller, "is" + suffix + "Autosized")():
        return "Autosize"
    value = getattr(chiller, suffix[0].lower() + suffix[1:])()
    return value.get() if value.is_initialized() else None


def connections(chiller):
    result = {}
    for side in ("supply", "demand", "tertiary"):
        result[side] = []
        for port in ("Inlet", "Outlet"):
            obj = getattr(chiller, side + port + "ModelObject")()
            result[side].append(
                str(obj.get().handle()) if obj.is_initialized() else None
            )
    if not all(result["supply"]):
        raise ValueError(
            "Chiller requires connected chilled-water inlet and outlet nodes"
        )
    return result


def translated_state(model, sdk, chiller):
    workspace = translated_workspace(model, sdk, "Cannot verify translated chiller")
    objects = [
        obj
        for obj in workspace.getObjectsByType(sdk.IddObjectType("Chiller_Electric_EIR"))
        if obj.nameString() == chiller.nameString()
    ]
    if len(objects) != 1:
        raise ValueError("Cannot identify one translated electric EIR chiller")
    obj = objects[0]
    index = obj.iddObject().getFieldIndex("Reference COP")
    if not index.is_initialized():
        raise ValueError("Translated chiller is missing Reference COP")
    value = obj.getDouble(index.get())
    if not value.is_initialized():
        raise ValueError("Translated chiller Reference COP is not numeric")
    return dict(
        settings=dict(reference_cop=value.get()),
        preserved_fields=[
            [obj.iddObject().getField(i).get().name(), optional_string(obj, i)]
            for i in range(obj.numFields())
            if i != index.get()
        ],
    )


def loop_context(loop):
    return dict(
        ref(loop),
        loop_type=loop.sizingPlant().loopType(),
        supply_pump_present=any(
            obj.iddObjectType()
            .valueName()
            .startswith(("OS_Pump_", "OS_HeaderedPumps_"))
            for obj in loop.supplyComponents()
        ),
        outlet_setpoint_present=bool(loop.supplyOutletNode().setpointManagers()),
    )


def condenser_sizing(chiller, condenser):
    equipment = []
    if condenser is not None:
        for obj in condenser.supplyComponents():
            if (
                not obj.iddObjectType()
                .valueName()
                .startswith(("OS_Pump_", "OS_HeaderedPumps_", "OS_CoolingTower_"))
            ):
                continue
            fields = []
            for index in range(obj.numFields()):
                # Blank pump fields can inherit Autosize from the pinned IDD.
                effective = obj.getString(index, True)
                value = (
                    effective.get().strip().lower()
                    if effective.is_initialized()
                    else ""
                )
                if value in ("autosize", "autocalculate"):
                    fields.append(
                        dict(
                            field=obj.iddObject().getField(index).get().name(),
                            sizing_method=value,
                        )
                    )
            if fields:
                equipment.append(dict(ref(obj), sizing_fields=fields))
    return dict(
        reference_condenser_flow_autosized=chiller.isReferenceCondenserFluidFlowRateAutosized(),
        autosized_equipment=sorted(equipment, key=lambda x: (x["name"], x["handle"])),
    )


def plan(model, sdk, config):
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "references/chiller_performance.schema.json"
        ).read_text()
    )
    errors = validate(config, schema)
    if errors:
        raise ValueError(
            "Invalid chiller performance configuration: " + "; ".join(errors)
        )
    planned = dict(
        ready=False,
        simulation_ready=False,
        simulation_readiness_scope="operation_and_companions",
        parameters=dict(output_model_path=config["output_model_path"]),
        missing_inputs=[
            key for key in ("plant_loop", "chiller", "settings") if not config.get(key)
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
        config["chiller"], loop_ref["chillers"], "chiller", planned["errors"]
    )
    if selected is None:
        return planned
    if not selected["supported"]:
        planned["errors"].append(
            "Select an air- or water-cooled ChillerElectricEIR on a Cooling plant supply side without connected heat recovery or thermosiphon; other classes/modes require separate coverage"
        )
        return planned
    chiller = chiller_object(model, sdk, selected)
    loop = model.getPlantLoop(sdk.toUUID(loop_ref["handle"])).get()
    if (
        not chiller.plantLoop().is_initialized()
        or chiller.plantLoop().get().handle() != loop.handle()
    ):
        raise ValueError("Selected chiller chilled-water plant ownership differs")
    before, after = values(chiller), dict(config["settings"])
    if after["reference_cop"] < 2 or after["reference_cop"] > 10:
        planned["warnings"].append(
            "Requested reference COP is outside the typical review range 2–10. Confirm units and rating conditions: COP = 3.517 / (kW per ton); COP = EER / 3.412. This is a non-blocking plausibility warning, not a standards limit; the explicit COP is retained without conversion"
        )
    if matches(before, after):
        planned["errors"].append("Edit must change reference COP")
        return planned
    translated = translated_state(model, sdk, chiller)
    if not matches(translated["settings"], before):
        planned["errors"].append(
            "Source chiller COP disagrees with EnergyPlus translation; diagnose the source model before editing"
        )
        return planned
    condenser = chiller.secondaryPlantLoop()
    condenser = condenser.get() if condenser.is_initialized() else None
    curves = {
        key: ref(getattr(chiller, method)())
        for key, method in (
            ("capacity_temperature", "coolingCapacityFunctionOfTemperature"),
            (
                "eir_temperature",
                "electricInputToCoolingOutputRatioFunctionOfTemperature",
            ),
            ("eir_part_load", "electricInputToCoolingOutputRatioFunctionOfPLR"),
        )
    }
    translated_fields = dict(translated["preserved_fields"])
    curve_fields = dict(
        capacity_temperature="Cooling Capacity Function of Temperature Curve Name",
        eir_temperature="Electric Input to Cooling Output Ratio Function of Temperature Curve Name",
        eir_part_load="Electric Input to Cooling Output Ratio Function of Part Load Ratio Curve Name",
    )
    if any(
        translated_fields.get(curve_fields[key]) != value["name"]
        for key, value in curves.items()
    ):
        planned["errors"].append(
            "Required chiller performance curves do not survive translation; diagnose the source model before editing"
        )
        return planned
    ems = []
    for actuator in model.getEnergyManagementSystemActuators():
        component = actuator.actuatedComponent()
        if component.is_initialized() and component.get().handle() == chiller.handle():
            ems.append(ref(actuator))
    protection = dict(excluded=[str(chiller.handle())], ignored={}, field_limits={})
    protected = snapshot(model, **protection)
    planned.update(
        ready=True,
        simulation_ready=True,
        parameters=dict(output_model_path=config["output_model_path"], settings=after),
        resolved_objects=dict(
            plant_loop=ref(loop),
            chiller=ref(chiller),
            ports=connections(chiller),
            condenser_loop=ref(condenser) if condenser else None,
        ),
        before_values=before,
        after_values=after,
        preserved_chiller=signature(chiller),
        before_objects=original_types(model),
        protection=protection,
        protected_objects=protected,
        translated_preserved_fields=translated["preserved_fields"],
        impact=dict(
            chiller=ref(chiller),
            plant_loop=loop_context(loop),
            condenser_loop=loop_context(condenser) if condenser else None,
            condenser_type=chiller.condenserType(),
            condenser_sizing=(
                condenser_sizing(chiller, condenser)
                if chiller.condenserType() == "WaterCooled"
                else None
            ),
            before=before,
            after=after,
            reference_capacity_w=sized(chiller, "ReferenceCapacity"),
            reference_chilled_water_flow_m3_s=sized(
                chiller, "ReferenceChilledWaterFlowRate"
            ),
            reference_condenser_flow_m3_s=sized(
                chiller, "ReferenceCondenserFluidFlowRate"
            ),
            reference_leaving_chilled_water_temperature_c=chiller.referenceLeavingChilledWaterTemperature(),
            reference_entering_condenser_temperature_c=chiller.referenceEnteringCondenserFluidTemperature(),
            curves=curves,
            part_load_ratios=dict(
                minimum=chiller.minimumPartLoadRatio(),
                maximum=chiller.maximumPartLoadRatio(),
                optimum=chiller.optimumPartLoadRatio(),
                minimum_unloading=chiller.minimumUnloadingRatio(),
            ),
            flow_mode=chiller.chillerFlowMode(),
            sizing_factor=chiller.sizingFactor(),
            condenser_fan_power_ratio=chiller.condenserFanPowerRatio(),
            compressor_heat_rejection_fraction=chiller.fractionofCompressorElectricConsumptionRejectedbyCondenser(),
            ems_actuator_count=len(ems),
            ems_actuators=sorted(ems, key=lambda x: x["handle"])[:8],
            supply_chiller_count=len(loop_ref["chillers"]),
            preservation_policy="Retain chiller, curves, sizing, all water circuits, plant controls, dispatch, references and identities; no Autosize reset",
        ),
    )
    planned["warnings"].append(
        "Reference COP is cooling watts per electric watt at the retained reference conditions, not IPLV, seasonal or whole-plant COP. Retained temperature/part-load curves, cycling, condenser conditions and auxiliaries determine operating energy; this edit does not certify the curve envelope or savings"
    )
    if ems:
        planned["warnings"].append(
            "Retained chiller EMS can override operation; inspect operating results"
        )
    if len(loop_ref["chillers"]) > 1:
        planned["warnings"].append(
            "Other chillers and plant dispatch are retained; the selected chiller may not carry the full cooling load or run"
        )
    contexts = [loop_context(loop)]
    if chiller.condenserType() == "WaterCooled":
        sizing = planned["impact"]["condenser_sizing"]
        if sizing["reference_condenser_flow_autosized"]:
            planned["warnings"].append(
                "Condenser flow is autosized. Changing reference COP changes condenser heat rejection and can resize condenser flow, autosized pumps and cooling towers on the next sizing run. Review the listed autosized condenser equipment and its energy use; unchanged sizing inputs do not imply unchanged sizes, and chiller electricity savings are not whole-plant savings"
            )
        elif sizing["autosized_equipment"]:
            planned["warnings"].append(
                "Condenser pumps or cooling towers retain autosized fields listed in the impact. Changing COP changes heat rejection; calculated equipment sizes and plant energy can change after sizing even though sizing inputs are preserved. Chiller electricity savings are not whole-plant savings"
            )
        if condenser is None:
            planned["warnings"].append(
                "Water-cooled chiller lacks a connected condenser plant; COP edits do not repair heat rejection"
            )
            planned["simulation_ready"] = False
        else:
            contexts.append(loop_context(condenser))
            if not any(
                obj.iddObjectType()
                .valueName()
                .startswith(
                    (
                        "OS_CoolingTower_",
                        "OS_FluidCooler_",
                        "OS_EvaporativeFluidCooler_",
                        "OS_DistrictCooling",
                        "OS_PlantComponent_TemperatureSource",
                    )
                )
                for obj in condenser.supplyComponents()
            ):
                planned["warnings"].append(
                    "Condenser plant has no identified heat-rejection source; inspect heat rejection before simulation"
                )
                planned["simulation_ready"] = False
    elif condenser is not None:
        planned["warnings"].append(
            "Air-cooled chiller retains a condenser plant connection inconsistent with its condenser type; review before simulation"
        )
        planned["simulation_ready"] = False
    if any(
        not item["supply_pump_present"] or not item["outlet_setpoint_present"]
        for item in contexts
    ):
        planned["warnings"].append(
            "An existing chilled/condenser plant lacks an identified supply pump or outlet setpoint manager; rating edits do not repair flow or controls"
        )
        planned["simulation_ready"] = False
    return planned


def edit(model, sdk, planned):
    chiller = chiller_object(model, sdk, planned["resolved_objects"]["chiller"])
    before = values(chiller)
    call(chiller, "setReferenceCOP", planned["after_values"]["reference_cop"])
    return dict(chiller=ref(chiller), before=before, after=values(chiller))


def validate_model(model, sdk, planned, result):
    r = planned["resolved_objects"]
    chiller = chiller_object(model, sdk, r["chiller"])
    condenser = chiller.secondaryPlantLoop()
    condenser_ref = ref(condenser.get()) if condenser.is_initialized() else None
    checks = {
        "Chiller identity/name/class changed": ref(chiller)
        == r["chiller"]
        == result["chiller"],
        "Reported chiller values differ": matches(
            result["before"], planned["before_values"]
        )
        and matches(result["after"], planned["after_values"]),
        "Saved chiller COP differs": matches(values(chiller), planned["after_values"]),
        "Unrequested chiller fields changed": signature(chiller)
        == planned["preserved_chiller"],
        "Chiller circuit boundaries changed": connections(chiller) == r["ports"],
        "Chiller chilled-water plant changed": chiller.plantLoop().is_initialized()
        and str(chiller.plantLoop().get().handle()) == r["plant_loop"]["handle"],
        "Chiller condenser plant changed": condenser_ref == r["condenser_loop"],
        "Model objects/handles changed": original_types(model)
        == planned["before_objects"],
        "Protected model objects/references changed": protected_state(
            model, sdk, planned
        ),
    }
    if all(checks.values()):
        translated = translated_state(model, sdk, chiller)
        checks["Translated chiller COP differs"] = matches(
            translated["settings"], planned["after_values"]
        )
        checks["Unrequested translated chiller fields changed"] = (
            translated["preserved_fields"] == planned["translated_preserved_fields"]
        )
    return dict(
        ok=all(checks.values()),
        checks=len(checks),
        errors=[message for message, ok in checks.items() if not ok],
    )
