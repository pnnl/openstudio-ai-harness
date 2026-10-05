# Skill-bound OpenStudio SDK scripts: development and review summary

Consolidated October 5, 2026. Branch: `enhance_skills_scripts`.
Scope: phases 1–5, the original 13 findings, follow-up reviews N1–N10/R1–R6/S1–S3,
the final weather-warning correction, and the plant/removal extension below.
This document replaces the development
plan, standards trace, evaluation reports, verification JSONs and review/probe
files from this development round. Historical measurements are identified below;
they are not a fresh full-suite or release certification.

## Decisions and architecture

The goal is to reduce agent context and repeated script drafting while making
model edits reproducible and reviewable. Reviewed Python SDK scripts ship with
the skill that owns the operation. Claude Code and Codex execute them directly
through host tools; supported VAV edits do not pass through the modeling MCP
runtime or measure registry. Shared helpers have one canonical source under
`skills/sdk_scripts/` and are copied into owning bundles by the manifest/adapters.
Normal agent runs read the skill and argument contract, rather than implementation
code or multiple SDK wiki packs.

Provider order remains: configured, compatible NLR OpenStudio MCP first; a
specific local modeling skill after provider fallback; bespoke SDK programming
only for requests no specific skill covers. A failed covered operation requires
diagnosis rather than bypassing its checks with generated code. Simulation,
results and active provider transitions retain their separate workflows.
Nine legacy VAV object-level child skills and their generation machinery were
removed. The top-level VAV wrapper and parent remain supported.

The user explicitly accepted a **package-wide OpenStudio 3.11.0 pin**, including
`pyproject.toml` and `uv.lock`, rather than a per-VAV-bundle pin. The canonical
script contract is `skills/sdk_scripts/compatibility.json`. Doctor discovers
installations but selects only the required CLI and matching embedded SDK;
explicit executable paths never silently fall back. Build metadata is allowed,
other releases/prereleases are rejected, and modeling entrypoints independently
check the executing SDK before reading the model. Doctor uses standard-library
host Python, isolates inherited Python paths, and defaults to 30 seconds per probe
with a positive `--probe-timeout` override.

A package/plugin release must identify its tested SDK release. Changing that
release requires coordinated contract, dependency/lock, documentation and release
matrix updates plus native verification of both exports. Updating the contract
alone is insufficient. Newer NLR models require a compatible provider or matching
package; local scripts do not downgrade them. Best-effort MCP loading for
inspection is distinct from accepting a model for pinned SDK editing.

## Completed phases

| Phase | Deliverable | Recorded verification |
| --- | --- | --- |
| 1 | Manifest v3 optional nested/shared resource export, bytes/modes preserved, unsafe paths/escapes/collisions rejected, both host adapters | 51 focused tests; relocated scripts run without the runtime/source tree |
| 2 | Standalone doctor, compatibility contract, executing-SDK guard | 96 focused tests; both exports accept 3.11.0 and reject explicit installed 3.8.0 |
| 3 | Read-only inventory/preflight, strict input schema, exact object selectors, resolved hash-bound plan and assumptions | 150 focused tests; relocated preflight preserves inputs and creates no OSM |
| 4 | VAV creation, apply transaction, independent saved-model validation and native sizing | 205 focused tests; 32 heating/cooling/reheat combinations; hydronic and electric/DX native sizing |
| 5 | Compact routing, retired legacy VAV routes, relocated export evaluation and context estimates | 250 focused tests; 9 exported skill frontmatter checks; four host/fixture native cases |

Counts describe different historical selections of tests and must not be added
as unique coverage. The user selected local evaluation and context-size estimates;
no live Claude/Codex agent runs, billed-token measurements or retry comparison
were performed.

## Final VAV transaction and approval contract

