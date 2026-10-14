"""Inspect HVAC topology into local JSON, Mermaid and Markdown artifacts."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import tempfile

from common.diagnostics import failure_report, handle_changes
from common.failure_reporting import capture_exception
from common.files import check_report_path, publish, write_json
from common.hvac_graph import extract
from common.hvac_diagram import artifacts
from common.model_preparation import stored_objects, translator_messages
from common.version_guard import load_model, model_version, object_types, require_sdk


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def visualize(source, output, selected=()):
    sdk = require_sdk()
    if (
        not source.is_absolute()
        or not source.is_file()
        or source.suffix.lower() != ".osm"
    ):
        raise ValueError("Input must be an existing absolute .osm path")
    if not output.is_absolute() or output.exists() or output.is_symlink():
        raise ValueError("Diagram output must be an absolute new directory")
    parent = output.parent
    while not parent.exists():
        if parent == parent.parent:
            raise ValueError("Output drive/root does not exist")
        parent = parent.parent
    if not parent.is_dir():
        raise ValueError("Output parent must be a directory")
    original = digest(source)
    model, translator = load_model(sdk, source)
    graph = extract(model, sdk)
    rendered, unknown = artifacts(graph, selected)
    graph["warnings"].extend(
        dict(code="opaque_port_view", handle=key) for key in unknown
    )
    graph["warnings"].sort(key=lambda w: (w["code"], w["handle"]))
    graph["coverage"]["warning_counts"] = dict(
        sorted(Counter(w["code"] for w in graph["warnings"]).items())
    )
    graph.update(
        schema_version=1,
        operation="visualize_hvac",
        input_sha256=original,
        source_version=model_version(source),
        openstudio_version=str(sdk.openStudioVersion()),
        load_provenance=dict(
            handle_guard="two_loads_all_model_objects",
            changes=handle_changes(stored_objects(source), object_types(model)),
            translator=translator_messages(translator),
            note="Read-only loaded-model view; generated/repaired object counts are provenance, not a semantic no-op claim.",
        ),
    )
    rendered["graph.json"] = (
        json.dumps(graph, sort_keys=True, indent=2, allow_nan=False) + "\n"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".hvac-diagram-", dir=output.parent
    ) as directory:
        staged = Path(directory)
        for name, text in rendered.items():
            (staged / name).write_text(text, encoding="utf-8")
        if digest(source) != original:
            raise ValueError("Input changed during HVAC inspection")
        output.mkdir()  # Exclusive reservation; never replace a concurrent output.
        owned = []
        try:
            for name in sorted(rendered):
                destination = output / name
                publish(staged / name, destination)
                owned.append(destination)
        except BaseException:
            for path in owned:
                path.unlink(missing_ok=True)
            try:
                output.rmdir()
            except OSError:
                pass  # Preserve concurrent foreign files.
            raise
    counts = dict(
        nodes=len(graph["nodes"]),
        edges=len(graph["edges"]),
        connections=graph["coverage"]["represented_connection_count"],
        zones=len(graph["zones"]),
        unserved_zones=sum(z["unserved"] for z in graph["zones"]),
    )
    counts.update(Counter(g["kind"] for g in graph["groups"]))
    return dict(
        ok=True,
        ready=False,
        mode="inspect_only",
        operation="visualize_hvac",
        status="visualized",
        input_model_path=str(source),
        input_sha256=original,
        source_version=graph["source_version"],
        openstudio_version=graph["openstudio_version"],
        output_directory=str(output),
        graph_path=str(output / "graph.json"),
        equipment_graph_path=str(output / "equipment_graph.json"),
        index_path=str(output / "index.md"),
        overview_path=str(output / "overview.mmd"),
        diagram_paths=[
            str(output / name)
            for name in sorted(rendered)
            if name.endswith(".mmd") and name != "overview.mmd"
        ],
        counts=counts,
        warning_counts=graph["coverage"]["warning_counts"],
        translator=graph["load_provenance"]["translator"],
        note="Full topology, model labels and omissions remain in local artifacts; no model or companion files are copied.",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--system",
        action="append",
        default=[],
        help="Exact air/plant/VRF system or zone handle; repeat to select diagrams. Full JSON and overview remain complete.",
    )
    args = parser.parse_args()
    try:
        check_report_path(args.report)
        report = visualize(args.input, args.output_dir, args.system)
        write_json(report, args.report)
        compact = {
            k: v for k, v in report.items() if k not in {"diagram_paths", "translator"}
        }
        compact.update(
            report_path=str(args.report),
            diagram_count=len(report["diagram_paths"]),
            diagram_paths=report["diagram_paths"][:8],
            translator_warning_count=report["translator"]["warnings"]["count"],
            warnings_details="graph.json and the saved report",
        )
        print(json.dumps(compact, allow_nan=False))
        return 0
    except Exception as exc:
        failure = failure_report(exc, "visualize_hvac")
        failure.update(
            capture_exception(
                exc, "visualize_hvac", "inspect", args, locals().get("report")
            )
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
