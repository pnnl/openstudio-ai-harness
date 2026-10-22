"""Case loading and SUT-entry validation for the interop runner (no LLM, no servers)."""
import json

import pytest

from evals.interop import load_cases, load_sut_entry, substitute


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
    from evals.interop import resolve_model

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
    from evals.checks import check_expected

    answer = "| **Site EUI** | **34.14 kBtu/ft²/yr** |\n| Total | 198.19 GJ |"
    spec = {"metrics": [{"name": "Site EUI", "value": 34.0, "tolerance_pct": 5}], "artifacts": ["*.sql"]}
    ok, art = check_expected(spec, answer, ["eplusout.sql"])
    assert ok.passed and art.passed
    bad = check_expected({"metrics": [{"name": "Site EUI", "value": 50, "tolerance_pct": 5}]}, answer)[0]
    assert not bad.passed and "34.14" in bad.reason
    assert not check_expected({"artifacts": ["*.sql"]}, answer, [])[0].passed
    assert check_expected(None, answer) == []


_OSM = """\
OS:Version,
  {aaa}, !- Handle
  3.10.0;                                 !- Version Identifier

OS:ThermalZone,
  {b1}, !- Handle
  Zone A;                                 !- Name

OS:ThermalZone,
  {b2}, !- Handle
  Zone B;                                 !- Name

OS:WeatherFile,
  {c1}, !- Handle
  Tampa International Ap,                 !- City
  FL;                                     !- State Province Region

OS:SizingPeriod:DesignDay,
  {d1}, !- Handle
  Tampa International Ap Htg 99.6%,       !- Name
  4.6;                                    !- Maximum Dry-Bulb Temperature {C}

OS:SizingPeriod:DesignDay,
  {d2}, !- Handle
  Tampa-MacDill Clg .4%,                  !- Name
  33.9;                                   !- Maximum Dry-Bulb Temperature {C}
"""


def test_parse_osm_reads_objects_and_labels() -> None:
    from evals.checks import parse_osm

    objs = parse_osm(_OSM)
    assert [o.type for o in objs].count("OS:ThermalZone") == 2
    weather = next(o for o in objs if o.type == "OS:WeatherFile")
    assert weather.get("city") == "Tampa International Ap"  # label match is case-insensitive
    day = next(o for o in objs if o.type == "OS:SizingPeriod:DesignDay")
    assert day.get("Maximum Dry-Bulb Temperature") == "4.6"  # unit in braces is stripped


def test_check_model_counts_version_and_fields(tmp_path) -> None:
    from evals.checks import check_model

    path = tmp_path / "m.osm"
    path.write_text(_OSM)
    spec = {
        "version_min": "3.0.0",
        "counts": {"OS:ThermalZone": 2},
        "fields": [
            {"type": "OS:WeatherFile", "field": "City", "contains": "International"},
            {"type": "OS:SizingPeriod:DesignDay", "field": "Name", "contains": "International"},  # any: passes
        ],
    }
    assert all(r.passed for r in check_model(spec, path))

    failing = {
        "version_min": "3.11.0",
        "counts": {"OS:ThermalZone": 3},
        "fields": [{"type": "OS:SizingPeriod:DesignDay", "field": "Name", "contains": "International", "match": "all"}],
    }
    assert [r.passed for r in check_model(failing, path)] == [True, False, False, False]
    # a missing object type or file fails instead of passing vacuously
    assert not check_model({"fields": [{"type": "OS:Nope", "field": "Name", "equals": "x"}]}, path)[-1].passed
    assert not check_model({"counts": {}}, None)[0].passed
    assert check_model(None, None) == []


def test_find_output_model_skips_unchanged_inputs(tmp_path) -> None:
    from evals.checks import find_output_model

    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "in.osm").write_text("original")
    assert find_output_model(tmp_path, {b"original"}) is None  # only the untouched input exists
    (tmp_path / "ws").mkdir()
    (tmp_path / "ws" / "out.osm").write_text("edited")
    assert find_output_model(tmp_path, {b"original"}).name == "out.osm"


def test_report_renders_results_failures_and_collapsed_sequences(tmp_path) -> None:
    from evals.report import render_report

    def rec(arm, passed, rep=1, calls=(("a", "harness"), ("a", "harness"), ("b", "srv"))):
        return {
            "case_id": "c1", "arm": arm, "rep": rep, "passed": passed,
            "checks": [{"check": "session", "passed": True, "reason": "ok"}]
            + ([] if passed else [{"check": "model:count:OS:X", "passed": False, "reason": "1 (want 2)"}]),
            "metrics": {"turns": 4 + rep, "tool_calls": 3, "output_tokens": 1000, "cost_usd": 0.5, "duration_s": 20.0},
            "tool_calls": [{"name": n, "provider": p} for n, p in calls],
        }

    (tmp_path / "summary.json").write_text(json.dumps([rec("both", True), rec("sut-only", False), rec("both", False, rep=2)]))
    text = render_report(tmp_path)
    assert "1/3 sessions passed" in text
    assert "| `c1` | - | FAIL | FAIL (1/2) |" in text  # arms without sessions show "-"; repeats show a rate
    assert "model:count:OS:X" in text and "1 (want 2)" in text
    assert "a(harness) x2 -> b(srv)" in text
    assert "| `c1` | sut-only | 5 | 3 | 1,000 | $0.50 | 20s |" in text  # single session
    assert "| `c1` | both | 6 | 3 | 1,000 | $0.50 | 20s |" in text  # median of 5 and 6 turns is 5.5, shown as 6