1. Run doctor and use its verified executable.
2. Inspect the model and create a strict configuration using exact names/handles.
   Select DX and `prototype_vav_v1` only after an explicit human choice; prior
   explicit selections persist. The JSON approval fields are declarations, not
   technical proof of human authorization.
   If defaults are undecided or declined, use partial preflight's `assumption_review`
   to present schedules/fan, ventilation/airflow, temperatures/sizing and equipment/
   controls as a compact form/table. Its values come from canonical profile constants,
   preserve user inputs and distinguish editable settings from fixed controls.
   Declining defaults leads to review/adjust, not cancellation. Proposed values do
   not select the profile or authorize apply. Unsupported fixed-control changes
   stay pending; they need additional bundle development/provider coverage.
3. Preflight resolves references, validates relationships, inventories resources,
   records approved assumptions and source/resource hashes, and saves the complete
   report directly with `--report`. Inventory success alone is not `ready: true`.
4. Apply consumes the unedited ready report, checks the SDK and source hash,
   validates plan shape, re-resolves/re-plans and compares the approved plan.
   Every behavior control is consumed by creation and the independent validator;
   descriptive profile notes remain in the assumption ledger separately.
5. Build in memory, check SDK setter outcomes, stage and reload, validate actual
   settings/topology/plant demand connections/counts, explicitly check external
   files, and forward-translate to EnergyPlus. Translation errors or unresolved
   workflow-attached ExternalFiles block publication; warnings are retained.
6. Recheck the source before exclusive publication. Original input and existing
   or concurrent output files are preserved. Repeating apply refuses the existing
   destination. Return compact results and persist full evidence.

Assumption-review update: 144 impacted preflight/apply/report/Claude/Codex adapter
tests passed, including a regression that unaccepted proposals preserve model and
configuration bytes, do not enable controls or publish an output, and retain full
review details on disk with compact stdout. This adds an agent-guided review
workflow, not a browser form or full fixed-control customization interface.

Preflight requires unserved target zones with spaces and dual thermostat heating/
cooling schedules. It checks air-temperature ordering, terminal versus system
minimum airflow, finite positive plant delta, hot-water return versus coil outlet
air and chilled-water supply versus cooling air. Water plants need appropriate
supply equipment, actual circulation pumps and outlet setpoint managers; presence
checks do not prove capacity or dynamic control adequacy. Pump types match
`OS_Pump_`/`OS_HeaderedPumps_`, excluding heat pumps. Water heaters and temperature-
source/user-defined plant components are recognized.

Return plenums use `canBePlenum()` plus equipment/thermostat/loop association
checks. A fresh eligible zone is accepted; a zone already serving another loop
or also selected as a target is rejected. `isPlenum()` alone is unsuitable because
it becomes true after a plenum object is attached.

Publication fsyncs staged models/reports before exclusive hard linking. An
exclusive-create/copy fallback handles filesystems without hard links and fsyncs
the destination; it cleans only partial files it owns. That fallback is visible
to concurrent readers while copying. Directory/cloud-sync durability and real
network shares remain unverified. Missing-drive traversal stops at a self-parent
root instead of looping forever.

Full JSON reports are written by preflight/apply; normal operation does not depend
on parsing the last stdout line. `report.py` remains a recovery utility. Candidate
summaries cap each category at eight entries, include totals/truncation markers,
and support `--candidate-filter`; full inventories remain in saved reports.
Top-level workflow patches append/deduplicate `completed_steps` and `assumptions`;
nested lists replace, explicit assumption events retain duplicates, and a new
workflow resets history.

## Openstudio-standards trace and engineering boundary

Reference checkout: `/Users/xuwe123/github/openstudio-standards/lib/openstudio-standards`,
commit `8bad404ef113019661fc0c14274a3554234219f7`. Scripts do not depend on that
checkout at runtime. The requested dispatcher is
`prototypes/common/objects/Prototype.Model.hvac.rb:21–92`; the generic inner builder
is `prototypes/common/objects/Prototype.hvac_systems.rb:1830`.

