"""Scoped no-reheat terminal class conversion with retained zone branches."""

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

from common.coil_topology import connection_graph, freeze, protected_state
from common.hvac_equipment import call
from common.hvac_inventory import resolve
from common.input_validation import validate
from common.model_preservation import fingerprint
from common.temperature_control import translated_workspace, optional_string
from common.terminal_edit import (
    inventory as terminal_inventory,
    optional,
    ports,
    ref,
    sized,
)
from common.ventilation_context import stable_evidence, zone_requirements
from common.water_coil import object_by_ref, original_types, raw_fields

CLASSES = {
    "VAVNoReheat": "AirTerminalSingleDuctVAVNoReheat",
    "ConstantVolumeNoReheat": "AirTerminalSingleDuctConstantVolumeNoReheat",
}
TYPES = {
    "OS_AirTerminal_SingleDuct_VAV_NoReheat": "VAVNoReheat",
    "OS_AirTerminal_SingleDuct_ConstantVolume_NoReheat": "ConstantVolumeNoReheat",
}
# Both pinned EnergyPlus terminal classes expose this output. VAV-only damper
# and minimum-fraction outputs are deliberately not promised by a CV terminal.
SHARED_OUTPUTS = {"zone air terminal outdoor air volume flow rate"}


def inventory(model):
    result = terminal_inventory(model)
    for row in result["terminals"]:
        row["supported"] = row["type"] in TYPES
    return result


def typed(model, sdk, reference):
    obj = model.getModelObject(sdk.toUUID(reference["handle"]))
    if not obj.is_initialized() or obj.get().iddObjectType().valueName() not in TYPES:
        raise ValueError("Selected no-reheat terminal is missing or unsupported")
    if obj.get().iddObjectType().valueName() != reference["type"]:
        raise ValueError("Selected terminal class changed")
    return getattr(obj.get(), "to_" + CLASSES[TYPES[reference["type"]]])().get()


def settings(terminal):
    result = dict(maximum_airflow_m3_s=sized(terminal, "maximumAirFlowRate"))
    if hasattr(terminal, "zoneMinimumAirFlowInputMethod"):
        result.update(
            minimum_method=optional(terminal.zoneMinimumAirFlowInputMethod()),
            minimum_airflow_fraction=optional(
                terminal.constantMinimumAirFlowFraction()
            ),
            fixed_minimum_airflow_m3_s=sized(terminal, "fixedMinimumAirFlowRate"),
            control_for_outdoor_air=terminal.controlForOutdoorAir(),
            minimum_schedule=optional(terminal.minimumAirFlowFractionSchedule()),
            turndown_schedule=optional(terminal.minimumAirFlowTurndownSchedule()),
        )
        for key in ("minimum_schedule", "turndown_schedule"):
            if result[key] is not None:
                result[key] = ref(result[key])
    return result


def scope_tokens(model, terminal):
    tokens = {str(terminal.handle()): "@terminal"}
    for obj in model.modelObjects():
        if obj.iddObjectType().valueName() != "OS_Connection":
            continue
        fields = dict(raw_fields(obj).values())
        if fields["Target Object"] == str(terminal.handle()):
            tokens[str(obj.handle())] = "@inlet-connection"
        if fields["Source Object"] == str(terminal.handle()):
            tokens[str(obj.handle())] = "@outlet-connection"
    if len(tokens) != 3:
        raise ValueError(
            "Selected terminal requires exactly two direct air connections"
        )
    return tokens


def signatures(model, terminal, handles):
    """Freeze every field, including all other extensible equipment-list slots."""
    tokens = scope_tokens(model, terminal)
    objects = {str(x.handle()): x for x in model.modelObjects()}
    if set(handles) - objects.keys():
        raise ValueError("Retained boundary or equipment-list object is missing")
    return {h: fingerprint(objects[h], tokens) for h in handles}


