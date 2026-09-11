"""MCP tools for opt-in, review-gated personal modeling lessons."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from openstudio_ai_mcp.tools.schemas import (
    LearningCandidateArgs,
    LearningCaptureArgs,
    LearningReviewArgs,
    LearningSearchArgs,
    error_payload,
    validation_error_payload,
)


def register_learning_tools(mcp, service) -> None:
    @mcp.tool(name="learning_capture_observation", description="Store an opt-in, untrusted modeling observation as local evidence. It does not change future assistant behavior.")
    async def learning_capture_observation(event_type: str, summary: str, source: str, workflow_id: str | None = None, scope: dict[str, Any] | None = None, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            args = LearningCaptureArgs(event_type=event_type, summary=summary, source=source, workflow_id=workflow_id, scope=scope or {}, evidence=evidence or {})
            return service.learning_capture_observation(**args.model_dump())
        except ValidationError as exc:
            return validation_error_payload(exc)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(name="learning_create_candidate", description="Create a reviewable personal-learning candidate from captured evidence. This does not change future assistant behavior.")
    async def learning_create_candidate(event_id: str, summary: str, guidance: str, tags: list[str] | None = None, scope: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            args = LearningCandidateArgs(event_id=event_id, summary=summary, guidance=guidance, tags=tags or [], scope=scope or {})
            return service.learning_create_candidate(**args.model_dump())
        except ValidationError as exc:
            return validation_error_payload(exc)
        except KeyError as exc:
            return error_payload("not_found", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(name="learning_list_candidates", description="List local personal-learning candidates awaiting or receiving review.")
    async def learning_list_candidates(status: str | None = None) -> dict[str, Any]:
        try:
            return service.learning_list_candidates(status=status)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(name="learning_review_candidate", description="Approve or reject a personal-learning candidate. Approval creates a local personal lesson; it never edits plugin skills or shared knowledge.")
    async def learning_review_candidate(candidate_id: str, approved: bool, reviewer_note: str | None = None) -> dict[str, Any]:
        try:
            args = LearningReviewArgs(candidate_id=candidate_id, approved=approved, reviewer_note=reviewer_note)
            return service.learning_review_candidate(**args.model_dump())
        except ValidationError as exc:
            return validation_error_payload(exc)
        except (KeyError, ValueError) as exc:
            return error_payload("invalid_review", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(name="learning_search_lessons", description="Retrieve approved local personal modeling lessons relevant to the current work.")
    async def learning_search_lessons(query: str = "", tags: list[str] | None = None, limit: int = 5) -> dict[str, Any]:
        try:
            args = LearningSearchArgs(query=query, tags=tags or [], limit=limit)
            return service.learning_search_lessons(**args.model_dump())
        except ValidationError as exc:
            return validation_error_payload(exc)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)