The outer dispatcher resolves zones/plenums through spaces, reuses or creates
HW/CHW plants, optionally creates a condenser loop, and calls `model_add_vav_reheat`
with water reheat and 4 inH2O fan pressure. The pilot implements the inner generic
VAV builder with explicit existing plants. It excludes automatic boiler/chiller/
tower/pump/HX creation, HVAC replacement and later template/compliance processing.
Independent plants for heating/reheat, electric main heat with water reheat, and
central heating `None` are explicit extensions. Ruby defaults missing central
heating to gas; `None` is not equivalent.

| Traced branch | Methods/files under the reference root | Assumptions and boundary |
| --- | --- | --- |
| Dispatch | `Prototype.Model.hvac.rb`: `model_add_hvac`, `model_get_zones_from_spaces_on_system`, `model_get_return_plenum_from_system` | Our exact zone selectors block missing/duplicate references rather than logging and continuing |
| HW plant | `Prototype.hvac_systems.rb:42`, `Prototype.BoilerHotWater.rb:22` | 180 F supply/20 R delta, variable pump by default, scheduled outlet setpoint, NaturalGas boiler; deferred plant creation |
| CHW plant | `Prototype.hvac_systems.rb:228`, `Standards.PlantLoop.rb:21/57`, `Standards.PumpVariableSpeed.rb:10` | Generic 44 F supply/10.1 R delta; primary/secondary variants and pump curves; preserve selected existing controls |
| CW/chillers | `Prototype.hvac_systems.rb:480`, `Prototype.CoolingTower.rb:9/109`, `Standards.Model.rb` curve/object lookup | WaterCooled tower/condenser choices, weather/DDY/fallback wet bulb, COP/PLR/sizing assumptions; excluded from pilot |
| Optional economizer | `Prototype.hvac_systems.rb:6640` | Waterside economizer defaults to none; integrated/nonintegrated HX branches deferred |
| Schedules/sizing | `Standards.Model.rb:2772/5759`, `schedules/create.rb:18/113`, `Prototype.hvac_systems.rb:7`, `Prototype.SizingSystem.rb:9` | Ruby schedule lookup/factory and design defaults traced; our explicit existing schedules must resolve and have suitable limits |
| Fan | `Prototype.Fan.rb:76/90/130/200`, `Prototype.FanVariableVolume.rb:104/154`, ASHRAE fan/curve JSON | Fan selection, shared variables and curve coefficients traced; pressure converts from inH2O despite higher-level Pa comments |
| Coils | `Prototype.CoilHeatingWater.rb:17`, `Prototype.CoilHeatingGas.rb:13`, `Prototype.CoilHeatingElectric.rb:13`, `Prototype.CoilCoolingWater.rb:15`, `Prototype.CoilCoolingDXTwoSpeed.rb:13` | Water ratings use captured plant temperatures; gas/electric/DX defaults limited to the reviewed generic branches |
| Preheat/terminals | `Standards.Model.rb:6101`, `thermal_zone/thermal_zone.rb:633/699`, `Prototype.AirTerminalSingleDuctVAVReheat.rb:11`, `Standards.AirTerminalSingleDuctVAVReheat.rb:69` | Generic preheat callback is a no-op; PRM preheat and template/building damper overrides are excluded |

Actual supply flow order is **OA → cooling → heating → fan → supply outlet**;
Ruby inserts fan/heating/cooling/OA at the inlet, reversing insertion order.
Saved validation checks the actual order.

Key generic defaults, applied only through the approved plan:

- Sensible system sizing; autosized OA; Coincident unless configured; ZoneSum;
  DesignDay heating/cooling; heating system airflow ratio 0.3; all-OA flags false.
- Preheat/precool/main heat/main cool/zone heat/zone cool: 45/55/55/55/104/55 F;
  design humidity ratios 0.008/0.0085 in their respective roles; scheduled SAT.
- Variable-volume fan: total efficiency 0.62, motor 0.9, motor-in-air 1,
  pressure 4 inH2O = 996.35564 Pa, power minimum fraction 0.25;
  coefficients 0.040759894, 0.08804497, −0.07292612, 0.943739823, 0.
