"""Measure the default all-handle guard on the largest checked-in OSM fixture."""

import argparse
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/sdk_scripts"))
from common.model_preparation import prepare
from common.version_guard import load_model, require_sdk
from common.files import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    sdk = require_sdk()
    fixture = max(
        (ROOT / "tests/fixtures").glob("*.osm"), key=lambda x: x.stat().st_size
    )
    with tempfile.TemporaryDirectory(prefix="load-guard-benchmark-") as directory:
        working = Path(directory) / "prepared.osm"
        result = prepare(fixture, working)
        working = Path(result["output_model_path"])
        model, _ = load_model(sdk, working)
        timings = {False: [], True: []}
        for _ in range(5):
            for enabled in timings:
                start = time.perf_counter()
                load_model(sdk, working, check_stability=enabled)
                timings[enabled].append(time.perf_counter() - start)
        single, double = (statistics.median(timings[k]) for k in (False, True))
        report = dict(
            openstudio_version=str(sdk.openStudioVersion()),
            fixture=str(fixture.relative_to(ROOT)),
            source_bytes=fixture.stat().st_size,
            prepared_bytes=working.stat().st_size,
            model_object_count=len(model.modelObjects()),
            default_guard="on",
            iterations=5,
            single_load_median_seconds=single,
            two_load_guard_median_seconds=double,
            added_seconds=double - single,
            ratio=double / single,
            single_load_seconds=timings[False],
            two_load_guard_seconds=timings[True],
        )
        write_json(report, args.report)
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
