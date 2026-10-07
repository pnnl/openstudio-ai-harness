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

## Skill-bound SDK development — October 5, 2026

Phases 1–5 and the review remediations are consolidated in
[the SDK development summary](docs/SKILL_BOUND_SDK_SUMMARY.md). It replaces the
phase/review documents and print-only probes. Production code and assertion-based
regressions remain. The exact phase-4 sizing baseline moved to
`tests/fixtures/vav_sizing_baseline.json`; evaluator/parity tests now read it there.

Current decisions: package-wide OpenStudio 3.11.0; compatible NLR first; local
specific skills before bespoke SDK programming. Covered VAV edits execute directly
from their skill bundles. Portable outputs retain their companion workflow;
internal runtime snapshots use absolute copied CSV paths across measure copies.
CSV snapshot failures block simulation; weather warnings permit replacement
weather through epw_path/model_set_weather. Complete reports are written directly.

Last modeling verification: 14 focused regressions passed, including four native
weather replacement simulations; 20 round-3/job/session tests passed. Historical
phase/review/export results and context estimates are in the summary. Actual
agent/billed tokens remain unmeasured. The remaining low-priority issue is runtime
OS App `file:files/x.epw` and companion weather fallback; explicit epw_path works.
Existing package artifacts predate the latest fix and this consolidation.

Documentation cleanup: unrelated docs retained, obsolete links updated, baseline
parity checks passed (6 tests). No commit/push/install/release performed. Next:
review the consolidated record and prepare coordinated package/plugin release checks.

## Main merge conflict resolution — October 5, 2026

Resolved `prompts/openstudio_agent.md` and `skills/openstudio_sdk_model_editor.md`.
Retained compatible NLR priority, specific skill routing before bespoke SDK code,
and the exact package SDK doctor/guard gate. Main's project-first Python order
now selects only the standard-library doctor launcher; SDK model scripts use the
native executable verified by doctor, with no project-virtualenv recovery after
an incompatible SDK result. Provider transitions/host-path rules are preserved.

Verification: 45 resource/export adapter tests passed; exported SDK skill passed
skill-creator validation. Other incoming merge changes were left intact. No merge
commit, push, install or release performed.

## Standalone CI lock correction — October 5, 2026

