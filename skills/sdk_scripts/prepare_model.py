"""Prepare a stable copied OSM before any reviewed modeling operation."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.diagnostics import failure_report
from common.files import check_report_path, write_json
from common.model_preparation import prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        check_report_path(args.report)
        report = prepare(args.input, args.output)
        write_json(report, args.report)
        print(json.dumps(dict(report, report_path=str(args.report)), allow_nan=False))
        return 0
    except Exception as exc:
        failure = failure_report(exc, "prepare_model")
        if "report" in locals() and report.get("status") == "prepared":
            failure.update(
                output_model_path=report["output_model_path"], report_error=True
            )
        if not args.report.exists():
            try:
                write_json(failure, args.report)
            except Exception:
                pass
        print(json.dumps(failure, allow_nan=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
