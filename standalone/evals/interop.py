"""Interop eval: the exported openstudio-ai plugin vs. any MCP server, in real Claude Code.

    uv run --project standalone python -m standalone.evals.interop \
        --sut-config sut.json [--model <model-id>] [--arms ...] [--cases ID ...] \
        [--cases-dir DIR] [--repeat N] [--run-name NAME]

The model defaults to ``$ANTHROPIC_MODEL`` (environment or repo-root ``.env``).

``--sut-config`` is a standard ``{"mcpServers": {"<name>": {command, args, env}}}``
file with exactly one entry: the server under test. ``{sandbox}`` inside any
string of the entry is replaced with a fresh per-session directory; test inputs
are staged in ``{sandbox}/inputs`` and cases refer to them as ``{input_dir}``.
The entry's key is the server name, so tools show up as ``mcp__<name>__<tool>``.

Arms: ``harness-only`` (openstudio-ai alone), ``sut-only`` (server under test
alone, still with the plugin's agent and skills) and ``both`` (routing). Routing
checks (required/forbidden tools) apply to ``both`` only.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from standalone.evals.checks import (
    CheckResult,
    check_expected,
    check_model,
    deepeval_tool_correctness,
    find_output_model,
    score_case,
)
from standalone.evals.report import write_report
from standalone.evals.claude_host import (
    ClaudeRun,
    connected_servers,
    extract_tool_calls,
    run_claude,
    run_metrics,
    tool_timeline,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLED_CASES_DIR = Path(__file__).resolve().parent / "cases"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
OUTPUT_ROOT = REPO_ROOT / "outputs" / "evals"
PLUGIN_NAME = "openstudio-ai"
ARMS = ("harness-only", "sut-only", "both")


# --------------------------------------------------------------------- cases
def load_cases(
    ids: list[str] | None = None, extra_dir: Path | None = None
) -> list[dict[str, Any]]:
    """Bundled cases plus any ``*.json`` in ``extra_dir``; duplicate ids are an error."""
    cases: dict[str, dict[str, Any]] = {}
    for directory in (BUNDLED_CASES_DIR, extra_dir):
        if directory is None:
            continue
        for path in sorted(directory.glob("*.json")):
            for case in json.loads(path.read_text()):
                if case["case_id"] in cases:
                    raise ValueError(f"duplicate case_id {case['case_id']!r} ({path})")
                cases[case["case_id"]] = case
    if ids:
        missing = set(ids) - set(cases)
        if missing:
            raise ValueError(f"unknown case id(s): {', '.join(sorted(missing))}")
    return [c for c in cases.values() if not ids or c["case_id"] in ids]


# --------------------------------------------------------------------- model
MODEL_ENV_VAR = "ANTHROPIC_MODEL"


def resolve_model(flag: str | None) -> tuple[str | None, str]:
    """The model id and where it came from: ``--model``, else ``$ANTHROPIC_MODEL``."""
    if flag:
        return flag, "--model"
    from_env = os.environ.get(MODEL_ENV_VAR)
    if from_env:
        return from_env, MODEL_ENV_VAR
    return None, "unset"


# ------------------------------------------------------------------- servers
def load_sut_entry(path: Path) -> tuple[str, dict[str, Any]]:
    servers = json.loads(path.read_text()).get("mcpServers") or {}
    if len(servers) != 1:
        raise ValueError(f"{path}: expected exactly one entry in mcpServers, found {len(servers)}")
    ((name, entry),) = servers.items()
    return name, entry


def substitute(value: Any, sandbox: Path) -> Any:
    if isinstance(value, str):
        return value.replace("{sandbox}", str(sandbox))
    if isinstance(value, list):
        return [substitute(v, sandbox) for v in value]
    if isinstance(value, dict):
        return {k: substitute(v, sandbox) for k, v in value.items()}
    return value


def export_plugin(out_dir: Path, runtime_mode: str) -> tuple[Path, str, dict[str, Any]]:
    """Export the marketplace with the CLI; return (plugin_dir, reference name, reference entry)."""
    proc = subprocess.run(
        [sys.executable, "-m", "cli", "export", "marketplace",
         "--output-dir", str(out_dir), "--runtime-mode", runtime_mode],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"plugin export failed:\n{proc.stdout}\n{proc.stderr}")
    plugin_dir = out_dir / PLUGIN_NAME
    servers = json.loads((plugin_dir / ".mcp.json").read_text())["mcpServers"]
    ((name, entry),) = servers.items()
    command = entry["command"]
    if runtime_mode != "local" and shutil.which(command) is None:
        raise RuntimeError(f"runtime mode {runtime_mode!r} needs `{command}` on PATH")
    return plugin_dir, name, entry


def isolate_reference(entry: dict[str, Any], sandbox: Path) -> dict[str, Any]:
    """Keep the reference server's workspace and learning state inside the sandbox."""
    entry = copy.deepcopy(entry)
    args = entry.get("args", [])
    if "--workspace-root" in args:
        args[args.index("--workspace-root") + 1] = str(sandbox / "reference_workspace")
    entry.setdefault("env", {})["OPENSTUDIO_AI_DATA_DIR"] = str(sandbox / "reference_data")
    return entry


