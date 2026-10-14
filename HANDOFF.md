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
- Phase 10a/E1–E2 has progressed through review. Phase 10b adds the independent
  minimum-OA/ZoneSum DCV editor and shared VAV/CAV ventilation setters, preserving
  zone OA/People, sizing, economizer and all identities. Native before/after pairs
  verify occupancy-driven OA modulation. Phase 10c adds direct OA intake/recovery
  attachment and in-place recovery editing, with explicit controls, protected graphs
  and native VAV/CAV execution. It is ready for review; the work guide records
  scope, source trace and evidence.
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
fan performance and coil-attachment contracts; the former is now implemented
below, and coil attachment remains the next checkpoint.
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

## Supply-fan performance editing, G1–G3 — October 6, 2026

Phase 4 now exposes `openstudio-supply-fan-performance-editor` and
`edit_supply_fan_performance.py`, replacing the unreleased same-class swap skill.
Explicit efficiency/pressure edits call setters on the existing CV/VV supply fan.
Fan, connections, metadata and incoming reference handles remain unchanged;
LifeCycleCost and EMS actuators are accepted and protected after reload.
Class-changing requests must not route here. The tested node-preserving swap
primitive remains unexported in `common/fan_replacement.py` pending curve,
terminal/sizing and reference-migration decisions.

The planner and editor share `fan_equipment.pressure_pa`. Whole VAV/CAV fan
construction requires complete performance values before creating a fan, and
full setters check before mutation. Only explicit edits permit partial inputs.
Compatible NLR stays first; the package-wide exact SDK pin remains unchanged.
Re-export both hosts and regenerate old replacement plans because the operation
name and approved preservation contract changed. Review files under docs/reviews
remain preserved. See docs/HVAC_MODULARIZATION_WORK.md for contract and checks.

Verification: 289 combined tests passed, including 52 fan cases, two native
design-day runs and both relocated host bundles. Saved tests preserve incoming
references/identities; six tests retain deferred node-surgery coverage. All three
edited skills passed exported validation, and nine changed Python files/diffs
passed formatting/whitespace checks. Current native evidence/logs are in ignored
outputs/supply-fan-performance-review/evidence.json; earlier phase-4 swap evidence
and user review/probe files remain historical.
Next review: phase 5 water-coil attachment/controller lifecycle, with rating-only
changes distinguished from attachment/replacement. No commit/push/install/release.

## Main-supply water-coil operations — October 7, 2026

H1/H2 remediation extends and renames the in-place skill to
`openstudio-water-coil-editor` / `edit_water_coil.py`. Explicit ratings, coil/
controller names, availability, sizing resets and partial controller settings use
existing-object setters, preserving coil/controller/connection/metadata/reference
handles, including EMS/LifeCycleCost. Unspecified fields and sensor/actuator nodes
remain protected. `sizing: Autosize` resets coil sizes and controller maximum flow,
with conflicts shown as unready.

`openstudio-water-coil-connector` now exposes attachment only at the supply outlet;
inlet/interior nodes stay unready even with a Temperature setpoint manager. The
same-class replacement schema/builder/validator/route is removed. Clone/retarget/
reconnect code is kept in unexported `common/coil_replacement.py` pending a real
class/location/plant-changing contract. Inventory exposes supported outlets.

Allowed raw-field lists are sorted so serialized configuration key order cannot
invalidate a reviewed plan. Re-export both hosts and regenerate all water-coil
plans; retired ratings-editor bundles/replacement configs are unsupported. NLR
priority and the package-wide exact OpenStudio release pin remain unchanged.

Baseline verification was 386 combined tests, including 97 water-coil cases. H1/H2
verification passed 416 combined checks, including 127 water-coil cases. Four
changed skills passed exported validation; five changed Python files and both
diffs passed formatting/whitespace checks. Twelve
native VAV/CAV design-day cases have passed with positive selected-coil capacity
and no Severe/Fatal errors; both relocated hosts passed doctor/preflight/apply.
Native evidence/logs: outputs/water-coil-review-h1-h2/evidence.json. Work guide:
docs/HVAC_MODULARIZATION_WORK.md. New export dependencies are staged; user review
files remain untouched/untracked. Review probes document superseded behavior.
H3/H4 are now addressed: UA attachment rated temperatures are optional and marked
informational in full/bounded review; pinned SDK defaults and actual sizing context
are recorded. Valid UA rating metadata is not checked against plant operating
temperatures. EnergyPlus 25.2.0 source confirms the sizing branch and unconditional
input relationship checks. In-place edits warn about missing plant equipment/pump/
outlet setpoint controls and retain false simulation readiness through companion
packing. Attachment still requires a ready plant, and wrong type still blocks edits.
H3/H4 combined verification passed 438 checks, including 149 water-coil cases.
Both changed skills passed exported validation; three changed Python files and
staged/unstaged diffs passed formatting/whitespace checks. Four paired native
VAV/CAV runs passed with equal positive capacity, UA and water flow despite changed
rating metadata; logs are in outputs/water-coil-review-h3-h4/.
CI follow-up: the missing-drive regression still mocked `Path` in `vav_plan`
after path validation moved into `multizone_plan`. It now patches the shared
module while calling the public VAV planner, and bounds the fake-root traversal
so a loop regression fails promptly. The review-regression/preflight checks passed
78 tests; the changed test passed formatting. The combined command in the work
guide now includes the previously omitted review-regression file. Full CI was
not rerun locally. Keep `openstudio-water-coil-editor` as the stable skill name:
its in-place settings extend beyond the initial ratings-only scope.
H1–H4 review is approved. The user reports successful real Claude Code and Codex
trials after re-exporting both plugins. Phase 6a plant migration follows below.
No commit/push/install/release initiated by this task.

## Phase 6a — main-supply water-coil plant migration — October 7, 2026

The existing connector adds `operation: migrate_plant` for a dedicated single-coil
demand branch moving to another ready compatible water plant. Explicit Autosize
resets coil sizing/controller maximum flow; other scalar settings remain unchanged.
Coil/controller/air-node/reference/metadata handles are retained. Native branch
removal would delete the owned controller, so temporary ownership protects it until
the new water connection is complete; no temporary equipment survives publication.
Water nodes and demand connection handles can change. External water-node references,
serial components, glycol and custom controller locations are rejected.

Private topology preview restricts changes to the selected coil and two demand
graphs. Saved validation checks preserved fields/identities, both supply orders and
demand membership, exact air order, controller nodes and an independent whole-model
connection graph. Existing hash/companion/fresh-plan/translation/publication protections
remain. The migration module is exported with both existing water-coil bundles;
no skill rename or public same-class replacement was introduced.

Verification passed 304 distinct targeted checks: 121 migration/review/preflight,
129 existing non-native coil cases and 54 import/manifest/host export cases. This
includes 43 migration cases, four positive native design-day capacities without
Severe/Fatal errors and both independently relocated host bundles. Seven affected
exported skill instances passed validation; three changed Python files and both
diffs passed formatting/whitespace checks. Full CI was not rerun. Evidence/logs are
in outputs/water-coil-phase6-review/evidence.json and its final/ test workspace.
The work guide documents review commands,
input examples and phase 6b/6c boundaries. New source/test files are staged for the
tracked-source manifest check; user review files remain untouched. No commit/push/
plugin installation/release. Next: phase 6a review, then explicit class-changing
replacement contract (6b); air relocation (6c) remains deferred.

J1–J4 review follow-up adds source-plant remaining coil/demand counts and an
unserved flag, zero-coil retention warnings and explicit rating-editor follow-up
for active water-temperature mismatches. The current remover cannot delete plants;
warnings state that boundary and do not authorize cleanup. Heating UA metadata
and Autosize cooling inlet temperature retain their informational/automatic roles.
Minimal SDK lifecycle probes now test branch removal deleting the owned controller
and attachment creating a replacement; they run independently of the 3.11-only
fixture to explain future SDK changes. Matched baseline/migration native pairs
use identical plant design conditions and verify heating capacity/UA/water flow
and cooling capacity/air/water flow, including the substantial CAV heating case.
J1–J4 verification passed 188 distinct targeted checks: 134 migration/review/preflight
and 54 import/manifest/host exports, including 56 migration cases (13 new), eight
matched native runs plus four existing design-day runs and both relocated hosts.
Both connector exports and two changed Python files passed skill/format checks;
staged/unstaged whitespace checks passed. Heating capacity/UA/water flow and cooling
capacity/air/water flow were identical in every matched pair, with CAV heating
above 20 kW. Full CI was not rerun; existing unchanged edit/attach code retains the
prior verification record. Evidence/logs: outputs/water-coil-review-j1-j4/evidence.json
and final/. The work guide records the review map and small VAV heating limitation.
Re-export both hosts and regenerate migration plans for the new impact/warnings.

