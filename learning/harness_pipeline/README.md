# Learning Contract Assets

This directory supplies schemas and reference guidance used by the
`propose-measure` and `capture-session-lesson` skills. The host-neutral MCP
runtime owns opt-in local capture, candidate review, and approved personal
lesson retrieval; this directory itself is not executable.

Plugin exports copy only these contract assets into skill-local `references/`:

- `schemas/candidate_measure.schema.json` and
  `schemas/candidate_recipe.schema.json` for `propose-measure`;
- `schemas/session_lesson.schema.json` and `runtime_learning.md` for
  `capture-session-lesson`.

The host plugin must use the MCP learning tools for persistence. The helpers in
this directory are not the persistence boundary. Capture requires explicit user
approval; candidate approval creates only a user-local personal lesson.

Candidate content never becomes trusted OpenStudio AI content automatically.
Promotion to shared OpenStudio AI assets remains a developer review and
evaluation workflow.
