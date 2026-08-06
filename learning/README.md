# OpenStudio AI Learning Pipelines

OpenStudio AI uses two separate learning pipelines.

Developer pipeline:

- captures raw usage, failures, warnings, and corrections;
- distills them into candidate lessons or assets;
- sends candidates through review;
- validates with evals;
- promotes approved assets into trusted knowledge, skills, SDK index notes, or
  MCP measures.

Host learning contracts:

- provide schemas and guidance for drafting candidate measures, recipes, and
  session lessons;
- are exported under the relevant skill's `references/` directory;
- do not execute a learning pipeline or persist candidate records in Claude
  Code or Codex;
- never directly edit trusted assets.

This separation keeps "AI learns" defensible: runtime observations can create
candidates, but trusted assets require review and validation.

## Developer Pipeline

Run the deterministic developer curation pass:

```bash
.venv/bin/python -m learning.developer_pipeline.run_pipeline
```

It reads:

- `logs/python_script_failure_experience.jsonl`
- `logs/telemetry.jsonl`

It writes reviewable candidates to:

- `learning/review_queue/`

These candidates are not trusted assets. A modeler/developer must review them,
add or update evals, and then promote them intentionally.

## Host Learning Contracts

Claude/Codex exports copy selected files from `learning/harness_pipeline/` into
`propose-measure` and `capture-session-lesson` skill references. They support
candidate drafting only; no plugin-root `learning/` directory, candidate
storage, or host-executed learning pipeline exists today.

A future runtime learning feature must add explicit MCP tools or an approved
host execution path, durable storage, validation, and review before it may
claim to capture candidates.
