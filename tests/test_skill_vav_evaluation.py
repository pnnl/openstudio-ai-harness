"""Protect the local evaluator against silently accepting sizing regressions."""

import copy
import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "skill_vav_evaluation", ROOT / "scripts/evaluate_skill_vav.py"
)
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


@pytest.fixture
def results():
    baseline = json.loads(
        (ROOT / "docs/SKILL_SCRIPT_PHASE4_VERIFICATION.json").read_text()
    )["cases"]
    cases = []
    for old in baseline:
        sizing = {
            key: copy.deepcopy(old[key])
            for key in (
                "fan_flow_m3_s",
                "terminal_flows_m3_s",
                "reheat_capacities_w",
                "cooling_capacity_or_design_load_w",
            )
        }
        sizing["reheat_capacities_w"] = sorted(sizing["reheat_capacities_w"].values())
        for host in ("claude", "codex"):
            cases.append(
                {
                    "host_export": host,
                    "fixture": old["case"],
                    "topology": {"checks": old["topology_checks"]},
                    "sizing": copy.deepcopy(sizing),
                }
            )
    return {"cases": cases, "baseline_sizing": baseline}


def test_local_comparison_accepts_phase4_sizing(results):
    evaluation.verify_parity(results)
    assert results["host_semantic_parity"] and results["phase4_sizing_parity"]


@pytest.mark.parametrize(
    "key",
    [
        "fan_flow_m3_s",
        "terminal_flows_m3_s",
        "reheat_capacities_w",
        "cooling_capacity_or_design_load_w",
    ],
)
def test_local_comparison_rejects_shared_regression_even_if_hosts_agree(results, key):
    fixture = results["cases"][0]["fixture"]
    for case in results["cases"]:
        if case["fixture"] == fixture:
            case["sizing"][key][0] *= 1.1
    with pytest.raises(RuntimeError, match="Sizing changed from phase 4"):
        evaluation.verify_parity(results)


def test_local_comparison_rejects_different_topology(results):
    results["cases"][0]["topology"]["checks"] -= 1
    with pytest.raises(RuntimeError, match="semantic topology"):
        evaluation.verify_parity(results)