## Phases 6b and 6c — October 7, 2026

Historical initial implementation: the constant-outlet-temperature contract below
is superseded by the October 8 K1–K3 correction. Capacity checks alone did not
establish correct control.

Initial contracts are implemented and ready for review on `enhance_skills_scripts`.
New `openstudio-coil-replacer` / `replace_coil.py` converts a direct main-supply
heating-water coil to electric with explicit efficiency, constant outlet temperature,
Autosize and Reject reference policy. Air boundaries, availability and coil metadata
remain; the water coil/controller/branch nodes are removed, and the output reports
new equipment/control identities. Source plant loads/retention are disclosed.

Existing `openstudio-water-coil-connector` / `connect_water_coil.py` now exposes
`relocate_air` to a selected main supply outlet on the same or another unsplit loop.
It preserves coil/controller/water nodes and the complete plant branch, resets coil
sizing/controller maximum flow to Autosize, and moves the sensor. One old interior
air node is removed and one new inlet node created. Native tests caught adjacent-node
branch errors despite clean translation; corrected explicit rewiring merges the old
location into one shared node. Named/UUID interior-node dependencies and destination
fan-control references needing retargeting block preflight. Source boundary nodes
and all zone assignments remain. Same-class edits retain their existing editor;
the prior same-class cloning primitives remain unexported.

Scripts remain directly skill-bound with NLR preferred and the package SDK pin
unchanged. The manifest exports the new skill and all import dependencies to both
hosts. New sources/tests are staged for tracked-manifest checks; pre-existing review
files are preserved. No commit, push, installation or release was performed.

Verification: **319 distinct targeted tests** (90 new cases, 175 legacy non-native
coil cases, 54 manifest/import/resource/adapter checks). This includes six native
design-day runs with positive capacities and no Severe/Fatal errors, and both
independently relocated host bundles for each operation. Seven exported skills and
seven changed Python files passed skill/format validation; whitespace checks passed.
Native environment: OpenStudio 3.11.0, EnergyPlus 25.2.0, embedded Python 3.12;
local SDK tests use Python 3.13.7. Full CI/legacy native cases were not repeated.
Evidence/logs: `outputs/coil-phase6bc-review/evidence.json` and `final/`.

See `docs/HVAC_MODULARIZATION_WORK.md` for contracts, review map, commands, capacity
table and the broader equipment backlog. Review 6b/6c before expansion; proposed
subsequent work covers fan class replacement, pumps, outdoor-air/DCV/economizer
controls, terminals/reheat, heat recovery, plant-equipment edits/replacement and
unitary/zone-system recipes. Gas/DX conversion, arbitrary destination nodes, embedded
coils and automatic plant deletion remain future coverage. The VAV heating fixture
is small; the substantial CAV case is the stronger heating check. Annual performance,
ventilation adequacy and actual agent-token savings remain unverified.

## K1–K3 control review correction — October 8, 2026

Conversion now requires explicit `temperature_control: Preserve`; the old
`outlet_temperature_c` field is rejected. It creates neither an outlet setpoint
manager nor a temperature schedule. Existing outlet managers retain identity and
settings, and unmanaged outlets retain OpenStudio's generated MixedAir supply-air
tracking with fan heat compensation. Before/preview/saved translated manager
fields must match. Custom water-controller strategies outside normal
Temperature/Flow control are refused before conversion. Fixed preheat control is
separate future coverage. Removing the new schedule resolves K2.

Relocation impact now includes before/after translated managers, supply-air
control references and position relative to each direct supply fan. The warning
explicitly describes draw-through to blow-through and fan heat compensation to
direct supply-outlet tracking where applicable; saved validation checks the
reviewed destination control context.

Verification: **328 distinct targeted tests passed** (99 conversion/relocation,
175 legacy non-native coil checks, 54 manifest/import/export/adapter checks).
The 99 include eight native design-day runs and four independently relocated
operation/host bundles. Two new native runs inspect active node temperatures,
setpoints and heating/electricity rates. VAV/CAV each supplied 432 active
timesteps; maximum fan-compensation errors were 0.01328/0.00141 K. Heating and
electricity were zero on all 432/288 no-heating-needed timesteps, respectively;
conditioned-air temperature errors remained below 0.02 K. These are short
design-day control checks, not annual energy evidence. SDK 3.11.0/EnergyPlus
25.2.0; local Python 3.13 and embedded CLI Python 3.12. Full CI and legacy native
cases were not rerun. Seven affected skill instances in refreshed Claude/Codex
exports passed validation; five changed Python files passed Black targeting
Python 3.10. Staged/unstaged whitespace checks passed.

Evidence: `outputs/coil-review-k1-k3/evidence.json`; final native SQL/logs and
per-case control evidence under `outputs/coil-review-k1-k3/final/`. Work guide:
`docs/HVAC_MODULARIZATION_WORK.md`, K1–K3 follow-up. Re-export both hosts and
regenerate conversion/relocation plans before use. User-owned review/probe files
remain untouched. No commit, push, installation or release is included.

## Phase 7 — supply-fan class replacement — October 8, 2026

K1–K3 review is completed and approved. Implemented the next equipment operation:
`openstudio-supply-fan-replacer` / `replace_supply_fan.py`, constant-volume ↔
variable-volume on an unsplit loop's sole direct supply fan. Requires opposite
class, complete efficiency/pressure inputs, explicit variable-volume coefficients/
minimum-power fraction, fan Autosize, terminal/system-sizing Preserve policies and
reference Reject. Missing choices stay unready; no prototype curve is inferred.
Same-class performance edits retain the existing in-place editor and identities.

Replacement retains boundary nodes, position, availability, motor heat fraction,
end-use subcategory and existing metadata identity/features; fan and connections
receive new handles. UUID/name references requiring migration block preflight.
Protected objects/graphs and independent saved getters verify unrelated equipment,
terminals, OA controls, sizing and zone assignments. All translated setpoint/NodeList
fields must remain identical through preview and saved reload. No new schedule or
manager. Inventory/report output stays bounded; full terminal references live in
the plan. Return/relief/exhaust/unitary fans and whole-system conversion are deferred.

Verification: **163 distinct targeted checks passed**, comprising 57 new
replacement, 52 existing fan edit and 54 manifest/import/export/adapter checks.
Four distinct native design-day cases and four independently relocated host
bundles passed. Latest replacement traces have 577 active part-load timesteps in
each direction, max flow 1.431015908 m³/s, normalized power errors below 3e-16.
The variable-volume trace exercises its explicit 0.5 power floor on 144 timesteps.
Two new native cases were rerun for the floor check; no duplicate test counts.
Seven exported skill instances, both new pinned doctor checks, three Python
format checks and whitespace checks passed. Full CI/upstream coil/system suites
were not rerun; their code was unchanged. No annual energy claim or live-agent eval.

Review map, source trace, configuration example and commands are in
`docs/HVAC_MODULARIZATION_WORK.md`, phase 7. Evidence/exports/logs:
`outputs/fan-class-phase7-review/evidence.json`, `final/`, `floor/`, `exports/`.
SDK/CLI 3.11.0, EnergyPlus 25.2.0, local Python 3.13/embedded Python 3.12.
Re-export both hosts for local trial. New assets are staged for tracked-source
checks; user-owned review/probe files are preserved. No commit/push/install/release.
Phase 7 review has since been approved; phase 8 below adds in-place pump operations before a separate
pump-class replacement contract.

