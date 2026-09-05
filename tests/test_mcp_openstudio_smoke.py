from __future__ import annotations

import asyncio
import os
import socket
import time
from pathlib import Path

import pytest
from dotenv import dotenv_values

from mcp import ClientSession
from mcp.client.sse import sse_client

import openstudio_mcp.server as mcp_server
from openstudio_mcp.server import (
    OpenStudioModelState,
    OpenStudioService,
)

MCP_HOST = "localhost"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


MCP_PORT = _find_free_port()
MCP_URL = f"http://{MCP_HOST}:{MCP_PORT}/sse"


def _find_local_epw() -> Path | None:
    candidates = [
        FIXTURE_DIR / "USA_FL_Tampa.Intl.AP.722110_TMY3.epw",
        Path.home()
        / "github/openstudio-standards/data/weather/USA_FL_Tampa-MacDill.AFB.747880_TMY3.epw",
    ]
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved.exists():
            return resolved
    return None


@pytest.fixture(scope="session", autouse=True)
def start_mcp():
    from multiprocessing import Process
    import time

    process = Process(
        target=mcp_server.serve,
        args=(MCP_HOST, MCP_PORT, "sse"),
        daemon=True,
    )
    process.start()
    time.sleep(2)
    yield
    process.terminate()


@pytest.mark.asyncio
async def test_openstudio_mcp_smoke_list_and_call_model_load() -> None:
    async with sse_client(MCP_URL) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            initialization = await session.initialize()
            assert initialization.serverInfo.name == "openstudio-ai-mcp"
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert "model_load" in names
            assert "model_clone" in names
            assert "model_export_geometry_viewer" in names
            assert "model_list_measures" in names
            assert "sim_run" in names
            assert "runtime_plugin_compatibility" in names
            assert "runtime_openstudio_status" in names
            assert "runtime_storage_usage" in names
            assert "runtime_prune_preview" in names
            assert "runtime_prune" in names
            assert "blackboard_initialize_workflow" in names
            assert "blackboard_get_workflow" in names
            assert "blackboard_update_state_patch" in names
            assert "blackboard_mark_step_complete" in names

            result = await session.call_tool(
                name="model_load",
                arguments={"model_uri": "file:///tmp/dummy.osm"},
            )
            payload = result.structuredContent
            assert isinstance(payload, dict)
            assert payload["ok"] is True
            assert isinstance(payload["model_id"], str)


def test_openstudio_runtime_state_store_prunes_unprotected_workspaces(
    tmp_path: Path,
) -> None:
    service = OpenStudioService(workspace_root=tmp_path)

    stale_workspace = service.workspace_manager.create_workspace("measure-stale")
    (stale_workspace / "out.osm").write_text("stale model", encoding="utf-8")
    service._register_workspace(
        workspace_id="measure-stale",
        kind="measure",
        model_id="stale-model",
        metadata={"measure_id": "test"},
    )

    viewer_workspace = service.workspace_manager.create_workspace("geometry-stale")
    (viewer_workspace / "geometry-viewer.html").write_text("viewer", encoding="utf-8")
    viewer_artifact = service.artifacts.create(
        kind="geometry_viewer_html",
        metadata={"path": str(viewer_workspace / "geometry-viewer.html")},
    )
    service._register_workspace(
        workspace_id="geometry-stale",
        kind="geometry_viewer",
        model_id="stale-model",
        artifact_id=viewer_artifact.artifact_id,
    )

    active_workspace = service.workspace_manager.create_workspace("measure-active")
    active_model = active_workspace / "out.osm"
    active_model.write_text("active model", encoding="utf-8")
    service._register_workspace(
        workspace_id="measure-active",
        kind="measure",
        model_id="active-model",
        metadata={"measure_id": "test"},
    )
    service.model_states["active-model"] = OpenStudioModelState(
        model_id="active-model",
        metadata={
            "model_uri": active_model.as_uri(),
            "weather": None,
            "workspace_id": "measure-active",
        },
    )

    preview = service.runtime_prune_preview()

    assert preview["ok"] is True
    assert {item["workspace_id"] for item in preview["candidates"]} == {
        "measure-stale",
        "geometry-stale",
    }
    protected = {item["workspace_id"]: item for item in preview["protected"]}
    assert protected["measure-active"]["protection_reason"] == "active_model_state"

    pruned = service.runtime_prune()

    assert pruned["ok"] is True
    assert pruned["reclaimed_bytes"] > 0
    assert not stale_workspace.exists()
    assert not viewer_workspace.exists()
    assert active_workspace.exists()

    usage = service.runtime_storage_usage()

    assert usage["ok"] is True
    assert usage["db_path"].endswith("openstudio_ai_runtime.sqlite")
    workspaces = {item["workspace_id"]: item for item in usage["workspaces"]}
    assert workspaces["measure-stale"]["status"] == "pruned"
    assert workspaces["measure-stale"]["size_bytes"] == 0
    assert workspaces["geometry-stale"]["status"] == "pruned"
    with pytest.raises(KeyError):
        service.artifacts.must_get(viewer_artifact.artifact_id)


