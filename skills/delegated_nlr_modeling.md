---
name: delegated-nlr-modeling
description: Use NLR OpenStudio-MCP as the preferred exclusive energy-modeling provider while OpenStudio AI owns workflow state, artifacts, and learning.
---

# Delegated NLR Modeling Workflow

Use this skill when `nlr_openstudio` is configured and passes preflight. NLR is
the preferred provider for model creation, model edits, measures, simulation,
and result retrieval. OpenStudio AI remains mandatory for blackboard state,
artifact provenance, provider decisions, and learning capture.

If NLR is not configured, unavailable, incompatible, or rejected by preflight,
do not attempt NLR operations. Record the reason in the OpenStudio AI
blackboard and use the normal OpenStudio AI-only skill route.

## Mandatory Start

1. Load this skill before calling any `nlr_openstudio` tool, including status
   and version calls.
2. Call `blackboard_initialize_workflow` and record `execution_provider` as
   `nlr_openstudio`, the NLR endpoint/image identity when available, and the
   configured host/container workspace mapping.
3. Call NLR `get_server_status` and `get_versions`. Record the result before
   model work. Check the OpenStudio and EnergyPlus versions against the model
   and project requirements.
4. Treat `/inputs`, `/runs`, and `/measures` as NLR provider paths. Record the
   corresponding host-visible paths as artifacts. Never use a provider path in
   a host shell command or host-side SDK script.

Do not make more than one critical NLR mutation without an intervening
blackboard write. Critical boundaries include model creation/load/save, measure
creation/application, simulation submission/completion, results extraction,
provider transition, and final handoff.

## NLR Skill Guidance

NLR's user-facing skills are retrieved from its MCP server; they are not
automatically native Claude Code or Codex skills. Before a non-trivial NLR task,
call NLR `list_skills` and retrieve only the task-relevant guide with
`get_skill`. Record the NLR skill name and version/source in the blackboard.

Use the retrieved NLR guide as provider-specific procedure. The OpenStudio AI
plugin remains the parent orchestrator and retains ownership of blackboard,
artifact, and learning calls. Do not bulk-load or blindly reproduce NLR skill
content.

For an NLR custom measure, the required sequence is:

```text
get_skill("measure-authoring")
→ search_api for each non-trivial OpenStudio class/method
→ create_measure
→ test_measure on a representative model
→ apply_measure
→ inspect and record the changed model
```

NLR `search_api` verifies methods against its live bindings, but does not
replace engineering review, unit checks, or before/after validation.

## NLR Execution And Blackboard Records

- Use only NLR tools for the selected modeling phase. Do not call OpenStudio AI
  `model_*`, `sim_*`, `results_*`, or measure tools against the same unstaged
  model.
- After each NLR action, call the relevant blackboard operation: record the
  model/run/result artifact, update state, mark the completed phase, or record
  the failure before retrying.
- Every artifact record must include provider, NLR run ID when available,
  `container_path`, `host_path`, source model, content hash when available,
  and warnings/log locations.
- Snapshot the workflow before a conversation pause and at final handoff.

## SDK Fallback Boundary

Switch to the OpenStudio AI SDK route only when the model has evidence that NLR
cannot express the requested operation after consulting the relevant NLR skill
and capability/API lookup. Record the unsupported operation, NLR evidence,
reason for the transition, input model artifact, and selected local runtime in
the blackboard before drafting code.

Export or copy the NLR model to its recorded host-visible staging path first.
For the demo topology, a provider path `/runs/<suffix>` maps to
`./nlr-workspace/runs/<suffix>` from the demo repository root. `/runs` is never
valid in host-side source code. Load `openstudio-sdk-model-editor`, retrieve
the required OpenStudio AI SDK documentation, verify a local OpenStudio runtime,
and write a new output model rather than overwriting the delegated artifact.

The SDK edit is a new provider phase. After it completes, validate and record
the output. A later simulation may use OpenStudio AI or may be explicitly
handed back to NLR through a recorded staging/import boundary; never allow both
providers to mutate the same unstaged model.

## Learning And Handoff

Capture NLR capability gaps, failures, and successful patterns as candidate
learning evidence through OpenStudio AI. Do not promote NLR guidance, generated
measure code, or runtime observations into trusted plugin assets without review.
At handoff, record the provider history, final model, run IDs, artifacts,
results, assumptions, warnings, failures, and next recommended action; mark
the workflow complete and snapshot it.
