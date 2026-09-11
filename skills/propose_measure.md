---
name: propose-measure
description: Draft a candidate OpenStudio measure from a repeated script or workflow.
---

# Propose Measure

Draft a candidate measure from a repeated OpenStudio script or workflow. Use
`references/candidate_measure.schema.json` and
`references/candidate_recipe.schema.json` for the candidate shapes. If the user
asks to save the reusable guidance, follow `capture-session-lesson` and require
explicit approval before creating a personal lesson.

For a script that succeeds and may be reused, ask whether the user wants to
record it as learning evidence. If approved, call `learning_capture_observation`
with `event_type: "script_execution"`, `evidence.outcome: "success"`, and a
stable `evidence.script_fingerprint`. Record only a concise logic summary and
safe provenance, not secrets or full transcripts. The background command
`openstudio-ai learning propose-measures` creates an unreviewed measure candidate
after the configured number of matching successful runs.

Do not edit trusted skills, knowledge, approved measures, or MCP tools directly.
A personal lesson is local guidance only; promoting a measure or shared plugin
asset still requires developer review and evaluation validation.
