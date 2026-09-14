from __future__ import annotations

import json
from pathlib import Path


def test_calibration_routing_preserves_service_and_provider_boundaries() -> None:
    skill = Path("skills/calibration_mcp_orchestration.md").read_text(encoding="utf-8")

    assert "`bem-calibration`" in skill
    assert "`lbnl_bem_calibration`" in skill
    assert "`skills/list`" in skill
    assert "`skills/get`" in skill
    assert "`skill://pattern-based-calibration/...`" in skill
    assert "former standalone LBNL calibration skill" in skill
    assert "never an `execution_provider`" in skill
    assert "`openstudio-mcp`" in skill
    assert "`nlr_openstudio`" in skill
    assert "`openstudio_ai`" in skill
    assert "exactly one mutating provider" in skill
    assert "host-visible" in skill
    assert "run_record.json" in skill
    assert "eplusout.sql" in skill
    assert "non-converged" in skill
    assert "Do not package or register LBNL's former filesystem calibration skill" in skill


def test_calibration_routing_encodes_live_session_lessons() -> None:
    """Guidance verified by the 2026-09-14 three-server smoke test."""
    skill = Path("skills/calibration_mcp_orchestration.md").read_text(encoding="utf-8")

    # Identity: framework versions are not application versions.
    assert "`get_versions.openstudio_mcp`" in skill
    assert "not from `serverInfo.version`" in skill
    assert "recorded as absent, never inferred" in skill
    assert "Call `skills/list`\n   directly" in skill
    # Evidence isolation and staged-seed lineage.
    assert "dedicated, initially empty\n   host directory per project" in skill
    assert "Stage the incoming model through the selected provider" in skill
    assert "gates against the\n   staged seed" in skill
    assert "expected_model_sha256=<its host\n   hash>" in skill
    # Measure resolution stays provider-side; recipes never deliver code.
    assert "`stage_measures`" in skill
    assert "`find_measure` → `selected_measure.measure_dir`" in skill
    assert "`list_measure_arguments`" in skill
    assert "record that as a blackboard assumption" in skill
    # Provider status vocabularies and ledger acceptance.
    assert "NLR `success`; EnergyPlus-MCP `completed`" in skill
    assert "returns the record under `run`" in skill
    assert 'placeholder `decision="rejected"`' in skill
    assert "`ok:\n   true` alone is not acceptance" in skill
    assert "never re-simulate a rung to retry a\n   ledger write" in skill
    # Honest completion after a committed sweep.
    assert "progress, not completion" in skill
    assert "termination basis is still the pattern loop" in skill


def test_calibration_contract_records_verified_live_facts() -> None:
    contract = Path("docs/CALIBRATION_MCP_INTEGRATION.md").read_text(encoding="utf-8")

    assert "## Verified Live Session Facts" in contract
    assert "NLR `success`/`failed`/`cancelled`; EnergyPlus-MCP `completed`/`failed`" in contract
    assert "does not advertise the skills extension" in contract
    assert "re-serialized seed" in contract
    assert "binds `check_measure_reach` to the baseline model hash" in contract
    assert 'placeholder `decision="rejected"`' in contract
    assert "`configured_disabled`" in contract
    assert "`~/.claude.json`" in contract
    assert "`claude_desktop_config.json`" in contract


def test_calibration_contract_maps_extensible_blackboard_metadata() -> None:
    contract = Path("docs/CALIBRATION_MCP_INTEGRATION.md").read_text(encoding="utf-8")
    workflow_schema = json.loads(
        Path("blackboard/schemas/workflow_state.schema.json").read_text(
            encoding="utf-8"
        )
    )
    artifact_schema = json.loads(
        Path("blackboard/schemas/artifact_record.schema.json").read_text(
            encoding="utf-8"
        )
    )

    for field in (
        "workflow_id",
        "calibration_project_id",
        'calibration_connector: "bem-calibration"',
        'calibration_domain_service: "lbnl_bem_calibration"',
        "calibration_service_version",
        "calibration_service_digest",
        "calibration_tool_inventory",
        "model_id",
        "host_path",
        "container_path",
        "provider_run_id",
        "calibration_ledger_run_id",
        "host_runs_dir",
        "provider_runs_dir",
        "openstudio_version",
        "energyplus_version",
        "weather_sha256",
        "calendar_year",
        "bill_electricity_unit",
        "bill_gas_unit",
        "calibration_report_sha256",
    ):
        assert field in contract

    assert "intentionally not added to generated" in contract
    assert "core_ready` true or false" in contract
    assert workflow_schema["additionalProperties"] is True
    assert artifact_schema["additionalProperties"] is True
    assert artifact_schema["properties"]["metadata"]["type"] == "object"


def test_claude_agent_prompt_routes_calibration_requests() -> None:
    """The Codex orchestrator skill is not exported for Claude; the agent prompt must route."""
    prompt = Path("prompts/openstudio_agent.md").read_text(encoding="utf-8")

    assert "load `calibration-mcp-orchestration`" in prompt
    assert "`bem-calibration`" in prompt
    assert "`lbnl_bem_calibration`, never an\n  execution provider" in prompt
    assert "report calibration as unavailable" in prompt
    # Routing appears before the NLR provider gate so calibration owns the workflow shape.
    assert prompt.index("calibration-mcp-orchestration") < prompt.index("delegated-nlr-modeling")
