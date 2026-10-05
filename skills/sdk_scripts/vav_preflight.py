"""Inspect an OSM and resolve a VAV plan without saving or changing the model."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from report import emit
from common.files import check_report_path
from common.companions import inspect as inspect_companions
from common.input_validation import validate, read_json
from common.vav_inventory import inventory
from common.vav_plan import plan, assumption_review
from common.version_guard import require_sdk, load_model


def preflight(input_path: Path, config_path: Path | None = None) -> dict:
    sdk = require_sdk()  # Must precede reading/loading any user model.
    input_path = input_path.expanduser().resolve(strict=True)
    if not input_path.is_file() or input_path.suffix.lower() != ".osm":
        raise ValueError("Input must be an existing .osm file")
    source_hash = hashlib.sha256(input_path.read_bytes()).hexdigest()
    config = {}
    if config_path:
        config = read_json(config_path)
    schema = json.loads(
        (
            Path(__file__).resolve().parent / "references/vav_input.schema.json"
        ).read_text(encoding="utf-8")
    )
    errors = validate(config, schema)
    if errors:
        return {
            "ok": False,
            "ready": False,
            "mode": "inspect_only",
            "errors": errors,
            "changes": [],
        }
    model, translator = load_model(sdk, input_path)
    catalog = inventory(model)
    resolved = plan(config, catalog, input_path)
    if resolved["ready"]:
        try:
            resolved["companions"] = inspect_companions(
                model,
                input_path,
                Path(resolved["parameters"]["output_model_path"]),
                sdk,
            )
        except (ValueError, OSError) as exc:
            resolved["ready"] = False
            resolved["errors"].append(str(exc))
    if hashlib.sha256(input_path.read_bytes()).hexdigest() != source_hash:
        raise ValueError("Input model changed during preflight; rerun inspection")
    warnings = (
        resolved["warnings"]
        + resolved.get("companions", {}).get("warnings", [])
        + [str(item.logMessage()) for item in translator.warnings()]
    )
    ok = config_path is None or resolved["ready"]
    return {
        "ok": ok,
        "ready": resolved["ready"],
        "simulation_ready": resolved.get("companions", {}).get(
            "simulation_ready", False
        ),
        "mode": "inspect_only",
        "plan_version": 2,
        "configuration": config,
        "openstudio_version": str(sdk.openStudioVersion()),
        "input_model_path": str(input_path),
        "input_sha256": source_hash,
        "output_model_path": resolved["parameters"].get("output_model_path"),
        "changes": [],
        "warnings": warnings,
        "errors": resolved["errors"],
        "missing_inputs": resolved["missing_inputs"],
        "assumptions": resolved["assumptions"],
        "assumption_review": assumption_review(config) if config_path else None,
        "counts": {key: len(value) for key, value in catalog.items()},
        "candidates": catalog,
        "plan": resolved,
        "summary": (
            "VAV plan is ready for review"
            if resolved["ready"]
            else "Inspection complete; resolve missing inputs and conflicts before editing"
        ),
        "state_patch": {
            "preflight": {"ready": resolved["ready"], "input_sha256": source_hash}
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument(
        "--config", type=Path, help="Partial or complete VAV configuration JSON"
    )
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
        report = preflight(args.input, args.config)
    except Exception as exc:
        report = {
            "ok": False,
            "ready": False,
            "mode": "inspect_only",
            "error": str(exc),
            "changes": [],
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
