# SDK integration and review summary

Consolidated October 13, 2026 from the integration investigation, increment A–D
implementation guides and historical review notes. This records completed work
through October 12; verification counts below are prior results, not new runs.
The final implementation and follow-up evidence supersede earlier proposals and
probes that deliberately asserted a defect.

## Status and development rules

| Increment | Delivered | Final disposition |
| --- | --- | --- |
| A | Central load gate, bundled model preparation, lineage and bounded plan diagnostics | Implemented and verified; Q1/Q2 addressed |
| B | One plugin-local SDK library and fixed skill launchers | Implemented and verified; complete-plugin relocation covered on both hosts |
| C | Automatic sanitized failure reporting with durable receipts | Implemented and verified; C1/C2 addressed before automatic use |
| D | Read-only equipment/zone HVAC topology views | Implemented and verified; D1–D3 addressed |
| E | Resume independent equipment development | Ready to begin; proposed next operation is in-place terminal airflow/reheat editing |

OpenStudio remains pinned package-wide to **3.11.0**. Compatible configured NLR
remains the preferred modeling provider; local scripts follow the existing
provider-transition rules. Skills invoke bundled scripts directly through the
verified native CLI. No modeling runtime service, utility-skill discovery step,
agent per component or ad hoc normalization script is required.

System recipes compose shared equipment functions in one model transaction.
Rating/performance-only changes happen in place. Attaching, moving or changing
class has a separate topology/control contract. Existing exact source hashes,
reviewed/fresh equality, cascades, protected snapshots, saved-model validation
and EnergyPlus translation checks remain intact. Readiness to resume development
does not certify an installation, release, annual performance or code compliance.

Detailed equipment history and source trace remain in
[the modularization guide](HVAC_MODULARIZATION_WORK.md); the earlier SDK strategy,
VAV assumptions and companion-file fixes remain in
[the skill-bound SDK summary](SKILL_BOUND_SDK_SUMMARY.md).

## A — deterministic inputs and explicit preparation

The reported remover failure was reproduced on an original OpenStudio 1.10.0
model. Two loads produced changing identities for 64 translated objects: 42 port
lists, 16 model-object lists, five availability-manager assignment lists and one
water-heater sizing object. Four selected air-loop lists caused the reviewed-plan
mismatch; the fifth belonged to the retained DHW loop. The model had 3,590 loaded
objects. Relaxing only the fresh-preflight comparison would not fix the later
cascade and saved-state checks.

The solution is a stable, reported working copy, with the original unchanged.
It is not filtering transient classes, ignoring handles or claiming translation
is a semantic no-op.

### Detection and diagnostics

`common/version_guard.load_model` gates every shared transaction consumer, the
separate VAV workflow and read-only visualization before planning:

| Input condition | Outcome |
| --- | --- |
| Older version than the pin | Bounded `requires_preparation`, source/target versions and next action; no ready plan or inventory candidates |
| Same version, stable handles | Continue after two independent loads comparing every model-object handle |
| Same version, changing handles | `requires_preparation`, with bounded added/removed counts categorized by type |
| Current model with missing/invalid air- or plant-loop availability-list reference | Bounded `invalid_model` before unsafe SDK access; no manufactured repair |
| Newer version | Reject; preparation does not downgrade |

The stability guard is on by default. Its internal opt-out is for explicit
preparation/benchmarking; agents have no CLI bypass. Same-handle value differences
still fail exact plan and saved-state checks.

The guard costs **about one extra load**, approximately doubling loader time.
On the 892-object prepared ten-loop fixture, five paired Mac measurements gave
38.2 ms single-load and 78.5 ms guarded medians, an extra 40.3 ms. This is not a
fixed overhead for larger models. Independent Linux review measured about 44 ms
extra on that fixture.

Fresh/reviewed mismatch reports show at most 12 differing JSON paths, each at most
180 characters, with handle-churn, stale-source, changed-value/type/structure/
length categories and a truncation marker. Values and full snapshots stay out
of the diagnostic; the exact comparison itself is unchanged.