- HW coils use plant exit and exit−delta ratings; controller minimum flow zero,
  convergence 0.1. CHW coil is CrossFlow with Reverse controller and autosizing.
- Gas efficiency 0.80 with zero specified parasitics; electric efficiency 1;
  approved DXTwoSpeed uses pinned SDK default curves.
- FixedMinimum OA, autosized minimum flow, ZoneSum mechanical ventilation;
  economizer choices/SDK limits are disclosed in assumptions, not climate claims.
- CycleOnAny availability, 1800-second night cycle. Reheat terminals use Constant
  0.3 minimum unless configured, Normal heating action and 40 C maximum reheat.
  No-reheat terminals preserve the existing zone heating method/temperature.

Template damper minima vary by vintage, coil type and building (often 0.2/0.3,
with special-zone exceptions). Later standards processing can change fan settings,
OA, damper minima and SAT reset. This generic construction profile makes no
ASHRAE compliance or ventilation-adequacy claim.

## Companion resources and runtime loading

Portable skill outputs use `<output-stem>/workflow.osw`, relative weather paths,
hashed copied resource names and `file_paths: ["files"]`. Lookup uses native
`WorkflowJSON.findFile/findMeasure`, not custom OpenStudio search rules. Copy only
referenced weather, ExternalFiles, valid workflow measures and supported file
arguments; deduplicate destinations and cap referenced copying at 256 MiB with
streamed hashes. Do not scan arbitrary neighboring libraries or copy stale workflows.

Skip/report VCS/cache metadata such as `.git`, `.hg`, `.svn`, `.github`, `.gitkeep`,
`.DS_Store` and `__pycache__`. Secret patterns target `.env*`, `.pem`/`.key`,
`id_rsa*`/`id_dsa*`/`id_ecdsa*`/`id_ed25519*`, exact `credentials`/`credentials.json`.
Ordinary `id_schedule.csv` and `credentials_report.pdf` are allowed.

Missing weather, unavailable measures or unresolved nonempty workflow input
arguments warn and set `simulation_ready: false` without blocking VAV editing;
references are retained. Empty/output/report/directory arguments are not required
as input files. Supported file-argument conventions are `_file`, `_path` and
`file_name`; other conventions require separate inspection. Required model
ExternalFiles must resolve. Resources hashed as available during preflight must
remain unchanged at apply. Version sniffing reads a bounded byte prefix with
tolerant decoding; non-UTF-8 OSMs are left to the SDK loader.

**Portable CSV output contract:** bare ExternalFile names may require the companion
workflow. Apply checks both a plain VersionTranslator reload and a workflow-attached
reload. Attached resolution must pass; plain-load limitations are reported as
`requires_companion_workflow: true`. Use `openstudio.model.Model.load`, explicitly
attach the workflow or run it, and keep the OSM and companion folder together.
ForwardTranslator alone can miss an empty Schedule:File filename.

**Internal runtime contract:** snapshots/jobs copy CSVs into retained workspaces
and write absolute hashed references so OSM-only measure inputs/outputs remain
usable. Original source files can then be deleted. Internal paths rely on retained
workspace resources and are not relocation-portable. Source measures are not
re-executed during simulation staging; the runtime writes its own workflow.

`model_load` performs CSV enrichment best-effort. Failures restore exact plain
snapshot bytes, discard partial companions and persist `resource_warnings` so
inspection/repair remains possible. Non-CSV models bypass Python SDK resource
loading, including synthetic newer versions and malformed companion workflows.
Fatal copy/quota failures clean the workspace. Sizes are checked before copying;
content hashes disambiguate equal basenames and remain stable across repeated
copies. Load/clone revisions hash the managed OSM; `original_source_sha256`
records the original input separately.

