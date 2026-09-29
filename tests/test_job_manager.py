from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from openstudio_ai_mcp.server import OpenStudioService


def test_fail_hydrates_a_persisted_job_before_marking_it_failed(tmp_path: Path) -> None:
    service = OpenStudioService(workspace_root=tmp_path)
    job = service.job_manager.create_job(
        model_id="model-1", run_mode="sizing", options={}
    )
    service.job_manager._jobs.pop(job.job_id)

    service.job_manager.fail(job.job_id, error={"message": "simulation failed"})

    persisted = service.state_store.get_job(job.job_id)
    assert persisted is not None
    assert persisted["state"] == "FAILED"
    assert persisted["error"] == {"message": "simulation failed"}


def test_fail_reports_an_unknown_job_id_consistently(tmp_path: Path) -> None:
    service = OpenStudioService(workspace_root=tmp_path)

    with pytest.raises(KeyError, match="Unknown job_id: missing-job"):
        service.job_manager.fail("missing-job", error={"message": "simulation failed"})


def test_failure_artifact_registration_cannot_leave_a_job_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = OpenStudioService(workspace_root=tmp_path)
    job = service.job_manager.create_job(
        model_id="model-1", run_mode="sizing", options={}
    )

    def raise_simulation_error(*_args, **_kwargs) -> None:
        raise RuntimeError("OpenStudio failed")

    def raise_artifact_error(*_args, **_kwargs) -> dict[str, str]:
        raise KeyError("model-1")

    monkeypatch.setattr(service, "_run_openstudio_cli_sync", raise_simulation_error)
    monkeypatch.setattr(
        service, "_register_failure_artifacts", raise_artifact_error
    )

    asyncio.run(
        service._run_simulation_async(
            job_id=job.job_id, model_id="model-1", options={}
        )
    )

    failed_job = service.job_manager.get(job.job_id)
    assert failed_job is not None
    assert failed_job.state == "FAILED"
    assert failed_job.error is not None
    assert failed_job.error["message"] == "OpenStudio failed"
    assert failed_job.artifacts == {}
