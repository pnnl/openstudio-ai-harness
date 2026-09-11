# OpenStudio AI Learning Pipelines

OpenStudio AI uses two separate learning pipelines.

Developer pipeline:

- captures raw usage, failures, warnings, and corrections;
- distills them into candidate lessons or assets;
- sends candidates through review;
- validates with evals;
- promotes approved assets into trusted knowledge, skills, SDK index notes, or
  MCP measures.

Host learning workflow:

- provide schemas and guidance for drafting candidate measures, recipes, and
  session lessons;
- are exported under the relevant skill's `references/` directory;
- use host-neutral MCP tools to capture opt-in evidence and retrieve approved
  personal lessons in Claude Code and Codex;
- use `openstudio-ai learning curate` outside the primary modeling workflow to
  create unreviewed lesson and measure candidates;
- never directly edit trusted assets.

This separation keeps "AI learns" defensible: runtime observations can create
candidates, but trusted assets require review and validation.

“Opt-in” means a host must explicitly invoke a learning MCP tool before any
evidence is persisted. The tools are registered with the runtime; there is not
currently a server configuration switch that disables them.

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

## Host Learning And CLI Curation

Claude/Codex exports copy selected files from `learning/harness_pipeline/` into
`propose-measure` and `capture-session-lesson` skill references. The shared MCP
runtime persists opt-in evidence and approved personal lessons under the
user-local OpenStudio AI data directory. The CLI reads the same SQLite store:

```bash
openstudio-ai learning curate
openstudio-ai learning propose-measures
openstudio-ai learning prune-preview
```

The CLI never approves, promotes, or deletes candidates without explicit user
action. A measure candidate remains untrusted until reviewed, implemented,
validated, and promoted through the developer workflow.