## L1–L3 fan review follow-up — October 8, 2026

Compatible fan-name keyed outputs now pass replacement preflight: the five common
pinned fan variables and custom/decrement electricity-energy meter keys retain
identities/fields, along with associated exact-name meter requests. Impact lists
up to eight retained reporting objects, count and full-plan details. Individual
keys are checked; direct UUID/EMS actuator/cost references and unsupported variables
still block. Own display names are not treated as incoming fan references.

Optional explicit `end_use_subcategory` changes the reporting label; omitted labels
are preserved, with a warning when recognizable text names the old fan type.
Changed labels warn about subcategory meter requests. Saved performance validation
checks the selected label. Impact now explicitly says terminal-driven airflow can
still vary with a constant-volume replacement; power is proportional to that flow
at fixed pressure/efficiency. Existing terminal and sizing protections remain.

Verification: **185 distinct targeted checks passed** (79 replacement, 52 existing
fan edits, 54 packaging/adapter). Four native design-day cases and four relocated
operation/host bundles passed; two changed exported skills and Python format/diff
checks passed. Latest new traces retain source name-keyed outputs/custom meters
and apply a new label. Meter/variable energy sums are exactly equal in both
directions, with 577 qualifying part-load timesteps each and 144 below the VV floor.
Full CI/upstream coil/system suites were not rerun. Native environment unchanged.
Evidence: `outputs/fan-review-l1-l3/evidence.json`, `final/`, `exports/`; review map
in `docs/HVAC_MODULARIZATION_WORK.md`, L1–L3 follow-up. Re-export both hosts and
regenerate plans. User-owned reviews/probes remain preserved/untracked. Changes
are staged; no commit/push/install/release. Phase 7 is now approved; phase 8 is recorded below.

## Phase 8 — independent pump edits — October 8, 2026

Phase 7/L1–L3 are approved. Added `openstudio-pump-performance-editor` for an
explicitly selected single constant/variable-speed plant pump on either side,
including multi-pump plants. It edits head/motor settings, operating mode, fixed
or autosized electric power, power-sizing method/factors and explicit variable-
speed coefficients in place. It preserves pump/connection/metadata/reference
identities and all unrequested plant state. Plans warn when fixed power or the
flow-only method masks head/efficiency changes. Genuine class replacement, pump
banks, flow changes and pressure-reset redesign remain separate future contracts.

Verification: **108 targeted checks** (54 pump, 54 packaging/adapters), including
12 native EnergyPlus design-day runs and both independently relocated host bundles
with doctor/inventory/preflight/apply. Native pressure-sized rated power changes
117.688→55.747 W at unchanged design flow; actual electricity ratios are 0.473684
(constant) and 0.473416 (variable). Flow-only and fixed-power cases retain rated
power; Continuous control and all scalar/curve inputs have saved/translation checks,
not dedicated annual/control-trace evidence. Details/limits/review map/commands:
`docs/HVAC_MODULARIZATION_WORK.md`, phase 8. Evidence: ignored
`outputs/pump-phase8/`, final tests, native SQL/logs and validation exports.

Environment remains SDK/CLI 3.11.0, EnergyPlus 25.2.0, local Python 3.13/embedded
Python 3.12. Full CI and unchanged upstream coil/fan/system suites were not rerun.
User-owned review/probe files remain unchanged. Changes staged, no commit/push/
installation/release. Next: phase 8 review and user trials before true pump-class
replacement. Re-export hosts and regenerate plans for the new operation.

## M1–M2 pump review follow-up — October 8, 2026

M1: fixed-power/autosized-flow plans now explicitly warn that motor-output
feasibility requires sizing. The warning includes the implied hydraulic-efficiency
check and maximum feasible design flow, and survives apply without changing fixed
power or resetting flow. Both constant/variable-speed 50 W / 600 ftH2O probes are
covered, including an equivalent Pa request. Fixed-flow impossibilities still fail.
This is a deferred-feasibility warning, not a post-sizing validator.

M2: head inputs are bounded to 10 MPa (3345.5256331296855 ftH2O), equivalently in
both units; the ceiling bounds this bundle's contract and is not a recommended
head or SDK hardware limit. Coefficients require exactly four entries in schema.
The shared validator now supports conditional branches and maxItems, with field-
specific schema errors before inventory. Boundary, partial-input and conditional/
array regressions supplement existing preflight coverage.

Verification: **181 targeted checks passed** (62 pump, 65 VAV/preflight/schema,
54 packaging/adapters), including 12 EnergyPlus design-day runs and relocated
pump/VAV resources on both hosts. Four changed Python files pass Black (Python
3.10 target) and whitespace checks. Evidence: ignored
`outputs/pump-review-m1-m2/final/`, `evidence.json`; review disposition in
`docs/HVAC_MODULARIZATION_WORK.md`, M1–M2 follow-up. No full CI run. Review/probe
files remain unchanged; the old M1 probe asserts the pre-fix absence of a warning.
Re-export and regenerate pump plans because fresh preflight now contains a new
warning and stricter schema. Changes staged for review; no commit/push/release.

## Phase 9 — genuine pump-class replacement — October 8, 2026

Phase 8/M1–M2 review is complete; phase 9 is implemented and ready for review.
New `openstudio-pump-replacer` changes one connected single constant ↔ variable-
speed pump on either plant side, including individually selected multi-pump and
common-pipe arrangements. The user chooses flow/power Preserve or Autosize,
plant Preserve, reference Reject, and explicit VS coefficients/minimum flow.
Same-class settings stay in-place in the editor; combined requests compose the
two reviewed copied outputs. No inferred standards profile or pressure reset.

Common settings, effective zone heat-loss split, schedules, metadata features,
water boundary nodes, equipment order, other pumps and plant state remain.
Pump/two connection handles change; compatible name-keyed reporting survives,
direct EMS/cost/object references block. Preview/saved validation protect raw
fields, topology and translated controls. Component-setpoint operations may
update only the exact selected pump's class reference; other operation fields
stay identical. Pressure/VFD hardware, banks/condensate and active plant pressure
simulation require separate coverage. Resources/routing work independently on
both hosts and preserve NLR priority and exact SDK 3.11.0.

Verification: **195 targeted checks passed** (79 replacement, 62 editor, 54
packaging/adapters), including 24 native EnergyPlus design-day runs and four
independently relocated operation/host bundles. Six replacement comparisons
retain rated flow/power to relative tolerance 1e-6; timestep power follows the
explicit cubic curve. VS/CV design-day electricity ratios: VAV supply 0.235154,
common-pipe demand 0.235196, CAV supply 0.372908. These are fixture evidence,
not annual savings. Four changed Python files pass Black targeting 3.10;
seven exported affected skills and whitespace checks pass.

Review map/contract/commands/limits: `docs/HVAC_MODULARIZATION_WORK.md`, phase 9.
Ignored evidence: `outputs/pump-phase9/evidence.json`, final native SQL/logs and
`validation_exports/`. SDK/CLI 3.11.0, EnergyPlus 25.2.0, local Python 3.13 and
embedded 3.12. Full CI and unrelated system/coil/fan suites were not rerun.
Existing user review/probe files remain unchanged. Task changes staged for review;
no commit/push/plugin installation/release. Next: review this bounded replacement
contract, then re-export both hosts for local trials before extending equipment
coverage. Prior phase summaries above are historical checkpoints.

## N1 pump-replacement follow-up — October 8, 2026

Constant-speed supply plans now inspect complete parallel demand paths and expose
explicit OSM and actual translated uncontrolled-branch status/count, bounded
paths, and common-pipe mode. No explicit OSM bypass raises a warning without
blocking the requested Preserve operation or adding an acknowledgement field.
Inlet/outlet pipes and pipe-plus-controlled-coil branches do not count. Unknown
passive equipment needs review; path presence alone does not establish adequacy.
Saved validation recomputes both statuses. No OSM bypass is inserted.

