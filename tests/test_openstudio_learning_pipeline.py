from __future__ import annotations

import json
from pathlib import Path

from learning.developer_pipeline.run_pipeline import (
    run_developer_learning_pipeline,
)


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