# ------------------------------------------------------------------- one run
def run_session(
    case: dict[str, Any],
    arm: str,
    *,
    plugin_dir: Path,
    ref: tuple[str, dict[str, Any]],
    sut: tuple[str, dict[str, Any]],
    model: str,
    out_dir: Path,
    timeout: float,
    use_deepeval: bool,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    sandbox = Path(tempfile.mkdtemp(prefix="osai-interop-"))
    try:
        inputs = sandbox / "inputs"
        inputs.mkdir()
        for name in case.get("inputs", []):
            shutil.copy2(FIXTURES_DIR / name, inputs / name)
        prompt = case["prompt"].format(input_dir=inputs)

        (ref_name, ref_entry), (sut_name, sut_entry) = ref, sut
        servers: dict[str, Any] = {}
        if arm in ("harness-only", "both"):
            servers[ref_name] = isolate_reference(ref_entry, sandbox)
        if arm in ("sut-only", "both"):
            servers[sut_name] = substitute(sut_entry, sandbox)
        config_path = sandbox / "mcp.json"
        config_path.write_text(json.dumps({"mcpServers": servers}, indent=2))
        work = sandbox / "work"
        work.mkdir()

        run = run_claude(
            prompt, mcp_config=config_path, model=model, plugin_dir=plugin_dir,
            cwd=work, timeout=timeout,
        )
        files = [p.name for p in sandbox.rglob("*") if p.is_file()]
        output_model = None
        if (case.get("expected") or {}).get("model"):
            originals = {p.read_bytes() for p in inputs.glob("*.osm")}
            output_model = find_output_model(sandbox, originals)
            if output_model is not None:  # keep it for calibration; the sandbox is deleted below
                shutil.copy2(output_model, out_dir / "output.osm")
        record = score_run(case, arm, run, prompt, ref_name, servers, use_deepeval, files, output_model)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)

    (out_dir / "raw.stream.jsonl").write_text(run.raw)
    (out_dir / "timeline.json").write_text(json.dumps(record["timeline"], indent=2))
    (out_dir / "result.json").write_text(json.dumps(record, indent=2))
    return record


def score_run(
    case: dict[str, Any], arm: str, run: ClaudeRun, prompt: str,
    ref_name: str, servers: dict[str, Any], use_deepeval: bool,
    files: list[str] = (),
    output_model: Path | None = None,
) -> dict[str, Any]:
    # Only the openstudio-ai server gets a label; the server under test keeps its own
    # name (its key in --sut-config), so cases name it directly, e.g. "openstudio-mcp".
    providers = {ref_name: "harness"}
    calls = extract_tool_calls(run.events, providers=providers)
    status = connected_servers(run)

    checks: list[CheckResult] = []
    for name in servers:
        ok = status.get(name) == "connected"
        checks.append(CheckResult(f"connected:{name}", ok, status.get(name, "missing from init")))
    checks.append(CheckResult(
        "session", not run.is_error,
        "ok" if not run.is_error else f"timed_out={run.timed_out} rc={run.returncode} {run.stderr[:200]}",
    ))
    checks += check_expected(case.get("expected"), run.final_text, files)
    checks += check_model((case.get("expected") or {}).get("model"), output_model)
    if arm == "both":
        checks += score_case(case, calls)
        if use_deepeval and case.get("expected_tools_ordered"):
            de = deepeval_tool_correctness(
                calls, case["expected_tools_ordered"], prompt=prompt, answer=run.final_text
            )
            if de is None:
                print("deepeval not installed; install the standalone 'eval' extra.", file=sys.stderr)
            else:
                checks.append(de)

    return {
        "case_id": case["case_id"],
        "arm": arm,
        "passed": all(c.passed for c in checks),
        "checks": [c.to_dict() for c in checks],
        "metrics": run_metrics(run),
        "tool_calls": [{"name": c.name, "provider": c.provider} for c in calls],
        "timeline": tool_timeline(run.events, providers=providers),
        "answer": run.final_text,
    }


def format_metrics(m: dict[str, Any]) -> str:
    def fmt(value: Any, template: str) -> str:
        return "n/a" if value is None else template.format(value)

    return (
        f"metrics: turns={fmt(m['turns'], '{}')} tools={m['tool_calls']} "
        f"out_tokens={fmt(m['output_tokens'], '{:,}')} cost={fmt(m['cost_usd'], '${:.2f}')} "
        f"time={fmt(m['duration_s'], '{:.0f}s')}"
    )


# ---------------------------------------------------------------- provenance
def _git_sha(path: Path) -> str | None:
    proc = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


