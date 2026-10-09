"""Deterministic preview guards for bounded direct outdoor-air attachments."""

import json
from common.hvac_inventory import resolve
from common.hvac_equipment import by_handle
from common.outdoor_air import ref
from common.ventilation_context import schedule_bounds
from collections import Counter
from common.coil_topology import freeze, connection_graph, protected_state
from common.model_preservation import fingerprint
from common.water_coil import original_types, raw_fields


def normalized_new(model, before):
    objects = {str(x.handle()): x for x in model.modelObjects()}
    new = original_types(model).keys() - before.keys()
    tokens = {}
    for handle in new:
        obj = objects[handle]
        if obj.iddObjectType().valueName() != "OS_Connection":
            role = "@new:" + obj.iddObjectType().valueName() + ":" + obj.nameString()
            if role in tokens.values():
                raise ValueError(
                    "New attachment objects need unique deterministic names"
                )
            tokens[handle] = role
    for handle in new:
        obj = objects[handle]
        if obj.iddObjectType().valueName() == "OS_Connection":
            fields = dict(raw_fields(obj).values())
            edge = [
                tokens.get(fields[k], fields[k])
                for k in ("Source Object", "Outlet Port", "Target Object", "Inlet Port")
            ]
            role = "@connection:" + json.dumps(edge)
            if role in tokens.values():
                raise ValueError("Duplicate attachment connection")
            tokens[handle] = role
    return tokens, {tokens[h]: fingerprint(objects[h], tokens) for h in new}


def preview_guard(model, preview, sdk, allowed, scope, new_types):
    before = original_types(model)
    tokens, fingerprints = normalized_new(preview, before)
    result = freeze(
        model,
        preview,
        sdk,
        allowed=allowed,
        removable=set(),
        connection_scope=scope,
        tokens=tokens,
        new_types=new_types,
    )
    result["new_fingerprints"] = fingerprints
    result["changed_fingerprints"] = {
        h: fingerprint(preview.getModelObject(sdk.toUUID(h)).get(), tokens)
        for h in allowed
    }
    return result


def verify_guard(model, sdk, planned):
    guard = planned["topology"]
    current = original_types(model)
    new = current.keys() - guard["before_objects"].keys()
    tokens, fingerprints = normalized_new(model, guard["before_objects"])
    return {
        "Protected model changed": protected_state(model, sdk, dict(planned, **guard)),
        "Removed object set changed": sorted(
            guard["before_objects"].keys() - current.keys()
        )
        == guard["removed_objects"],
        "Added object counts changed": dict(Counter(current[h] for h in new))
        == guard["added_counts"],
        "New equipment, controls or curves changed": fingerprints
        == guard["new_fingerprints"],
        "Approved boundary/controller fields differ": all(
            model.getModelObject(sdk.toUUID(h)).is_initialized()
            and fingerprint(model.getModelObject(sdk.toUUID(h)).get(), tokens)
            == expected
            for h, expected in guard["changed_fingerprints"].items()
        ),
        "Connection graph differs from preview": connection_graph(model, tokens)
        == guard["connection_graph"],
    }


def schedule(model, sdk, selector, errors):
    selected = resolve(
        selector,
        [ref(x) for x in model.getSchedules()],
        "availability_schedule",
        errors,
    )
    if selected is None:
        return None
    obj = by_handle(model, sdk, selected, "Schedule")
    bounds = schedule_bounds(obj)
    if (
        bounds["unit_type"] not in ("Availability", "Dimensionless")
        or not bounds["verified"]
        or bounds["minimum"] < 0
        or bounds["maximum"] > 1
    ):
        errors.append(
            "Availability must be an existing typed Constant/Ruleset schedule with values in [0,1]"
        )
    return ref(obj)
