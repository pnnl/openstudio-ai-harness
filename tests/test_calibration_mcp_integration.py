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