The final weather correction separates `weather_warnings` from CSV
`resource_warnings`, persists both through clone/restart and returns both at load.
Only CSV failures block simulation. An explicit `options.epw_path` or later
`model_set_weather` can supply weather despite a load-time weather warning;
actual weather existence and simulation quotas are still checked. Weather copying
is separate from CSV enrichment and is not duplicated during simulation.

## Review outcome and verification history

| Review/checkpoint | Final disposition | Recorded checks |
| --- | --- | --- |
| Original C1–C3, H1–H5, M1–M5 (13 findings) | Plenums, plan-derived controls, approvals, cross-checks, translation, history, contract references, reports, companions, missing drives, bounded context and publication addressed; C2 pin accepted by user | 273 focused; MCP 8 passed/2 optional skips; four native export cases |
| Follow-up N1–N10 and partial C3/H2/H4/M5 | Native lookup, referenced-only copying, metadata handling, portability, byte-safe sniff, top-level history, fsync, plant coverage, tracked manifest sources and hygiene addressed | 299 impacted; 41 nearest rerun; three native sizing cases plus four export cases |
| Round 3 R1–R6 | Explicit CSV loading contract/runtime retention, optional workflow-input warnings, narrow secret rules, real pump types, no explicit parent lookup, tracking test skips without Git | 231 impacted including 12 new regressions; four native exports; 28 nearest rerun |
| Round 4 S1–S3 | Absolute internal CSV paths, best-effort load, newer non-CSV bypass, collisions, rollback, early quotas and consistent hashes | 10 focused; surrounding 54 passed/2 optional skips |
| Round 5 review | Reviewer verified S1–S3 with no blocking findings; two low-priority weather notes | Reviewer full suite: 414 passed/11 skipped/1 environmental Playwright failure |
| Final weather-warning correction | Weather-only warnings no longer block replacement weather; CSV failures still block | 14 focused, including four native simulations; 20 round-3/job/session tests |

These are recorded historical runs, not a newly rerun full suite. Native CLI
verification was on macOS arm64: CLI `3.11.0+241b8abb4d`, embedded Python 3.12.2;
development Python 3.13.7/SDK 3.11.0. Review probes also used the Linux aarch64 SDK
without native CLI; those SDK checks alone do not prove EnergyPlus execution.
Some review environments could not run Playwright; the broader round-3/4 browser
checks passed when the relevant sandbox restriction was lifted.

Four relocated Claude/Codex hydronic/electric-DX cases preserved inputs, rejected
stale plans/existing outputs/wrong versions, and matched settings and numerical
sizing across hosts and the phase-4 baseline (tolerance 1e-8). Initial saved checks
were 193/138, rising to 208/139 after review coverage. Native fan flow was
1.4310159079597569 m3/s; five terminal flows were positive (0.250193–0.329048 m3/s).
Cooling design load/capacity was about 32.431 kW hydronic / 32.763 kW electric-DX;
reheat capacities were positive. Sizing retained 28/29 seed/default warnings,
with zero severe/fatal or node-connection errors. Warning categories included
inherited schedules, location/comfort/daylighting inputs, ignored alternate
terminal fields, default air effectiveness and unavailable meters/monthly reports.
Fixture plants use district sources; unrelated seed HVAC/service water was
removed only in disposable copies. Exact numerical baseline data now lives in
`tests/fixtures/vav_sizing_baseline.json`, consumed by the evaluator and parity tests.

Offline wheel/sdist checks verified the exact SDK dependency and required helpers,
and excluded fixtures/candidate measures and the development evaluator from the
wheel. Existing package artifacts predate the final weather-warning correction
and this documentation consolidation; rebuild before release. Determinism means
engineering settings and topology, not identical SDK-generated UUIDs/OSM bytes.

## Context reduction evidence

Baseline commit: `871378c43563139d78efb8bf493adbe2a0bc4536`.
The selected legacy route counted the agent prompt, wrapper/parent, SDK editor,
workflow reference, nine child skills and five wiki packs once each: **98,062
characters**, approximately **24,516 tokens** using `ceil(characters/4)`.