### Preparation and report contract

Each owning skill can invoke its `scripts/prepare_model.py` launcher. It loads
through VersionTranslator, resolves companions from the **original** location,
stages a new current-version OSM and same-stem companion directory, then reloads
and checks all handles and raw fields across independent loads. Translator errors
block publication. Source hashes and companion hashes are rechecked; publication
is fsynced and exclusive, with rollback of owned outputs on failure. Existing
model, companion and report destinations are never overwritten.

The report records:

- `operation: prepare_model`, `status: prepared`, `ok: true`, `ready: false`;
- input/output paths and SHA-256, source and target versions;
- translator warning/error totals, up to eight messages per severity, each up to
  240 characters;
- generated/removed handles and translator-refactoring counts by type, capped at
  24 categories plus an overflow count;
- stable-handle and stable-raw-field validation, companion/resource readiness,
  workflow/plain-load CSV requirements and packaging warnings;
- `lineage.source` and `lineage.prepared` records containing path/hash/version;
- `state_patch.model_preparation[output_sha256]`, completed preparation step and
  current working-model path for the workflow blackboard.

A current, handle-stable input returns `already_current`; only the requested
new report is written, with no new model/companion copy. Counts describe stored
versus loaded objects and translation events, not semantic equivalence. Resource
readiness is not simulation certification. After preparation, re-inventory and
re-preflight the returned copy; never reuse the blocked old-model plan.

Tests use genuine unchanged upstream **1.13.4** and **2.2.2** OSMs, with sources,
licenses and hashes in [fixture provenance](../tests/fixtures/LEGACY_OSM_PROVENANCE.md).
Changing a current file's version header is not a valid fixture. Removing current
assignment lists does not reproduce translation churn: it causes an SDK error
and is tested separately. Q1 extends that guard to PlantLoop; Q2 checks native
CLI availability before importing optional `jsonschema`.

## B — shared SDK packaging

Canonical source remains `skills/sdk_scripts/`. Both exports contain:

```text
openstudio-ai/
  sdk/
    compatibility.json
    common/, references/, schemas/
    doctor.py, prepare_model.py, ...
    bundle.json
    PACKAGING.json
  skills/<owning-skill>/
    SKILL.md
    scripts/<entrypoint>.py   # fixed launcher
    references/              # progressive skill-facing instructions
```

The **complete plugin** is the distribution, installation and relocation unit.
Existing Git-repository installation and doctor/setup flows remain. A launcher
resolves only its own plugin's SDK, checks its embedded bundle identity and
payload hashes, and refuses missing, mismatched, escaping or symlinked payloads
with bounded `plugin_incomplete`, exit 2 and restoration guidance. It never
searches CWD, another plugin, environment overrides or a developer checkout.
Detached skills intentionally fail. Integrity checks establish bundle consistency,
not software signing. Individually standalone skill exports are future scope.

Manifest `scope: plugin-sdk` remains restricted to canonical sources and safe
paths with collision checks. No filesystem links or `..` destination shortcuts
are used. Execution code/data are copied once; skill-facing references remain
local. The independent failure reporter's small recovery copy is intentional.

`PACKAGING.json` records comparable former owner-copy bytes, shared payloads,
launchers, total/unique/duplicate whole-plugin bytes and a **1 MiB** SDK-resource
budget enforced at export, including the report. Its own bytes are excluded from
reported totals to avoid self-reference. Fixtures, caches and native evidence
are not shipped. At initial B verification, resources fell from a comparable
2,445,693-byte owner-copy baseline to 686,836 bytes (**71.9%**); 78 payloads and
66 launchers served 16 owning skills. The final D export uses **816,079 bytes**
excluding its size report, still under budget. These are packaging measurements,
not agent-token measurements.

Both hosts are tested after moving the whole plugin into paths with spaces,
deleting the original export and running from unrelated working directories.
Missing/tampered libraries, detached skills, scope/path/collision rules and
representative native operations are covered. Archive builds may require the
`build` package and access to their pinned isolated build dependencies.