def translated_signature(model, sdk, terminal):
    workspace = translated_workspace(
        model, sdk, "Cannot verify translated terminal service"
    )
    result = []
    terminals = []
    adus = []
    for obj in workspace.objects():
        kind = obj.iddObject().name()
        name = optional_string(obj, 0)
        values = [optional_string(obj, i) for i in range(obj.numFields())]
        if kind.startswith(("SetpointManager:", "NodeList", "ZoneHVAC:EquipmentList")):
            result.append([kind, values])
        if kind.startswith("AirTerminal:") and name == terminal.nameString():
            terminals.append([kind, values])
        if (
            kind == "ZoneHVAC:AirDistributionUnit"
            and optional_string(obj, 3) == terminal.nameString()
        ):
            adus.append([kind, values])
    if len(terminals) != 1 or len(adus) != 1:
        raise ValueError(
            "Cannot verify one translated terminal and air distribution unit"
        )
    return dict(
        controls_and_equipment=sorted(result),
        terminal=terminals[0],
        air_distribution_unit=adus[0],
    )


def plan(model, sdk, config):
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "references/terminal_replacement.schema.json"
        ).read_text()
    )
    invalid = validate(config, schema)
    if invalid:
        raise ValueError(
            "Invalid terminal replacement configuration: " + "; ".join(invalid)
        )
    required = (
        "air_loop",
        "zone",
        "terminal",
        "target_class",
        "maximum_airflow_m3_s",
        "availability_policy",
        "reheat_policy",
        "zone_sizing_policy",
        "system_sizing_policy",
        "reference_policy",
    )
    planned = dict(
        ready=False,
        parameters=dict(output_model_path=config["output_model_path"]),
        missing_inputs=[x for x in required if x not in config],
        errors=[],
        warnings=[],
        assumptions=[],
    )
    if (
        config.get("target_class") == "VAVNoReheat"
        and "minimum_airflow_fraction" not in config
    ):
        planned["missing_inputs"].append("minimum_airflow_fraction")
    if planned["missing_inputs"]:
        return planned
    errors = planned["errors"]
    if (
        config["target_class"] == "ConstantVolumeNoReheat"
        and "minimum_airflow_fraction" in config
    ):
        errors.append("Constant-volume target must not include a VAV minimum fraction")
    rows = inventory(model)["terminals"]
    for selector, key in (
        ("air_loop", "air_loop"),
        ("zone", "zone"),
        ("terminal", None),
    ):
        candidates = {
            x[key]["handle"] if key else x["handle"]: x[key] if key else x for x in rows
        }
        selected = resolve(
            config[selector], list(candidates.values()), selector, errors
        )
        if selected is None:
            return planned
        rows = [
            x
            for x in rows
            if (x[key]["handle"] if key else x["handle"]) == selected["handle"]
        ]
    if len(rows) != 1 or not rows[0]["supported"]:
        errors.append(
            "Select one connected VAVNoReheat or ConstantVolumeNoReheat terminal; reheat and other terminal classes need separate coverage"
        )
        return planned
    row = rows[0]
    if TYPES[row["type"]] == config["target_class"]:
        errors.append(
            "Select a different terminal class; same-class VAV controls use openstudio-terminal-editor"
        )
        return planned
    old = typed(model, sdk, row)
    before = settings(old)
    if hasattr(old, "controlForOutdoorAir") and (
        before["control_for_outdoor_air"]
        or before["minimum_method"] != "Constant"
        or before["minimum_schedule"]
        or before["turndown_schedule"]
    ):
        errors.append(
            "VAV source must use Constant minimum flow with no minimum/turndown schedules and no terminal outdoor-air control; these controls cannot be retained by the constant-volume target"
        )
    zone = object_by_ref(model, sdk, row["zone"], "ThermalZone")
    loop = object_by_ref(model, sdk, row["air_loop"], "AirLoopHVAC")
    equipment = next(
        x
        for x in model.getZoneHVACEquipmentLists()
        if x.thermalZone().handle() == zone.handle()
    )
    slots = [
        i
        for i, (name, value) in raw_fields(equipment).items()
        if name == "Zone Equipment" and value == str(old.handle())
    ]
    if len(slots) != 1:
        raise ValueError(
            "Cannot identify one zone equipment-list slot for selected terminal"
        )
    metadata = next(
        (
            ref(x)
            for x in model.modelObjects()
            if x.iddObjectType().valueName() == "OS_AdditionalProperties"
            and dict(raw_fields(x).values()).get("Object Name") == str(old.handle())
        ),
        None,
    )
    retained = []
    for obj in model.modelObjects():
        h, kind = str(obj.handle()), obj.iddObjectType().valueName()
        if h == str(old.handle()) or kind == "OS_Connection":
            continue
        fields = raw_fields(obj)
        for i, (name, value) in fields.items():
            if name == "Handle":
                continue
            allowed = (h == str(equipment.handle()) and i == slots[0]) or (
                metadata and h == metadata["handle"] and name == "Object Name"
            )
            if value == str(old.handle()) and not allowed:
                errors.append(
                    "Reference policy Reject: direct reference to removed terminal: "
                    + obj.nameString()
                )
            if value.casefold() == old.nameString().casefold() and name != "Name":
                variable = fields.get(i + 1, ("", ""))[1]
                if (
                    kind == "OS_Output_Variable"
                    and name == "Key Value"
                    and variable.casefold() in SHARED_OUTPUTS
                ):
                    retained.append(ref(obj))
                elif kind == "OS_EnergyManagementSystem_Sensor":
                    errors.append(
                        "Reference policy Reject: EMS sensor blocked by policy, even for a compatible output; retaining EMS control dependencies requires separate coverage: "
                        + obj.nameString()
                    )
                else:
                    errors.append(
                        "Reference policy Reject: incompatible name-keyed terminal reference: "
                        + obj.nameString()
                    )
    if errors:
        return planned
    maximum = config["maximum_airflow_m3_s"]
    if maximum == "Preserve":
        maximum = before["maximum_airflow_m3_s"]
    if maximum is None:
        errors.append(
            "Source maximum flow is unset; choose a fixed maximum or Autosize explicitly"
        )
        return planned
    boundary = ports(old)
    planned.update(
        parameters=deepcopy(config),
        resolved_objects=dict(
            terminal=ref(old),
            air_loop=row["air_loop"],
            zone=row["zone"],
            equipment_list=ref(equipment),
            equipment_slot=slots[0],
            metadata=metadata,
            ports=boundary,
        ),
        before_values=before,
        maximum_airflow_m3_s=maximum,
        retained_output_references=sorted(retained, key=lambda x: x["handle"]),
        before_translation=translated_signature(model, sdk, old),
    )
    planned["weather_was_empty"] = not any(
        value
        for name, value in raw_fields(model.getWeatherFile()).values()
        if name not in ("Handle", "Url", "Checksum")
    )
    preview = sdk.model.Model(model.clone(True))
    result = replace(preview, sdk, planned)
    new = typed(preview, sdk, result["replacement_terminal"])
    target_type = new.iddObjectType().valueName()
    tokens = scope_tokens(preview, new)
    allowed = {h: ["Inlet Port", "Outlet Port"] for h in boundary}
    allowed[str(equipment.handle())] = ["Zone Equipment"]
    if metadata:
        allowed[metadata["handle"]] = ["Object Name"]
    planned.update(
        freeze(
            model,
            preview,
            sdk,
            allowed=allowed,
            removable={str(old.handle())},
            connection_scope={str(old.handle()), *boundary},
            tokens={str(new.handle()): "@terminal"},
            new_types=(target_type, "OS_Connection"),
        )
    )
    removed_counts = Counter(
        planned["before_objects"][h] for h in planned["removed_objects"]
    )
    if planned["added_counts"] != {
        target_type: 1,
        "OS_Connection": 2,
    } or removed_counts != {row["type"]: 1, "OS_Connection": 2}:
        raise ValueError(
            "Terminal conversion must replace exactly one terminal and its two air connections"
        )
    # Named allowances in freeze cover repeated IDD field names. These complete
    # fingerprints additionally pin every slot, priority, schedule and node port.
    planned["mutable_fingerprints"] = signatures(preview, new, allowed)
    if planned["mutable_fingerprints"] != signatures(model, old, allowed):
        raise ValueError(
            "Terminal conversion changes an unrelated boundary, metadata or equipment-list field"
        )
    planned["new_fingerprints"] = {
        tokens[h]: fingerprint(preview.getModelObject(sdk.toUUID(h)).get(), tokens)
        for h in tokens
    }
    planned["after_values"] = settings(new)
    planned["after_translation"] = translated_signature(preview, sdk, new)
    if (
        planned["before_translation"]["controls_and_equipment"]
        != planned["after_translation"]["controls_and_equipment"]
    ):
        raise ValueError(
            "Terminal conversion changes translated controls or zone equipment sequencing"
        )
    nominal = stable_evidence(
        next(
            x["nominal_oa_m3_s"]
            for x in zone_requirements(loop)["zones"]
            if x["zone"]["handle"] == str(zone.handle())
        )
    )
    minimum = (
        maximum * config.get("minimum_airflow_fraction", 1)
        if type(maximum) in (int, float)
        else None
    )
    fans = {
        str(x.handle()): ref(x)
        for x in loop.supplyComponents()
        if x.iddObjectType().valueName().startswith("OS_Fan_")
    }
    supply_fan = loop.supplyFan()
    if supply_fan.is_initialized():
        fan = supply_fan.get()
        fans[str(fan.handle())] = ref(fan)
    planned["retained_supply_fans"] = sorted(fans.values(), key=lambda x: x["handle"])
    for fan in planned["retained_supply_fans"]:
        if fan["type"] == "OS_Fan_SystemModel":
            system_fan = object_by_ref(model, sdk, fan, "FanSystemModel")
            curve = system_fan.electricPowerFunctionofFlowFractionCurve()
            fan.update(
                speed_control_method=system_fan.speedControlMethod(),
                number_of_speeds=system_fan.numberofSpeeds(),
                power_curve=ref(curve.get()) if curve.is_initialized() else None,
            )
    oa = loop.airLoopHVACOutdoorAirSystem()
    methods = dict(
        sizing_system=loop.sizingSystem().systemOutdoorAirMethod(),
        mechanical_ventilation=(
            oa.get()
            .getControllerOutdoorAir()
            .controllerMechanicalVentilation()
            .systemOutdoorAirMethod()
            if oa.is_initialized()
            else None
        ),
    )
    vrp = any(
        "VentilationRateProcedure" in (method or "") for method in methods.values()
    )
    planned["impact"] = dict(
        old_terminal=ref(old),
        target_class=config["target_class"],
        zone=row["zone"],
        air_loop=row["air_loop"],
        before=before,
        after=planned["after_values"],
        new_terminal_identity=True,
        air_nodes_retained=boundary,
        availability_schedule=ref(old.availabilitySchedule()),
        equipment_list_retained=ref(equipment),
        equipment_slot_retained=slots[0],
        metadata_retained=metadata,
        reheat="No coil before or after; no plant changes",
        sizing="Zone/system sizing retained; terminal maximum follows explicit policy",
        zone_nominal_oa_m3_s=nominal,
        zone_multiplier=zone.multiplier(),
        nominal_minimum_supply_flow_m3_s=minimum,
        retained_supply_fans=planned["retained_supply_fans"][:8],
        retained_supply_fan_count=len(fans),
        outdoor_air_methods=methods,
        system_oa_sizing_may_change=vrp,
        retained_output_references=planned["retained_output_references"][:8],
        retained_output_reference_count=len(retained),
        airflow_behavior=(
            "Constant-volume target requests maximum flow whenever available"
            if config["target_class"] == "ConstantVolumeNoReheat"
            else "VAV target modulates with zone cooling load down to the explicit Constant minimum fraction; no reheat"
        ),
        whole_system_conversion=False,
    )
    planned["warnings"].extend(
        [
            "Only this terminal changes class. Supply fan, other terminals, zone/air-system sizing, OA/DCV, schedules and zone service are retained; this is not a whole-system VAV/CAV conversion. Re-run sizing and check operating flow, ventilation and comfort.",
            "Neither terminal has reheat. Constant-volume cold supply can overcool at part load; VAV minimum flow can also overcool when heating is needed. Separate zone heating is not added.",
            "The old terminal and two connections receive new handles; boundary nodes, equipment-list slot and metadata identity are retained. Direct external references are rejected.",
            "Terminal-specific wildcard output requests are retained but variables available only for the old class may disappear; no VAV damper output is promised by the constant-volume target.",
        ]
    )
    if config["target_class"] == "VAVNoReheat":
        for fan in planned["retained_supply_fans"]:
            if fan["type"] == "OS_Fan_ConstantVolume":
                planned["warnings"].append(
                    f"Retained supply fan '{fan['name']}' is OS_Fan_ConstantVolume. With the new VAV terminal, EnergyPlus fan power follows actual flow proportionally at fixed pressure/efficiency, without a variable-volume part-load curve. Terminal conversion alone does not model variable-speed fan savings. Use openstudio-supply-fan-replacer for an explicitly chosen fan-class/curve change."
                )
            elif (
                fan["type"] == "OS_Fan_SystemModel"
                and fan["speed_control_method"] == "Discrete"
            ):
                behavior = (
                    "Single-speed Discrete control cycles on/off to meet average flow, without a continuous variable-speed part-load curve."
                    if fan["number_of_speeds"] == 1
                    else "Multiple Discrete speeds use time-weighted speed-level power; review the retained speed fractions and power inputs/curve rather than assuming a continuous variable-speed part-load curve."
                )
                planned["warnings"].append(
                    f"Retained supply fan '{fan['name']}' is OS_Fan_SystemModel with Discrete speed control. {behavior} Terminal conversion alone does not model continuous variable-speed fan savings. FanSystemModel speed/power edits or class conversion need separate coverage."
                )
    if vrp:
        planned["warnings"].append(
            "Ventilation Rate Procedure is enabled in retained system sizing or mechanical ventilation controls. Its zone minimum-primary-flow calculation depends on terminal airflow; conversion may change the recalculated system outdoor-air requirement even though sizing objects are preserved. Re-run sizing and verify system OA before interpreting ventilation or energy results."
        )
    if maximum == "Autosize":
        planned["warnings"].append(
            "Terminal maximum flow is Autosize; operating flow and ventilation adequacy require sizing and simulation, not this preview"
        )
    elif maximum < nominal - 1e-9:
        planned["warnings"].append(
            "Selected terminal maximum supply flow is below total nominal zone outdoor-air demand, including the zone multiplier; review alternate ventilation or increase capacity before simulation"
        )
        planned["simulation_ready"] = False
    if minimum is not None and minimum < nominal - 1e-9:
        planned["warnings"].append(
            "Nominal supply minimum is below nominal zone OA demand. Supply fraction is not OA fraction; retained system ventilation and alternate sources require separate verification"
        )
    if len(zone.airLoopHVACs()) > 1:
        planned["warnings"].append(
            "Zone has multiple serving air loops; this selected terminal does not establish combined conditioning or ventilation"
        )
    planned["ready"] = True
    return planned


