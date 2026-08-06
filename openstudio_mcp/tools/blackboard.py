from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from openstudio_mcp.tools.schemas import (
    BlackboardGetPhaseStateArgs,
    BlackboardInitializeWorkflowArgs,
    BlackboardMarkStepCompleteArgs,
    BlackboardRecordArtifactArgs,
    BlackboardRecordAssumptionArgs,
    BlackboardRecordFailureArgs,
    BlackboardSnapshotWorkflowArgs,
    BlackboardUpdateStatePatchArgs,
    BlackboardWorkflowIdArgs,
    error_payload,
    validation_error_payload,
)


def register_blackboard_tools(mcp, service) -> None:
    @mcp.tool(
        name="blackboard_initialize_workflow",
        description="Create a persistent OpenStudio AI workflow state in the MCP blackboard.",
    )
    async def blackboard_initialize_workflow(
        goal: str,
        workflow_id: str | None = None,
        initial_patch: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            args = BlackboardInitializeWorkflowArgs(
                goal=goal,
                workflow_id=workflow_id,
                initial_patch=initial_patch or {},
            )
            return service.blackboard_initialize_workflow(
                goal=args.goal,
                workflow_id=args.workflow_id,
                initial_patch=args.initial_patch,
            )
        except ValidationError as exc:
            return validation_error_payload(exc)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(
        name="blackboard_list_workflows",
        description="List workflow states stored in the MCP blackboard.",
    )
    async def blackboard_list_workflows() -> dict[str, Any]:
        try:
            return service.blackboard_list_workflows()
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(
        name="blackboard_get_workflow",
        description="Read one workflow state from the MCP blackboard.",
    )
    async def blackboard_get_workflow(workflow_id: str) -> dict[str, Any]:
        try:
            args = BlackboardWorkflowIdArgs(workflow_id=workflow_id)
            return service.blackboard_get_workflow(workflow_id=args.workflow_id)
        except ValidationError as exc:
            return validation_error_payload(exc)
        except KeyError as exc:
            return error_payload("not_found", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(
        name="blackboard_update_state_patch",
        description="Deep-merge a state patch into one MCP blackboard workflow.",
    )
    async def blackboard_update_state_patch(
        workflow_id: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            args = BlackboardUpdateStatePatchArgs(
                workflow_id=workflow_id,
                patch=patch,
            )
            return service.blackboard_update_state_patch(
                workflow_id=args.workflow_id,
                patch=args.patch,
            )
        except ValidationError as exc:
            return validation_error_payload(exc)
        except KeyError as exc:
            return error_payload("not_found", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(
        name="blackboard_get_phase_state",
        description="Read narrow phase state from one MCP blackboard workflow.",
    )
    async def blackboard_get_phase_state(
        workflow_id: str,
        phase: str | None = None,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        try:
            args = BlackboardGetPhaseStateArgs(
                workflow_id=workflow_id,
                phase=phase,
                fields=fields or [],
            )
            return service.blackboard_get_phase_state(
                workflow_id=args.workflow_id,
                phase=args.phase,
                fields=args.fields,
            )
        except ValidationError as exc:
            return validation_error_payload(exc)
        except KeyError as exc:
            return error_payload("not_found", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(
        name="blackboard_mark_step_complete",
        description="Mark a workflow step or phase complete in the MCP blackboard.",
    )
    async def blackboard_mark_step_complete(
        workflow_id: str,
        step: str,
    ) -> dict[str, Any]:
        try:
            args = BlackboardMarkStepCompleteArgs(
                workflow_id=workflow_id,
                step=step,
            )
            return service.blackboard_mark_step_complete(
                workflow_id=args.workflow_id,
                step=args.step,
            )
        except ValidationError as exc:
            return validation_error_payload(exc)
        except KeyError as exc:
            return error_payload("not_found", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(
        name="blackboard_record_assumption",
        description="Append an assumption to one MCP blackboard workflow.",
    )
    async def blackboard_record_assumption(
        workflow_id: str,
        assumption: str,
    ) -> dict[str, Any]:
        try:
            args = BlackboardRecordAssumptionArgs(
                workflow_id=workflow_id,
                assumption=assumption,
            )
            return service.blackboard_record_assumption(
                workflow_id=args.workflow_id,
                assumption=args.assumption,
            )
        except ValidationError as exc:
            return validation_error_payload(exc)
        except KeyError as exc:
            return error_payload("not_found", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(
        name="blackboard_record_artifact",
        description="Append an artifact reference to one MCP blackboard workflow.",
    )
    async def blackboard_record_artifact(
        workflow_id: str,
        artifact: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            args = BlackboardRecordArtifactArgs(
                workflow_id=workflow_id,
                artifact=artifact,
            )
            return service.blackboard_record_artifact(
                workflow_id=args.workflow_id,
                artifact=args.artifact,
            )
        except ValidationError as exc:
            return validation_error_payload(exc)
        except KeyError as exc:
            return error_payload("not_found", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(
        name="blackboard_record_failure",
        description="Append a failure record and mark a workflow as needing attention.",
    )
    async def blackboard_record_failure(
        workflow_id: str,
        failure: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            args = BlackboardRecordFailureArgs(
                workflow_id=workflow_id,
                failure=failure,
            )
            return service.blackboard_record_failure(
                workflow_id=args.workflow_id,
                failure=args.failure,
            )
        except ValidationError as exc:
            return validation_error_payload(exc)
        except KeyError as exc:
            return error_payload("not_found", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)

    @mcp.tool(
        name="blackboard_snapshot_workflow",
        description="Write one MCP blackboard workflow state to a JSON snapshot file.",
    )
    async def blackboard_snapshot_workflow(workflow_id: str) -> dict[str, Any]:
        try:
            args = BlackboardSnapshotWorkflowArgs(workflow_id=workflow_id)
            return service.blackboard_snapshot_workflow(
                workflow_id=args.workflow_id,
            )
        except ValidationError as exc:
            return validation_error_payload(exc)
        except KeyError as exc:
            return error_payload("not_found", str(exc), retryable=False)
        except Exception as exc:
            return error_payload("internal_error", str(exc), retryable=False)
