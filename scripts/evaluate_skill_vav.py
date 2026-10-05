"""Local VAV bundle evaluation; context estimates are not billed agent tokens."""

from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from adapters.claude_code_adapter import ClaudeCodeAdapter
from adapters.codex_adapter import CodexAdapter
from adapters.contracts import HostAdapterConfig
from vav_fixture import prepare_vav_fixture


def context_size(text):
    return {
        "characters": len(text),
        "utf8_bytes": len(text.encode()),
        "words": len(text.split()),
        "estimated_tokens_chars_div_4": math.ceil(len(text) / 4),
    }


def context_comparison(baseline_ref):
    revision = subprocess.run(
        ["git", "rev-parse", "--verify", baseline_ref],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    # Historical names come from the baseline, independent of retired source assets.
    child_names = sorted(
        path.removeprefix("skills/").removesuffix(".md")
        for path in subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", revision, "skills"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        if path.startswith("skills/openstudio_hvac_")
        and not path.endswith("workflow_state.md")
        and path.endswith(".md")
    )
    old_paths = [
        "prompts/openstudio_agent.md",
        "skills/add_vav_reheat.md",
        "skills/openstudio_vav_reheat_system_creator.md",
        "skills/openstudio_sdk_model_editor.md",
        "skills/openstudio_hvac_workflow_state.md",
    ]
    old_paths += [f"skills/{name}.md" for name in child_names]
    old_paths += [
        f"knowledge/openstudio_sdk_wiki/{name}.md"
        for name in (
            "sdk_index",
            "sdk_core_patterns",
            "sdk_hvac",
            "sdk_schedules",
            "sdk_spaces_zones_loads",
        )
    ]
    new_paths = [
        "prompts/openstudio_agent.md",
        "skills/add_vav_reheat.md",
        "skills/openstudio_vav_reheat_system_creator.md",
        "skills/sdk_scripts/references/vav_input.schema.json",
    ]

    def measure(paths, old):
        texts, files = [], []
        for path in paths:
            text = (
                subprocess.run(
                    ["git", "show", f"{revision}:{path}"],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout
                if old
                else (ROOT / path).read_text()
            )
            texts.append(text)
            files.append({"path": path, **context_size(text)})
        return {"files": files, **context_size("\n".join(texts))}

    before, after = measure(old_paths, True), measure(new_paths, False)
    return {
        "baseline_revision": revision,
        "method": "Unique instruction/reference files loaded once over the specified route; estimated tokens = ceil(characters/4).",
        "legacy_phased_route": before,
        "bundled_route": after,
        "instruction_character_reduction_percent": 100
        * (1 - after["characters"] / before["characters"]),
        "excluded": [
            "Generated legacy code",
            "SDK API lookup responses",
            "Global host/tool catalog",
            "User messages",
            "Reasoning",
            "Model tokenizer differences and caching",
        ],
        "actual_agent_tokens": None,
        "legacy_execution_seconds": None,
        "legacy_agent_retries": None,
    }


def run(command, cwd, log, expected=0):
    start = time.perf_counter()
    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    result = subprocess.run(
        [str(x) for x in command],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    elapsed = time.perf_counter() - start
    log.write_text(result.stdout)
    log.with_suffix(log.suffix + ".stderr").write_text(result.stderr)
    if result.returncode != expected:
        raise RuntimeError(
            f"Unexpected exit {result.returncode}; inspect {log} and its stderr"
        )
    return {"seconds": elapsed, "exit_code": result.returncode}, result.stdout


def size_output(raw, compact):
    before, after = context_size(raw), context_size(compact)
    return {
        "full_report": before,
        "compact_summary": after,
        "character_reduction_percent": 100
        * (1 - after["characters"] / before["characters"]),
    }


def evaluate_case(executable, skill, case_dir, hydronic, sdk):
    case_dir.mkdir()
    source, config, fixture, original_fixture = prepare_vav_fixture(
        sdk, case_dir, hydronic
    )
    original_source = source.read_bytes()
    config_path = case_dir / "config.json"
    config_path.write_text(json.dumps(config))
    timing = {}
    timing["doctor"], doctor_raw = run(
        [sys.executable, "-S", skill / "scripts/doctor.py", "--openstudio", executable],
        case_dir,
        case_dir / "doctor.log",
    )
    doctor = json.loads(doctor_raw)
    if doctor.get("ok") is not True:
        raise RuntimeError("Doctor did not establish required SDK readiness")
    verified = doctor["openstudio_executable"]
    prefix = [verified, "execute_python_script"]
    plan_path = case_dir / "plan.json"
    timing["preflight"], compact_preflight = run(
        prefix
        + [
            skill / "scripts/vav_preflight.py",
            "--input",
            source,
            "--config",
            config_path,
            "--report",
            plan_path,
        ],
        case_dir,
        case_dir / "preflight.log",
    )
    ready = json.loads(plan_path.read_text())
    if ready.get("ready") is not True:
        raise RuntimeError("Preflight not ready")
    preflight_raw = plan_path.read_text()
    apply_path = case_dir / "apply-report.json"
    timing["apply"], compact_apply = run(
        prefix
        + [skill / "scripts/vav_apply.py", "--plan", plan_path, "--report", apply_path],
        case_dir,
        case_dir / "apply.log",
    )
    apply_raw = apply_path.read_text()
    applied = json.loads(apply_path.read_text())
    if not applied["validation"]["ok"]:
        raise RuntimeError("Saved topology did not pass")
    output = Path(applied["output_model_path"])
    original_output = output.read_bytes()
    _, repeated = run(
        prefix
        + [
            skill / "scripts/vav_apply.py",
            "--plan",
            plan_path,
            "--report",
            case_dir / "repeat-failure.json",
        ],
        case_dir,
        case_dir / "repeat-blocked.log",
        expected=2,
    )
    if (
        json.loads((case_dir / "repeat-failure.json").read_text())["ok"] is not False
        or output.read_bytes() != original_output
    ):
        raise RuntimeError("Repeated apply did not preserve existing output")
    stale = json.loads(plan_path.read_text())
    stale["input_sha256"] = "0" * 64
    stale_path = case_dir / "stale-plan.json"
    stale_path.write_text(json.dumps(stale))
    _, rejected = run(
        prefix
        + [
            skill / "scripts/vav_apply.py",
            "--plan",
            stale_path,
            "--report",
            case_dir / "stale-failure.json",
        ],
        case_dir,
        case_dir / "stale-blocked.log",
        expected=2,
    )
    if "Stale input hash" not in json.loads(
        (case_dir / "stale-failure.json").read_text()
    ).get("error", ""):
        raise RuntimeError("Changed plan hash did not block")
    workflow = Path(applied["workflow_path"])
    timing["sizing"], _ = run(
        [verified, "run", "-w", workflow], workflow.parent, case_dir / "sizing-cli.log"
    )
    error_log = (workflow.parent / "run/eplusout.err").read_text()
    if (
        "** Severe **" in error_log
        or "**  Fatal  **" in error_log
        or "No node connection errors were found." not in error_log
    ):
        raise RuntimeError(f"Sizing/connection errors: {case_dir / 'run/eplusout.err'}")
    summary = next(
        line.strip()
        for line in error_log.splitlines()
        if "EnergyPlus Completed Successfully" in line
    )
    with sqlite3.connect(workflow.parent / "run/eplusout.sql") as connection:
        rows = connection.execute(
            "SELECT CompType, CompName, Description, Value, Units FROM ComponentSizes WHERE upper(CompName) LIKE '%SIZING VAV%' OR upper(CompName) LIKE '%VAV TERMINAL%' OR upper(CompName) LIKE '%REHEAT COIL%'"
        ).fetchall()
    fan = [
        r[3]
        for r in rows
        if r[0] == "Fan:VariableVolume" and "Maximum Flow Rate" in r[2]
    ]
    terminals = sorted(
        r[3]
        for r in rows
        if r[0] == "AirTerminal:SingleDuct:VAV:Reheat"
        and "Maximum Air Flow Rate" in r[2]
    )
    reheat = sorted(
        r[3]
        for r in rows
        if r[1].endswith("REHEAT COIL")
        and r[2] in ("Design Size Rated Capacity", "Design Size Nominal Capacity")
    )
    cooling = [
        r[3]
        for r in rows
        if r[1] == "SIZING VAV COOLING COIL"
        and r[2]
        in (
            "Design Size Design Coil Load",
            "Design Size High Speed Gross Rated Total Cooling Capacity",
        )
    ]
    if (
        len(fan) != 1
        or len(terminals) != 5
        or len(reheat) != 5
        or len(cooling) != 1
        or any(x <= 0 for x in fan + terminals + reheat + cooling)
    ):
        raise RuntimeError("Expected positive fan, terminal, reheat and cooling sizing")
    if (
        source.read_bytes() != original_source
        or fixture.read_bytes() != original_fixture
        or output.read_bytes() != original_output
    ):
        raise RuntimeError("Source/fixture/output bytes changed unexpectedly")
    return {
        "fixture": "hydronic" if hydronic else "electric_dx",
        "artifacts": str(case_dir),
        "openstudio_version": applied["openstudio_version"],
        "timing": timing,
        "modeling_and_reporting_seconds": sum(
            value["seconds"] for key, value in timing.items() if key != "sizing"
        ),
        "script_recovery_retries": 0,
        "actual_agent_retries": None,
        "expected_negative_checks": {
            "existing_output_preserved": True,
            "stale_hash_blocked": True,
        },
        "original_input_preserved": True,
        "topology": applied["validation"],
        "sizing": {
            "fan_flow_m3_s": fan,
            "terminal_flows_m3_s": terminals,
            "reheat_capacities_w": reheat,
            "cooling_capacity_or_design_load_w": cooling,
            "severe_errors": 0,
            "fatal_errors": 0,
            "warning_count": int(re.search(r"-- (\d+) Warning", summary).group(1)),
            "summary": summary,
        },
        "preflight_output_size": size_output(preflight_raw, compact_preflight),
        "apply_output_size": size_output(apply_raw, compact_apply),
    }


def verify_parity(result):
    numeric_keys = (
        "fan_flow_m3_s",
        "terminal_flows_m3_s",
        "reheat_capacities_w",
        "cooling_capacity_or_design_load_w",
    )
    for fixture in ("hydronic", "electric_dx"):
        pair = [c for c in result["cases"] if c["fixture"] == fixture]
        if len(pair) != 2 or pair[0]["topology"] != pair[1]["topology"]:
            raise RuntimeError("Host exports differ in semantic topology")
        baseline = next(c for c in result["baseline_sizing"] if c["case"] == fixture)
        for key in numeric_keys:
            old = baseline[key]
            if isinstance(old, dict):
                old = sorted(old.values())
            for case in pair:
                current = case["sizing"][key]
                if len(current) != len(old) or not all(
                    math.isclose(a, b, rel_tol=1e-8, abs_tol=1e-8)
                    for a, b in zip(current, old)
                ):
                    raise RuntimeError(f"Sizing changed from phase 4: {fixture}/{key}")
            if pair[0]["sizing"][key] != pair[1]["sizing"][key]:
                raise RuntimeError(f"Host sizing differs: {fixture}/{key}")
    result["host_semantic_parity"] = True
    result["phase4_sizing_parity"] = True


def evaluate(output_dir, executable, baseline_ref, incompatible_executable=None):
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("Evaluation requires a new output directory")
    output_dir.mkdir(parents=True)
    sdk_scripts = ROOT / "skills/sdk_scripts"
    sys.path.insert(0, str(sdk_scripts))
    from common.version_guard import require_sdk

    sdk = require_sdk()  # Developer fixture creation also uses the exact SDK.
    result = {
        "mode": "local_evaluation",
        "context": context_comparison(baseline_ref),
        "cases": [],
        "agent_runs": 0,
        "user_selected_local_evaluation": True,
        "limitations": [
            "No live Claude/Codex agents or actual billed-token measurement",
            "No legacy generated-code execution/timing/retry comparison",
            "One local run per host/fixture; timings are not a statistical benchmark",
            "Generic construction and existing fixture plants; no annual or compliance validation",
        ],
    }
    for host, adapter_type in (("claude", ClaudeCodeAdapter), ("codex", CodexAdapter)):
        export = adapter_type(
            HostAdapterConfig(
                host_name="claude_code" if host == "claude" else host,
                workspace_root=ROOT,
                runtime_mode="marketplace",
            )
        ).export_plugin(output_dir / f"{host}-export", dry_run=False)
        # Run only the relocated owning skill, with the rest of the plugin removed.
        skill = output_dir / f"{host}-skill"
        shutil.copytree(
            export.plugin_dir / "skills/openstudio-vav-reheat-system-creator", skill
        )
        shutil.rmtree(output_dir / f"{host}-export")
        if incompatible_executable:
            _, raw = run(
                [
                    sys.executable,
                    "-S",
                    skill / "scripts/doctor.py",
                    "--openstudio",
                    incompatible_executable,
                ],
                output_dir,
                output_dir / f"{host}-wrong-version.log",
                expected=2,
            )
            rejected = json.loads(raw)
            if rejected["ok"] or rejected.get("openstudio_executable"):
                raise RuntimeError("Incompatible explicit executable was accepted")
            result.setdefault("incompatible_version_checks", {})[host] = rejected
        for hydronic in (True, False):
            case = evaluate_case(
                executable,
                skill,
                output_dir / f"{host}-{'hydronic' if hydronic else 'electric-dx'}",
                hydronic,
                sdk,
            )
            case["host_export"] = host
            result["cases"].append(case)
    result["baseline_sizing"] = json.loads(
        (ROOT / "tests/fixtures/vav_sizing_baseline.json").read_text()
    )["cases"]
    verify_parity(result)
    (output_dir / "evaluation.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--openstudio", type=Path, required=True)
    parser.add_argument("--baseline-ref", default="fbfd8f6^")
    parser.add_argument("--incompatible-openstudio", type=Path)
    args = parser.parse_args()
    result = evaluate(
        args.output_dir.resolve(),
        args.openstudio.resolve(),
        args.baseline_ref,
        (
            args.incompatible_openstudio.resolve()
            if args.incompatible_openstudio
            else None
        ),
    )
    print(
        json.dumps(
            {
                "ok": True,
                "report": str(args.output_dir.resolve() / "evaluation.json"),
                "instruction_character_reduction_percent": result["context"][
                    "instruction_character_reduction_percent"
                ],
                "cases": len(result["cases"]),
                "host_semantic_parity": result["host_semantic_parity"],
            }
        )
    )


if __name__ == "__main__":
    main()
