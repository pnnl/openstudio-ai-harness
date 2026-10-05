"""Apply a reviewed VAV preflight plan; publish only independently validated OSM."""

from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.version_guard import require_sdk, release_version
from common.input_validation import validate
from common.vav_inventory import inventory
from common.vav_plan import plan
from common.vav_create import create
from common.vav_validate import counts, validate_model
from vav_preflight import unique_object, reject_constant


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply(plan_path: Path) -> dict:
    sdk = require_sdk()  # Check before reading the plan or the model.
    reviewed = json.loads(
        plan_path.read_text(encoding="utf-8"),
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )
    if (
        reviewed.get("plan_version") != 2
        or release_version(str(reviewed.get("openstudio_version", ""))) != "3.11.0"
    ):
        raise ValueError("Unsupported plan version; rerun bundled preflight")
    if (
        reviewed.get("ready") is not True
        or reviewed.get("ok") is not True
        or reviewed.get("mode") != "inspect_only"
    ):
        raise ValueError("Apply requires a ready preflight plan")
    source = Path(reviewed["input_model_path"])
    if (
        not source.is_absolute()
        or not source.is_file()
        or source.suffix.lower() != ".osm"
    ):
        raise ValueError("Plan input must be an existing absolute .osm path")
    original = digest(source)
    if original != reviewed["input_sha256"]:
        raise ValueError("Stale input hash; rerun preflight before applying")
    config = reviewed["configuration"]
    schema = json.loads(
        (
            Path(__file__).resolve().parent / "references/vav_input.schema.json"
        ).read_text()
    )
    errors = validate(config, schema)
    if errors:
        raise ValueError(f"Invalid plan configuration: {errors}")
    loaded = sdk.osversion.VersionTranslator().loadModel(str(source))
    if not loaded.is_initialized():
        raise ValueError("Could not load input model")
    model = loaded.get()
    fresh = plan(config, inventory(model), source)
    if not fresh["ready"]:
        raise ValueError(
            f"Preflight no longer ready: {fresh['errors']} {fresh['missing_inputs']}"
        )
    if fresh != reviewed["plan"]:
        raise ValueError(
            "Resolved plan differs from bundled preflight; rerun inspection"
        )
    output = Path(fresh["parameters"]["output_model_path"])
    if str(output) != reviewed["output_model_path"]:
        raise ValueError("Plan output path differs from resolved configuration")
    if digest(source) != original:
        raise ValueError("Input model changed while loading")
    before = counts(model)
    before_handles = {str(x.handle()) for x in model.modelObjects()}
    loop_handle = create(model, sdk, fresh)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".vav-stage-", dir=output.parent, ignore_cleanup_errors=True
    ) as directory:
        staged = Path(directory) / "validated.osm"
        if not model.save(str(staged), True):
            raise RuntimeError("SDK could not save staged model")
        saved = sdk.osversion.VersionTranslator().loadModel(str(staged))
        if not saved.is_initialized():
            raise RuntimeError("Could not reload staged output")
        saved = saved.get()
        validation = validate_model(saved, sdk, fresh, loop_handle, before)
        if not validation["ok"]:
            raise RuntimeError(
                f"Staged topology validation failed: {validation['errors']}"
            )
        if digest(source) != original:
            raise ValueError(
                "Input model changed during creation; output was not published"
            )
        output_hash = digest(staged)
        # Report engineering objects, not every automatically generated node and
        # connector. The OSM retains all objects; keep routine agent output small.
        visible_types = {
            "OS_AirLoopHVAC",
            "OS_Fan_VariableVolume",
            "OS_Coil_Heating_Water",
            "OS_Coil_Heating_Gas",
            "OS_Coil_Heating_Electric",
            "OS_Coil_Cooling_Water",
            "OS_Coil_Cooling_DX_TwoSpeed",
            "OS_AirTerminal_SingleDuct_VAV_Reheat",
            "OS_AirTerminal_SingleDuct_VAV_NoReheat",
            "OS_AirLoopHVAC_OutdoorAirSystem",
            "OS_AirLoopHVAC_ReturnPlenum",
            "OS_Controller_OutdoorAir",
            "OS_Controller_MechanicalVentilation",
            "OS_Controller_WaterCoil",
            "OS_Schedule_Ruleset",
            "OS_SetpointManager_Scheduled",
            "OS_AvailabilityManager_NightCycle",
        }
        all_created = [
            x for x in saved.modelObjects() if str(x.handle()) not in before_handles
        ]
        created = sorted(
            (
                {
                    "name": x.nameString(),
                    "handle": str(x.handle()),
                    "type": x.iddObjectType().valueName(),
                }
                for x in all_created
                if x.iddObjectType().valueName() in visible_types
            ),
            key=lambda x: (x["type"], x["name"], x["handle"]),
        )
        # Same filesystem hard link is atomic and refuses an existing destination.
        # No rename/save-overwrite race; unsupported filesystems fail closed.
        os.link(staged, output)
    return {
        "ok": True,
        "mode": "edit_model",
        "openstudio_version": "3.11.0",
        "input_model_path": str(source),
        "input_sha256": original,
        "output_model_path": str(output),
        "output_sha256": output_hash,
        "changes": created,
        "created_object_count": len(all_created),
        "counts": validation["counts"],
        "validation": validation,
        "assumptions": fresh["assumptions"],
        "warnings": fresh["warnings"],
        "summary": "VAV created and saved topology validated; sizing/simulation remain pending",
        "state_patch": {
            "completed_steps": ["vav_creation", "vav_topology_validation"],
            "created_objects": {"air_loop": loop_handle},
            "output_model_path": str(output),
            "assumptions": fresh["assumptions"],
            "warnings": fresh["warnings"],
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = apply(args.plan)
    except Exception as exc:
        report = {
            "ok": False,
            "mode": "edit_model",
            "error": str(exc),
            "changes": [],
            "state_patch": {},
        }
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