## C — automatic failure reporting

`report-openstudio-failure` targets **pnnl/openstudio-ai-harness on GitHub**.
The earlier GitLab wording is superseded. Automatic submission was explicitly
selected by the user. **Issues are created under the user's own authenticated
GitHub account**, using existing `gh` authentication on the fixed host. Setup,
skills, README and doctor disclose authorship and the project opt-out. The
separate general `github-issue-submitter` retains its own preview-approved
plugins-repository behavior.

Unexpected script failures persist a local `failure_receipt` before recovery;
receipt-capture failure never masks the original error. Publication followed by
a report-write error is distinguished so recovery does not repeat the edit.
The orchestrator/owning skills invoke the reporter before a workaround or
abandonment and inspect pending receipts on resume. MCP/process/import/doctor/
plugin failures outside a script boundary need agent-level capture. This is
explicit skill execution, not background telemetry or a crash-proof guarantee.

Expected missing inputs, unsupported scope, cancellations, compatibility,
preparation, invalid-list and stale-source outcomes do not automatically submit.
Unexpected SDK rejection, saved/translation failure and handle churn qualify.
Explicit user bug reports may supply evidence for an otherwise expected outcome.
Reporting errors retain local evidence and do not recursively report themselves
or block safe modeling recovery.

### Privacy and reproduction

C1 replaced raw public exception prose with fixed error codes/messages. Public
tracebacks contain at most 12 source-verified relative plugin file/function/line
frames, without original messages, source lines, locals or external frames.
Original exception text stays in owner-only private local evidence on POSIX;
the submitter never reads that file. AST validation inspects shipped source
without executing it. The same policy works when SDK sources are missing.

Structured evidence is allowlisted and bounded: operation/stage/provider,
release/bundle/SDK/host identity where known, sanitized invocation/configuration,
numeric choices, mismatch paths, relevant component counts, publication state,
attempts, recovery and reproduction steps. Names/handles/paths use consistent
aliases. Unknown configuration fields, credentials, environment/transcript dumps,
user models, companions, graphs and attachments are excluded. Raw errors must
not be copied into agent observations. Sensitive security reports stay private.
Arbitrary agent-authored prose still cannot be guaranteed safe by regex alone.

Reports distinguish a verified synthetic reproducer from
`not_independently_reproducible_yet`; a private building path is not an accessible
fixture. Native privacy regressions force company/address/email names through
five real bundled error paths and prove they remain local. C2 supplies the
account-authorship disclosure. The earlier C3 draft-first recommendation was
conditional on the C1 defect; C1 is fixed and the user's automatic policy remains.

### Receipts, deduplication and recovery

Default project state is `.openstudio_ai_failures/`, containing an ignore file,
optional `policy.json`, and per-fingerprint `receipt.json`, private evidence,
exact sanitized `issue.json` and an exclusive submission lock. Use one absolute
`OPENSTUDIO_AI_FAILURE_DIR` / `--state-dir` across working-directory changes.
The reporter is stdlib-only and runs without SDK, MCP, harness installation or
a healthy plugin library. Store incident/status/issue in the workflow blackboard.

Fingerprints bind operation/stage/provider, release/bundle/SDK, fixed error code
and verified plugin failure location; retries and transient/private names do not
create a new incident. Local capture retains the first incident. Before the only
POST, persist `submitting`. Search open/closed issues for the exact fingerprint
marker; duplicates are linked without edits/comments. Template requirements
that cannot be mapped retain a draft. Before-create auth/network failures remain
`pending`. Ambiguous creation becomes `submission_uncertain`: later attempts
search only and never POST again, even with delayed indexing. Locks prevent
local races; global cross-machine exactly-once submission is not claimed.

Receipt format 2 holds legacy receipts as `requires_recapture` before network
access. Preserve submitted/uncertain identities rather than automatically
recapturing them. A later security classification holds pending evidence locally.
The bounded pending view shows at most 20 incidents plus a total. A stale lock
requires confirming that its owning process stopped before manual removal.
`policy disabled` keeps capture/drafts local; `policy automatic` restores project
submission. Installation does not publish historical incidents. Doctor checks
reporting separately from modeling readiness; authentication does not prove
issue-write permission. Automated tests use mocked transport; no live issue was
created for verification.