def _sut_root(entry: dict[str, Any]) -> Path | None:
    """Best-effort source checkout of the SUT: the first existing path-valued env var."""
    for value in (entry.get("env") or {}).values():
        if isinstance(value, str) and "{sandbox}" not in value and Path(value).is_dir():
            return Path(value)
    return None


def build_provenance(args: argparse.Namespace, sut_name: str, sut_entry: dict[str, Any], cases: list[dict[str, Any]]) -> dict[str, Any]:
    from openstudio_ai_mcp.compatibility import package_version

    claude = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip()
    root = _sut_root(sut_entry)
    cases_blob = json.dumps(cases, sort_keys=True).encode()
    return {
        "openstudio_ai_version": package_version(),
        "openstudio_ai_git_sha": _git_sha(REPO_ROOT),
        "sut_server": sut_name,
        "sut_root": str(root) if root else None,
        "sut_git_sha": _git_sha(root) if root else None,
        "claude_version": claude,
        "model": args.model,
        "model_source": args.model_source,
        "runtime_mode": args.runtime_mode,
        "arms": args.arms,
        "cases_sha256": hashlib.sha256(cases_blob).hexdigest(),
        "case_ids": [c["case_id"] for c in cases],
    }


# ---------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sut-config", type=Path, required=True,
                        help="mcpServers JSON with the single server under test")
    parser.add_argument(
        "--model",
        help=f"model id exactly as your gateway names it (default: ${MODEL_ENV_VAR}, "
        "read from the environment or the repo-root .env)",
    )
    parser.add_argument("--arms", default=",".join(ARMS), help=f"comma list of {ARMS}")
    parser.add_argument("--cases", nargs="*", help="case ids (default: all)")
    parser.add_argument("--cases-dir", type=Path, help="extra directory of case *.json files")
    parser.add_argument("--runtime-mode", default="local", choices=["local", "installed", "marketplace"])
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--run-name", default="interop")
    parser.add_argument("--timeout", type=float, default=900, help="seconds per claude session")
    parser.add_argument("--deepeval", action="store_true")
    load_dotenv(REPO_ROOT / ".env")  # does not override variables already in the environment
    args = parser.parse_args(argv)
    args.model, args.model_source = resolve_model(args.model)
    if not args.model:
        parser.error(f"no model: pass --model or set {MODEL_ENV_VAR} (environment or repo-root .env)")

    arms =[a.strip() for a in args.arms.split(",") if a.strip()]
    if bad := [a for a in arms if a not in ARMS]:
        parser.error(f"unknown arm(s): {', '.join(bad)}")
    if args.repeat < 1:
        parser.error("--repeat must be >= 1")
    if shutil.which("claude") is None:
        print("`claude` not found on PATH.", file=sys.stderr)
        return 2

    sut_name, sut_entry = load_sut_entry(args.sut_config)
    cases = load_cases(args.cases, args.cases_dir)

    export_dir = Path(tempfile.mkdtemp(prefix="osai-plugin-"))
    run_dir = OUTPUT_ROOT / args.run_name
    records: list[dict[str, Any]] = []
    try:
        plugin_dir, ref_name, ref_entry = export_plugin(export_dir, args.runtime_mode)
        if ref_name == sut_name:
            print(f"SUT server name {sut_name!r} collides with the reference server name.", file=sys.stderr)
            return 2
        for case in cases:
            for arm in (a for a in arms if a in case.get("arms", ARMS)):
                for rep in range(1, args.repeat + 1):
                    out_dir = run_dir / arm / case["case_id"]
                    label = f"{case['case_id']} [{arm}]"
                    if args.repeat > 1:
                        out_dir /= f"rep_{rep}"
                        label += f" [{rep}/{args.repeat}]"
                    print(f"== {label}", flush=True)
                    record = run_session(
                        case, arm, plugin_dir=plugin_dir, ref=(ref_name, ref_entry),
                        sut=(sut_name, sut_entry), model=args.model, out_dir=out_dir,
                        timeout=args.timeout, use_deepeval=args.deepeval,
                    )
                    record["rep"] = rep
                    records.append(record)
                    for check in record["checks"]:
                        print(f"  [{'PASS' if check['passed'] else 'FAIL'}] {check['check']}: {check['reason']}")
                    print("  " + format_metrics(record["metrics"]))
                    print("  tools: " +(" -> ".join(f"{c['name']}({c['provider']})" for c in record["tool_calls"]) or "(none)"))
    finally:
        shutil.rmtree(export_dir, ignore_errors=True)

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "provenance.json").write_text(
        json.dumps(build_provenance(args, sut_name, sut_entry, cases), indent=2))
    (run_dir / "summary.json").write_text(json.dumps(
        [{k: v for k, v in r.items() if k not in ("timeline", "answer")} for r in records], indent=2))
    write_report(run_dir)
    passed = sum(r["passed"] for r in records)
    print(f"{passed}/{len(records)} sessions passed. Results: {run_dir}")
    return 0 if records and passed == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
