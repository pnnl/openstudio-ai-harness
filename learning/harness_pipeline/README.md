# Learning Contract Assets

This directory supplies the schemas and reference guidance used by the
`propose-measure` and `capture-session-lesson` skills. It is not an executable
learning pipeline in Claude Code or Codex.

Plugin exports copy only these contract assets into skill-local `references/`:

- `schemas/candidate_measure.schema.json` and
  `schemas/candidate_recipe.schema.json` for `propose-measure`;
- `schemas/session_lesson.schema.json` and `runtime_learning.md` for
  `capture-session-lesson`.

The Python helper modules in this directory are not exposed as MCP tools and
are not invoked by either host plugin. A future executable learning workflow
must add an explicit MCP tool or an approved host execution path, storage, and
review lifecycle before it can claim to capture or persist candidates.

Candidate content never becomes trusted OpenStudio AI content automatically.
Promotion remains a developer review and evaluation workflow.