| Measurement checkpoint | Bundled characters | Estimated tokens | Instruction text reduction |
| --- | ---: | ---: | ---: |
| Phase 5, October 4 | 22,922 | 5,731 | 76.6% |
| Initial review fixes, October 5 | 24,341 | 6,086 | 75.2% |
| Follow-up fixes, October 5 | 24,798 | 6,200 | 74.7% |
| Round 3 reported estimate | — | — | 74.0% |

These historical route estimates exclude implementation code, user messages,
tool catalogs, reasoning, tokenizers/caching, generated legacy scripts and API
responses. Actual agent tokens, costs, retrieval behavior, retries and live NLR
routing remain unmeasured. Early compact summaries were 85–90% smaller than full
reports; that percentage is separate from instruction reduction. Initial local
sequences took 3.38–4.88 seconds plus 0.85–1.14 seconds sizing, one run per case,
with zero script recovery retries. There is no measured legacy timing baseline
or statistical speedup claim.

## Reproduction and remaining work

Focused checks from the repository root (native cases skip if CLI unavailable):

```bash
OPENSTUDIO_AI_DATA_DIR=/tmp/openstudio-sdk-summary-check .venv/bin/python -m pytest -q \
  tests/test_skill_vav_evaluation.py tests/test_sdk_review_regressions.py \
  tests/test_sdk_followup_regressions.py tests/test_sdk_round3_regressions.py \
  tests/test_sdk_round4_regressions.py --disable-warnings --maxfail=1
```

Fresh isolated export/native evaluation:

```bash
.venv/bin/python scripts/evaluate_skill_vav.py \
  --output-dir outputs/skill-vav-NEW \
  --baseline-ref 871378c43563139d78efb8bf493adbe2a0bc4536 \
  --openstudio /Applications/OpenStudio-3.11.0/bin/openstudio \
  --incompatible-openstudio /Applications/OpenStudio-3.8.0/bin/openstudio
```

Use a fresh directory; the incompatible executable check is optional. Local
artifacts, where retained, are under `outputs/skill-vav-phase5-nlr-priority/`,
`outputs/sdk-review-20261005-final/`, `outputs/sdk-followup-20261005-final/`,
`outputs/sdk-round3-20261005/`, `outputs/sdk-round3-native-case/` and
`outputs/sdk-round4-native-case/`, with test logs/package directories alongside.
These local outputs are not guaranteed release assets or portable runtime bundles.

The remaining low-priority round-5 note is runtime weather lookup for the OS App
`file:files/x.epw` URL and companion-workflow weather fallback. Such runtime models
currently need explicit `options.epw_path`. Skill companion resolution already
uses native workflow lookup. This note was not included in the weather-warning fix.

Earlier review suggestions also included static per-skill import-closure checks,
generated SDK object-name collision checks and explicit unsupported `$ref` sibling
validation. The remediation records do not establish completion of those broader
hygiene suggestions; they should not be counted as verified fixes.

Native Windows/Linux execution, real network/cloud drives, annual performance,
ventilation adequacy, plant capacity/control adequacy, template compliance and
live-agent token savings remain unverified. Next release work should regenerate
and verify coordinated package/plugin exports and document SDK requirements.
Documentation consolidation performs no SDK install, plugin install, commit,
push or release; unrelated CalBEM and general architecture/release docs are retained.

## Plant creation and HVAC removal extension

Implemented October 5, 2026 in response to agent runs that could neither create
missing hydronic plants nor remove existing HVAC through a bundled script. These
are independent modeling modules for standalone requests and stages of broader
HVAC workflows, not restricted to missing plants or VAV preparation. The plant
module builds supply equipment, pumping, controls and condenser connections;
the selected air-side skill connects its coils to plant demand branches. VAV is
one supported consumer. The original VAV builder's existing-plant contract remains
unchanged. A replacement workflow selects removal scope, applies
removal to a new copy, creates any explicitly chosen missing plants on another
copy, then runs fresh VAV preflight against the latest output. Compatible
configured NLR remains the preferred provider. Neither missing plants nor fuel
matching alone establishes an appropriate performance-comparison strategy.

