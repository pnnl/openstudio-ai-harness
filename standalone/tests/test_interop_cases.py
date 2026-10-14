"""Case loading and SUT-entry validation for the interop runner (no LLM, no servers)."""
import json

import pytest

from standalone.evals.interop import load_cases, load_sut_entry, substitute


def test_bundled_case_targets_openstudio_mcp() -> None:
    (case,) = load_cases(["openstudio_mcp_simulation_001"])
    assert case["required_tools"] == [{"tool": "run_simulation", "provider": "openstudio-mcp"}]
    assert "{input_dir}" in case["prompt"]


def test_cases_dir_adds_cases_and_rejects_duplicates(tmp_path) -> None:
    (tmp_path / "mine.json").write_text(json.dumps([{"case_id": "mine_001", "prompt": "hi"}]))
    assert {c["case_id"] for c in load_cases(extra_dir=tmp_path)} >= {"mine_001", "openstudio_mcp_simulation_001"}
    (tmp_path / "dup.json").write_text(json.dumps([{"case_id": "openstudio_mcp_simulation_001", "prompt": "x"}]))
    with pytest.raises(ValueError, match="duplicate"):
        load_cases(extra_dir=tmp_path)


def test_unknown_case_id_is_an_error() -> None:
    with pytest.raises(ValueError, match="unknown"):
        load_cases(["nope"])


def test_sut_entry_needs_exactly_one_server(tmp_path) -> None:
    path = tmp_path / "sut.json"
    path.write_text(json.dumps({"mcpServers": {"a": {"command": "x"}, "b": {"command": "y"}}}))
    with pytest.raises(ValueError, match="exactly one"):
        load_sut_entry(path)
    path.write_text(json.dumps({"mcpServers": {"srv": {"command": "x"}}}))
    assert load_sut_entry(path)[0] == "srv"


def test_model_comes_from_flag_then_anthropic_model(monkeypatch) -> None:
    from standalone.evals.interop import resolve_model

    monkeypatch.setenv("ANTHROPIC_MODEL", "from-env")
    assert resolve_model("from-flag") == ("from-flag", "--model")
    assert resolve_model(None) == ("from-env", "ANTHROPIC_MODEL")
    monkeypatch.delenv("ANTHROPIC_MODEL")
    assert resolve_model(None) == (None, "unset")


def test_sandbox_placeholder_is_substituted_everywhere(tmp_path) -> None:
    entry = {"command": "x", "args": ["{sandbox}/a"], "env": {"K": "{sandbox}"}}
    out = substitute(entry, tmp_path)
    assert out["args"] == [f"{tmp_path}/a"] and out["env"]["K"] == str(tmp_path)


def test_expected_metric_within_tolerance_and_artifacts() -> None:
    from standalone.evals.checks import check_expected

    answer = "| **Site EUI** | **34.14 kBtu/ft²/yr** |\n| Total | 198.19 GJ |"
    spec = {"metrics": [{"name": "Site EUI", "value": 34.0, "tolerance_pct": 5}], "artifacts": ["*.sql"]}
    ok, art = check_expected(spec, answer, ["eplusout.sql"])
    assert ok.passed and art.passed
    bad = check_expected({"metrics": [{"name": "Site EUI", "value": 50, "tolerance_pct": 5}]}, answer)[0]
    assert not bad.passed and "34.14" in bad.reason
    assert not check_expected({"artifacts": ["*.sql"]}, answer, [])[0].passed
    assert check_expected(None, answer) == []