Native evidence found that 3.11.0 synthesizes a demand bypass when the OSM has
none. The warning distinguishes this verified translation path and the risk if
downstream measures remove it. Four native before/after runs exercise one HW
coil with/without an explicit bypass, Continuous control and 6 kPa head; the
coil can receive zero flow while the constant-speed pump circulates through the
translated bypass. A fifth run removes that bypass only from a diagnostic IDF:
all nonzero flow passes through the sole coil, with 144 flow and 433 zero-flow
timesteps. It finishes without a specific excess-flow warning or Severe/Fatal
errors. This does not establish controller-request mismatch or universal
over-delivery; the full behavior and limits are in the work guide.

Verification: **145 checks passed** (91 replacement, 54 packaging/adapters),
including 17 native runs, relocated Claude/Codex bundles, two exported skill
validators and changed-file Black/whitespace checks. Full CI and unrelated
equipment suites were not rerun. Evidence: `outputs/pump-review-n1/evidence.json`
and `final/` SQL/IDFs/logs. Version/environment unchanged from phase 9 above.
User-owned review/probe files remain unchanged; round-17 P3 asserts the old silent
behavior and is superseded by new regressions. Re-export both plugins and
regenerate reviewed pump plans for the added hash-bound status/warnings.
Changes staged for review; no commit, push, installation or release.

## Round 18 lookup safeguards — October 8, 2026

Removed the translated PlantLoop field-number dependency: demand connector-list
lookup uses its IDD field name. Missing/empty fields, missing translated objects
and a missing splitter entry raise `Cannot verify translated demand bypass`
ValueErrors with specific context. Successful plans/model behavior are unchanged.
Eight new regressions cover field movement and lookup failures.

Verification: **122 focused checks passed** (91 non-native pump replacement,
31 manifest/import/resource exports); eight native cases deselected. Both
relocated hosts execute the changed helper. Changed-file Black and whitespace
checks pass. Prior N1 native evidence remains applicable; no EnergyPlus/full CI
rerun. Artifacts: `outputs/pump-review-lookups/final/`; source/review map in
`docs/HVAC_MODULARIZATION_WORK.md`. Review files remain unchanged. Changes staged
for review; no commit/push/install/release. Re-export hosts for these diagnostics.

## Phase 10a economizer editing — October 9, 2026

Phase 9/N1/round-18 are approved. Added `openstudio-economizer-editor` for explicit
in-place economizer type, lockout and four optional limits. Existing direct OA
controller, MV, nodes, connections, metadata and reference handles stay intact;
ventilation/DCV, schedules, sizing and equipment are protected. Null explicitly
resets a limit; no climate/template assumptions or blanket approval profile.
The preview exposes effective additive cutoffs and retained OA overrides, with
simulation warnings for unmatched 100% OA sizing and conflicting flow caps.
VAV/CAV creation shares canonical setters and retains existing recipe behavior.
Both host exports include a self-contained skill, pinned doctor/probe and schema.

Verification: **185 targeted checks passed** (50 economizer, 81 VAV/CAV, 54
packaging/adapters), including four native economizer before/after runs and two
existing CAV sizing runs. Mild-design-day economizer status activates in 368
reported timesteps in both systems; maximum OA fraction rises about 0.4943→1.0.
No Severe/Fatal errors. Both new host bundles and affected parent bundles pass
relocation execution; six affected exported skills pass validation. Changed-file
Black targeting Python 3.10 and whitespace checks pass. No annual/compliance,
live-agent token, full CI or unrelated equipment verification is claimed.

Review/source map and rerun command: `docs/HVAC_MODULARIZATION_WORK.md`, Phase 10a.
Evidence: `outputs/oa-phase10/evidence.json`; native SQL/IDFs/logs and final tests:
`outputs/oa-phase10/final/`; review exports: `outputs/oa-phase10/review-exports/`.
Environment remains host Python 3.13.7, pinned SDK/CLI 3.11.0, embedded Python
3.12, EnergyPlus 25.2.0; release metadata stays 0.4.0.
Phase 10a is ready for review. Next is 10b minimum OA/DCV with separate ventilation,
schedule, occupancy and sizing checks; 10c OA topology/heat recovery follows its
own checkpoint. The remaining equipment backlog is retained. User review/probe
files remain untouched. Changes staged for review; no commit/push/install/release.
Re-export both plugins for this route/shared helper and regenerate reviewed plans.

## Phase 10a E1–E2 follow-up — October 9, 2026

Preflight now edits a cloned preview and verifies a translated mixed-air single
Temperature setpoint source for active economizers. The node and its managers are
recorded in retained context/impact and checked again after saving. Missing control
keeps the scoped edit ready but warns and marks plan, companion and apply result
`simulation_ready: false`. No implicit manager or supply setpoint is created.
NoEconomizer skips this requirement. Generated/direct temperature managers and
NodeLists are recognized; humidity-only/dual-setpoint/reference-only matches do
not qualify. Custom EMS execution and reference chains require separate review.

Extracted the existing coil node-manager collector into
`common/temperature_control.py`, preserving coil control checks and explicitly
exporting it to all six affected skill bundles. Saved/reported economizer numbers
now use `rel_tol=1e-9`, `abs_tol=1e-9`; nulls/enums/identities, protected raw fields
and source/plan binding stay exact. Seventeen new regressions include a realistic
load-controlled unitary case as well as VAV/CAV fixtures and rounding boundaries.

Verification: **283 distinct checks passed**: 225 selected regression cases and
121 economizer/packaging cases (63 overlap), including four native economizer runs,
both relocated host bundles and two exported skill validators. Changed-file Black
(Python 3.10 target) and whitespace checks pass. Full CI and the deselected coil/
fan native cases were not rerun. Environment/version unchanged from phase 10a.
Evidence: `outputs/economizer-review-e1/evidence.json` and `final/` SQL/IDFs/logs/
relocated bundles; source/review map and commands are in the E1–E2 subsection of
`docs/HVAC_MODULARIZATION_WORK.md`.

E1/E2 are addressed and ready for review. Re-export affected bundles and regenerate
economizer plans for the added translated context. User review/probe files are
unchanged; round-19 P1 asserts the superseded silent-readiness behavior. Changes
staged for review; no commit/push/install/release. Phase 10b remains next after
this checkpoint.

## Near-Term Backlog

- Skill-bound SDK development is complete within the user-selected local
  evaluation scope. See `docs/SKILL_BOUND_SDK_SUMMARY.md` for decisions, review
  disposition, source trace, historical verification and remaining limitations.
  Prepare a coordinated SDK/package/plugin release after review.

- Refresh CI/release checks into an explicit host/runtime/version/evaluation
  matrix, including real simulation readiness where the native executable is
  available.
- Align `measures/approved/` with the live measure registry before presenting
  it as the trusted measure source.
- Design user-facing runtime retention and installed-measure administration.
- Add parametric-study orchestration only after the engineering-session and
  diagnostic evidence contracts are established.


## Phase 10b minimum OA / ZoneSum DCV — October 9, 2026

User advanced after phase 10a/E1–E2. Added `openstudio-ventilation-editor` with
strict explicit flow limits, three existing schedule references and ZoneSum DCV.
DCV does not implicitly reset controller/fraction floors. Typed Constant/Ruleset
schedule ranges, occupancy, inherited zone OA, nominal airflow, sizing and retained
control checks inform the preview and simulation readiness. Schedule selection
refuses implicit SDK type-limit changes. All zone/load/sizing/economizer objects,
topology, metadata, incoming references and identities stay protected. VAV/CAV
share the setters in their parent transaction; no per-object agent invocation.

Shared direct-OA context/translated mixed-air control moved to `outdoor_air.py`.
Raw UUID MV lookup fixes missing MV context in economizer plans; regenerate plans
and both host exports. Geometry summaries normalize last-bit SDK aggregate
variation, with 30 repeated native preflights identical. Requested settings/raw
protected state are not rounded. The saved model undergoes seven independent
check groups and EnergyPlus translation before copied publication.

Verification: **259 distinct targeted checks passed**, including 57 final
ventilation tests, 67 economizer, 81 VAV/CAV and 54 packaging/adapters. Ten native
design-day runs cover four DCV comparisons, four economizer comparisons and two
existing CAV sizing cases. Both relocated hosts execute doctor/inventory/preflight/
apply. Eight affected exported skills pass validation; Black/whitespace checks
pass. Full CI, annual performance and Linux/Windows native execution were not run.