def test_openstudio_workspace_manager_does_not_size_external_paths(
    tmp_path: Path,
) -> None:
    service = OpenStudioService(workspace_root=tmp_path / "workspace")
    external = tmp_path / "outside.txt"
    external.write_text("outside workspace", encoding="utf-8")

    assert service.workspace_manager.path_size(external) == 0


def test_openstudio_mcp_blackboard_supports_workflow_state(tmp_path: Path) -> None:
    service = OpenStudioService(workspace_root=tmp_path)

    initialized = service.blackboard_initialize_workflow(
        goal="Add VAV reheat system",
        workflow_id="vav_reheat_001",
        initial_patch={
            "mode": "preflight",
            "pending_steps": ["preflight_inspection", "clarification_gate"],
            "system": {"system_name": "3 Zone VAV", "target_zone_names": []},
        },
    )

    assert initialized["ok"] is True
    workflow_id = initialized["workflow_id"]

    patched = service.blackboard_update_state_patch(
        workflow_id=workflow_id,
        patch={"current_model_path": "/tmp/model.osm"},
    )
    assert patched["state"]["current_model_path"] == "/tmp/model.osm"

    completed = service.blackboard_mark_step_complete(
        workflow_id=workflow_id,
        step="preflight_inspection",
    )
    state = completed["state"]
    assert state["completed_steps"] == ["preflight_inspection"]
    assert state["pending_steps"] == ["clarification_gate"]

    assumption = service.blackboard_record_assumption(
        workflow_id=workflow_id,
        assumption="Use default VAV sizing temperatures until user overrides.",
    )
    assert assumption["state"]["assumptions"]

    phase = service.blackboard_get_phase_state(
        workflow_id=workflow_id,
        phase="clarification_gate",
        fields=["pending_steps", "completed_steps"],
    )
    assert phase["phase_state"]["phase"] == "clarification_gate"
    assert phase["phase_state"]["phase_pending"] is True

    listed = service.blackboard_list_workflows()
    assert listed["workflows"][0]["workflow_id"] == workflow_id

    snapshot = service.blackboard_snapshot_workflow(workflow_id=workflow_id)
    assert Path(snapshot["snapshot_path"]).exists()