## D — read-only HVAC visualization

`openstudio-hvac-visualizer` produces `graph.json`, `equipment_graph.json`,
`overview.mmd`, `index.md`, per-group Mermaid/Markdown and a separate JSON report.
Success is `status: visualized`, `mode: inspect_only`, `ok: true`, `ready: false`.
Input and exact in-memory object states are checked for changes; output/report
paths must be new. Older/unstable models use A preparation. Missing weather/CSV
files do not block read-only inspection. No source model or companions are saved.

The raw format-1 graph preserves native connection handles, stored numeric ports,
current endpoint fields, object identities, ownership, served-zone memberships,
translator/load provenance and coverage warnings. Legacy ports are resolved by
explicit references, preserved and warned, never silently repaired. Condensed
edges carry contiguous original-edge evidence and stop at physical equipment.
Separate circuit views retain a coil's air/water identity and recovery's two
streams. Unknown internals remain unexpanded with warnings. Dashed containment/
service/VRF relations do not claim internal airflow or refrigerant piping.

Green boxes are thermal zones, blue equipment is air-side/secondary-loop and
orange equipment is water-side/primary-loop. Routing nodes, virtual connectors,
adiabatic routing pipes and controls stay in JSON. One connected air drawing
reads supply/intake left → terminals/zones → return/relief/exhaust right. Actual
model order wins, including fans before coils. OA intake/mixed and return/relief
boxes are views of the same assembly; recovery appears on both actual streams.
Verified outdoor boundaries appear as open arrows. Zone exhaust-list names alone
do not prove outdoor exhaust. DHW pipe-only bypass paths stay in JSON evidence
but are omitted with a note; they are not district/mains inlets. Water-use
connections have one water view and an explicit return to the pump.

Final D follow-ups:

- **D1:** Stored OA/MV controller references assign both controls to their air
  loop. Groups with no visible equipment generate no diagram/index row and do
  not inflate diagram counts; isolated physical equipment remains visible.
- **D2:** VRF views and the overview fold contained coils/fans without external
  flow into the indoor/parent label. Any child with external flow in any circuit
  remains visible. Both JSON graphs retain all components and relations.
- **D3:** Default type-plus-number names show the type once; custom names remain
  escaped. Shared air-loop/VRF zones name the other systems with `also:` in each
  system view and `served by:` in overview/zone views.

Stable IDs use full handles/circuits; duplicate names never merge. `--system`
selects exact root handles for per-system views while JSON, overview and zone
index stay complete. Overview individually displays the first 40 zones; all
zones remain indexed. Stdout shows counts and at most eight diagram paths.
Graphs/diagrams stay local and never accompany automatic public issues.

The final integration run has 745 nodes, 884 edges and **522/522 connections**,
4 air loops, 4 VRF systems, 1 plant and 42 zones (4 unserved), producing 51 group
diagrams without the empty unassigned group. Both exports match; original and
prepared hashes are unchanged. The genuine legacy ten-loop regression owns all
20 OA/MV controllers and produces 20 loop/zone diagrams.

Nine rendered system previews pass 139 edge-position checks. The nine-unit VRF
view shrinks from 46 to 19 boxes and 5,366 to 1,742 px tall. A synthetic 40-unit
view retains 81 boxes at about 1,009 × 6,046 px; scrolling remains necessary and
pagination is not implemented. Temporary local Mermaid 11.12.0 and isolated,
network-blocked Chrome generated development SVG/PNG previews; the plugin has
no renderer dependency. Native Mermaid caught the required three-dash water
return start-arrow syntax. Earlier split supply/return lanes are superseded.
A diagram does not validate sizing, ventilation adequacy or EnergyPlus controls.

## Equipment review resolutions retained for continuity

