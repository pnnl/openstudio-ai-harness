import asyncio
from pathlib import Path

import pytest

from openstudio_ai_mcp.server import OpenStudioService
from openstudio_ai_mcp.tools.session import register_session_tools
from openstudio_ai_mcp.tools.schemas import (
    ModelCloneArgs,
    ModelLoadArgs,
    SessionCheckpointArgs,
    SessionCreateArgs,
    SessionFindingArgs,
)


def test_session_preserves_model_lineage_findings_and_checkpoint(tmp_path: Path) -> None:
    source = tmp_path / "source.osm"
    source.write_text("Version,3.8;\n", encoding="utf-8")
    workspace = tmp_path / "runtime"
    learning_db = tmp_path / "learning.sqlite"
    service = OpenStudioService(workspace_root=workspace, learning_db_path=learning_db)

    session_id = service.session_create(SessionCreateArgs(goal="Diagnose lighting"))["session"]["session_id"]
    loaded = service.model_load(ModelLoadArgs(model_uri=source.as_uri(), session_id=session_id))
    loaded_artifact = service.artifacts.must_get(loaded["model_id"])
    assert loaded_artifact.session_id == session_id
    assert loaded_artifact.model_revision_id == loaded["model_revision_id"]
    cloned = service.model_clone(ModelCloneArgs(model_id=loaded["model_id"]))

    revisions = service.session_get(session_id)["model_revisions"]
    assert [revision["operation"] for revision in revisions] == ["load", "clone"]
    assert revisions[1]["parent_revision_id"] == loaded["model_revision_id"]
    assert Path(service._get_model_state(loaded["model_id"]).metadata["model_uri"].removeprefix("file://")).exists()

    finding = service.session_record_finding(SessionFindingArgs(
        session_id=session_id,
        category="results_plausibility",
        severity="warning",
        assertion="Interior lighting energy is unexpectedly high.",
        evidence=[{"artifact_id": loaded["model_id"]}],
    ))["finding"]
    checkpoint = service.session_checkpoint(SessionCheckpointArgs(session_id=session_id, reason="handoff"))["checkpoint"]

    assert finding["finding_id"]
    assert loaded["model_id"] in checkpoint["artifact_ids"]
    assert cloned["model_revision_id"]

    restarted = OpenStudioService(workspace_root=workspace, learning_db_path=learning_db)
    rehydrated = restarted._get_model_state(loaded["model_id"])
    assert rehydrated.metadata["model_uri"]
    assert rehydrated.metadata["model_revision_id"] == loaded["model_revision_id"]
    resumed_clone = restarted.model_clone(ModelCloneArgs(model_id=loaded["model_id"]))
    assert restarted.state_store.get_model_revision(resumed_clone["model_revision_id"])["parent_revision_id"] == loaded["model_revision_id"]
    assert restarted.session_get(session_id)["checkpoint"]["checkpoint_id"] == checkpoint["checkpoint_id"]

    other_session = service.session_create(SessionCreateArgs(goal="Other"))["session"]["session_id"]
    with pytest.raises(ValueError, match="does not belong"):
        service.session_record_finding(SessionFindingArgs(
            session_id=other_session,
            category="results",
            severity="warning",
            assertion="cross-session evidence",
            evidence=[{"artifact_id": loaded["model_id"]}],
        ))


def test_session_finding_tool_reports_cross_session_evidence_as_invalid_argument(
    tmp_path: Path,
) -> None:
    class FakeMcp:
        def __init__(self) -> None:
            self.tools: dict[str, object] = {}

        def tool(self, *, name: str, description: str):
            def register(func):
                self.tools[name] = func
                return func

            return register

        def resource(self, *_args, **_kwargs):
            def register(func):
                return func

            return register

    service = OpenStudioService(workspace_root=tmp_path / "runtime")
    owner_session = service.session_create(SessionCreateArgs(goal="Owner"))["session"][
        "session_id"
    ]
    other_session = service.session_create(SessionCreateArgs(goal="Other"))["session"][
        "session_id"
    ]
    artifact = service.artifacts.create(
        kind="osm", metadata={}, session_id=owner_session
    )
    mcp = FakeMcp()
    register_session_tools(mcp, service)

    payload = asyncio.run(
        mcp.tools["session_record_finding"](
            session_id=other_session,
            category="results",
            severity="warning",
            assertion="cross-session evidence",
            evidence=[{"artifact_id": artifact.artifact_id}],
        )
    )

    assert payload["ok"] is False
    assert payload["error"]["type"] == "invalid_argument"


def test_persisted_job_can_be_recovered_by_new_service(tmp_path: Path) -> None:
    service = OpenStudioService(workspace_root=tmp_path / "runtime", learning_db_path=tmp_path / "learning.sqlite")
    job = service.job_manager.create_job(model_id="model", run_mode="sizing", options={}, session_id="session")
    service.job_manager.fail(job.job_id, error={"message": "failed"})

    restarted = OpenStudioService(workspace_root=tmp_path / "runtime", learning_db_path=tmp_path / "learning.sqlite")
    recovered = restarted.job_manager.get(job.job_id)
    assert recovered is not None
    assert recovered.state == "FAILED"
    assert recovered.session_id == "session"


def test_running_job_is_marked_interrupted_after_restart(tmp_path: Path) -> None:
    workspace = tmp_path / "runtime"
    learning_db = tmp_path / "learning.sqlite"
    service = OpenStudioService(workspace_root=workspace, learning_db_path=learning_db)
    job = service.job_manager.create_job(model_id="model", run_mode="sizing", options={})

    restarted = OpenStudioService(workspace_root=workspace, learning_db_path=learning_db)
    recovered = restarted.job_manager.get(job.job_id)
    assert recovered is not None
    assert recovered.state == "FAILED"
    assert recovered.error["type"] == "interrupted"
    assert job.job_id not in restarted.job_manager.running_job_ids()


def test_diagnostic_bundle_bounds_logs_and_falls_back_to_energyplus_error(tmp_path: Path) -> None:
    service = OpenStudioService(workspace_root=tmp_path / "runtime", learning_db_path=tmp_path / "learning.sqlite")
    job = service.job_manager.create_job(model_id="model", run_mode="sizing", options={})
    workspace = service.workspace_manager.workspace_path(job.job_id)
    (workspace / "openstudio.stdout.log").write_text("0123456789", encoding="utf-8")
    (workspace / "run").mkdir()
    (workspace / "run" / "eplusout.err").write_text("EnergyPlus failure", encoding="utf-8")
    logs = service.artifacts.create(
        kind="logs",
        metadata={
            "job_id": job.job_id,
            "stdout_path": str(workspace / "openstudio.stdout.log"),
            "stderr_path": str(workspace / "missing.stderr.log"),
            "err_path": None,
        },
    )
    service.job_manager.fail(job.job_id, error={"message": "failed"}, artifacts={"logs_id": logs.artifact_id})

    bundle = service.session_diagnostic_bundle(job_id=job.job_id, max_chars=4)
    assert bundle["log_excerpts"]["stdout"] == "6789"
    assert bundle["log_excerpts"]["err"] == "lure"
    assert "stderr" not in bundle["log_excerpts"]