Native 10% occupancy reduces MV request to 0.118033 of baseline in VAV/CAV;
minimum actual ratios are 0.219791 / 0.118033. Full-occupancy MV requests match;
no Severe/Fatal errors in the four DCV runs. Review/source map and rerun command:
`docs/HVAC_MODULARIZATION_WORK.md`, Phase 10b. Artifacts:
`outputs/ventilation-phase10b/evidence.json`, `verification/` SQL/IDFs/logs and
`exports/` host plugins. Environment remains OpenStudio 3.11.0 / EnergyPlus 25.2,
host Python 3.13.7 and embedded Python 3.12. No live-agent token measurement.

Phase 10b is ready for review; 10c OA attachment/topology/heat recovery is next.
Other MV-method DCV, CO2/IAQ policy, zone OA/People editing and ventilation/sizing
redesign need separate coverage. User review/probe files remain untouched.
Changes are staged for review; no commit/push/install/release.


## Phase 10b V1 follow-up — October 9, 2026

Added a direct DCV ineffectiveness warning for verified persistent fixed floors
at/above nominal ZoneSum design OA. Impact now records `dcv_effective` and a
`dcv_floor` breakdown with declared/translated minima and scheduled lower bound.
Partial, varying/unverified and proportional floors keep qualified warnings.
No floor is reset and no new readiness gate is imposed. Saved validation rechecks
the translated minimum by named field; stale plans must be regenerated.

Correction to V1's Autosize premise: native OpenStudio 3.11.0 translation changes
an Autosize OSM minimum to zero when DCV is enabled, and actual OA falls. The
OSM field remains Autosize. Report this verified behavior rather than claiming
DCV is ineffective in that case. `dcv_effective: null` means not established,
not a promise of annual savings; false also applies when DCV is disabled.

**108 targeted checks passed**: 77 ventilation and 31 manifest/import/resource,
including six native before/after cases (twelve design-day runs). VAV/CAV fixed
design floors keep actual OA unchanged; Autosize and zero floors permit reductions.
No Severe/Fatal errors. Both relocated hosts pass, both exported ventilation
skills validate/resources match source, and changed-file formatting passes.
Full CI and unrelated native suites were not rerun. Environment remains exact
OpenStudio 3.11.0 / EnergyPlus 25.2, host Python 3.13.7 / embedded Python 3.12.

Review/source/artifact map: work guide's Phase 10b V1 section and
`outputs/ventilation-review-v1/evidence.json`, `native-verified/`, `final/`, `exports/`.
Regenerate ventilation plans and host exports. User review/probe files remain
untouched; round-20 P2's prior warning assertion is superseded. Phase 10c remains
next after review. No commit, push, installation or release.


## Phase 10c — direct OA topology and heat recovery, October 9, 2026

Phase 10b/V1 has progressed through review. Added independent
`openstudio-outdoor-air-connector` and `openstudio-heat-recovery-editor` bundles.
The connector attaches an explicitly configured direct intake at the main inlet
of a served unsplit loop without OA, or a sensible/latent HX on empty OA/relief
streams. The editor changes explicit existing HX settings in place. Curves,
controls, nodes and incoming references remain protected; 100% effectiveness
changes scale retained curve multipliers and are disclosed.

Attachment requires explicit performance, frost, availability, bypass and
outlet-control choices. Optional pretreat requires a verified translated mixed-air
reference; no fixed hot-air setpoint or template policy is inferred. Existing
outlet-control/economizer failures mark simulation unready. New and allowed
boundary/controller fields, normalized new-object identities, counts, removed
objects and the whole connection graph are checked after saving. Workflow-only
weather can populate empty climate metadata with an independent EPW check.
NLR-first routing, exact package SDK pin, report files, companion handling and
copied publication remain intact. New resources are staged for tracked-source
packaging; existing staged work and user review/probe files are preserved.

**109 targeted checks passed**: 55 operation, 31 manifest/import/resource and
23 host-adapter checks. Eight native VAV/CAV design-day cases verify recovery,
pretreat, economizer lockout and sequential new-intake/recovery attachment, with
no Severe/Fatal errors. Six moved owning bundles run doctor/inventory/preflight/
apply after deleting the original exports; four new exported skills validate.
The initial peak-recovery comparison did not establish useful recovery. W1's
paired coil-energy evidence below shows that pretreat avoids excess recovery
which otherwise becomes downstream cooling load in these fixtures.
Host Python 3.13.7 / embedded Python 3.12, OpenStudio 3.11.0 / EnergyPlus 25.2.
Full CI, Linux/Windows and annual/cold-climate defrost performance were not run.

Review map: work guide Phase 10c. Artifacts:
`outputs/heat-recovery-phase10c/evidence.json`, `verification/`, `exports/`.
Phase 10c is ready for review; terminals/reheat and plant-equipment operations
remain on the broader backlog. No commit, push, installation or release.


## Phase 10c W1 — uncontrolled recovery, October 9, 2026

Effective outlet-control-off settings now warn about heat-then-cool when direct
cooling equipment is downstream or a verified scheduled supply range lies below
verified served-zone heating minima. Covers attachment and in-place edits, even
when the edit only changes power. Impact records the risk and context; saved
validation rechecks it. This is advisory: settings and readiness remain unchanged.
Both skills explain explicit pretreat/bypass choices and why recovered watts are
not savings.

The native comparison sums thermal central cooling/heating and zone reheat energy
per design day, excluding warmup, and reports HX electricity and mixed-air
overshoot. Outlet control off adds 75.357 kWh winter cooling in VAV and
73.039 kWh in CAV, almost exactly its additional recovered heat. Central heating
is zero in both cases, reheat is essentially unchanged, and HX electricity is
2.4 kWh with either control choice. Pretreat avoids unnecessary recovery/cooling
in these fixtures. Thermal coil loads do not establish net HVAC input energy or
annual savings. Original doc conclusions have been corrected.

**100 targeted checks passed**: 69 operation checks and 31 manifest/import/
resource checks, including 16 new warning cases, six moved bundles and six native
checks running eight simulations. All native runs have no Severe/Fatal errors.
Both refreshed exports/resources and their affected skills validate. Formatting
and whitespace checks pass. Full CI, unchanged host-adapter tests and annual/
Linux/Windows native runs were not repeated.

Review/source map: work guide Phase 10c W1. Artifacts:
`outputs/heat-recovery-review-w1/evidence.json`, `verification/`, `exports/`.
Refresh host plugins and regenerate reviewed recovery plans. User review/probe
files remain unchanged; round-21 P1's former no-warning assertion is superseded.
No commit, push, installation or release.

## Integration review pause — October 9, 2026

The user paused further phase development to review real Claude integration
feedback. Investigation is recorded in `docs/SDK_INTEGRATION_SUMMARY.md` and
ignored `outputs/integration-review-20261009/`. No production scripts or tests
were changed for this review; the preceding implementation and user review files
remain intact.

Two original-model removal preflights are ready but differ in `removed_objects`:
four missing AvailabilityManagerAssignmentList objects get fresh IDs each load.
The cascade for the other removed objects is identical. Two preflights from the
user's normalized copy match. Both source hashes are unchanged. The native CLI
reproduction uses exact OpenStudio 3.11.0: ready preflight exits 0, apply exits 2
with the fresh-preflight mismatch, and no output is published. Normalization
stabilizes this case; whole-model semantic equivalence has not been independently
certified. The source declares 1.10.0, while the normalized copy is 3.11.0.
Repeated original loads generate 64 varying identities: 42 port lists, 16 object
lists, five availability lists and one water-heater sizing object. Only four
assignment lists affect this removal diff. Prefer a bundled, reported preparation
copy for this upgrade, keeping subsequent exact hash/report checks intact.

Manifest measurement: 332 resource copies, 86 unique sources across 16 owning
skills, 2,088,015 versus 546,522 logical bytes (73.8% duplicate script-resource
bytes). Resource-only deflated ZIP estimate: 679,413 versus 173,381 bytes.
This is not a whole-plugin or token-saving measurement. Recommended packaging
uses one plugin-local SDK library and fixed launcher paths from each skill.
The full plugin becomes the relocation unit; no runtime service is introduced.

