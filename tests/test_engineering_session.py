from pathlib import Path

from openstudio_ai_mcp.server import OpenStudioService
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
    assert restarted._get_model_state(loaded["model_id"]).metadata["model_uri"]
    assert restarted.session_get(session_id)["checkpoint"]["checkpoint_id"] == checkpoint["checkpoint_id"]


def test_persisted_job_can_be_recovered_by_new_service(tmp_path: Path) -> None:
    service = OpenStudioService(workspace_root=tmp_path / "runtime", learning_db_path=tmp_path / "learning.sqlite")
    job = service.job_manager.create_job(model_id="model", run_mode="sizing", options={}, session_id="session")
    service.job_manager.fail(job.job_id, error={"message": "failed"})

    restarted = OpenStudioService(workspace_root=tmp_path / "runtime", learning_db_path=tmp_path / "learning.sqlite")
    recovered = restarted.job_manager.get(job.job_id)
    assert recovered is not None
    assert recovered.state == "FAILED"
    assert recovered.session_id == "session"
