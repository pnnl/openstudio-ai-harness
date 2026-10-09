"""Reviewed, hash-bound transactions shared by skill-bound model edits."""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import tempfile
from common.version_guard import (
    require_sdk,
    load_model,
    load_contract,
    PreparationRequired,
)
from common.diagnostics import failure_report, mismatch
from common.input_validation import read_json
from common.files import publish, check_report_path, write_json
from common.companions import inspect, stage, verify, digest, external_file_status


from common.files import check_model_paths as check_paths


def preflight(source, config, operation, planner):
    sdk = require_sdk()
    if not isinstance(config, dict):
        raise ValueError("Configuration must be an object")
    output = Path(config.get("output_model_path", ""))
    original = digest(source)
    try:
        model, translator = load_model(sdk, source)
    except PreparationRequired as exc:
        return dict(failure_report(exc, operation), input_sha256=original)
    check_paths(source, output)
    warnings = [x.logMessage() for x in translator.warnings()]
    planned = planner(model, sdk, config)
    ready = planned.get("ready", True)
    if ready:
        planned["companions"] = inspect(model, source, output, sdk)
        if planned.get("simulation_ready") is False:
            planned["companions"]["simulation_ready"] = False
    if digest(source) != original:
        raise ValueError("Input changed during preflight")
    return dict(
        ok=ready,
        ready=ready,
        mode="inspect_only",
        plan_version=1,
        operation=operation,
        openstudio_version=load_contract()["required_openstudio_version"],
        input_model_path=str(source),
        output_model_path=str(output),
        input_sha256=original,
        configuration=config,
        plan=planned,
        warnings=warnings
        + planned.get("companions", {}).get("warnings", [])
        + planned.get("warnings", []),
    )


def apply(plan_path, operation, planner, creator, validator):
    sdk = require_sdk()
    report = read_json(plan_path)
    if not isinstance(report, dict):
        raise ValueError("Plan must be an object")
    if (
        report.get("operation") != operation
        or report.get("plan_version") != 1
        or report.get("openstudio_version")
        != load_contract()["required_openstudio_version"]
        or report.get("ready") is not True
        or report.get("ok") is not True
    ):
        raise ValueError("Apply requires a ready matching bundled preflight plan")
    required = {
        "input_model_path",
        "output_model_path",
        "input_sha256",
        "configuration",
        "plan",
    }
    if not required <= report.keys():
        raise ValueError("Incomplete preflight plan; rerun preflight")
    source = Path(report["input_model_path"])
    if digest(source) != report["input_sha256"]:
        raise mismatch(
            {"input_sha256": report["input_sha256"]},
            {"input_sha256": digest(source)},
            "Stale input hash; rerun preflight",
        )
    fresh = preflight(source, report["configuration"], operation, planner)
    if fresh != report:
        raise mismatch(report, fresh)
    output = Path(report["output_model_path"])
    model, _ = load_model(sdk, source)
    if digest(source) != report["input_sha256"]:
        raise ValueError("Input changed while loading")
    result = creator(model, sdk, report["plan"])
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".hvac-stage-", dir=output.parent
    ) as directory:
        staged = Path(directory) / "validated.osm"
        companions = Path(directory) / output.stem
        stage(model, sdk, report["plan"]["companions"], companions)
        if not model.save(str(staged), True):
            raise RuntimeError("SDK could not save staged output")
        saved, _ = load_model(sdk, staged)
        plain = external_file_status(saved)
        saved, _ = load_model(sdk, staged)
        saved.workflowJSON().setOswPath(str(companions / "workflow.osw"))
        if not external_file_status(saved)["ok"]:
            raise ValueError("Staged external files do not resolve")
        validation = validator(saved, sdk, report["plan"], result)
        if not validation["ok"]:
            raise ValueError(f"Saved validation failed: {validation['errors']}")
        ft = sdk.energyplus.ForwardTranslator()
        ft.translateModel(saved)
        translation = dict(
            ok=not ft.errors(),
            errors=[x.logMessage() for x in ft.errors()],
            warnings=[x.logMessage() for x in ft.warnings()],
        )
        if not translation["ok"]:
            raise ValueError(f"EnergyPlus translation failed: {translation['errors']}")
        if digest(source) != report["input_sha256"]:
            raise ValueError("Input changed before publication")
        verify(report["plan"]["companions"])
        companion_output = output.with_suffix("")
        companion_output.mkdir()
        try:
            shutil.copytree(companions, companion_output, dirs_exist_ok=True)
            method = publish(staged, output)
        except BaseException:
            shutil.rmtree(companion_output)
            raise
        output_hash = digest(staged)
    return dict(
        ok=True,
        mode="edit_model",
        operation=operation,
        input_model_path=str(source),
        input_sha256=report["input_sha256"],
        output_model_path=str(output),
        output_sha256=output_hash,
        changes=result,
        validation=validation,
        translation=translation,
        assumptions=report["plan"].get("assumptions", []),
        warnings=report["warnings"] + translation["warnings"],
        publication_method=method,
        requires_companion_workflow=not plain["ok"],
        companion_directory=str(companion_output),
        simulation_ready=report["plan"]["companions"]["simulation_ready"],
    )


def cli(operation, planner, creator, validator, inventory):
    parser = argparse.ArgumentParser(description=operation)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--input", type=Path)
    mode.add_argument("--plan", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        require_sdk()
        check_report_path(args.report)
        if args.plan:
            if args.config:
                raise ValueError("--config is only valid for preflight")
            report = apply(args.plan, operation, planner, creator, validator)
        elif args.config:
            report = preflight(args.input, read_json(args.config), operation, planner)
        else:
            model, translator = load_model(require_sdk(), args.input)
            warnings = [x.logMessage() for x in translator.warnings()]
            report = dict(
                ok=True,
                ready=False,
                mode="inspect_only",
                operation=operation,
                candidates=inventory(model),
                warnings=warnings,
            )
        write_json(report, args.report)
        compact = {
            k: v
            for k, v in report.items()
            if k
            not in ("plan", "changes", "candidates", "configuration", "assumptions")
        }
        if "plan" in report:
            compact["parameters"] = report["plan"]["parameters"]
            compact["impact"] = report["plan"].get("impact")
            if "outdoor_air_policy" in report["plan"]:
                compact["outdoor_air_policy"] = report["plan"]["outdoor_air_policy"]
            for key in ("missing_inputs", "errors"):
                if key in report["plan"]:
                    compact[key] = report["plan"][key]
            if report["plan"].get("assumption_review"):
                compact["assumption_review"] = {
                    "status": report["plan"]["assumption_review"]["status"],
                    "details": "plan.assumption_review in the saved report",
                }
        if "candidates" in report:
            compact["candidate_counts"] = {
                k: len(v) for k, v in report["candidates"].items()
            }
            compact["candidates"] = {k: v[:8] for k, v in report["candidates"].items()}
        compact["report_path"] = str(args.report)
        print(json.dumps(compact, allow_nan=False))
        return 0 if report["ok"] else 2
    except Exception as exc:
        failure = failure_report(exc, operation)
        if (
            "report" in locals()
            and report.get("mode") == "edit_model"
            and report.get("ok")
        ):
            failure.update(
                output_model_path=report["output_model_path"], report_error=True
            )
        if not args.report.exists():
            try:
                write_json(failure, args.report)
            except Exception:
                pass
        print(json.dumps(failure))
        return 2