def replace(model, sdk, planned):
    r, p = planned["resolved_objects"], planned["parameters"]
    old = typed(model, sdk, r["terminal"])
    new = getattr(sdk.model, CLASSES[p["target_class"]])(
        model, old.availabilitySchedule()
    )
    maximum = planned["maximum_airflow_m3_s"]
    if maximum == "Autosize":
        new.autosizeMaximumAirFlowRate()
    else:
        call(new, "setMaximumAirFlowRate", maximum)
    if p["target_class"] == "VAVNoReheat":
        call(new, "setZoneMinimumAirFlowInputMethod", "Constant")
        call(new, "setConstantMinimumAirFlowFraction", p["minimum_airflow_fraction"])
        call(new, "setControlForOutdoorAir", False)
    inlet, outlet = [
        object_by_ref(model, sdk, {"handle": h}, "Node") for h in r["ports"]
    ]
    model.disconnect(old, old.inletPort())
    model.disconnect(old, old.outletPort())
    model.connect(inlet, inlet.outletPort(), new, new.inletPort())
    model.connect(new, new.outletPort(), outlet, outlet.inletPort())
    call(
        object_by_ref(model, sdk, r["equipment_list"], "ZoneHVACEquipmentList"),
        "setPointer",
        r["equipment_slot"],
        new.handle(),
    )
    if r["metadata"]:
        metadata = object_by_ref(model, sdk, r["metadata"], "AdditionalProperties")
        index = next(
            i for i, (name, _) in raw_fields(metadata).items() if name == "Object Name"
        )
        call(metadata, "setPointer", index, new.handle())
    old.remove()
    call(new, "setName", r["terminal"]["name"])
    return dict(
        air_loop=r["air_loop"],
        zone=r["zone"],
        removed_terminal=r["terminal"],
        replacement_terminal=ref(new),
        air_nodes=r["ports"],
    )