Implementation units completed:

1. Trace generic prototype plant helpers and add a shared guarded, reviewed-plan
   transaction with companion relocation and saved-model/translation checks.
2. Add `openstudio-plant-loop-creator`, bound to `scripts/plant_loops.py`.
3. Add `openstudio-hvac-remover`, bound to `scripts/remove_hvac.py`, and route
   covered replacement work through these skills before VAV creation.

### Source trace and supported plant profile

The authoritative local reference remains `openstudio-standards` at commit
`8bad404ef113019661fc0c14274a3554234219f7`. Under
`lib/openstudio-standards/`, the implementation follows
`prototypes/common/objects/Prototype.hvac_systems.rb` HW lines 42–190, CHW
228–460 and condenser 480–664; `Prototype.BoilerHotWater.rb:22` supplies boiler
details. `standards/Standards.PlantLoop.rb:21–67` supplies generic CHW control
and common-pipe behavior. `Prototype.utilities.rb:414` defines the kW/ton-to-COP
conversion, and `standards/ashrae_90_1/data/ashrae_90_1.curves.json:16529–16553`
provides the tower fan cubic coefficients. These are bounded ports of generic
branches, rather than a complete standards/template implementation.

| Plant | Explicit sources/options | Approved generic defaults |
| --- | --- | --- |
| HW | NaturalGas/Electricity boiler or DistrictHeatingWater; Variable/Constant pumping | 180 F supply, 20 R delta; 60 ft head, motor efficiency 0.9; boiler efficiency 0.78 unless overridden; scheduled outlet setpoint |
| CHW | AirCooled/WaterCooled electric EIR chiller or DistrictCooling; const_pri/const_pri_var_sec pumping | 44 F supply, 10.1 R delta; 60 ft primary or 15/45 ft primary/secondary head; COP 3.517/1.188 air-cooled or 3.517/0.66 water-cooled |
| Condenser | New loop automatically included with WaterCooled; variable-speed two-cell tower | Fixed 85 F supply, 10 R delta; 49.7 ft pump; wet-bulb-following setpoint, minimum 70 F and 7 R offset/approach; prototype tower fan cubic |

The human must explicitly choose sources and the `prototype_plants_v1` profile.
Either HW or CHW can be created alone. Chillers may number 1–3; district cooling
uses one source. SI supply-temperature/delta and HW boiler-efficiency overrides
are accepted with consistency checks. Existing plants are preserved; duplicate
names block. Water-cooled creation makes its own condenser loop, without reuse of
an existing one. Capacity and flow autosizing and unspecified performance curves
use the pinned SDK behavior. Condenser design is fixed, not derived from weather.
Heat-pump plants, waterside economizers, PRM heat-exchanger/EMS arrangements and
subsequent standards postprocessing are outside this initial profile.

### Removal scope and transaction contract

Removal selectors explicitly name or identify air loops, VRF systems and/or zone
equipment. Shared roots affect all served zones, including zones not named in a
replacement request; the plan shows that scope. There is no implicit remove-all
or plant deletion. The SDK's owned-component cascade is previewed on an in-memory
clone and compared with actual removal. Saved-model checks protect unselected
systems, plant supply equipment/sizing, geometry, loads, schedules, thermostats
and zone multipliers. Unsupported cascades that alter protected state block.
Unserved zones remain pending replacement; ideal loads are not silently enabled.

Both new entrypoints support inventory, preflight and apply, using the doctor-
verified exact-release native CLI:

```text
<verified-cli> execute_python_script <skill>/scripts/plant_loops.py --input <input.osm> --report <inventory.json>
<verified-cli> execute_python_script <skill>/scripts/plant_loops.py --input <input.osm> --config <config.json> --report <plan.json>
<verified-cli> execute_python_script <skill>/scripts/plant_loops.py --plan <plan.json> --report <apply.json>
```

