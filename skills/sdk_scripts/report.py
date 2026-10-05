"""Persist an SDK script's final JSON line and print only decision-relevant data."""

from __future__ import annotations
import argparse
import json
import math
import os
from pathlib import Path
import tempfile


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def finite_float(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("Nonfinite JSON number")
    return parsed


def reject_constant(value):
    raise ValueError(f"Nonfinite JSON value: {value}")


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


def summarize(report, report_path):
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
                for zone in catalog.get("zones", [])
            ],
            "plant_loops": catalog.get("plant_loops", []),
            "schedules": catalog.get("schedules", []),
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
        os.link(staged, report_path)  # Exclusive publication; no overwrite race.
    finally:
        if staged:
            staged.unlink(missing_ok=True)
    return summary


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
