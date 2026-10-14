"""Stream-json extraction tests on a recorded Claude Code session (no LLM, no servers)."""
from pathlib import Path

from standalone.evals.checks import mcp_tool_name, score_case
from standalone.evals.claude_host import (
    ClaudeRun,
    connected_servers,
    extract_tool_calls,
    parse_stream_json,
    tool_timeline,
)

STREAM = Path(__file__).parent / "data" / "claude_both_stream.ndjson"
PROVIDERS = {"openstudio_ai": "harness"}


def _events() -> list[dict]:
    return parse_stream_json(STREAM.read_text())


def test_extract_tool_calls_in_order_with_providers() -> None:
    calls = extract_tool_calls(_events(), providers=PROVIDERS)
    assert [(c.name, c.provider) for c in calls] == [
        ("load_osm_model", "openstudio-mcp"),
        ("change_building_location", "openstudio-mcp"),
        ("list_weather_files", "openstudio-mcp"),
    ]
    assert calls[0].arguments


def test_unmapped_server_keeps_its_name_and_builtins_are_agent() -> None:
    events = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "1", "name": "Skill", "input": {}},
            {"type": "tool_use", "id": "2", "name": mcp_tool_name("other", "ping"), "input": {}},
        ]}},
    ]
    calls = extract_tool_calls(events, providers=PROVIDERS)
    assert [(c.name, c.provider) for c in calls] == [("Skill", "agent"), ("ping", "other")]


def test_timeline_pairs_results_and_flags_errors() -> None:
    timeline = tool_timeline(_events(), providers=PROVIDERS)
    assert [t["name"] for t in timeline][:2] == ["load_osm_model", "change_building_location"]
    assert all(t["is_error"] is not None for t in timeline)


def test_init_reports_connected_servers() -> None:
    run = ClaudeRun(_events(), "", 0)
    assert connected_servers(run) == {"openstudio_ai": "connected", "openstudio-mcp": "connected"}
    assert not run.is_error
    assert run.final_text


def test_scoring_reuses_checks_on_extracted_calls() -> None:
    calls = extract_tool_calls(_events(), providers=PROVIDERS)
    case = {
        "required_tools": [{"tool": "run_simulation", "provider": "openstudio-mcp"}],
        "forbidden_tools": ["sim_*"],
    }
    results = {r.check: r for r in score_case(case, calls)}
    assert not results["required:run_simulation@openstudio-mcp"].passed  # recorded run never simulated
    assert results["forbidden:sim_*"].passed


def test_plugin_installed_server_names_map_to_the_same_provider() -> None:
    events = [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "1", "name": "mcp__plugin_openstudio-ai_openstudio_ai__model_load", "input": {}},
    ]}}]
    (call,) = extract_tool_calls(events, providers=PROVIDERS)
    assert (call.name, call.provider) == ("model_load", "harness")
