from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from openstudio_ai_mcp.tools.schemas import (
    SessionCheckpointArgs,
    SessionCreateArgs,
    SessionFindingArgs,
    SessionIdArgs,
    error_payload,
    validation_error_payload,
)


def register_session_tools(mcp, service) -> None:
    @mcp.resource(
        "openstudio://sessions/{session_id}",
        name="engineering_session",
        description="Read a durable OpenStudio engineering session and its resumable state.",
        mime_type="application/json",
    )
    async def engineering_session(session_id: str) -> dict[str, Any]:
        return service.session_get(session_id)

    @mcp.tool(name="session_create", description="Create a durable engineering session.")
    async def session_create(goal: str, session_id: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            return service.session_create(SessionCreateArgs(goal=goal, session_id=session_id, metadata=metadata or {}))
        except ValidationError as exc:
            return validation_error_payload(exc)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(name="session_get", description="Read model lineage, findings, and the latest checkpoint for a session.")
    async def session_get(session_id: str) -> dict[str, Any]:
        try:
            return service.session_get(SessionIdArgs(session_id=session_id).session_id)
        except ValidationError as exc:
            return validation_error_payload(exc)
        except KeyError as exc:
            return error_payload("not_found", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(name="session_record_finding", description="Record an evidence-backed engineering finding without changing the model.")
    async def session_record_finding(**kwargs: Any) -> dict[str, Any]:
        try:
            return service.session_record_finding(SessionFindingArgs(**kwargs))
        except ValidationError as exc:
            return validation_error_payload(exc)
        except KeyError as exc:
            return error_payload("not_found", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(name="session_checkpoint", description="Create a resumable checkpoint and pin its referenced evidence.")
    async def session_checkpoint(session_id: str, reason: str) -> dict[str, Any]:
        try:
            return service.session_checkpoint(SessionCheckpointArgs(session_id=session_id, reason=reason))
        except ValidationError as exc:
            return validation_error_payload(exc)
        except KeyError as exc:
            return error_payload("not_found", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(name="session_diagnostic_bundle", description="Read bounded failure/simulation log excerpts and artifact references for one job.")
    async def session_diagnostic_bundle(job_id: str, max_chars: int = 12000) -> dict[str, Any]:
        try:
            return service.session_diagnostic_bundle(job_id=job_id, max_chars=max_chars)
        except KeyError as exc:
            return error_payload("not_found", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)