Proposed order for review: A) bundled model preparation with version/hash/repair
provenance, stable repeated loading and bounded mismatch diagnostics;
B) shared exports and complete-plugin relocation; D) read-only graph/JSON/Mermaid
HVAC visualization with explicit air/water/VRF semantics and zone boxes; then
resume the existing equipment backlog. The review document lists tradeoffs and
acceptance criteria. These changes are proposals, not implemented features.
No plugin installation, commit, push or release.

### Failure-reporting addition — October 9, 2026

Added planned increment C, `report-openstudio-failure`, before visualizer D and
backlog E. The user explicitly selected automatic submission to the confirmed
GitHub destination `pnnl/openstudio-ai-harness`; the earlier GitLab mention is
resolved by that answer. Existing `github-issue-submitter` targets the plugin repo
and retains its separate preview-approved general-reporting contract.

The integration review now specifies mandatory orchestrator/agent routing for
unexpected failures, structured receipts and resume handling, sufficient sanitized
reproduction context, minimal synthetic reproducers where possible and explicit
incomplete-reproduction status when private data prevents one. Source models,
secrets and transcripts are excluded from automatic uploads. Capture precedes
workarounds; duplicate/retry failures produce one issue. Offline/auth failures keep
local drafts; reporting must function without OpenStudio/MCP and stay independent
of modeling readiness. Setup/doctor report optional GitHub reporting readiness.

This turn updates the development/review plan only. No reporting skill, orchestrator
change or external issue has been published or enabled yet. No live issue submission
is implied by planning the feature. Production implementation remains paused.

## Increment A ready for review — October 9, 2026

Implemented the user-requested preparation increment only. Central loader gates
older/current-handle-unstable models before all transaction/VAV planners; default
all-handle double loading stays on. Current broken assignment references return
bounded errors. New skill-local prepare_model uses VersionTranslator, original-
location companions, exclusive output publication and exact all-object raw-field
reload checks. Reports carry versions/hashes, bounded diagnostics/type counts and
blackboard-compatible original → prepared lineage. Apply retains exact checks
and now reports bounded differing paths/categories. All 16 owning skills and both
host exports include preparation resources/instructions. NLR-first and exact
OpenStudio 3.11.0 remain unchanged.

1,357 unique tests passed across all 40 test modules: 347 SDK core/preparation,
596 equipment, 216 air-side/native sizing, and 198 harness/adapter/MCP checks.
The final preparation file passed 51/51. The main harness batch's two native MCP
skips passed when rerun with the installed CLI; no test modules were omitted.
Two expected SDK-doc-override warnings remain. Both exports and 32 exported
skills validate. Formatting and non-fixture whitespace checks pass; genuine
upstream OSMs retain two trailing-blank-line warnings to preserve exact hashes.

Largest fixture: 481,106 source bytes, prepared 503,258 bytes / 892 objects;
five paired timings measured 38.2 ms single load vs 78.5 ms guarded load (+40.3 ms).
Native 3.11.0 preparation and partial removal leave nine assignment lists; moved
CSV/weather/measure companions, repeated process plans, idempotence, stale/
tampered plans and genuine injected object/value changes are covered.

Review and exact commands: docs/SDK_INTEGRATION_SUMMARY.md; work guide has
a linked increment-A section. Evidence/logs/refreshed exports are in ignored
outputs/model-preparation-increment-a/. Historical fixture provenance/licenses
are in tests/fixtures/. New resources/fixtures are staged solely to satisfy the
existing tracked-manifest test. No commit, push, installation or release.
User docs/reviews/ files are untouched. Stop here for A review; B/shared packaging,
C/failure submission and D/visualization remain unimplemented. Previous user docs
edits are preserved. Mac-only evidence; no new live agent sessions or cross-platform
runs were performed.


### Increment A review Q1/Q2 addressed

Extended the shared missing-list guard to PlantLoop as well as AirLoopHVAC,
retaining bounded typed diagnostics. Added a native plant missing-list case.
Moved the native preparation test's optional jsonschema import below its CLI
availability check; a regression simulates both dependencies being absent.
Documentation now describes default guard overhead as about one extra model load,
with 40.3 ms retained only as evidence for the measured 892-object fixture.

Focused checks: 75 passed (53 preparation, 22 plant/removal), including native
execution and relocated bundles. Both refreshed host exports validate; Black
and whitespace checks pass. Full-suite baseline remains the preceding 1,357-test
run; it was not repeated for this follow-up. Results/exports are in ignored
outputs/model-preparation-q1-q2/. No commit, push, installation or release;
docs/reviews/ remains untouched. Stop for review; increment B has not started.


## Integration increment B ready for review — October 9, 2026

Implemented one plugin-local SDK library with fixed owning-skill launchers for
both hosts. Canonical modeling sources remain unchanged; manifest `plugin-sdk`
scope and positive `sdk_library.max_bytes` enforce explicit resources and a 1 MiB
budget. Launchers resolve only their complete plugin, verify payload hashes and
return bounded `plugin_incomplete` failures before SDK/model execution if missing,
mismatched or detached. No service, utility skill or separate Python package is
introduced. Git-based plugin installation, setup/doctor, exact 3.11.0, NLR-first,
A's preparation gates and exact transaction checks are preserved.

Exports contain 78 canonical Python/JSON payload files plus generated integrity/
size metadata, and 66 launchers across 16 owners. SDK resources: 2,445,693
comparable former owner-copy bytes vs 686,836 shared-resource bytes excluding the
size report (71.9% reduction). Whole-plugin totals excluding that report: Claude
934,236 bytes / 239 files; Codex 1,655,433 bytes / 237 files. These are fresh
marketplace exports, not compressed-download or AI-token measurements.

Verification: 272 unique targeted checks passed (236 packaging/manifest/import/
doctor/preparation/adapters/CLI/archive; 36 native relocated modeling). Complete
plugins were moved to paths with spaces and executed from unrelated CWDs; all
public launchers, source-checkout deletion, library damage and detached skills
are covered. Both marketplace exports and 32 owning-skill documents validate.
The archive test initially failed because sandboxed PyPI was unavailable; its
network-enabled isolated-build rerun passed. Built wheel includes
harness/plugin_sdk.py. Formatting and whitespace checks pass.

Full equipment/simulation suites were not rerun; modeling Python sources did not
change. Prior A full baseline remains 1,357 checks plus the two Q follow-ups.
No native Linux/Windows or live-agent runs. Review guide:
docs/SDK_INTEGRATION_SUMMARY.md; logs, exports and evidence:
outputs/shared-sdk-increment-b/. No commit, push, plugin installation or release;
docs/reviews/ untouched and all preexisting changes retained.

Stop for B review. Next increment C is automatic sanitized failure reporting to
pnnl/openstudio-ai-harness, then D read-only HVAC visualization, then equipment E.
Neither C nor D is implemented by this turn.


## Integration increment C ready for review — October 9, 2026

B is approved. Implemented report-openstudio-failure for both hosts, automatic
sanitized submissions to fixed pnnl/openstudio-ai-harness, durable local receipts,
copy-ready drafts, duplicate lookup and one-POST uncertain-state handling. Uses
existing gh authentication; no reporting package/service or OpenStudio import.
A verbatim independent recovery helper intentionally works even if sdk/ is lost.
Captured payloads exclude raw models/companions/transcripts and explicitly mark
private-model reproducers incomplete. Supported Markdown bug templates and labels
are mapped; unknown forms/requirements retain drafts. Security holds and project
opt-out never contact GitHub. Local locks and durable submitting state prevent
repeat POSTs in one state directory; no global cross-machine guarantee is made.

Shared transaction, VAV and preparation error handlers save receipts without
changing source/plans or masking original failures. Output-publication status is
recorded accurately after report errors. Both orchestrators and all 16 SDK owning
skills route unexpected failures to the reporter before recovery; resume processes
pending receipts. Expected readiness/input/preparation/stale outcomes are excluded,
with explicit user bug reports still eligible. Setup/doctor expose optional
reporting readiness and the selected automatic policy. Existing 3.11.0 pin,
NLR priority, preparation and exact transactions are unchanged.