These findings predate A–D; final resolutions are documented in the tracked
modularization guide and implemented regression suites. Findings IDs are scoped
to their review, so economizer E1 is distinct from integration increment E.

| Review | Final engineering decision / correction |
| --- | --- |
| F1–F5, VAV/CAV extraction | Explicit CAV OA schedule choice; disclose 100% OA and align sizing when applicable; native positive HW capacity; count both fan classes; use recipe fan fields; shared recipe descriptor and HVAC-neutral inventory |
| G1–G3, fan performance | Same-class scalar edits use setters in place, preserving fan/connections/metadata/references; one pressure helper; complete system assembly rejects missing required performance fields |
| H1–H4, water coils | Attach only at supported supply outlet; same-class reconfiguration stays in place; UA-method rated temperatures are informational for design sizing; incomplete untouched plants warn/mark simulation-unready for edits instead of preventing the edit |
| J1–J4, plant migration | Dedicated single-coil branch and retained coil/controller/air identity; show remaining source demand and unused-plant warnings; paired same-temperature sizing parity; pinned controller lifecycle canary; name the ratings-editor follow-up for retained fixed temperatures |
| K1–K3, coil conversion/relocation | Water→electric conversion preserves translated outlet control with no fixed 32.2 °C schedule; retain/control-check generated MixedAir and existing managers; report fan-relative position/control changes on relocation |
| L1–L3, fan class change | Keep supported name-keyed outputs/meters when name survives; reject direct-object references; optional end-use label or source-type warning; describe terminal-driven variable flow with constant-volume fan linear power |
| M1–M2, pump editing | Fixed power with autosized flow warns that feasibility needs post-sizing review; check flow × head / (power × motor efficiency); 10 MPa head ceiling and exactly four curve coefficients |
| N1 and lookup safeguards, pump replacement | Report explicit OSM versus translated demand bypass and common-pipe context; pinned translator can synthesize bypass; no implicit OSM plumbing change; look up demand connector field by name and give bounded missing-object error |
| E1–E2, economizer | Verify translated mixed-air Temperature setpoint; absent control warns/marks simulation-unready; allow tiny numeric rounding tolerance while exact identity/raw-state checks remain |
| V1, DCV | The initial reviewer premise was disproved: SDK 3.11 translates an Autosize controller minimum to zero when DCV is enabled. Report declared and translated floors; record `dcv_effective: false` for a verified fixed floor at/above nominal design OA |
| W1, recovery | Warn about uncontrolled recovery with downstream cooling/cool supply and record `uncontrolled_recovery_cooling_risk`; compare recovered and coil energy, not recovered watts alone; no implicit control change or extra simulation-readiness gate |

Native W1 winter pairs showed that additional uncontrolled recovery was nearly
all removed by central cooling: +75.357 kWh VAV and +73.039 kWh CAV, while heating/
reheat stayed essentially unchanged and HX electricity remained 2.4 kWh. These
are design-day thermal loads, not fuel/input energy, annual savings or a universal
control recommendation. Native K1 pairs checked outlet tracking within 0.02 K
and zero unnecessary heating, rather than relying on positive sizing alone.