The standalone lock's editable parent metadata still declared OpenStudio >=3.10.0
while pyproject.toml requires ==3.11.0. Corrected only that constraint, preserving
all resolved dependency versions. CI's uv 0.12.5 accepts `uv lock --project
standalone --check --offline`; Python 3.10.18 locked-sync dry run passes. The local
uv 0.8.18 resolver rewrites markers/downgrades uncached packages, so use CI's pinned
uv when regenerating this lock.

Updated the standalone SDK-guidance assertion to follow the conditional bespoke
reference introduced by skill-bound routing. All 22 standalone tests pass in the
existing Python 3.13.7 environment. Python 3.10 dependency installation/tests and
Linux CI execution were not performed locally; the 3.10 check was resolution-only.
No workflow changes, commit or push performed. Rerun standalone CI after committing
these changes.

## Plant creation and HVAC removal — October 5, 2026

Implemented two additional skills with directly bound scripts:
`openstudio-plant-loop-creator` and `openstudio-hvac-remover`. Both are independent
modeling modules, not restricted to VAV preparation. Plant requests build supply
equipment, pumping and controls; the selected air-side skill connects its water
coils to the returned plants. VAV is one supported consumer. Removal is composed
only when the requested workflow needs it. Compatible configured NLR retains
priority. No automatic fuel
choice or broader removal scope is authorized by a VAV request alone.

Plant creation follows the traced generic prototype HW/CHW/CW functions, with
explicit sources and `prototype_plants_v1` assumptions. Water-cooled chillers
receive a new condenser loop and variable-speed tower; primary/secondary CHW uses
generic common-pipe pumping. Weather-derived condenser sizing, heat-pump plants,
PRM heat exchangers/EMS and standards postprocessing remain outside this profile.
Removal inventories air loops, VRF roots and zone equipment, previews their SDK
cascade, and independently validates preserved plants/geometry/loads/schedules/
thermostats after saving. Both transactions preserve inputs and existing outputs,
carry referenced companions and require EnergyPlus translation before publication.

Verification: 22 new bundle tests passed, including nine plant-source combinations,
three native plant-to-hydronic-VAV design-day runs with positive sized capacities,
failure cases and independently relocated Claude/Codex bundles. Another 217
surrounding VAV/doctor/report/manifest/export tests passed. Five affected exported
skills passed frontmatter validation. Native execution was macOS OpenStudio 3.11.0;
annual performance and Linux/Windows execution remain unverified. Details and
commands are in the consolidated SDK summary. Regenerate exports before local
agent trials; installed plugins do not acquire these scripts automatically.
No commit, push, plugin installation or release performed.

Routing clarification: orchestrator, agent prompt and SDK/plant skill now explicitly
describe plant building and removal as independent modules. Plant-only requests
do not imply VAV creation or HVAC removal; air-side skills own coil-to-plant demand
connections. Claude/Codex adapter checks passed (23 tests); diff whitespace check
passed. Script behavior did not change in this clarification.

## VAV assumption review — October 5, 2026

Replaced skill guidance's implicit accept-or-stop behavior with use-proposed or
review/adjust. Partial configured preflight now emits `assumption_review` from
the canonical defaults, distinguishing user inputs, proposed defaults and fixed
controls. It does not select a profile, enable control assumptions or authorize
apply. The host presents grouped questions or a compact table; supported changes
update input fields. Unsupported fixed-control changes remain pending for scoped
development/provider coverage rather than being silently accepted. Creation still
requires a ready approved plan. No browser UI or custom-control schema was added.

Verification: 144 impacted preflight/apply/report/host adapter tests passed, with
a new no-approval/no-publication review regression. Full review records remain
on disk; stdout exposes status/counts only. The consolidated summary records the
workflow. No plugin installation, commit or push performed.

## Shared HVAC modules and CAV — October 6, 2026

Phases 1–3 of [the modularization work guide](docs/HVAC_MODULARIZATION_WORK.md)
are implemented and verified. VAV retains its contract through thin interfaces;
shared modules own equipment, multizone planning/assembly and independent saved
getters. New `openstudio-cav-system-creator` runs guarded inventory/preflight/apply
without a modeling runtime and is exported/routed for both hosts. It models the
generic prototype CAV arrangement, not arbitrary constant-airflow topology.
Compatible NLR stays first. Partial CAV plans support review without approval.

Verification: 218 combined tests passed; three strengthened native VAV sizing tests
match the historical numeric baseline (normal hydronic/electric-DX cases). Both
native CAV cooling cases and independently relocated Claude/Codex bundles passed.
Static bundle import closure and three exported skill validations passed. The initial CAV
zero central-heating result is superseded by F1 remediation below; real
capacity/control review remains necessary. Native Windows/Linux, annual runs
and live-agent token measurements remain unverified. Next review: independent
fan-replacement and coil-attachment contracts; those skills are not yet exposed.
No commit/push/install/release performed; regenerate exports before agent trials.

## HVAC review follow-up F1–F5 — October 6, 2026

CAV now requires an explicit OA schedule/null choice independently of profile
approval. Constant-1 fraction schedules mean 100% outdoor air; both all-OA sizing
flags follow that choice, and review/summary state the economizer consequence.
Other positive/variable fractions conservatively size at 100% OA and disclose
possible oversizing. Null keeps minimum ventilation sizing. Re-preflight old CAV
plans. Native hydronic comparison confirmed central HW capacity rises from 0 to
20.88 kW, cooling design load from 32.43 to 74.31 kW, with unchanged 1.431 m³/s fan
flow and no Severe/Fatal errors. Native tests require positive central heat.

All fan-class deltas are checked, recipe metadata is frozen/shared across assembly
and validation, custom-profile pressure conversion uses its own fields, and shared
inventory is HVAC-neutral with a VAV compatibility import. Details/evidence and
review commands are in the modularization guide. Verification: 237 combined tests
passed, including native CAV water/DX, historical VAV numeric parity and relocated
Claude/Codex bundles. Three exported skills passed validation; changed-Python
formatting and diff whitespace checks passed.
User review/probe files under docs/reviews remain preserved. No commit/push/install
or release performed.

## Near-Term Backlog

- Skill-bound SDK development is complete within the user-selected local
  evaluation scope. See `docs/SKILL_BOUND_SDK_SUMMARY.md` for decisions, review
  disposition, source trace, historical verification and remaining limitations.
  Prepare a coordinated SDK/package/plugin release after review; preserve CalBEM work.

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
