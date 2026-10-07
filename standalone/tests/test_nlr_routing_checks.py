"""Unit tests for dual-MCP routing eval scoring (no NLR server or LLM needed)."""
import json

from standalone.evals.checks import (
    extract_tool_calls,
    mcp_tool_name,
    score_case,
    split_mcp_tool_name,
)
from standalone.evals.run import CASES_PATH

PROVIDERS = {"openstudio-mcp": "nlr", "openstudio_ai_mcp": "harness"}


def nlr(tool: str) -> str:
    return mcp_tool_name("openstudio-mcp", tool)


def harness(tool: str) -> str:
    return mcp_tool_name("openstudio_ai_mcp", tool)


def _span(name: str) -> dict:
    return {"type": "span_start", "name": "tool.call", "attributes": {"tool.name": name}}


def _trace(*names: str) -> list[dict]:
    noise = {"type": "event", "name": "tool.requested", "attributes": {"tool.name": harness("sim_run")}}
    return [noise, *(_span(n) for n in names)]


def _case() -> dict:
    return json.loads(CASES_PATH.read_text())[0]


def test_mcp_tool_name_round_trips() -> None:
    assert nlr("run_simulation") == "mcp__openstudio-mcp__run_simulation"
    assert split_mcp_tool_name(nlr("run_simulation")) == ("openstudio-mcp", "run_simulation")
    assert split_mcp_tool_name("load_skill") == (None, "load_skill")


def test_extract_tool_calls_tags_provider_in_order() -> None:
    calls = extract_tool_calls(
        _trace(harness("blackboard_initialize_workflow"), nlr("run_simulation"), "load_skill"),
        providers=PROVIDERS,
    )
    assert [(c.name, c.provider) for c in calls] == [
        ("blackboard_initialize_workflow", "harness"),
        ("run_simulation", "nlr"),
        ("load_skill", "agent"),
    ]


def test_simulation_case_passes_when_nlr_runs_simulation() -> None:
    calls = extract_tool_calls(
        _trace(nlr("load_osm_model"), nlr("run_simulation"), nlr("get_run_status")),
        providers=PROVIDERS,
    )
    assert all(r.passed for r in score_case(_case(), calls))


def test_simulation_case_fails_when_harness_simulates() -> None:
    calls = extract_tool_calls(
        _trace(harness("model_load"), harness("sim_run")), providers=PROVIDERS
    )
    results = {r.check: r for r in score_case(_case(), calls)}
    assert not results["required:run_simulation@nlr"].passed
    assert not results["forbidden:sim_*"].passed
    assert "sim_run" in results["forbidden:sim_*"].reason
