from __future__ import annotations

import json
from pathlib import Path

from learning.developer_pipeline.run_pipeline import (
    run_developer_learning_pipeline,
)
from openstudio_ai_mcp.server import OpenStudioService


def test_developer_learning_pipeline_writes_candidate_lesson(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    review_queue = tmp_path / "review_queue"
    logs_dir.mkdir()
    failure = {
        "stderr": "OpenStudio SDK error: Surface.getAzimuth returned radians but script treated it as degrees.",
        "script": {
            "code": "azimuth = surface.getAzimuth()  # incorrectly assumed degrees",
        },
    }
    (logs_dir / "python_script_failure_experience.jsonl").write_text(
        json.dumps(failure) + "\n",
        encoding="utf-8",
    )

    writes = run_developer_learning_pipeline(
        logs_dir=logs_dir,
        review_queue=review_queue,
        limit=5,
    )

    assert len(writes) == 1
    candidate = json.loads(writes[0].path.read_text(encoding="utf-8"))
    assert candidate["status"] == "candidate"
    assert candidate["review_required"] is True
    assert candidate["target"]["asset"] == "knowledge/openstudio_sdk_wiki/sdk_geometry.md"
    assert candidate["recommended_eval"]["expected_behavior"]
    assert candidate["evidence"][0]["line_number"] == 1


def test_personal_learning_requires_review_before_retrieval(tmp_path: Path) -> None:
    service = OpenStudioService(
        workspace_root=tmp_path / "workspace",
        learning_db_path=tmp_path / "user-data" / "learning.sqlite",
    )

    captured = service.learning_capture_observation(
        event_type="user_correction",
        summary="Validate schedule values are in degrees before applying a geometry edit.",
        source="codex",
        workflow_id="geometry-001",
        scope={"project": "office-retrofit", "openstudio_version": "3.10"},
        evidence={"user_feedback": "Azimuth values must be converted before editing."},
    )
    event_id = captured["event"]["event_id"]
    candidate = service.learning_create_candidate(
        event_id=event_id,
        summary="Confirm azimuth units before geometry edits.",
        guidance="Inspect the API documentation and convert radians before using degree-based inputs.",
        tags=["geometry", "sdk", "azimuth"],
        scope={"openstudio_version": "3.10"},
    )["candidate"]

    assert service.learning_search_lessons(query="geometry azimuth", tags=[], limit=5)["lessons"] == []

    approved = service.learning_review_candidate(
        candidate_id=candidate["candidate_id"],
        approved=True,
        reviewer_note="Confirmed against the project workflow.",
    )

    assert approved["scope"] == "personal_local"
    lessons = service.learning_search_lessons(
        query="geometry azimuth", tags=["sdk"], limit=5
    )["lessons"]
    assert len(lessons) == 1
    assert lessons[0]["candidate_id"] == candidate["candidate_id"]
    assert lessons[0]["guidance"].startswith("Inspect the API documentation")
