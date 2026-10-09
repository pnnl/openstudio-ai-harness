"""Bounded prototype CAV recipe composed from shared multizone modules."""

from __future__ import annotations
from copy import deepcopy
import json
import math
from pathlib import Path
from common.input_validation import validate
from common.hvac_inventory import inventory
from common.multizone_plan import (
    PROFILE as BASE_PROFILE,
    CONTROLS as BASE_CONTROLS,
    PROFILE_NOTES as BASE_NOTES,
    plan as resolve_plan,
    assumption_review,
)
from common.multizone_assembly import assemble
from common.air_system_recipe import PROTOTYPE_CAV as RECIPE
from common.air_loop_validate import counts, validate_model as check_model

PROFILE = deepcopy(BASE_PROFILE)
PROFILE.update(
    minimum_system_airflow_ratio=1.0,
    outdoor_air_schedule=None,
)
PROFILE["design_temperatures_c"].update(
    central_heating=(62 - 32) * 5 / 9, zone_heating=50.0
)
CONTROLS = deepcopy(BASE_CONTROLS)
for key in (
    "fan_power_minimum_flow_fraction",
    "fan_power_minimum_flow_input_method",
    "fan_power_coefficients",
    "gas_burner_efficiency",
    "electric_coil_efficiency",
    "gas_on_cycle_parasitic_electric_w",
    "gas_off_cycle_parasitic_gas_w",
):
    del CONTROLS[key]
CONTROLS.update(
    fan_end_use_subcategory="CAV System Fans",
    night_cycle_runtime_seconds=3600,
    damper_heating_action="ReverseWithLimits",
    terminal_maximum_reheat_flow_per_area=0.0,
    terminal_maximum_reheat_flow_fraction=0.5,
)
NOTES = dict(
    BASE_NOTES,
    damper_profile="generic 0.3 minimum, Dual Maximum HW reheat; no template/building override",
    oa_schedule_role="minimum fraction, not minimum outdoor-air flow",
    airflow_scope="constant-volume supply fan with VAV-reheat terminals; not fixed airflow in every zone",
)
PROFILE_NAME = "prototype_cav_v1"


def outdoor_air_policy(model, sdk, config, catalog):
    if "outdoor_air_schedule" not in config:
        return dict(
            meaning="Outdoor-air choice required: null for ZoneSum minimum ventilation, or an explicit minimum-fraction schedule",
            all_outdoor_air_sizing=False,
            choice_required=True,
        )
    selector = config["outdoor_air_schedule"]
    if selector is None:
        return dict(
            meaning="ZoneSum minimum ventilation; no additional minimum outdoor-air fraction",
            all_outdoor_air_sizing=False,
            choice_required=False,
        )
    fraction = None
    if selector.get("builtin") == "AlwaysOnDiscrete":
        fraction = 1.0
    else:
        key = "handle" if "handle" in selector else "name"
        matches = [x for x in catalog["schedules"] if x[key] == selector[key]]
        if len(matches) == 1:
            sch = (
                model.getSchedule(sdk.toUUID(matches[0]["handle"]))
                .get()
                .to_ScheduleConstant()
            )
            if sch.is_initialized():
                fraction = sch.get().value()
                if not math.isfinite(fraction) or not 0 <= fraction <= 1:
                    raise ValueError("CAV outdoor-air fraction must lie within [0,1]")
    if fraction == 1:
        meaning = "100% outdoor air whenever the system runs; heating and cooling sized for all outdoor air"
    elif fraction == 0:
        meaning = (
            "Zero additional fraction floor; ZoneSum minimum ventilation still applies"
        )
    else:
        meaning = (
            (
                f"Minimum outdoor-air fraction {fraction:g}; "
                if fraction is not None
                else "Variable or unclassified minimum outdoor-air fraction schedule; "
            )
            + "conservatively size heating and cooling for 100% outdoor air; this can oversize coils at lower fractions"
        )
    return dict(
        meaning=meaning,
        all_outdoor_air_sizing=fraction != 0,
        constant_minimum_fraction=fraction,
        choice_required=False,
    )


def schema():
    # Shared input vocabulary has one source; only CAV-specific constraints differ.
    root = Path(__file__).resolve().parents[1] / "references/vav_input.schema.json"
    result = json.loads(root.read_text(encoding="utf-8"))
    result["title"] = "Prototype CAV input (partial review allowed)"
    props = result["properties"]
    props["defaults_profile"]["enum"] = [PROFILE_NAME]
    for role in ("central_heating", "reheat"):
        props[role]["properties"]["type"]["enum"] = ["Water"]
        del props[role]["properties"]["dx_approved"]
    props["return_plenum"] = {"type": "null"}
    props["minimum_system_airflow_ratio"] = {"enum": [1.0], "type": "number"}
    return result


def plan(model, sdk, config):
    errors = validate(config, schema())
    if errors:
        raise ValueError(f"Invalid CAV configuration: {errors}")
    catalog = inventory(model)
    oa_policy = outdoor_air_policy(model, sdk, config, catalog)
    controls = dict(
        CONTROLS,
        all_outdoor_air_cooling=oa_policy["all_outdoor_air_sizing"],
        all_outdoor_air_heating=oa_policy["all_outdoor_air_sizing"],
    )
    notes = dict(NOTES, outdoor_air_operation=oa_policy["meaning"])
    # The transaction independently checks actual input/output paths and hashes.
    planned = resolve_plan(
        config,
        catalog,
        None,
        profile_name=PROFILE_NAME,
        profile=PROFILE,
        controls=controls,
        notes=notes,
    )
    if oa_policy["choice_required"]:
        planned["missing_inputs"].append(
            "outdoor_air_schedule: explicitly choose minimum ventilation (null) or a fraction schedule"
        )
        planned["ready"] = False
    if oa_policy.get("constant_minimum_fraction") == 1:
        planned["warnings"].append(
            "100% outdoor air: economizer selection cannot increase the outdoor-air fraction; both all-outdoor-air sizing flags are enabled"
        )
    elif oa_policy["all_outdoor_air_sizing"]:
        planned["warnings"].append(oa_policy["meaning"])
    planned["outdoor_air_policy"] = oa_policy
    planned["system_kind"] = RECIPE.system_kind
    planned["before_counts"] = counts(model, recipe=RECIPE)
    planned["assumption_review"] = assumption_review(
        config,
        profile_name=PROFILE_NAME,
        profile=PROFILE,
        controls=controls,
        notes=notes,
    )
    for row in planned["assumption_review"]["inputs"]:
        if row["field"] == "outdoor_air_schedule":
            row["meaning"] = oa_policy["meaning"]
            if oa_policy["choice_required"]:
                row["source"] = "requires_user_choice"
        if row["field"] in ("minimum_system_airflow_ratio", "return_plenum"):
            row["editable"] = False
    return planned


def create(model, sdk, planned):
    return {
        "air_loop_handle": assemble(
            model,
            sdk,
            planned,
            recipe=RECIPE,
        )
    }


def validate_model(model, sdk, planned, result):
    return check_model(
        model,
        sdk,
        planned,
        result["air_loop_handle"],
        planned["before_counts"],
        recipe=RECIPE,
    )