Use `remove_hvac.py` in the remover bundle for the same three modes. Paths must
be absolute and output/report destinations new. Full inventories, settings and
cascade details stay in reports; stdout is compact, with inventory categories
capped at eight entries. Apply checks the exact plan and input hash, reloads the
saved model, validates the operation, checks external resources and EnergyPlus
translation, and publishes exclusively to a new location. Referenced companions
travel with the OSM under `<stem>/`; honor `requires_companion_workflow` for CSV
models. Source changes, stale/tampered plans and translation failures do not
publish a successful output. These skills use shared helpers exported into each
owning bundle; they do not need a modeling MCP runtime or agent-drafted code.

### Extension verification

`tests/test_plant_and_removal_bundles.py`: **22 passed**. Coverage includes nine
HW/CHW source combinations, saved getters/topology/translation, hydronic VAV
readiness, selective VRF/OA and zone-equipment removal, protected-state checks,
stale/tampered plans, input/output preservation, SDK guards and translation
failure publication checks. Both new skills also passed native execution after
independent relocation from Claude and Codex exports and deletion of the original
export tree.

Three macOS OpenStudio 3.11.0 design-day cases attached hydronic VAV to newly
created plants: air-cooled constant-primary, water-cooled primary/secondary and
district-cooling constant-primary. Each completed without Severe/Fatal errors;
SQL asserts positive boiler and cooling-source capacities, fan flow and, for the
water-cooled case, tower capacity. These are sizing fixtures, not annual runs.

Another **217 surrounding tests passed** across manifest/export adapters, VAV
preflight/apply and SDK doctor/report. Five affected exported skills passed
skill-creator frontmatter validation. Run the extension checks with:

```bash
.venv/bin/python -m pytest -q tests/test_plant_and_removal_bundles.py --disable-warnings --maxfail=1
```

Native cases require the 3.11.0 CLI. Linux/Windows native execution, annual energy,
template compliance and live-agent token savings remain unverified. Regenerate
Claude/Codex exports before agent trials; an already installed plugin does not
automatically include this development change. No commit/push/install/release is
part of this extension.

## Consolidated source inventory

The following superseded files were read and removed. Their final decisions,
review outcomes, measurements and limitations are consolidated above. Print-only
review probes are retired; assertion-based regressions remain under `tests/`.

- `docs/SDK_SCRIPT_FOLLOWUP_FIXES.md`
- `docs/SDK_SCRIPT_FOLLOWUP_VERIFICATION.json`
- `docs/SDK_SCRIPT_REVIEW_FIXES.md`
- `docs/SDK_SCRIPT_REVIEW_VERIFICATION.json`
- `docs/SDK_SCRIPT_ROUND3_FIXES.md`
- `docs/SDK_SCRIPT_ROUND4_FIXES.md`
- `docs/SDK_SCRIPT_ROUND4_VERIFICATION.json`
- `docs/SKILL_SCRIPT_DEVELOPMENT_PLAN.md`
- `docs/SKILL_SCRIPT_PHASE4_VERIFICATION.json`
- `docs/SKILL_SCRIPT_PHASE5_EVALUATION.md`
- `docs/SKILL_SCRIPT_PHASE5_VERIFICATION.json`
- `docs/VAV_STANDARDS_TRACE.md`
- `docs/reviews/REVIEW_enhance_skills_scripts.md`
- `docs/reviews/REVIEW_followup_round3.md`
- `docs/reviews/REVIEW_remediation_followup.md`
- `docs/reviews/REVIEW_round4.md`
- `docs/reviews/REVIEW_round5.md`
- `docs/reviews/followup_probes_test.py`
- `docs/reviews/repro_return_plenum.py`
- `docs/reviews/round3_probes_test.py`
- `docs/reviews/round4_probes.py`

The phase-4 numerical baseline was extracted into the test fixture rather than
discarded. General user/developer/release docs and unrelated work remain intact.
