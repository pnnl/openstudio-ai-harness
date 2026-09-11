"""Deterministic background curation of local OpenStudio AI learning evidence."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from openstudio_ai_mcp.runtime.learning_store import LearningStore

_LESSON_EVENT_TYPES = {"user_correction", "script_failure", "workflow_note"}


def curate_learning(
    store: LearningStore,
    *,
    minimum_script_runs: int = 3,
    include_lessons: bool = True,
    include_measures: bool = True,
) -> dict[str, Any]:
    """Create untrusted candidates from evidence without approving or deleting anything."""
    lesson_candidates: list[str] = []
    measure_candidates: list[str] = []
    script_runs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    lesson_event_sets = store.candidate_event_sets(candidate_type="lesson")
    measure_event_sets = store.candidate_event_sets(candidate_type="measure")
    events = store.list_events()

    for event in events:
        event_set = frozenset([event["event_id"]])
        if (
            include_lessons
            and event["event_type"] in _LESSON_EVENT_TYPES
            and event_set not in lesson_event_sets
        ):
            candidate = store.create_candidate(
                event_id=event["event_id"],
                candidate_type="lesson",
                summary=event["summary"],
                guidance="Review this evidence and state the reusable modeling guidance before approval.",
                tags=[event["event_type"], *event["scope"].get("tags", [])],
                scope=event["scope"],
            )
            lesson_candidates.append(candidate["candidate_id"])
            lesson_event_sets.add(event_set)

        fingerprint = event["evidence"].get("script_fingerprint")
        successful = event["evidence"].get("outcome") == "success"
        if event["event_type"] == "script_execution" and successful and isinstance(fingerprint, str):
            script_runs[fingerprint].append(event)

    for fingerprint, runs in script_runs.items():
        if not include_measures:
            continue
        event_ids = [run["event_id"] for run in runs]
        event_set = frozenset(event_ids)
        if len(event_ids) < minimum_script_runs or event_set in measure_event_sets:
            continue
        anchor = runs[0]
        candidate = store.create_candidate(
            event_id=anchor["event_id"],
            candidate_type="measure",
            summary=f"Repeated OpenStudio script logic: {fingerprint}",
            guidance=(
                "Draft a candidate OpenStudio Measure with explicit arguments, a model-diff "
                "expectation, and a regression test before user review."
            ),
            tags=["measure", "script", *anchor["scope"].get("tags", [])],
            scope={**anchor["scope"], "script_fingerprint": fingerprint, "run_count": len(event_ids)},
            evidence_event_ids=event_ids,
        )
        measure_candidates.append(candidate["candidate_id"])
        measure_event_sets.add(event_set)

    return {
        "lesson_candidate_ids": lesson_candidates,
        "measure_candidate_ids": measure_candidates,
        "events_considered": len(events),
        "minimum_script_runs": minimum_script_runs,
    }
