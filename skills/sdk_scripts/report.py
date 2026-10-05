"""Persist an SDK script's final JSON line and print only decision-relevant data."""

from __future__ import annotations
import argparse
import json
import math
import os
from pathlib import Path
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.files import publish, write_json


from common.input_validation import unique_object, finite_float, reject_constant


def read_report(log_path):
    lines = log_path.read_text(encoding="utf-8").splitlines()
    lines = [line for line in lines if line.strip()]
    if not lines:
        raise ValueError("SDK log is empty")
    raw = lines[-1]
    report = json.loads(
        raw,
        object_pairs_hook=unique_object,
        parse_float=finite_float,
        parse_constant=reject_constant,
    )
    if not isinstance(report, dict) or type(report.get("ok")) is not bool:
        raise ValueError("Final line must be a structured SDK report with boolean ok")
    if report.get("mode") not in ("inspect_only", "edit_model"):
        raise ValueError("Unknown SDK report mode")
    if report["ok"]:
        if report["mode"] == "inspect_only" and type(report.get("ready")) is not bool:
            raise ValueError("Successful preflight report needs boolean ready")
        if report["mode"] == "edit_model":
            validation = report.get("validation")
            if not isinstance(validation, dict) or validation.get("ok") is not True:
                raise ValueError(
                    "Successful apply report needs saved-topology validation"
                )
    return report, raw


def summarize(report, report_path, candidate_filter=None):
    keys = (
        "ok",
        "ready",
        "mode",
        "input_model_path",
        "input_sha256",
        "output_model_path",
        "output_sha256",
        "counts",
        "summary",
        "error",
        "errors",
        "missing_inputs",
        "warnings",
        "created_object_count",
        "publication_method",
        "translation",
        "companion_directory",
        "workflow_path",
        "simulation_ready",
    )
    summary = {key: report[key] for key in keys if key in report}
    summary["report_path"] = str(report_path)
    summary["assumption_count"] = len(report.get("assumptions", []))
    if report.get("plan"):
        summary["parameters"] = report["plan"]["parameters"]
        summary["resolved_objects"] = report["plan"]["resolved_objects"]
    if report.get("validation"):
        summary["validation"] = {
            key: report["validation"][key]
            for key in ("ok", "checks", "errors", "supply_order")
            if key in report["validation"]
        }
    if report["mode"] == "inspect_only" and not report.get("ready"):
        catalog = report.get("candidates", {})
        limit = 8
        filtered = {
            key: [
                item
                for item in catalog.get(key, [])
                if candidate_filter is None
                or candidate_filter.casefold() in item.get("name", "").casefold()
            ]
            for key in ("zones", "plant_loops", "schedules")
        }
        summary["candidate_counts"] = {
            key: len(catalog.get(key, [])) for key in filtered
        }
        summary["matching_candidate_counts"] = {
            key: len(items) for key, items in filtered.items()
        }
        summary["candidate_filter"] = candidate_filter
        summary["candidates_truncated"] = any(
            len(items) > limit for items in filtered.values()
        )
        summary["candidates"] = {
            "zones": [
                {
                    "name": zone["name"],
                    "handle": zone["handle"],
                    "is_plenum": zone["is_plenum"],
                    "has_thermostat": zone["has_thermostat"],
                    "space_count": len(zone["spaces"]),
                    "air_loop_count": len(zone["air_loops"]),
                    "equipment_count": len(zone["equipment"]),
                }
                for zone in filtered["zones"][:limit]
            ],
            "plant_loops": filtered["plant_loops"][:limit],
            "schedules": filtered["schedules"][:limit],
        }
    return summary


def persist(log_path: Path, report_path: Path):
    if not report_path.is_absolute() or report_path.suffix.lower() != ".json":
        raise ValueError("Report must be a new absolute .json path")
    if report_path.exists() or report_path.is_symlink():
        raise ValueError("Report already exists; use a new report path or inspect it")
    report_path = report_path.resolve()
    report, raw = read_report(log_path)
    # Prepare the summary before publishing, so malformed reports create no artifact.
    summary = summarize(report, report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    staged = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=report_path.parent,
            prefix=".sdk-report-",
            delete=False,
        ) as file:
            staged = Path(file.name)
            file.write(raw + "\n")
        publish(staged, report_path)
    finally:
        if staged:
            staged.unlink(missing_ok=True)
    return summary


def emit(report, report_path=None, candidate_filter=None):
    if report_path is not None:
        # Validate shape/summary before writing; errors never publish malformed data.
        summary = summarize(report, report_path, candidate_filter)
        write_json(report, report_path)
        return summary
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    try:
        summary = persist(args.log, args.report)
    except Exception as exc:
        summary = {"ok": False, "error": str(exc)}
    print(json.dumps(summary, sort_keys=True, allow_nan=False))
    return 0 if summary["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