def validate_model(model, sdk, planned, result):
    errors, checks = [], 0

    def check(ok, message):
        nonlocal checks
        checks += 1
        if not ok:
            errors.append(message)

    r = planned["resolved_objects"]
    terminal = typed(model, sdk, result["replacement_terminal"])
    h = str(terminal.handle())
    check(
        ref(terminal) == result["replacement_terminal"]
        and h not in planned["before_objects"],
        "Replacement terminal identity differs",
    )
    check(
        TYPES[ref(terminal)["type"]] == planned["parameters"]["target_class"],
        "Wrong terminal class",
    )
    check(terminal.nameString() == r["terminal"]["name"], "Terminal name changed")
    check(ports(terminal) == r["ports"], "Terminal air boundary nodes changed")
    zone = object_by_ref(model, sdk, r["zone"], "ThermalZone")
    check(
        h in {str(x.handle()) for x in zone.airLoopHVACTerminals()},
        "Terminal zone service differs",
    )
    check(
        terminal.airLoopHVAC().is_initialized()
        and str(terminal.airLoopHVAC().get().handle()) == r["air_loop"]["handle"],
        "Terminal air-loop service differs",
    )
    check(
        ref(terminal.availabilitySchedule())
        == planned["impact"]["availability_schedule"],
        "Availability schedule changed",
    )
    current, before = original_types(model), planned["before_objects"]
    check(
        sorted(before.keys() - current.keys()) == planned["removed_objects"],
        "Unexpected removed objects",
    )
    check(
        dict(Counter(current[x] for x in current.keys() - before.keys()))
        == planned["added_counts"],
        "Unexpected added objects",
    )
    check(protected_state(model, sdk, planned), "Protected model objects changed")
    check(
        connection_graph(model, {h: "@terminal"}) == planned["connection_graph"],
        "Connection graph differs",
    )
    check(
        signatures(model, terminal, planned["mutable_fingerprints"])
        == planned["mutable_fingerprints"],
        "Boundary, metadata or equipment-list fields differ",
    )
    tokens = scope_tokens(model, terminal)
    check(
        {
            tokens[x]: fingerprint(model.getModelObject(sdk.toUUID(x)).get(), tokens)
            for x in tokens
        }
        == planned["new_fingerprints"],
        "New terminal or connection raw fields differ",
    )
    # Do not hand malformed sequencing/topology to the native translator. It can
    # crash rather than return errors for an invalid EquipmentList sequence.
    if errors:
        return dict(ok=False, checks=checks, errors=errors)
    check(
        translated_signature(model, sdk, terminal) == planned["after_translation"],
        "Translated terminal, distribution unit, sequencing or temperature controls differ",
    )
    check(
        result
        == dict(
            air_loop=r["air_loop"],
            zone=r["zone"],
            removed_terminal=r["terminal"],
            replacement_terminal=ref(terminal),
            air_nodes=r["ports"],
        ),
        "Reported terminal mapping differs",
    )
    return dict(ok=not errors, checks=checks, errors=errors)