def test_openstudio_mcp_warns_but_starts_for_incompatible_plugin_contract(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENSTUDIO_AI_PLUGIN_CONTRACT_VERSION", "999")

    class FakeMcp:
        def __init__(self) -> None:
            self.transport: str | None = None

        def run(self, *, transport: str) -> None:
            self.transport = transport

    fake_mcp = FakeMcp()
    monkeypatch.setattr(mcp_server, "create_server", lambda **_: fake_mcp)

    mcp_server.serve(transport="stdio")

    assert fake_mcp.transport == "stdio"
    assert "plugin/runtime compatibility notice" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_openstudio_mcp_apply_add_daylighting_measure() -> None:
    env_path = Path(".env")
    env_values = dotenv_values(env_path) if env_path.exists() else {}
    openstudio_path = (
        os.getenv("OPENSTUDIO_PATH", "").strip()
        or str(env_values.get("OPENSTUDIO_PATH", "")).strip()
    )
    if not openstudio_path or not Path(openstudio_path).exists():
        pytest.skip("OPENSTUDIO_PATH is not configured to a valid executable.")

    sample_model_uri = (FIXTURE_DIR / "sample.osm").resolve().as_uri()
    async with sse_client(MCP_URL) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            load_result = await session.call_tool(
                name="model_load",
                arguments={"model_uri": sample_model_uri},
            )
            load_payload = load_result.structuredContent
            assert isinstance(load_payload, dict)
            assert load_payload["ok"] is True
            original_model_id = load_payload["model_id"]

            measures_result = await session.call_tool(
                name="model_list_measures",
                arguments={},
            )
            measures_payload = measures_result.structuredContent
            assert isinstance(measures_payload, dict)
            assert measures_payload["ok"] is True
            measures = measures_payload.get("measures", [])
            assert any(item.get("measure_id") == "add_daylighting" for item in measures)

            apply_result = await session.call_tool(
                name="model_apply_measure",
                arguments={
                    "model_id": original_model_id,
                    "measure_id": "add_daylighting",
                    "args": {},
                },
            )
            apply_payload = apply_result.structuredContent
            assert isinstance(apply_payload, dict)
            assert apply_payload["ok"] is True
            assert isinstance(apply_payload["model_id"], str)
            assert apply_payload["model_id"] != original_model_id
            assert isinstance(apply_payload.get("changes", []), list)
            assert any(
                "daylight" in str(item).lower()
                for item in apply_payload.get("changes", [])
            )

            validate_result = await session.call_tool(
                name="model_validate",
                arguments={"model_id": apply_payload["model_id"]},
            )
            validate_payload = validate_result.structuredContent
            assert isinstance(validate_payload, dict)
            assert validate_payload["ok"] is True


@pytest.mark.asyncio
async def test_openstudio_mcp_simulation_flow_with_sample_model() -> None:
    sample_model_uri = (FIXTURE_DIR / "sample.osm").resolve().as_uri()
    async with sse_client(MCP_URL) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            load_result = await session.call_tool(
                name="model_load",
                arguments={"model_uri": sample_model_uri},
            )
            load_payload = load_result.structuredContent
            assert isinstance(load_payload, dict)
            assert load_payload["ok"] is True
            model_id = load_payload["model_id"]

            run_result = await session.call_tool(
                name="sim_run",
                arguments={"model_id": model_id, "run_mode": "sizing", "options": {}},
            )
            run_payload = run_result.structuredContent
            assert isinstance(run_payload, dict)

            # If no compatible CLI is configured, fail fast with invalid_state.
            if not run_payload.get("ok", False):
                assert run_payload["error"]["type"] == "invalid_state"
                return

            # Otherwise, the job should run asynchronously and eventually reach a terminal state.
            job_id = run_payload["job_id"]
            assert isinstance(job_id, str)

            final_state = None
            for _ in range(120):
                status_result = await session.call_tool(
                    name="sim_status",
                    arguments={"job_id": job_id},
                )
                status_payload = status_result.structuredContent
                assert isinstance(status_payload, dict)
                assert status_payload["ok"] is True
                final_state = status_payload["state"]
                if final_state in {"SUCCEEDED", "FAILED"}:
                    break
                await asyncio.sleep(0.5)

            assert final_state in {"SUCCEEDED", "FAILED"}


@pytest.mark.asyncio
async def test_openstudio_mcp_real_simulation_with_sample_model() -> None:
    env_path = Path(".env")
    env_values = dotenv_values(env_path) if env_path.exists() else {}
    openstudio_path = (
        os.getenv("OPENSTUDIO_PATH", "").strip()
        or str(env_values.get("OPENSTUDIO_PATH", "")).strip()
    )
    if not openstudio_path or not Path(openstudio_path).exists():
        pytest.skip("OPENSTUDIO_PATH is not configured to a valid executable.")
    epw_path = _find_local_epw()
    if epw_path is None:
        pytest.skip("Local EPW file not found for real simulation test.")

    sample_model_uri = (FIXTURE_DIR / "sample.osm").resolve().as_uri()
    workspace_root = Path(".openstudio_mcp_workspace").resolve()
    existing_sqls = (
        {str(p.resolve()) for p in workspace_root.rglob("run/eplusout.sql")}
        if workspace_root.exists()
        else set()
    )
    started_at = time.time()

    async with sse_client(MCP_URL) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            load_result = await session.call_tool(
                name="model_load",
                arguments={"model_uri": sample_model_uri},
            )
            load_payload = load_result.structuredContent
            assert isinstance(load_payload, dict)
            assert load_payload["ok"] is True
            model_id = load_payload["model_id"]

            set_weather_result = await session.call_tool(
                name="model_set_weather",
                arguments={"model_id": model_id, "epw_path": str(epw_path)},
            )
            set_weather_payload = set_weather_result.structuredContent
            assert isinstance(set_weather_payload, dict)
            assert set_weather_payload["ok"] is True

            run_result = await session.call_tool(
                name="sim_run",
                arguments={"model_id": model_id, "run_mode": "sizing", "options": {}},
            )
            run_payload = run_result.structuredContent
            assert isinstance(run_payload, dict)
            assert run_payload["ok"] is True
            job_id = run_payload["job_id"]

            final_state = None
            for _ in range(360):
                status_result = await session.call_tool(
                    name="sim_status",
                    arguments={"job_id": job_id},
                )
                status_payload = status_result.structuredContent
                assert isinstance(status_payload, dict)
                assert status_payload["ok"] is True
                final_state = status_payload["state"]
                if final_state in {"SUCCEEDED", "FAILED"}:
                    break
                await asyncio.sleep(1.0)

            assert final_state == "SUCCEEDED", status_payload

            artifacts_result = await session.call_tool(
                name="sim_artifacts",
                arguments={"job_id": job_id},
            )
            artifacts_payload = artifacts_result.structuredContent
            assert isinstance(artifacts_payload, dict)
            assert artifacts_payload["ok"] is True
            assert isinstance(artifacts_payload["sql_id"], str)
            assert isinstance(artifacts_payload["logs_id"], str)

            query_result = await session.call_tool(
                name="results_query",
                arguments={
                    "sql_id": artifacts_payload["sql_id"],
                    "query_type": "sizing_summary",
                    "params": {},
                },
            )
            query_payload = query_result.structuredContent
            assert isinstance(query_payload, dict)
            assert query_payload["ok"] is True
            summary_data = query_payload["data"]
            assert "annual_end_use_fuel_gj" in summary_data
            assert "design_day_end_use_fuel_j" in summary_data
            assert "annual_eui" in summary_data
            assert summary_data["annual_eui"]["total_site_energy_gj"] > 0.0

    assert workspace_root.exists()
    new_sqls = {str(p.resolve()) for p in workspace_root.rglob("run/eplusout.sql")}
    created_sqls = new_sqls - existing_sqls
    assert created_sqls, "No new eplusout.sql found in .openstudio_mcp_workspace."
    assert any(Path(p).stat().st_mtime >= started_at for p in map(Path, created_sqls))
