# OpenStudio AI Harness Handoff

## Product Direction

OpenStudio AI is the durable, host-neutral foundation that enables LLMs to do
reliable building-energy engineering work. It must support more than model
creation and simulation: an agent should be able to preserve a model's lineage
and evidence, inspect the model and run artifacts, diagnose errors and
implausible results, propose safe corrections, and verify the outcome.

The product sequence is deliberately dependency-led:

1. Durable engineering sessions and reproducible execution.
2. Model inspection and evidence-backed debugging.
3. Results analysis and plausibility/benchmark validation.
4. Parametric studies built on the same variant, job, and result contracts.
5. Optimization and machine-learning extensions consuming those contracts.

Do not add isolated agent features that bypass the durable artifact, provenance,
and approval model.

## Current Status

- Release candidate `0.4.0` uses MCP plugin interface contract `5`, adding
  durable engineering-session, finding, and checkpoint surfaces. Hosts must
  refresh exported plugins to use those workflows.
- The diagnostic MVP (`model_inspect`, `sim_diagnose`, and
  `results_plausibility`) and its curated fixtures are planned for contract `6`.
- Current branch: `main`; release metadata is being prepared for `0.4.0`.
- The current foundation is a Python 3.10+ package with an MCP 2.x runtime,
  Codex and Claude Code plugin exports, trusted skills/knowledge, local
  SQLite-backed workflow state, model lifecycle support, asynchronous
  simulation, SQL-backed results, SDK lookup, geometry export, and user-local
  review-gated learning evidence.
- Simulation jobs have durable records and artifacts. The canonical live status
  resource is `openstudio://jobs/{job_id}`; transitions publish MCP resource
  updates, including worker-thread transitions. `sim_status` remains a
  diagnostic mirror.
- The runtime uses per-job workspaces. A run can retain the source model,
  EnergyPlus logs (including `eplusout.err`), SQL output, reports, and metadata
  needed for later diagnosis, subject to runtime retention policy.
- Host adapters distinguish PNNL's `openstudio-ai-mcp` / `openstudio_ai` from
  NLR's optional `openstudio-mcp` connection. NLR discovery is configuration
  detection, not a verified live connection.
- The base package intentionally excludes AUTOMA-AI and Streamlit. The
  standalone AUTOMA-AI/Streamlit environment is isolated under `standalone/`;
  its dependency supply chain has been resolved and is no longer an open
  planning item.

## This Week: Debugging Foundation Vertical Slice

The immediate objective is to turn existing model, job, artifact, and results
surfaces into a reliable diagnostic workflow. Scope the work as a vertical slice
rather than a broad new platform:

1. Define an engineering-session contract that ties model lineage, assumptions,
   model edits, simulation jobs, retained artifacts, findings, approvals, and
   resumable checkpoints together.
2. Implement/standardize read-only diagnostic access to model structure, job
   status, simulation logs, warnings/errors, and SQL result evidence.
3. Add results plausibility checks that can identify abnormal end uses, loads,
   schedules, unmet hours, and benchmark deltas without claiming a cause that
   the evidence does not support.
4. Require agents to produce evidence-linked hypotheses and minimal proposed
   repairs; model-changing fixes remain user-approved and must be followed by a
   before/after rerun or explicit reason verification is unavailable.
5. Create deterministic evaluation fixtures for: a failed run, a warning-heavy
   run, and an intentionally implausible lighting-energy result. Evaluate the
   quality and grounding of diagnosis as well as tool completion.
6. Record parametric-study requirements against this session/artifact contract;
   do not start a disconnected sweep implementation this week.

## Current Boundaries

- The harness owns trusted skills, prompts, knowledge, policies, MCP runtime
  operations, and SQLite-backed job/artifact/workflow metadata.
- Candidate learning and proposed measures remain untrusted until explicit
  review and validation promote them. The harness must not silently alter a
  model, approved measures, or trusted guidance.
- Host adapters remain host-specific only at their plugin/configuration edge;
  runtime contracts and engineering evidence must remain host-neutral.
- Local OpenStudio fixtures belong in `tests/fixtures/`; they are not release
  assets and must not enter wheels or plugins.

## Verification Baseline

Run from repository root with `.venv/bin/python`:

```bash
.venv/bin/python -m pytest -q \
  tests/test_harness_asset_manifest.py \
  tests/test_openstudio_cli.py \
  tests/test_openstudio_claude_code_adapter.py \
  tests/test_openstudio_codex_adapter.py

.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
```

Run OpenStudio-gated simulation tests only with a configured native CLI:

```bash
OPENSTUDIO_PATH=/path/to/openstudio \
  .venv/bin/python -m pytest -q tests/test_mcp_openstudio_smoke.py
```

Run standalone checks in their separate locked environment:

```bash
uv sync --project standalone
uv run --project standalone python -m pytest -q standalone/tests
```

## Near-Term Backlog

- Refresh CI/release checks into an explicit host/runtime/version/evaluation
  matrix, including real simulation readiness where the native executable is
  available.
- Align `measures/approved/` with the live measure registry before presenting
  it as the trusted measure source.
- Design user-facing runtime retention and installed-measure administration.
- Add parametric-study orchestration only after the engineering-session and
  diagnostic evidence contracts are established.
