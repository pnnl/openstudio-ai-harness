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
- Current development branch: `enhance_skills_scripts`; release metadata remains
  at `0.4.0`.
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

## SDK review remediation (October 5, 2026)

Addressing all 13 user findings; tracking and release limitations are in
`docs/SDK_SCRIPT_REVIEW_FIXES.md`. User review/repro files are preserved. Package-wide
exact SDK compatibility is intentional: pyproject and lock metadata now pin 3.11.0,
matching the exported contract. Runtime plan/report version checks read the contract
and executing SDK; skill text reads the bundled contract rather than duplicating
its release. Newer input models fail with actionable provider/package guidance.
NLR provider priority remains unchanged.

Creation and independent getter checks consume the approved plan controls and
plant design snapshots. Human DX/default selections must be explicit. Preflight
checks unused eligible return plenums, loop ownership, temperature relationships,
plant equipment/setpoint presence and finite positive water delta; nonexistent
output roots terminate. Apply checks EnergyPlus translation before publication,
carries and hashes companion resources, emits a relative-path workflow, and
supports exclusive-copy fallback where hard links are unavailable. Copy fallback
is not atomic for concurrent readers; source input and existing outputs remain
preserved. Entry points persist full reports directly (`--report`) and print
bounded/filterable candidate summaries; normal runs need preflight and apply,
without last-line log parsing. Completed steps/assumptions append without losing
workflow history. New behavioral regressions and native relative-weather sizing
checks are included. Final verification: 273 focused tests passed (23 review regressions), MCP smoke
8 passed/2 optional simulation skips, nine exported skill frontmatter checks,
offline uv lock validation, and four native relocated-host cases passed. Wheel
and sdist built offline through the isolated backend; exact SDK dependency and
new helpers verified, local fixtures/candidates excluded. The development venv
lacks hatchling, so use the isolated build path rather than --no-isolation. The
supplied plenum repro now accepts/applies A and rejects B at preflight. See
`docs/SDK_SCRIPT_REVIEW_VERIFICATION.json`; current native artifacts are in
`outputs/sdk-review-20261005-final/`. Native sizing uses copied companion OSWs
and relative EPWs; 207/138 topology checks, unchanged sizing and 28/29 warnings.
Current specified instruction context is 75.2% smaller; actual agent tokens
remain unmeasured. No live NLR, installed plugin, marketplace, commit or release
change. Next: review all 13 remediations before release preparation.

## Near-Term Backlog

- Skill-bound SDK development phase 5 is complete within the user-selected
  local evaluation scope, ready for review on `enhance_skills_scripts`.
  Phases 1–4 were reviewed. Plan: `docs/SKILL_SCRIPT_DEVELOPMENT_PLAN.md`;
  Ruby assumptions: `docs/VAV_STANDARDS_TRACE.md`; final local findings:
  `docs/SKILL_SCRIPT_PHASE5_EVALUATION.md`, with machine-readable evidence in
  `docs/SKILL_SCRIPT_PHASE5_VERIFICATION.json`.
  Exact release: OpenStudio 3.11.0, native CLI 3.11.0+241b8abb4d and embedded
  Python 3.12.2; developer Python 3.13.7 and SDK 3.11.0. Model scripts are exported
  directly with owning skills; doctor/report use standard-library host Python.
  Supported VAV routing chooses the reviewed transaction before docs/wiki or
  object-by-object drafting. Legacy child skills and their generator, specs and
  template are removed. Configured, compatible NLR OpenStudio MCP has priority
  before any local route, including requests mentioning bundled scripts. After
  provider fallback, use a specific modeling skill; bespoke SDK programming
  covers only requests those skills cannot handle. Bespoke SDK guidance
  is loaded only for other operations. Local config/plans/logs/reports provide
  continuity without a modeling MCP/state-tool prerequisite. Active NLR provider
  transitions and separate simulation/results workflows remain respected.
  Guards reject other SDK releases before reading input. Apply revalidates source
  hash/plan, creates in memory, stages/reloads/validates settings and topology,
  and publishes by exclusive hard link. Existing or concurrent output is preserved;
  failed operations publish no OSM. Repeated apply refuses existing output.
  Generic inner VAV builder scope persists: explicit existing plants, no automatic
  plants/template/compliance postprocessing or HVAC replacement. Central heating
  None and independent coil roles are extensions. UUIDs differ; semantic settings
  and topology are deterministic.
  Focused verification: 250 tests passed, 9 changed exported skills passed frontmatter
  validation. Four relocated host/fixture local runs passed native design-day sizing:
  hydronic 193/electric-DX 138 topology checks, positive fan/terminal flows and coil
  capacities, no severe/fatal or node connection errors. All numerical sizing
  matches between host exports and phase 4. Seed/default warnings remain 28/29.
  Explicit OpenStudio 3.8.0 doctor checks blocked without fallback; repeated output
  and stale-plan negative checks preserved input/output bytes. Native macOS only;
  Windows/Linux discovery remains unit-tested. Original fixtures are preserved.
  Estimated route context fell 98,062 → 22,922 characters (76.6%); chars/4 estimate
  24,516 → 5,731 tokens. Compact reports reduce full stdout by 85–90% while saving
  complete evidence. Actual agents, billed tokens, retrieval and retries were
  not evaluated, at the user's request. Script sequences took 3.38–4.88 seconds
  plus 0.85–1.14 seconds sizing, one run each; no legacy timing comparison.
  Reproduce with `scripts/evaluate_skill_vav.py` and a new output directory;
  saved logs/models/SQL: `outputs/skill-vav-phase5-nlr-priority/`.
  Five conversation scenarios are future acceptance cases, not live results.
  Next: user review and release-scope decision; no export into the marketplace
  source repo, install, commit, push or release yet. Preserve the CalBEM work.

- CalBEM five-minute talk and two-minute lighting-retrofit recording plan drafted
  in `docs/CALBEM_FLASH_TALK.md` (October 4, 2026). Includes speaker script,
  storyboard, prompts, and proposed acceptance criteria. The demonstration case
  has not been run; measured results and runtime/version verification remain
  prerequisites for filming.

- Refresh CI/release checks into an explicit host/runtime/version/evaluation
  matrix, including real simulation readiness where the native executable is
  available.
- Align `measures/approved/` with the live measure registry before presenting
  it as the trusted measure source.
- Design user-facing runtime retention and installed-measure administration.
- Add parametric-study orchestration only after the engineering-session and
  diagnostic evidence contracts are established.
