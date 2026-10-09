"""Explicit HVAC selection, cascade preview, and saved preservation checks."""

from __future__ import annotations
import hashlib


def ref(obj):
    return dict(
        name=obj.nameString(),
        handle=str(obj.handle()),
        type=obj.iddObjectType().valueName(),
    )


def inventory(model):
    air = [
        dict(ref(x), zones=[ref(z) for z in x.thermalZones()])
        for x in model.getAirLoopHVACs()
    ]
    vrf = [
        dict(
            ref(x),
            zones=[
                ref(t.thermalZone().get())
                for t in x.terminals()
                if t.thermalZone().is_initialized()
            ],
            terminals=[ref(t) for t in x.terminals()],
        )
        for x in model.getAirConditionerVariableRefrigerantFlows()
    ]
    equipment = [
        dict(ref(x), zone=ref(z))
        for z in model.getThermalZones()
        for x in z.equipment()
    ]
    return dict(
        air_loops=sorted(air, key=lambda x: x["handle"]),
        vrf_systems=sorted(vrf, key=lambda x: x["handle"]),
        zone_equipment=sorted(equipment, key=lambda x: x["handle"]),
        plant_loops=[ref(x) for x in model.getPlantLoops()],
    )


def protected(model):
    # Root HVAC removal must not alter geometry, loads, constructions or schedules.
    prefixes = (
        "OS_Space",
        "OS_Surface",
        "OS_SubSurface",
        "OS_Building",
        "OS_Construction",
        "OS_Material",
        "OS_People",
        "OS_Lights",
        "OS_ElectricEquipment",
        "OS_GasEquipment",
        "OS_Schedule",
        "OS_Thermostat",
        "OS_DesignDay",
    )
    return {
        str(x.handle()): hashlib.sha256(str(x).encode()).hexdigest()
        for x in model.modelObjects()
        if x.iddObjectType().valueName().startswith(prefixes)
    }


def zone_state(model):
    return {
        str(z.handle()): dict(
            name=z.nameString(),
            multiplier=z.multiplier(),
            ideal=z.useIdealAirLoads(),
            thermostat=(
                str(z.thermostatSetpointDualSetpoint().get().handle())
                if z.thermostatSetpointDualSetpoint().is_initialized()
                else None
            ),
            equipment=sorted(str(x.handle()) for x in z.equipment()),
            air_loops=sorted(str(x.handle()) for x in z.airLoopHVACs()),
        )
        for z in model.getThermalZones()
    }


def plant_state(model):
    return {
        str(p.handle()): dict(
            name=p.nameString(),
            sizing=str(p.sizingPlant()),
            supply={str(x.handle()): str(x) for x in p.supplyComponents()},
        )
        for p in model.getPlantLoops()
    }


def remove(model, sdk, planned):
    before = {str(x.handle()): ref(x) for x in model.modelObjects()}
    for key in ("air_loops", "vrf_systems", "zone_equipment"):
        for selected in planned["parameters"][key]:
            obj = model.getModelObject(sdk.toUUID(selected["handle"]))
            # Selecting a loop/system also selects its terminals; don't remove twice.
            if obj.is_initialized():
                obj.get().remove()
    after = {str(x.handle()) for x in model.modelObjects()}
    return [before[h] for h in sorted(before.keys() - after)]


def plan(model, sdk, config):
    keys = {"output_model_path", "air_loops", "vrf_systems", "zone_equipment"}
    if config.keys() - keys:
        raise ValueError(
            "Select explicit air_loops, vrf_systems or zone_equipment; plants are preserved"
        )
    catalog = inventory(model)
    selected = {}
    seen = set()
    affected = {}
    for key in ("air_loops", "vrf_systems", "zone_equipment"):
        requests = config.get(key, [])
        if not isinstance(requests, list):
            raise ValueError(f"{key} must be a list")
        selected[key] = []
        for request in requests:
            if (
                not isinstance(request, dict)
                or len(request) != 1
                or not request.keys() <= {"name", "handle"}
            ):
                raise ValueError(
                    "Every selector must contain exactly one name or handle"
                )
            field, value = next(iter(request.items()))
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Empty selector")
            matches = [x for x in catalog[key] if x[field] == value]
            if len(matches) != 1:
                raise ValueError(f"Missing or ambiguous {key}: {value}; use a handle")
            item = matches[0]
            if item["handle"] in seen:
                raise ValueError("Duplicate selection")
            seen.add(item["handle"])
            selected[key].append(item)
            for z in item.get("zones", [item["zone"]] if "zone" in item else []):
                affected[z["handle"]] = z
    if not seen:
        raise ValueError("Select at least one HVAC object; no implicit remove-all")
    # Reject accidental extra selections that are already covered by a selected root.
    owned = {t["handle"] for v in selected["vrf_systems"] for t in v["terminals"]}
    owned.update(
        x["handle"]
        for x in catalog["zone_equipment"]
        if x["zone"]["handle"]
        in {z["handle"] for a in selected["air_loops"] for z in a["zones"]}
        and x["type"].startswith("OS_AirTerminal_")
    )
    if owned.intersection(x["handle"] for x in selected["zone_equipment"]):
        raise ValueError(
            "A selected terminal is already covered by its selected system"
        )
    preview = model.clone(True).to_Model()
    planned = dict(
        parameters=selected,
        resolved_objects={},
        assumptions=[
            "Remove only explicitly selected roots and their SDK-owned cascades; preserve plants, geometry, loads, schedules and thermostats."
        ],
    )
    removed = remove(preview, sdk, planned)
    if protected(preview) != protected(model) or plant_state(preview) != plant_state(
        model
    ):
        raise ValueError(
            "Removal would alter protected objects or plant supply equipment; unsupported scope"
        )
    planned.update(
        removed_objects=removed,
        protected_objects=protected(model),
        remaining_zones=zone_state(preview),
        preserved_plants=plant_state(model),
        remaining_roots={
            k: [x["handle"] for x in inventory(preview)[k]]
            for k in ("air_loops", "vrf_systems")
        },
        impact=dict(
            affected_zones=sorted(affected.values(), key=lambda z: z["handle"]),
            removed_object_count=len(removed),
        ),
    )
    return planned


def validate_model(model, sdk, planned, result):
    errors = []

    def test(ok, text):
        if not ok:
            errors.append(text)

    test(
        result == planned["removed_objects"],
        "Removal cascade differs from approved preview",
    )
    test(
        protected(model) == planned["protected_objects"],
        "Protected geometry/load/schedule/thermostat objects changed",
    )
    test(
        zone_state(model) == planned["remaining_zones"],
        "Zone HVAC membership/thermostat/multiplier differs",
    )
    test(
        plant_state(model) == planned["preserved_plants"],
        "Plant supply equipment or sizing changed",
    )
    catalog = inventory(model)
    for k, handles in planned["remaining_roots"].items():
        test(
            sorted(x["handle"] for x in catalog[k]) == sorted(handles),
            "Unselected system removed",
        )
    remaining = {str(x.handle()) for x in model.modelObjects()}
    test(
        not remaining.intersection(x["handle"] for x in result),
        "Selected objects remain",
    )
    return dict(ok=not errors, checks=7, errors=errors)