Some old probes deliberately assert superseded defects (notably round 6's
implicit CAV OA choice, round 19's missing economizer warning, round 20's Autosize
DCV premise and round 25's public error leak). They are historical evidence, not
acceptance tests to restore. Executable probe files and tracked review records
under the retired review directory are removed after consolidation. Maintained
regression suites under `tests/` remain unchanged.

### Retired probe coverage and migration verification

All 12 historical probe scripts were inspected before removal. Their scenarios
and final expectations are retained above and in the maintained suites below;
old defect assertions must not be restored as current acceptance criteria.

| Retired probe round | Scenarios retained | Maintained regression suites under `tests/` |
| --- | --- | --- |
| 6 | CAV outdoor-air/sizing mismatch and stray opposite-class fan | `test_cav_system.py` |
| 7 | In-place fan identity/LifeCycleCost retention and pressure conversion | `test_supply_fan_performance.py` |
| 9 | Interior-node refusal, outlet attachment, same-class in-place settings, UA rating interpretation and incomplete-plant edit warnings | `test_water_coil_operations.py` |
| 11 | Empty source-plant impact and native controller deletion/recreation canary | `test_water_coil_migration.py` |
| 13 | VAV/CAV water-to-electric control preservation and rejection of legacy fixed-temperature configuration | `test_coil_conversion.py` |
| 15–16 | Retained name-keyed outputs, stale end-use-label warning, fixed pump power with autosized flow | `test_supply_fan_replacement.py`, `test_pump_performance.py` |
| 17 | Deferred pump feasibility warning, head ceiling, explicit versus translated demand bypass | `test_pump_performance.py`, `test_pump_replacement.py` |
| 19–20 | Missing economizer mixed-air setpoint and declared versus translated DCV floor | `test_economizer.py`, `test_ventilation.py` |
| 21 | Uncontrolled recovery on a cooling-supply loop | `test_heat_recovery.py` |
| 25 | Unquoted/quoted private model names in error reporting | `test_failure_reporting.py` |

The tracked round-12 migration verification is also consolidated here. Its final
J1 impact fields are `source_plant_remaining_coil_count`,
`source_plant_remaining_demand_equipment_count` and
`source_plant_will_be_unserved`. Non-coil demand equipment is counted separately;
an unserved source plant, its supply equipment and sizing settings remain. The
warning explicitly says the HVAC remover does not yet delete plants.

J2 pairs source/destination design supply and delta exactly, removes unrelated
destination demand before both runs and compares coil capacity, UA (or airflow)
and water flow at 1e-9 relative tolerance. CAV heating must exceed 10 kW. J3's
heating/cooling canary deliberately checks the installed SDK rather than skipping
a future version: branch removal deletes the owned controller but preserves the
coil, and attachment creates a controller pointing back to that coil. J4 reports
`retained_water_rating_mismatches`, leaves fixed values untouched and names
`openstudio-water-coil-editor` as the explicit follow-up. UA-method metadata and
autosized cooling inlet temperatures do not trigger that mismatch warning.
The independent round-12 Linux review recorded 467 passed and 50 native skips;
native parity results remain the recorded Mac evidence, not a new run here.

## Recorded verification and evidence

Counts overlap between increments and must **not** be added into one suite total.
These are prior Mac/native results unless labeled otherwise; no modeling tests
are rerun merely to consolidate Markdown.

| Checkpoint | Recorded result | Local evidence |
| --- | --- | --- |
| A baseline | 1,357 unique passes across all 40 modules: 347 core, 596 equipment, 216 air, 198 harness; native MCP skips explicitly rerun | `outputs/model-preparation-increment-a/` |
| A Q1/Q2 | 75 passes: 53 preparation and 22 plant/removal | `outputs/model-preparation-q1-q2/` |
| B | 272 unique passes: 236 packaging/host/preparation/archive plus 36 relocated native modeling checks | `outputs/shared-sdk-increment-b/` |
| C initial | 451 unique passes: 280 reporter/contract, 170 model regressions, 1 archive | `outputs/failure-reporting-increment-c/` |
| C C1/C2 | 242 passes, no skips: 60 reporter plus 182 packaging/doctor/host/CLI | `outputs/failure-reporting-c1-c2/` |
| D initial | 317 unique passes, no skips: 136 graph/reporting/packaging, 98 preparation/doctor, 82 host/CLI, 1 archive | `outputs/hvac-visualizer-increment-d/native-final/` |
| D final D1–D3 | 100 unique passes, no skips: final 45 visualizer plus 55 packaging/resource/import/manifest | `outputs/hvac-visual-review-d1-d3-20261012/review/evidence.json` |
| W1 follow-up | 100 targeted passes, including six native checks/eight simulations | `outputs/heat-recovery-review-w1/` |

Independent Linux reviews used the 3.11.0 wheel **without the native CLI**, so
native skips are coverage limits, not equivalent native verification. Examples:
A 1,020 passed/110 skipped; B batches 120/3, 111/1, 266/27 with an unavailable
archive-build environment; C reporter 43/2; D visualizer 31/2. Review D's legacy
fixture originally produced 21 diagrams including the empty group; D1's final
regression produces 20. Historical partial counts and initial failed probes are
superseded by the final implementation results above, not silently counted as
new verification. Two expected SDK-doc fallback warnings occurred in some host
batches. Restricted archive builds passed after supplying their isolated build
dependencies; no plugin installation was part of those checks.

The current local gallery is
[HVAC visual inspection](../outputs/hvac-visual-review-d1-d3-20261012/review/inspection.html).
Its directory contains native logs, both exports/reports, full graphs, SVG/PNG,
layout evidence and the synthetic stress fixture. Ignored `outputs/` artifacts
are machine-local evidence, not shipped dependencies or portable reproducers.
Older gallery paths are historical. Fixture-based tests do not depend on the
user's building. No live GitHub issue, live AI-agent token measurement, annual
simulation or native Linux/Windows run is claimed by these increments.

## Reproduction commands

Run from the checkout with its existing development environment. Select the
exact 3.11.0 CLI (or set `OPENSTUDIO_SKILL_TEST_EXE` for native tests on another
platform). Use exported launchers for native execution; raw source entrypoints
are not standalone plugin launchers.

```sh
.venv/bin/pytest -q -x tests/test_model_preparation.py tests/test_plant_and_removal_bundles.py
.venv/bin/pytest -q -x tests/test_failure_reporting.py tests/test_shared_sdk_packaging.py tests/test_harness_asset_manifest.py tests/test_skill_resource_exports.py tests/test_sdk_import_closure.py
.venv/bin/pytest -q -x tests/test_hvac_visualizer.py
.venv/bin/pytest -q -x tests/test_skill_sdk_doctor.py tests/test_openstudio_claude_code_adapter.py tests/test_openstudio_codex_adapter.py tests/test_adapter_runtime_helpers.py tests/test_openstudio_cli.py
.venv/bin/pytest -q -x tests/test_package_contents.py
.venv/bin/python tests/benchmark_model_loading.py --report "$(mktemp -d /tmp/openstudio-load-review.XXXXXX)/cost.json"
```

Complete current affected visualizer/export batch (100 cases at final D):

```sh
.venv/bin/pytest -q -x tests/test_hvac_visualizer.py tests/test_shared_sdk_packaging.py tests/test_harness_asset_manifest.py tests/test_skill_resource_exports.py tests/test_sdk_import_closure.py
```

Native public-launcher preparation and visualization, without installation:

```sh
REVIEW="$(mktemp -d /tmp/openstudio-sdk-review.XXXXXX)"
.venv/bin/python cli.py export marketplace --runtime-mode marketplace --output-dir "$REVIEW/marketplace"
.venv/bin/python cli.py validate-export "$REVIEW/marketplace/openstudio-ai" --runtime-mode marketplace
.venv/bin/python cli.py validate-export "$REVIEW/marketplace/plugins/openstudio-ai" --runtime-mode marketplace
OSCLI=/Applications/OpenStudio-3.11.0/bin/openstudio
CLAUDE_PLUGIN="$REVIEW/marketplace/openstudio-ai"
CODEX_PLUGIN="$REVIEW/marketplace/plugins/openstudio-ai"
CLAUDE_SKILL="$CLAUDE_PLUGIN/skills/openstudio-hvac-visualizer"
CODEX_SKILL="$CODEX_PLUGIN/skills/openstudio-hvac-visualizer"
"$OSCLI" execute_python_script "$CLAUDE_SKILL/scripts/prepare_model.py" --input "$PWD/tests/fixtures/openstudio-legacy-multiloop.osm" --output "$REVIEW/prepared.osm" --report "$REVIEW/preparation.json"
"$OSCLI" execute_python_script "$CLAUDE_SKILL/scripts/visualize_hvac.py" --input "$REVIEW/prepared.osm" --output-dir "$REVIEW/claude-topology" --report "$REVIEW/claude.json"
"$OSCLI" execute_python_script "$CODEX_SKILL/scripts/visualize_hvac.py" --input "$REVIEW/prepared.osm" --output-dir "$REVIEW/codex-topology" --report "$REVIEW/codex.json"
cmp "$REVIEW/claude-topology/graph.json" "$REVIEW/codex-topology/graph.json"
cmp "$REVIEW/claude-topology/equipment_graph.json" "$REVIEW/codex-topology/equipment_graph.json"
"$OSCLI" execute_python_script "$CLAUDE_SKILL/scripts/prepare_model.py" --input "$REVIEW/prepared.osm" --output "$REVIEW/unused.osm" --report "$REVIEW/already-current.json"
```

For partial-removal verification, use
`tests/test_model_preparation.py` and its genuine ten-loop fixture: old-model
inventory/preflight must require preparation; prepare, inventory/select one
loop, review the removal plan, then apply while the other nine lists persist.
Tampered/stale plans, genuine second-load changes, CSV/weather/measures resolved
from the original location and moved companions have dedicated regressions.

For relocation, move the **whole** exported plugin to a path with spaces and run
its doctor from another CWD. Inspect its `sdk/PACKAGING.json`; do not copy one
skill folder or modify bundled source to make integrity checks pass. Relocated
native tests in each owning equipment suite cover the same contract.

Read-only reporter readiness/local-draft checks using that export:

```sh
SCRIPT="$CLAUDE_PLUGIN/skills/report-openstudio-failure/scripts/report_failure.py"
.venv/bin/python -I -S "$SCRIPT" --state-dir "$REVIEW/failure-state" doctor
.venv/bin/python -I -S "$SCRIPT" --state-dir "$REVIEW/failure-state" policy disabled
.venv/bin/python -I -S "$SCRIPT" --state-dir "$REVIEW/failure-state" pending
```

Submission regression tests use mocked GitHub transport. Creating a live issue
is not required to reproduce verification. Archive builds may need network
access; optional/native dependencies skip where the corresponding tests specify.

## Remaining scope and next equipment work

A–D requested implementation fixes are complete. No new equipment phase starts
as part of consolidation. The next proposed bounded operation is terminal
in-place airflow/reheat editing, then a distinct terminal replacement contract.
Other retained backlog items are broader fan locations/classes, independent
boiler/chiller/tower/district performance/replacement and unused-plant cleanup,
and PSZ/unitary/fan-coil/PTAC/PTHP/unit-heater/WSHP recipes. Attach/replace scope
must define placement, controls, sizing and reference preservation before export.

Future visualization enhancements include pagination, highlight/compare views,
verified embedded flow expansion and richer plant/control views. Recovery and DCV
results are pin- and fixture-specific. Full unrelated suites were not rerun after
each presentation change; no general annual-energy/compliance claim or measured
agent-token savings is made. No commit, push, installation, release or live issue
submission is part of this cleanup.

## Consolidation scope

The following five untracked implementation guides were read, consolidated and
removed on October 13, 2026:

- `MODEL_PREPARATION_INCREMENT_A.md`
- `SHARED_SDK_PACKAGING_INCREMENT_B.md`
- `FAILURE_REPORTING_INCREMENT_C.md`
- `HVAC_VISUALIZER_INCREMENT_D.md`
- `SDK_INTEGRATION_REVIEW.md`

Their active links in README, the tracked SDK/modularization guides and HANDOFF
now point here. The user subsequently authorized removing all consolidated files
under `docs/reviews/`, superseding the earlier preservation instruction. All
**34 files** in that directory were inspected and consolidated: 21 untracked
Markdown notes, the tracked round-12 migration verification and 12 historical
Python probes. The directory is retired. The review decisions, final-versus-
historical distinctions, probe scenarios and migration details are retained here.
Tracked living guides, maintained tests, model fixtures, production source and
ignored native evidence remain. No existing uncommitted tracked guide edits were
discarded; the tracked round-12 review is the only tracked review-file deletion.