Verification: 451 unique checks passed (280 contracts/reporting/adapters/CLI,
170 modeling regressions, 1 archive). Final reporter suite: 45/45, including
native injected faults through both public remover launchers, unchanged source
hashes, recorded required/observed/source 3.11.0 and plugin/bundle identities.
Relocated standalone reporters work with sdk/ deleted. Both fresh marketplace
exports and 34 affected owning/reporter documents validate; formatting/whitespace
pass. Two expected SDK-doc warnings. All issue-writing tests used mocked transport
or disabled policy; no live issues submitted. Archive build only resolves temporary
pinned build dependencies and does not install a plugin or publish artifacts.

Review guide: docs/SDK_INTEGRATION_SUMMARY.md. Logs/exports/native receipts
and evidence: outputs/failure-reporting-increment-c/. Full unrelated equipment,
annual-energy, MCP/live-provider and native Linux/Windows suites were not rerun.
No live AI host session. New manifest sources are staged for the existing tracking
check, without commit/push/plugin installation/release. docs/reviews/ untouched;
all preexisting changes preserved. Stop for C review; next D is read-only HVAC
visualization, then remaining equipment E. D has not been implemented.

## Increment C review fixes C1/C2 ready — October 9, 2026

C1: public exception messages now use fixed error codes/templates, including a
generic fallback. Public tracebacks carry only up to 12 relative plugin
file/function/line locations verified against shipped Python source; source
lines, locals, external frames and raw exception text are excluded. Original
message/traceback stay in a separate private.json file, never consumed by the
submitter. Receipt format 2 prevents old regex-only receipts from contacting
GitHub and preserves their submitted/uncertain identity for manual reconciliation.
Fingerprinting retains a verified plugin-location digest without model names.
Private aliases remain stable across repeated sanitization.

C2: the reporter, both orchestrator policies, README, generated installation and
setup/doctor/repair guidance and doctor output explicitly explain that issues are
created under the user's own authenticated GitHub account. No username is collected.

Follow-up verification: 242 targeted tests passed, no skips (60 reporter,
182 packaging/manifest/resource/import/doctor/adapter/runtime-helper/CLI).
Five genuine bundled error paths use a synthetic 3.11.0 model with company,
address and email names absent from private-value hints. Those values remain
local and never occur in public receipts/drafts/mocked POSTs. Both native public
remover launchers preserve source hashes. Fresh marketplace exports and nine
changed SKILL documents validate; shared SDK resources are 736,717 bytes within
the 1 MiB budget. Two expected SDK-doc warnings. Black/whitespace checks pass.
No live issues, commit, push, installation or release. User docs/reviews/ and
all preexisting changes are preserved. Model transaction logic is unchanged;
prior model/archive batches and full equipment/annual/live-provider/native
Linux/Windows suites were not repeated.

Review guide: docs/SDK_INTEGRATION_SUMMARY.md, C1/C2 follow-up section.
Logs, fresh exports, synthetic fixtures/native receipts and evidence.json:
outputs/failure-reporting-c1-c2/. Stop for C review; D remains unimplemented.


## Increment D ready for review — October 11, 2026

Added openstudio-hvac-visualizer with read-only graph extraction, deterministic
Mermaid/Markdown overview and per-system views, full zone index and exact-handle
selection. Both exports use fixed launchers into one shared sdk/ payload; NLR
priority, the 3.11.0 pin, preparation and exact transaction checks are unchanged.
Source/companions are never saved by visualization. Exact in-memory state and
source-hash checks precede exclusive publication. Full private labels/topology
remain in local artifacts, excluded from automatic public reporting.

Physical edges retain every OS_Connection handle, direction and numeric port.
Current endpoint fields are verified through explicit references to the same
connection; legacy port discrepancies retain both coordinates and warn. Coil air/
water and heat-recovery streams render separately. Controls, containment, VRF and
zone membership use dashed relationships. Embedded air paths remain unexpanded;
unsupported ports remain separate views. Every zone is indexed, including zone
only equipment, ideal loads, plenums and unserved zones. No sizing/control or
operational correctness claim is made.

317 unique targeted tests passed, no skips: 136 visualizer/reporting/packaging/
manifest/resource/import, 98 preparation/doctor, 82 adapters/runtime-helper/CLI,
one archive-content test. Includes 21 visualizer cases and native execution of
both relocated public launchers. Two expected SDK-doc warnings. Archive check
initially failed fetching its build dependency under network restrictions and
passed on the isolated network-enabled retry. Both final marketplace exports and
five affected SKILL documents validate; Black and whitespace checks pass.

The original version-1.10.0 integration model first returned requires_preparation.
The exported bundled preparation operation wrote a separate 3.11.0 copy. Both
native exports produced byte-identical graphs: 4 air / 4 VRF / 1 plant loops,
42 zones, 745 nodes, 884 edges, all 522 native connections. Observed 184 legacy
endpoint port discrepancies, 74 unexpanded embedded objects, one opaque water-use
port view. Visualization took 1.475/1.453 s including startup/guarded loads, with
stdout below 3 KB. Original and prepared hashes stayed unchanged. Shared resources
are 795,050 bytes excluding size report, within the 1 MiB budget.

Review guide: docs/SDK_INTEGRATION_SUMMARY.md. Logs/exports/private evidence:
outputs/hvac-visualizer-increment-d/; final native evidence in native-final/.
No live AI-host session, SVG/HTML rendering, annual simulation, full unrelated
MCP/equipment or native Linux/Windows run. No commit, push, plugin installation,
release or live issue submission. New manifest sources are staged for the tracking
check; docs/reviews/ and preexisting user changes are preserved. Stop for D review.
After approval, settle any desired diagram follow-up before remaining equipment E.


## Increment D equipment-view refinement — October 11, 2026

User requested physical-equipment diagrams and three color groups. Mermaid now
hides SDK nodes/port lists/connections, abstract loop boundaries, virtual mixers/
splitters, adiabatic routing pipes and controls. Equipment and rectangular zones
remain: zones green, air-side secondary equipment blue, water-side primary
equipment orange. Exact graph.json is unchanged. equipment_graph.json maps each
condensed flow to a contiguous path of original edge IDs; contraction stops at
physical components, preserves branches and keeps separate coil/recovery circuits.
Dashed containment/service/VRF links remain associations. Unknown embedded internal
flow remains unexpanded. Overview-only folding reduces unconnected contained
components; per-system views retain them. No handle/port suffixes clutter labels.

82 affected tests passed, no skips: 27 visualizer, 55 packaging/manifest/resource/
import. Both relocated native exports and two affected SKILL documents validate;
Black/whitespace pass. Both fresh native exports inspect the existing prepared
integration copy into identical equipment JSON; detailed JSON is byte-identical
to the previous D output, all 522 native connections intact, source unchanged.
Sample air loop: 131 → 24 boxes; Mermaid text 26,071 → 5,013 bytes. Shared SDK
resources: 799,998 bytes excluding packaging report, within 1 MiB.

Updated local diagrams/exports/evidence/logs:
outputs/hvac-visualizer-equipment-review/. Review contract and commands:
docs/SDK_INTEGRATION_SUMMARY.md, equipment-view refinement section. Older D
artifacts remain historical. Unchanged preparation/doctor, adapters/CLI and archive
batches were not rerun; no annual/live-agent/native Linux/Windows/SVG check. No
commit, push, installation, release or live issue submission. Preexisting changes
and docs/reviews/ are preserved. Stop for D review before additional equipment.

## Increment D airflow direction refinement — October 11, 2026

Closed-cycle Mermaid layout obscured correct airflow arrows. Supply/intake now
reads left to right in the upper lane; return/relief/exhaust reads right to left
below it. Fan roles derive from connected OA/loop boundaries. Actual equipment
order remains, including blow-through fans before coils. Repeated OA/zone boxes
are views of the same objects. Lane-local IDs and invisible links between whole
subgraphs preserve LR/RL directions and stack the views. Three equipment colors
remain; routing nodes and controls remain hidden. Detailed graph.json is unchanged.
Equipment JSON adds air_paths and fan_roles without changing endpoint/evidence
checks. Unknown paths stay unclassified rather than receiving an assumed role.

