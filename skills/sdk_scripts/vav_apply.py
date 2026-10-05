"""Apply a reviewed VAV preflight plan; publish only independently validated OSM."""

from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.version_guard import require_sdk, release_version, load_contract, load_model
from report import emit
from common.files import check_report_path
from common.input_validation import validate
from common.vav_inventory import inventory
from common.vav_plan import plan
from common.vav_create import create
from common.vav_validate import counts, validate_model
from common.files import publish
from common.companions import (
    inspect as inspect_companions,
    stage as stage_companions,
    verify as verify_companions,
)
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
        or release_version(str(reviewed.get("openstudio_version", "")))
        != load_contract()["required_openstudio_version"]
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
    model, _ = load_model(sdk, source)
    fresh = plan(config, inventory(model), source)
    if not fresh["ready"]:
        raise ValueError(
            f"Preflight no longer ready: {fresh['errors']} {fresh['missing_inputs']}"
        )
    fresh["companions"] = inspect_companions(
        model, source, Path(fresh["parameters"]["output_model_path"])
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
        companion_stage = Path(directory) / "companions"
        stage_companions(model, sdk, fresh["companions"], companion_stage)
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
        translator = sdk.energyplus.ForwardTranslator()
        workspace = translator.translateModel(saved)
        translation = {
            "ok": not translator.errors(),
            "errors": [str(item.logMessage()) for item in translator.errors()],
            "warnings": [str(item.logMessage()) for item in translator.warnings()],
            "object_count": len(workspace.objects()),
        }
        if not translation["ok"]:
            raise RuntimeError(
                f"EnergyPlus translation failed: {translation['errors']}"
            )
        if digest(source) != original:
            raise ValueError(
                "Input model changed during creation; output was not published"
            )
        verify_companions(fresh["companions"])
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
        companion_output = Path(fresh["companions"]["directory"])
        companion_output.mkdir()  # Exclusive ownership; preserve an existing folder.
        try:
            shutil.copytree(companion_stage, companion_output, dirs_exist_ok=True)
            publication_method = publish(staged, output)
        except BaseException:
            shutil.rmtree(companion_output)
            raise
    return {
        "ok": True,
        "mode": "edit_model",
        "openstudio_version": str(sdk.openStudioVersion()),
        "input_model_path": str(source),
        "input_sha256": original,
        "output_model_path": str(output),
        "output_sha256": output_hash,
        "changes": created,
        "created_object_count": len(all_created),
        "counts": validation["counts"],
        "validation": validation,
        "translation": translation,
        "publication_method": publication_method,
        "companion_directory": str(companion_output),
        "workflow_path": str(companion_output / "workflow.osw"),
        "assumptions": fresh["assumptions"],
        "warnings": fresh["warnings"]
        + translation["warnings"]
        + (
            [
                "Hard links unavailable: exclusive copy publication preserved existing files, but readers can see an incomplete file until the successful report."
            ]
            if publication_method == "exclusive_copy"
            else []
        ),
        "summary": "VAV created; saved topology and EnergyPlus translation passed; sizing/simulation remain pending",
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
    parser.add_argument(
        "--report",
        type=Path,
        help="Persist complete JSON directly to a new absolute report path",
    )
    parser.add_argument(
        "--candidate-filter",
        help="Filter candidate summary names; full report retains all candidates",
    )
    args = parser.parse_args()
    try:
        if args.report:
            check_report_path(args.report)
        report = apply(args.plan)
    except Exception as exc:
        report = {
            "ok": False,
            "mode": "edit_model",
            "error": str(exc),
            "changes": [],
            "state_patch": {},
        }
    try:
        summary = emit(report, args.report, args.candidate_filter)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "output_model_path": report.get("output_model_path"),
                    "report_error": True,
                }
            )
        )
        return 2
    print(json.dumps(summary, sort_keys=True, allow_nan=False))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
