"""Render an interop run's ``summary.json`` + ``provenance.json`` as a readable ``report.md``.

    uv run python -m evals.report [RUN_DIR ...]

With no arguments every run under ``outputs/evals/`` that has a ``summary.json`` is
rendered. The runner also writes ``report.md`` at the end of each run. Nothing is
re-run: the report is built only from the files already on disk.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "outputs" / "evals"
ARM_ORDER = ("harness-only", "sut-only", "both")


def _cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _table(header: list[str], rows: Iterable[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return lines


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _fmt(value: float | None, template: str) -> str:
    return "n/a" if value is None else template.format(value)


def _groups(records: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[(record["case_id"], record["arm"])].append(record)
    return groups


def _ordered(groups: dict[tuple[str, str], Any]) -> list[tuple[str, str]]:
    cases = list(dict.fromkeys(case for case, _ in groups))
    return sorted(groups, key=lambda k: (cases.index(k[0]), ARM_ORDER.index(k[1]) if k[1] in ARM_ORDER else 99))


def _result(group: list[dict[str, Any]]) -> str:
    passed = sum(r["passed"] for r in group)
    if len(group) == 1:
        return "PASS" if passed else "FAIL"
    return f"{'PASS' if passed == len(group) else 'FAIL'} ({passed}/{len(group)})"


def _metric(group: list[dict[str, Any]], key: str) -> float | None:
    return _median([m[key] for r in group if (m := r.get("metrics")) and m.get(key) is not None])


def _sequence(calls: list[dict[str, str]]) -> str:
    """Tool calls in order as ``name (provider)``, collapsing immediate repeats to ``name xN``."""
    out: list[str] = []
    prev, count = None, 0
    for call in calls + [None]:  # type: ignore[list-item]
        key = (call["name"], call["provider"]) if call else None
        if key == prev:
            count += 1
            continue
        if prev is not None:
            out.append(f"{prev[0]}({prev[1]})" + (f" x{count}" if count > 1 else ""))
        prev, count = key, 1
    return " -> ".join(out) or "(none)"


def render_report(run_dir: Path) -> str:
    records: list[dict[str, Any]] = json.loads((run_dir / "summary.json").read_text())
    prov_path = run_dir / "provenance.json"
    prov: dict[str, Any] = json.loads(prov_path.read_text()) if prov_path.exists() else {}
    groups = _groups(records)
    passed = sum(r["passed"] for r in records)
    reps = max((r.get("rep", 1) for r in records), default=1)

    lines = [f"# Interop eval report: `{run_dir.name}`", ""]
    lines.append(
        f"**{passed}/{len(records)} sessions passed**"
        + (f" ({reps} repetitions per case and arm; metrics are medians)." if reps > 1 else ".")
    )
    lines.append("")

    if prov:
        lines += ["## Run", ""]
        lines += _table(["Item", "Value"], [
            ["openstudio-ai", f"{prov.get('openstudio_ai_version')} @ {str(prov.get('openstudio_ai_git_sha'))[:10]}"],
            ["Server under test", f"{prov.get('sut_server')} @ {str(prov.get('sut_git_sha'))[:10]}"],
            ["Claude Code", prov.get("claude_version")],
            ["Model", f"{prov.get('model')} (from {prov.get('model_source')})"],
            ["Runtime mode", prov.get("runtime_mode")],
            ["Arms", prov.get("arms")],
            ["Cases hash", str(prov.get("cases_sha256"))[:12]],
        ])
        lines.append("")

    cases = list(dict.fromkeys(case for case, _ in groups))
    lines += ["## Results", ""]
    lines += _table(["Case", *ARM_ORDER], [
        [f"`{case}`", *[(_result(groups[(case, arm)]) if (case, arm) in groups else "-") for arm in ARM_ORDER]]
        for case in cases
    ])
    lines.append("")

    lines += ["## Effort", "",
              "Turns, tool calls and output tokens measure what the agent did. Cost mostly reflects the "
              "fixed size of the system prompt and tool schemas, so compare it across arms with care.", ""]
    effort = []
    for case, arm in _ordered(groups):
        group = groups[(case, arm)]
        effort.append([
            f"`{case}`", arm,
            _fmt(_metric(group, "turns"), "{:.0f}"),
            _fmt(_metric(group, "tool_calls"), "{:.0f}"),
            _fmt(_metric(group, "output_tokens"), "{:,.0f}"),
            _fmt(_metric(group, "cost_usd"), "${:.2f}"),
            _fmt(_metric(group, "duration_s"), "{:.0f}s"),
        ])
    lines += _table(["Case", "Arm", "Turns", "Tool calls", "Output tokens", "Cost", "Wall time"], effort)
    lines.append("")

    failures = [(r, c) for r in records for c in r["checks"] if not c["passed"]]
    lines += ["## Failed checks", ""]
    if not failures:
        lines += ["None.", ""]
    else:
        for key in _ordered(groups):
            for record in groups[key]:
                bad = [c for c in record["checks"] if not c["passed"]]
                if not bad:
                    continue
                rep = f" (rep {record['rep']})" if reps > 1 else ""
                lines.append(f"- `{record['case_id']}` / {record['arm']}{rep}")
                lines += [f"  - `{c['check']}`: {c['reason']}" for c in bad]
        lines.append("")

    lines += ["## Routing: tool sequences", "",
              "`harness` is openstudio-ai; `agent` is a Claude Code built-in; any other name is that MCP server. "
              "Repeated calls are collapsed (`x3`).", ""]
    for key in _ordered(groups):
        case, arm = key
        for record in groups[key]:
            rep = f" rep {record['rep']}" if reps > 1 else ""
            lines.append(f"- `{case}` / {arm}{rep}: {_sequence(record['tool_calls'])}")
    lines.append("")
    return "\n".join(lines)


def write_report(run_dir: Path) -> Path:
    path = run_dir / "report.md"
    path.write_text(render_report(run_dir))
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_dirs", nargs="*", type=Path,
                        help="run folders (default: every run under outputs/evals/)")
    args = parser.parse_args(argv)
    run_dirs = args.run_dirs or sorted(p.parent for p in OUTPUT_ROOT.glob("*/summary.json"))
    if not run_dirs:
        print(f"no runs with a summary.json under {OUTPUT_ROOT}", file=sys.stderr)
        return 1
    for run_dir in run_dirs:
        print(write_report(run_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