85 affected tests passed, no skips (30 visualizer, 55 packaging/manifest/resources/
imports). Final stacking change reran all 30 visualizer cases, including relocated
native commands for both hosts. Native role/accessor, no-OA, zone exhaust and
blow-through cases pass. Both final exports validate; Black/whitespace pass.
Both native exports produced identical equipment JSON and every Mermaid file;
raw JSON remains byte-identical to prior D output, all 522 connections retained.
Original/prepared hashes unchanged. Sample Fan 5 is supply, Fan 6 return.

Final local artifacts: outputs/hvac-visualizer-direction-review/final/. Sample
air_loop_4c488bcfc733444086d90ae01d984005.md and .mmd.svg/.mmd.png are under
claude-topology/. A temporary local Mermaid 11.12.0/headless Chrome verification
with blocked network checked all 32 airflow arrow directions and supply-above-
return placement; PNG visually inspected. No new runtime/render dependency.
Review contract/evidence: docs/SDK_INTEGRATION_SUMMARY.md, airflow refinement.
Unchanged prep/doctor, adapters/CLI and archive checks not repeated. No live agent,
annual/native Linux/Windows run, commit, push, plugin installation, release or
live issue submission. docs/reviews/ and preexisting changes preserved. Stop for D review.

### Sample refresh for visual inspection — October 11, 2026

Regenerated all 52 per-group Mermaid/Markdown artifacts from the existing prepared
integration copy using the exported launcher (its renderer matches current source).
Rendered nine system samples: four air loops, four VRF systems and DHW-Loop.
Local SVG/PNG previews, cropped to diagram bounds, and gallery:
outputs/hvac-visual-inspection-20261011/inspection.html (also inspection.md).
All 128 air-loop arrows satisfy rendered LR/RL checks and all four supply lanes
sit above return. Representative air/water/VRF previews inspected visually.
Detailed graph is byte-identical to prior output; prepared source hash unchanged.
inspection-report.json and render.log record the artifact checks. No implementation
changes or automated suite rerun; this request only regenerates review artifacts.
No commit, push, installation, release or edits to docs/reviews/.

## Increment D connected air/DHW refinement — October 12, 2026

Current presentation replaces separate lanes with one connected LR air diagram:
supply/intake left → terminals/zones once → return/relief/recovery right. OA boxes
are intake/mixed and return/relief views of one assembly; recovery has separate
streams with the same handle. Verified outdoor intake/exhaust boundaries appear
as open arrows with exact evidence, never as node boxes. Zone air state points and
recirculating VRF/PTAC exhaust-list connections do not imply outdoor exhaust.

DHW floating self-loop proved to be the path through supply and demand bypasses,
not mains/district water. Three routing-only condensed bypass paths are tagged and
retained in equipment JSON, omitted from the drawing with a note. WaterUseConnections
has one water view; pump → heater → water use and explicit return to pump remain.
Mermaid's correct three-dash start-arrow syntax was verified by native rendering.

88 unique affected tests passed, no skips (33 visualizer + 55 packaging/resources/
manifest/import). Final corrections reran all 33 visualizer cases with relocated
native launchers. Both exports validate and produce identical artifacts. Raw model
nodes/edges/ports/groups/load provenance and all 522 connections unchanged; the
obsolete opaque WaterUseConnections warning clears. Source/prepared hashes intact.
Current projection: 260 views, 359 edges, eight outdoor markers, three bypass paths.
Nine samples render locally with Mermaid 11.12.0; 136 air/boundary plus three DHW
edge positions pass. Story 1/DHW PNGs inspected. No added runtime dependency.

Current gallery/evidence: outputs/hvac-visual-refinement-20261012/review/inspection.html.
Full review contract: docs/SDK_INTEGRATION_SUMMARY.md, October 12 refinement.
Earlier directories contain historical/intermediate views. Unchanged prep/doctor/
adapter/archive batches not repeated; no annual/live-agent/native Linux/Windows
run, commit, push, installation, release, live issue or docs/reviews/ edits.
Stop for visual review before additional equipment work.

## Increment D review D1–D3 — October 12, 2026

OA and mechanical-ventilation controllers now belong to the owning air loop via
stored references. Hidden-only groups stay in JSON but create no empty diagram.
VRF drawings fold contained coils/fans without external flow into indoor labels;
full JSON components remain. Default type-plus-number labels show the type once,
custom names remain, and shared air-loop/VRF zones name their other systems.

100 unique affected tests passed, no skips: 45 final visualizer cases, 55
packaging/manifest/resource/import. The broader 98-case run preceded two added
cases; the complete final 45-case visualizer run passes. Both native relocated
host tests, final exports and SKILL validations pass; Black/whitespace pass.
Genuine legacy multiloop regression: 20 owned controllers, 20 diagrams, no orphan
group. Actual integration exports are identical, retain 522 connections and
original node/edge fields (group ownership intentionally changes), and produce
51 diagrams. Original/prepared source hashes unchanged. SDK resources 816,079
bytes excluding packaging report, under 1 MiB.

Nine native Mermaid 11.12.0/isolated-Chrome previews render; 139 direction/position
checks pass. Story 1 air/VRF and DHW PNGs inspected. Nine-unit VRF: 46 → 19 boxes,
5,366 → 1,742 px tall. Synthetic native 40-terminal fixture: 81 boxes, 6,046 px;
height remains linear and pagination is not implemented. No renderer dependency.

Current gallery/exports/native logs/evidence/stress sample:
outputs/hvac-visual-review-d1-d3-20261012/review/inspection.html.
Contract and reviewer commands: docs/SDK_INTEGRATION_SUMMARY.md, D1–D3 section.
Earlier galleries are historical. Unchanged preparation/doctor/adapter/archive
and unrelated equipment checks not repeated. No annual/live-agent/native Linux/
Windows run, commit, push, installation, release, live issue or docs/reviews/ edits.
Stop for review before equipment backlog work.

## A–D readiness confirmation — October 12, 2026

Checked the integration checklist and recorded evidence at the user's request.
All A–D implementations and requested Q1/Q2, C1/C2 and D1–D3 follow-ups are
addressed. No known implementation blocker remains to resuming equipment E.
Updated stale overview text that still described C/D as planned. Latest evidence
remains 100 unique affected tests passed, no skips, with identical native host
artifacts and all 522 connections retained; no new test run was needed for this
documentation-only status correction. Large VRF diagrams still need scrolling;
pagination is not part of the completed increment. No release readiness claim,
commit, push, installation or new equipment implementation. User docs/reviews/
remain untouched. The next equipment operation has not begun; recommend bounded
in-place zone-terminal airflow/reheat editing before terminal replacement.

## Documentation consolidation — October 13, 2026

Created docs/SDK_INTEGRATION_SUMMARY.md from the five untracked A–D/investigation
guides and the 21 untracked Markdown review notes. It preserves final contracts,
review resolutions (including the corrected Autosize-DCV premise), verification
counts/limits, native evidence locations, reproduction commands and the equipment
backlog. Removed the five untracked implementation guides after checking their
source hashes against the initial inventory. Updated README, docs/README and
tracked guide/handoff references to the surviving summary.

The user subsequently authorized removing all consolidated files under
docs/reviews/, superseding the earlier preservation instruction. All 34 files
are retired: 21 untracked Markdown notes, the tracked round-12 migration review
and 12 historical Python probes. The summary now includes a probe-to-maintained-
suite map and the round-12 migration verification details. The modularization
guide's obsolete probe reference points to that summary. No review cleanup is
pending; the directory is removed.

Tracked living guides and their preexisting edits, maintained tests, production
code, fixtures, ignored native evidence, git index and installed plugins are
preserved. Documentation-only checks: consolidated-summary links/anchors and
probe-suite targets pass, the review directory is absent and git diff --check
passes. No model tests rerun. Ready to resume the next equipment phase.
