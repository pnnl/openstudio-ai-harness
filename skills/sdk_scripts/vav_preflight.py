"""Inspect an OSM and resolve a VAV plan without saving or changing the model."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.input_validation import validate
from common.vav_inventory import inventory
from common.vav_plan import plan
from common.version_guard import require_sdk


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"Nonfinite JSON value: {value}")


def preflight(input_path: Path, config_path: Path | None = None) -> dict:
    sdk = require_sdk()  # Must precede reading/loading any user model.
    input_path = input_path.expanduser().resolve(strict=True)
    if not input_path.is_file() or input_path.suffix.lower() != ".osm":
        raise ValueError("Input must be an existing .osm file")
    source_hash = hashlib.sha256(input_path.read_bytes()).hexdigest()
    config = {}
    if config_path:
        config = json.loads(
            config_path.read_text(encoding="utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
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
    translator = sdk.osversion.VersionTranslator()
    loaded = translator.loadModel(str(input_path))
    if not loaded.is_initialized():
        raise ValueError("OpenStudio 3.11.0 could not load the input model")
    model = loaded.get()
    catalog = inventory(model)
    resolved = plan(config, catalog, input_path)
    if hashlib.sha256(input_path.read_bytes()).hexdigest() != source_hash:
        raise ValueError("Input model changed during preflight; rerun inspection")
    warnings = resolved["warnings"] + [
        str(item.logMessage()) for item in translator.warnings()
    ]
    ok = config_path is None or resolved["ready"]
    return {
        "ok": ok,
        "ready": resolved["ready"],
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
    args = parser.parse_args()
    try:
        report = preflight(args.input, args.config)
    except Exception as exc:
        report = {
            "ok": False,
            "ready": False,
            "mode": "inspect_only",
            "error": str(exc),
            "changes": [],
        }
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
