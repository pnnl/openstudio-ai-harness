# HVAC modularization work and review guide

Started October 6, 2026 on `enhance_skills_scripts`. This work extends the
consolidated SDK development record; it is a review guide for this new sequence.

## Scope and decisions

System skills own user intent, assumptions and complete-system recipes. Equipment
scripts are shared functions executed inside the parent's single model transaction.
Independent equipment skills will wrap meaningful attach/replace operations when
their contracts are defined; a complete system does not invoke an agent for every
component. Compatible NLR remains first, local SDK stays pinned to OpenStudio
3.11.0, and bundled execution remains independent of a modeling MCP runtime.

The CAV target is the generic arrangement in `model_add_cav`: constant-volume fan,
water central heat/reheat, water or explicitly approved two-speed DX cooling,
scheduled supply-air temperature and VAV-reheat terminals. This is not an assertion
that every zone has constant airflow. Prototype Hospital selection and template/
building-specific ventilation/damper overrides are separate policies.

## Phases and checkpoints

| Phase | Work | Acceptance / review checkpoint | Status |
| --- | --- | --- | --- |
| 1 | Extract shared SDK access, coils, fans, outdoor-air assemblies, terminal attachment and air-loop utilities from VAV | VAV input contract/settings/topology preserved; fan count checks expanded; branch and native sizing checks pass; historical numeric parity and relocated imports verified | Implemented and verified |
| 2 | Add bounded CAV recipe, input contract, independent saved-model checks and skill routing | Explicit differences from VAV; water/DX and saved topology checks; transaction rejection protections and native sizing | Implemented and verified |
| 3 | Verify independent Claude/Codex bundles and document results | Bundles operate after relocation without source tree/runtime; review commands and known limitations recorded | Implemented and verified |
| 4 | Independent supply-fan performance edit | In-place setters, stable fan/connection/reference handles, explicit changes, protected state, saved checks and native execution | Implemented; G1–G3 remediated |
| 5 | Water-coil ratings, attachment and controller lifecycle | Separate in-place edits from node/controller rewiring; explicit placement/plant/ratings; saved identity/topology and native sizing | H1–H4 approved; user reports successful Claude Code/Codex trials |
| 6a | Migrate a main-supply water coil to another plant | Dedicated branch, explicit target/Autosize, stable coil/controller/air identities, protected demand graphs and native sizing | Implemented and verified; ready for review |
| 6b | Real coil-class replacement | Heating water to electric; explicit efficiency/preserved control, reference policy, new coil identity and retained air boundaries | K1–K3 reviewed and approved |
| 6c | Air-location migration | Water coil to a main supply outlet; stable coil/controller/plant branch, explicit sizing and protected source/destination air paths | K1–K3 reviewed and approved |
| 7 | Genuine supply-fan class replacement | Constant ↔ variable volume, explicit new performance/curve, preserved air boundaries/controls, explicit terminal and sizing policy | Reviewed and approved (including L1–L3) |
| 8 | Independent pump operations | In-place performance/control edits before genuine pump-class replacement | Reviewed; M1–M2 addressed |
| 9 | Genuine pump-class replacement | Single constant ↔ variable-speed replacement; explicit curve/minimum flow and sizing/reference policies; retain plant graph and control context | Reviewed; N1 and lookup safeguards addressed |
| 10a | Independent economizer control edits | In-place control type, limits and lockout; stable identities, preserved ventilation/DCV/schedules, effective-limit review and native control evidence | Reviewed; E1–E2 addressed; proceeding to 10b |
| 10b | Minimum outdoor-air and DCV edits | Separate ventilation/sizing/occupancy contract, schedules and airflow cross-checks | Reviewed; V1 addressed with verified translation behavior |
| 10c | Outdoor-air topology / heat recovery | Separate intake/recovery attachment and in-place recovery edits; explicit controls, protected graphs and native execution | Implemented; review pending |

## Source trace

Reference: local `openstudio-standards`, commit
`8bad404ef113019661fc0c14274a3554234219f7`, under
`lib/openstudio-standards/`:

- `prototypes/common/objects/Prototype.Model.hvac.rb:93–129`: CAV dispatcher
  obtains HW, creates CHW only for Hospital if absent, then invokes the CAV builder.
- `prototypes/common/objects/Prototype.hvac_systems.rb:2562–2708`: actual CAV
  assembly; compare VAV at 1830 and generic temperatures at 7.
- `Prototype.SizingSystem.rb:9`: common sizing fields; CAV passes heating airflow
  ratio 1.0. In current SDK this is central heating maximum system airflow ratio.
- `Prototype.Fan.rb:130` and constant/variable-volume fan helpers: fan factory,
  units and prototype data; preserve SI values in our resolved plans.
- `Prototype.CoilHeatingWater.rb:17`, `Prototype.CoilCoolingWater.rb:15`:
  demand and air connections must precede controller finalization; later attachment
  can overwrite controller settings.
- `Prototype.AirTerminalSingleDuctVAVReheat.rb:11` and
  `standards/Standards.AirLoopHVAC.rb:2703`: generic minimum fraction 0.3;
  generic damper-action callback selects Dual Maximum / ReverseWithLimits for HW.
  ASHRAE/building subclasses override these policies. No implicit template port.

## Review invariants

- Parent owns topology and publication, with no published half-built components.
- Equipment settings have one canonical implementation; saved validators read SDK
  getters independently of construction helpers.
- Final water-coil controllers are checked after terminal/air/plant attachments.
- Defaults and custom choices stay in reviewed plans; no profile/approval selected
  by the agent to manufacture readiness.
- Existing plants, source/output files and referenced companion resources retain
  the established transaction protections.
- CAV OA minimum-fraction schedules are distinct from VAV minimum-flow schedules.
- Profiles do not establish ventilation adequacy, template compliance or annual
  performance. Native design-day sizing is recorded separately from translation.

## Verification and review map

Review the implementation in this order:

| Files under `skills/sdk_scripts/` | Review focus |
| --- | --- |
| `common/hvac_equipment.py` | Coil construction and plant attachment; controller finalization; terminal and zone attachment |
| `common/air_loop_components.py` | Sizing, scheduled SAT, fan selection, explicit OA schedule role and availability |
| `common/multizone_assembly.py` | Single in-memory recipe assembly; physical OA/cooling/heating/fan order |
| `common/multizone_plan.py` | Shared canonical defaults, proposals and selector/temperature/schedule checks |
| `common/air_system_recipe.py` | Frozen per-system fan class and OA schedule role used across assembly/counts/validation |
| `common/hvac_inventory.py` | HVAC-neutral inventory and selector resolution; `vav_inventory.py` remains a compatibility interface |
| `common/air_loop_validate.py` | Independent saved getters/topology/counts for all six fan classes, expected OA field and unused field; extra reheat limits |
| `common/vav_create.py`, `vav_plan.py`, `vav_validate.py` | Thin stable VAV interfaces; existing version-2 plan and input contract retained |
| `common/cav_system.py`, `cav_system.py`, `references/cav_input.md` | Explicit CAV profile/recipe/validation; schema projected from the shared input vocabulary; guarded inventory/preflight/apply |
| `common/model_transaction.py` | Partial configured plans now remain unready, save review details and cannot apply; plant/removal ready plans retain their behavior |

The manifest exports shared modules to each owning bundle. There is no implicit
host skill-dependency loader. Orchestrator/agent/SDK-editor routing includes the
new `openstudio-cav-system-creator` skill; existing compatible NLR priority remains.

### Explicit CAV differences

| Setting | VAV | Prototype CAV |
| --- | --- | --- |
| Supply fan | VariableVolume with fan-power curve | ConstantVolume; no VAV power curve |
| Central/reheat heating | Independent Water/gas/electric/None | Water; explicit HW selectors, which may select different plants |
| Cooling | Water or human-approved DXTwoSpeed | Same supported choices; no silent fallback to DX |
| Central/zone heating design | 55 F / 104 F | 62 F / 122 F |
| Heating system sizing ratio | Default 0.3 | Fixed 1.0 in this recipe; does not force terminal operating flow |
| OA schedule | Minimum outdoor-air flow | Explicit minimum-fraction schedule or null for minimum ventilation; no automatic choice |
| Water terminal damper action | Generic Normal | Generic ReverseWithLimits, maximum reheat fraction 0.5 and flow per area 0.0 |
| Night cycle runtime | Explicit 1800 seconds | Explicit 3600 seconds, matching pinned SDK default left unchanged by Ruby CAV |
| Return plenum | Optional reviewed selector | Not exposed in initial CAV recipe |

The CAV profile is `prototype_cav_v1`; the human chooses it. Partial preflight
produces `plan.assumption_review` with editable inputs versus fixed controls.
Gas/electric-coil and variable-volume-fan control defaults are removed from the
CAV control profile. Its fixed sizing ratio and absent plenum are marked noneditable.
The underlying schema vocabulary has one source; CAV restricts it explicitly.

### Recorded verification

- Before extraction: 105 VAV preflight/apply tests passed.
- First extraction: 130 VAV preflight/apply/sizing/resource tests passed.
- Initial combined regression (before F1–F5): **218 passed**, spanning CAV, static SDK import
  closure, VAV, native sizing, plant/removal, manifest/resources, both host adapters
  and report handling. This includes all 32 VAV heating/cooling/reheat combinations.
- New CAV/import coverage: 20 tests within that combined pass. Includes unsupported
  topology/input choices, unapproved defaults/DX, stale/tampered plans, wrong
  accepted setters, wrong OA schedule field, water/DX saved outputs, two native
  design-day runs and independently relocated native Claude/Codex bundles.
- Strengthened VAV numeric parity check: three sizing tests passed after adding
  comparisons with `tests/fixtures/vav_sizing_baseline.json`. Normal hydronic and
  electric/DX fan/terminal flows, reheat capacities and cooling loads match the
  historical values within 1e-6 relative/absolute tolerance. The CSV relocation
  case checks successful sizing separately because it changes loads.
- Three affected exported skills passed skill-creator validation.
- Both native CAV cases passed again after strengthening the positive cooling
  capacity/design-load assertion (2 passed). Diff whitespace and changed-Python
  formatting checks passed.

Run the combined checks from the repository root:

```bash
.venv/bin/python -m pytest -q \
  tests/test_cav_system.py tests/test_sdk_import_closure.py \
  tests/test_vav_apply.py tests/test_vav_preflight.py tests/test_vav_sizing.py \
  tests/test_plant_and_removal_bundles.py tests/test_harness_asset_manifest.py \
  tests/test_skill_resource_exports.py tests/test_openstudio_claude_code_adapter.py \
  tests/test_openstudio_codex_adapter.py tests/test_skill_sdk_report.py \
  --disable-warnings --maxfail=1
```

Native tests use `OPENSTUDIO_SKILL_TEST_EXE`, defaulting on this machine to
`/Applications/OpenStudio-3.11.0/bin/openstudio`; they skip if unavailable.
Development Python is 3.13.7; native execution uses the pinned CLI's embedded
Python/SDK. Linux/Windows native execution was not performed.

### CAV local trial

Regenerate the chosen host export first. Load the new CAV skill, run its doctor,
and select explicit zones/plants/settings using its contract. The example assumes
approved generic choices; do not copy its approval into an undecided request.

```text
<verified-cli> execute_python_script <skill>/scripts/cav_system.py --input <input.osm> --report <inventory.json>
<verified-cli> execute_python_script <skill>/scripts/cav_system.py --input <input.osm> --config <config.json> --report <plan.json>
<verified-cli> execute_python_script <skill>/scripts/cav_system.py --plan <plan.json> --report <apply.json>
```

Use absolute paths/new destinations, inspect full reports, and keep the OSM and
companion folder together. Missing profile/input choices yield an unready saved
plan and nonzero preflight exit, allowing discussion to continue without publication.

## Review follow-up: F1–F5

- **F1:** CAV requires an explicit OA choice. Null keeps ZoneSum minimum ventilation;
  constant 1 means **100% outdoor air when running** and enables both all-OA sizing
  flags. The review and compact preflight summary state that operation and the
  ineffective economizer. Other positive or variable fraction schedules use
  conservative 100% OA sizing and warn about that policy; it may oversize coils.
  Accepted profiles do not choose OA for the user. Approved CAV plans must be
  regenerated after this change.
- **F2:** Validation checks count deltas for every SDK fan class, retaining existing
  fans but rejecting an unintended fan of another class before publication.
- **F3:** Pressure-unit conversion uses the passed system profile's fan fields.
  A regression uses a smaller custom fan field set.
- **F4:** A frozen per-system description supplies fan class and OA schedule role
  to assembly, attachment, counting and validation. Recipe/plan mismatches reject.
- **F5:** The shared implementation is `hvac_inventory`; production consumers use
  the neutral name. The old VAV import remains a thin compatibility interface.

### Native F1 confirmation

OpenStudio 3.11.0 design-day runs of the same five-zone hydronic CAV fixture:

| Sizing with constant-1 minimum OA fraction | Central HW capacity | CHW design coil load | Fan flow |
| --- | ---: | ---: | ---: |
| Original minimum-OA sizing | 0 W | 32,430.776 W | 1.431016 m³/s |
| Corrected all-OA sizing | 20,881.688 W | 74,311.970 W | 1.431016 m³/s |

Both comparisons completed without Severe/Fatal errors. Engineering evidence is
in the local ignored `outputs/hvac-review-f1-native/comparison.json` with logs/SQL
under `original/` and `aligned/`; the table preserves results in this tracked guide.
Native water and DX regression tests require **all six** water heating capacities
(central plus five reheats) to be positive, positive fan/cooling sizes and successful
EnergyPlus completion. This confirms the fixture mismatch; it does not establish
annual performance or adequacy of arbitrary user models.

Follow-up verification: **237 passed** in the combined suite, including all new
OA choice/policy, extra-fan, custom-profile and recipe-mismatch regressions,
positive native CAV capacities, historical native VAV sizing parity, plant/removal
integration and independently relocated Claude/Codex exports. All 15 changed Python
files passed formatting, all three affected exported skills passed validation,
and staged/unstaged diffs passed whitespace checks.

## Phase 4 contract: independent supply-fan performance editing

Scope: edit the sole directly connected `FanVariableVolume` or `FanConstantVolume`
on an explicitly selected, unsplit AirLoopHVAC supply chain. Only explicitly
supplied total efficiency, motor efficiency and pressure rise (Pa/inH2O) change.
No generic profile is selected. Effective total efficiency must not exceed motor
efficiency. Zero pressure is allowed for an explicit idealized fan; efficiencies
must lie in (0,1]. Missing selection/values remain unready for discussion.

Apply calls setters on the existing fan, then validates a reloaded output copy.
The fan, both connections, metadata and incoming references retain their handles.
LifeCycleCost and EMS actuator references are permitted and checked unchanged.
The fan's name/class, boundary nodes, availability schedule, maximum-flow/autosize,
curve/minimum-flow, end-use category and all unselected objects remain protected.
Only requested performance fields are excluded from the selected fan fingerprint;
connections and metadata are fingerprinted with their original identities.
Companion packaging retains its existing path/checksum exceptions and verifies
resource contents. Sizing/simulation remains a separate requested operation;
an unchanged EMS program can still override fan performance at runtime.

G1–G3 review disposition:

| Finding | Resolution and review evidence |
| --- | --- |
| G1 | In-place `edit_supply_fan_performance` replaces the same-class swap; saved regressions preserve fan, connection, metadata and EMS/LifeCycleCost references for both supported classes. Skill names/routing promise performance edits only. |
| G2 | `fan_equipment.pressure_pa` is the single conversion implementation for the multizone planner and editor. Native SDK parity covers Pa and inH2O. |
| G3 | Full performance setters require all three fields before mutation. System fan factories check before fan creation; only explicit partial edits opt out. CV/VV regressions cover each missing field. |

Embedded/unitary/zone fans, split paths, multiple direct fans and class conversion
require separate contracts. A request to replace a CAV fan with a variable-speed
fan must not be routed to this editor. The tested node-preserving clone/reconnect
algorithm remains in the unexported `common/fan_replacement.py` primitive. Before
exposing real replacement, settle fan curve/minimum-flow inputs, terminal/sizing
changes, and reference migration. Rating-only coil edits should likewise preserve
identity; attachment/replacement requires the node/controller lifecycle contract.

### Phase 4 review map and local trial

| Files | Review focus |
| --- | --- |
| `skills/openstudio_supply_fan_performance_editor.md` | User intent, independent operation, supported placements and provider/version gate |
| `skills/sdk_scripts/references/fan_performance.md`, `.schema.json` | Partial inputs, explicit units/changes, in-place scope and protected-state exceptions |
| `skills/sdk_scripts/common/fan_equipment.py` | Shared pressure conversion and full/partial setters; VAV/CAV require complete inputs |
| `skills/sdk_scripts/common/fan_edit.py` | Selector/ownership checks, in-place edits, raw-field fingerprints, stable identities, saved getters and reporting |
| `skills/sdk_scripts/common/fan_replacement.py` | Retained node-preserving swap primitive; deliberately not exported or routed |
| `skills/sdk_scripts/edit_supply_fan_performance.py` | Direct inventory/preflight/apply entrypoint; no modeling-runtime dependency |
| `tests/test_supply_fan_performance.py` | Saved identity/reference preservation, inlet/middle/end positions, fixed/autosized flow, boundary setpoint managers, rejected mutations, native runs and relocated exports |

The fan setters follow `Prototype.Fan.rb:81–83`, for example
`fan.setFanEfficiency(fan_efficiency) unless fan_efficiency.nil?` and
`fan.setPressureRise(pressure_rise) unless pressure_rise.nil?`. The unit spelling
in that file at line 33 is exactly `'inH_{2}O'`; the public input `inH2O` maps to
that native spelling. The shared pure helper uses the verified factor 249.08891;
OpenStudio 3.11.0 confirms 3 inH2O = 747.26673 Pa. Performance edits use no port
surgery. Historical probes showed ordinary add/remove deleting an interior node;
the retained deferred primitive uses native Model.disconnect/connect to preserve
boundary nodes. Its regression tests cover inlet/middle/end positions for CV/VV.

Regenerate either host export and load `openstudio-supply-fan-performance-editor`. Run the
exported doctor first, then use its returned executable:

```text
<verified-cli> execute_python_script <skill>/scripts/edit_supply_fan_performance.py --input <input.osm> --report <inventory.json>
<verified-cli> execute_python_script <skill>/scripts/edit_supply_fan_performance.py --input <input.osm> --config <config.json> --report <plan.json>
<verified-cli> execute_python_script <skill>/scripts/edit_supply_fan_performance.py --plan <plan.json> --report <apply.json>
```

The performance-edit plan's `impact` exposes loop/fan, affected-zone count and complete
before/after performance values. Apply's `changes.before`/`changes.after` record
actual getter values and are checked against the plan. Large fingerprints remain
in the saved report. Do not populate unspecified values from a prototype profile.
Use the output copy as input to a later independently requested operation.

G1–G3 verification: **289 combined tests passed**, including **52** fan cases.
The fan suite covers stable saved identities/references, partial edits, each missing
full-construction field, native SDK unit parity, scope/value mutations, stale
plans/resources, incompatible SDK, and the six deferred reconnect regressions.
Both native design-day runs and both independently relocated Claude/Codex bundles
passed. The combined run also covers existing VAV/CAV sizing and historical numeric
parity, plants/removal, manifest tracking/import closure, reports and exports.
All three edited skills passed exported skill validation; changed Python files and
staged/unstaged diffs passed formatting/whitespace checks.

Current native evidence and CLI/EnergyPlus logs are retained locally under the
ignored `outputs/supply-fan-performance-review/`; `evidence.json` records both fan
classes, unchanged handles, values and design flows. Protected snapshots now cover
705/707 objects, including fan connection identities. Both cases changed total
efficiency 0.62 → 0.70 and pressure 996.35564 → 747.26673 Pa while retaining motor
efficiency 0.90. Variable-volume flow was 1.431016 m³/s; constant-volume flow with
moved external lighting CSV was 1.268206 m³/s. Different fixture loads make these
flows unsuitable as a before/after comparison or savings claim. Annual performance
and Linux/Windows native execution remain unverified.

The pre-remediation baseline was 269 passing tests, including 32 replacement cases;
its evidence under `outputs/supply-fan-phase4-native/` and user review/probe files
remain historical. Round-7 probes import the old API and are superseded by the
integrated reference/identity regressions. Re-export bundles and regenerate old
replacement plans; the new operation is `edit_supply_fan_performance`.

```bash
.venv/bin/python -m pytest -q tests/test_supply_fan_performance.py \
  tests/test_cav_system.py tests/test_sdk_import_closure.py \
  tests/test_vav_apply.py tests/test_vav_preflight.py tests/test_vav_sizing.py \
  tests/test_plant_and_removal_bundles.py tests/test_harness_asset_manifest.py \
  tests/test_skill_resource_exports.py tests/test_openstudio_claude_code_adapter.py \
  tests/test_openstudio_codex_adapter.py tests/test_skill_sdk_report.py \
  tests/test_skill_vav_evaluation.py --disable-warnings --maxfail=1
```

Phase 5 below implements the water-coil contracts. Fan-class conversion remains
a separate deferred contract.

## Phase 5: water-coil settings and attachment — H1–H4 remediation

Two directly bound skills now expose two public operations:

| Operation | Skill / entrypoint | Identity and connection contract |
| --- | --- | --- |
| Edit settings, including rating-only requests | `openstudio-water-coil-editor` / `edit_water_coil.py` | Only requested coil/controller setters; coil, controller, connections, metadata, boundary nodes and incoming references retain their handles |
| Attach a new coil | `openstudio-water-coil-connector` / `connect_water_coil.py` | New coil/controller at the explicit air-loop supply outlet and compatible existing plant demand; preserve existing branches/components |

Phase-5 coverage remains CoilHeatingWater/CoilCoolingWater directly on an unsplit main
supply path. OA streams, unitary equipment, terminal/reheat locations, other coil
classes and class conversion need separate contracts. Phase 6a below adds plant
migration. Compatible
configured NLR remains preferred; the package-wide exact SDK version pin is unchanged.
Whole-system VAV/CAV construction calls shared setters within its parent transaction.

### Review findings and changes

| Finding | Resolution | Regression/evidence |
| --- | --- | --- |
| H1: interior nodes pass preflight but insert downstream | Restrict `air_node` to `supplyOutletNode()`; reject inlet/interior nodes before projection. Inventory exposes each outlet and flags supported node candidates. Documentation describes the supported insertion precisely. | Heating and cooling interior fan-inlet cases with Temperature setpoint managers stay unready; source/output untouched. Supply-inlet rejection retained. Native outlet attachment passes saved validation and sizing. |
| H2: same-class replacement unnecessarily changes handles | Move name, availability, Autosize reset and partial controller settings into the in-place editor. Rename the broader skill/entrypoint. Remove replacement from the connector schema, builder, validator and routing. | Rating-only/full settings edits preserve EMS/LifeCycleCost references, coil/controller identities, four ports and existing object identities. Individual setting and hostile-mutation cases check saved values and protected fields. |
| Deferred replacement algorithm | Retain clone/retarget/reconnect in `common/coil_replacement.py`, deliberately absent from manifest/export/import closure. A future topology-changing contract must settle reference migration and controller lifecycle. | Heating/cooling primitive tests verify saved boundary nodes, owned controller retarget, metadata and translation. Both host exports exclude this module and the retired ratings-editor skill. |
| Cross-process plan ordering | Sort allowed raw-field lists, because JSON report writing sorts configuration keys. | Reordered-config plan equality and relocated native apply regressions. |

The historical water-coil review probes have been consolidated into the
[integration summary](SDK_INTEGRATION_SUMMARY.md#retired-probe-coverage-and-migration-verification)
and removed. Integrated tests assert the corrected public contracts; the old
replacement configuration is intentionally unsupported.
H3/H4 follow-up now also resolves rating-field interpretation and edit readiness.
The historical H4 probe is superseded by regressions that allow in-place editing
while preserving and warning about incomplete plants.

### H3/H4 follow-up and EnergyPlus confirmation

| Finding | Resolution | Regression/evidence |
| --- | --- | --- |
| H3: required rated temperatures look like a UA design point | Heating attachment no longer requires `design` or its four rated-temperature fields. Omitted metadata retains pinned SDK defaults, identified in the plan. `rating_usage`, the informational review item and bounded impact explain the method and existing plant/system sizing context. | Omitted/partial metadata and visible CLI preview cases; valid UA metadata no longer fails plant-versus-rated-temperature checks. Native VAV/CAV pairs use very different rated temperatures and produce identical positive capacity, UA and maximum water flow. |
| H4: an unchanged incomplete plant blocks edits | Matching type and finite supply/positive delta remain required. Missing supply equipment, an actual pump or outlet setpoint manager warns for in-place edits and sets simulation readiness false; attachment still rejects. | Heating/Cooling × rating/full settings edits × missing pump/setpoint/source pass saved validation and translation, preserving original identities and plant fields. Wrong plant type still rejects; existing attachment readiness regressions remain. |

The installed OpenStudio 3.11.0 bundles EnergyPlus 25.2.0 (local Energy+.idd header).
The versioned [WaterCoils sizing source](https://github.com/NREL/EnergyPlus/blob/v25.2.0/src/EnergyPlus/WaterCoils.cc#L2410-L2457)
uses the rated point for applicable NominalCapacity inputs. UA autosizing instead
uses air-system sizing and plant supply conditions; line 2457 assigns inlet water
from Sizing:Plant. The separate
[input checks](https://github.com/NREL/EnergyPlus/blob/v25.2.0/src/EnergyPlus/WaterCoils.cc#L394-L408)
validate three temperature relationships for both methods. Therefore optional UA
metadata still rejects invalid relationships; it does not specify operating design
conditions. An autosized NominalCapacity can also use system sizing conditions.
No claim is made about all operating modes or annual effects.

### In-place editor contract

`ratings` is optional: name, availability, sizing or controller settings can be
changed independently. Inputs reflect the user's request; unspecified fields retain
their values. `coil_name` and `controller_name` are independently explicit; renaming
one does not rename the other. Existing Availability schedules or explicit builtin
AlwaysOnDiscrete/AlwaysOffDiscrete are supported. If a requested builtin is absent,
the isolated preview records its expected additional object types.

An explicit `sizing: Autosize` resets heating capacity/UA/maximum water flow, or
cooling design air/water flow, plus controller maximum actuated flow. It retains
design temperatures/humidity and the heating performance method. Fixed size values
conflicting with this reset make the plan unready. Partial ratings can still set
fixed values or Autosize, subject to their active performance method.

Controller patches expose Temperature control, Flow actuator, Normal heating or
Reverse cooling action, nonnegative minimum flow, positive/Autosize maximum flow
and positive/Autosize convergence tolerance. Minimum must not exceed a fixed
maximum. Existing sensor/actuator nodes and ownership remain protected; scalar
edits never invoke controller finalization or rewire nodes. Before/after reports
include all effective ratings, names, availability and controller scalar settings.
Only requested raw fields are exempt from the snapshot, and independent saved
getters verify those values even if the builder reports a self-consistent mistake.
An existing plant lacking supply equipment, pump or outlet setpoint manager is
left unchanged with a repair warning and `simulation_ready: false`. That does not
prevent an in-place edit or authorize repair. Plant type/design conditions and
saved-validation/translation errors retain their checks.

### Attachment and source/API trace

Only the selected air loop's supply outlet is supported. It must have an incoming
connection and Temperature setpoint manager. Native addToNode inserts immediately
upstream there; inlet/interior nodes have downstream insertion semantics and are
unready, even if a Temperature setpoint manager exists. Plant demand must match
Heating/Cooling, with supply equipment, an actual pump, outlet setpoint manager,
finite supply temperature and positive design delta. Existing demand components
and plant supply topology are protected; first-demand attachment is covered.
Independent plant creation can be composed when requested.

Heating attachment uses the UA method with autosized UA/capacity/water flow.
Its four rated temperatures are optional, informational nominal-rating metadata;
omitted values retain the pinned SDK defaults shown in the review. They do not
set a UA design point. Existing plant and system sizing conditions are shown
separately. Cooling requires water/inlet-air/
outlet-air temperature, inlet/outlet humidity, heat-exchanger configuration and
analysis method; conditions can explicitly use Autosize. Water/air flow are
autosized. Choose cooling Autosize air/humidity conditions for system sizing unless
the user supplies fixed design conditions, which change capacity. Temperature
input relationships remain checked for both heating methods; heating plant-versus-
rated checks apply to NominalCapacity only. Cooling design/plant checks are unchanged.

`Prototype.CoilHeatingWater.rb:31–34` and `Prototype.CoilCoolingWater.rb:27–30`
attach plant demand before the air node. Heating's line 87 warns exactly:
"These inputs will get overwritten if addToNode or addDemandBranchForComponent is
called on the htg_coil object after this". New-controller finalization therefore
runs after both connections: Normal heating/Reverse cooling action, Flow actuator,
maximum flow Autosize, sensor at air outlet and actuator at water inlet. Minimum
flow 0 and numeric positive/Autosize convergence are explicit construction inputs.

Manual Model.connect creates no controller; the retained deferred algorithm clones
and retargets the owned controller before restoring four port connections. It is
not a public replacement capability. Location/class/plant changes require a new
reviewed contract before adapting or exposing it.

Attachment previews SDK topology on an isolated handle-preserving model copy.
Independent saved checks verify original identities, exact supply order, plant
supply order, demand components, expected additions/removals, ratings and controller
nodes/settings. Protected raw-field fingerprints preserve neighboring equipment,
sizing, thermostats, schedules, metadata and references. Resource hashes bind
external files. Weather hydration from a workflow is checked against its bound EPW;
missing weather warns without blocking edits. Saved validation and EnergyPlus
translation precede exclusive publication of a new copy.

### Review map and local trial

| Files | Review focus |
| --- | --- |
| `skills/openstudio_water_coil_editor.md`, `openstudio_water_coil_connector.md` | In-place intent versus outlet attachment; provider/version selection |
| `skills/sdk_scripts/references/water_coil_edit.md`, `water_coil_connection.md`, matching schemas | Units, partial edits, explicit Autosize reset, controller settings and rejection boundaries |
| `skills/sdk_scripts/common/coil_equipment.py` | Canonical rating/controller getter/setter vocabulary; attachment finalization |
| `skills/sdk_scripts/common/water_coil.py` | Node restriction, plan equality, isolated projection, in-place mutation and independent saved checks |
| `skills/sdk_scripts/common/coil_replacement.py` | Deferred algorithm only; not an exported dependency |
| `tests/test_water_coil_operations.py` | H1–H4, informational preview, incomplete-plant edits, paired UA sizing, identity/tampering and relocated exports |
| `skills/sdk_scripts/common/model_transaction.py` | Preserve a planner's explicit false simulation-readiness flag when companion files are ready |
| Manifest, agent/orchestrator/SDK editor, README | New editor name/resources and precise routing |

Re-export Claude/Codex bundles before testing. The old ratings-editor bundle and
replacement configurations are retired; regenerate all reviewed water-coil plans.
The new operation identifier is `edit_water_coil`. Each entrypoint has inventory,
config preflight and ready-plan apply modes with its own report file:

```text
<verified-cli> execute_python_script <skill>/scripts/edit_water_coil.py --input <input.osm> --config <edit.json> --report <edit-plan.json>
<verified-cli> execute_python_script <skill>/scripts/edit_water_coil.py --plan <edit-plan.json> --report <edit-apply.json>
<verified-cli> execute_python_script <skill>/scripts/connect_water_coil.py --input <input.osm> --config <attach.json> --report <attach-plan.json>
<verified-cli> execute_python_script <skill>/scripts/connect_water_coil.py --plan <attach-plan.json> --report <attach-apply.json>
```

Run the owning skill's doctor first and use its verified executable. Omit config
for inventory. Stdout candidates remain bounded; complete details stay in reports.
Keep output OSM and `<stem>/` companion together; simulation is separately requested.

The phase-5 baseline passed 386 combined checks (97 water-coil cases). H1/H2
passed 416 combined checks (127 water-coil cases). H3/H4 final verification
passed **438 combined checks**, including **149 water-coil cases**, all prior
native/relocated host tests and the new paired sizing cases. Both changed skills
passed exported validation; three changed Python files passed formatting checks,
and staged/unstaged diffs passed whitespace checks. The new paired native
runs cover VAV/CAV × omitted/changed rated-temperature metadata: all four runs
complete without Severe/Fatal errors, with identical positive coil capacity, UA
and maximum water flow within each system pair. Evidence and CLI/EnergyPlus logs
are retained in ignored `outputs/water-coil-review-h3-h4/`.

Earlier native/export evidence is historical under
`outputs/water-coil-review-h1-h2/evidence.json` and
`outputs/water-coil-phase5-review/`. Original capacities were not matched before/
after savings comparisons. This follow-up's matched UA pairs test sizing behavior;
no annual-performance, manufacturer validity or savings claim is made.

```bash
.venv/bin/python -m pytest -q tests/test_water_coil_operations.py \
  tests/test_supply_fan_performance.py tests/test_cav_system.py \
  tests/test_sdk_import_closure.py tests/test_vav_apply.py \
  tests/test_sdk_review_regressions.py \
  tests/test_vav_preflight.py tests/test_vav_sizing.py \
  tests/test_plant_and_removal_bundles.py tests/test_harness_asset_manifest.py \
  tests/test_skill_resource_exports.py tests/test_openstudio_claude_code_adapter.py \
  tests/test_openstudio_codex_adapter.py tests/test_skill_sdk_report.py \
  tests/test_skill_vav_evaluation.py --disable-warnings --maxfail=1
```

CI follow-up corrected a stale `Path` mock in the missing-drive regression after
path validation moved to `multizone_plan`. The test still calls the public VAV
planner and now bounds traversal to catch hangs. The review-regression and VAV
preflight files passed **78 tests**; formatting passed for the changed test.
The command above includes that previously omitted regression file. These are
overlapping targeted checks, not a new full-suite result.

## Phase 6a: plant migration — October 7, 2026

The user approved H1–H4 and reported successful real trials in Claude Code and
Codex. Phase 6 proceeds in bounded increments: migrate existing water coils to
another plant first; settle real class replacement and air relocation separately.
Setting-only requests keep using `openstudio-water-coil-editor`; there is no
same-class clone/reconnect operation or new skill name.

### Public contract and review map

`openstudio-water-coil-connector` / `connect_water_coil.py` adds
`operation: migrate_plant`. The configuration selects the existing coil, another
existing compatible plant, a new output path and explicit `sizing: Autosize`.
The coil remains on the same unsplit main air supply. It must be the sole component
of its source demand branch, and both plants must use water without glycol.
The destination requires supply equipment, an actual pump, outlet setpoint control,
finite supply temperature and positive delta. Existing source deficiencies remain
warnings with false simulation readiness. Create a requested plant with the
independent plant-loop skill first, then carry its copied model into migration.

Temperature/Flow control with matching Normal/Reverse action and zero minimum
flow is supported. Other controller scalars, coil names, availability, rating
metadata, performance method and design conditions retain their values. The explicit
sizing reset covers heating capacity/UA/maximum flow or cooling air/water flow,
plus controller maximum flow. The impact report shows both plant conditions,
affected zones, sizing changes and removed-object counts. Cooling temperature and
NominalCapacity checks still apply; heating UA metadata remains informational.

| File | Review focus |
| --- | --- |
| `skills/sdk_scripts/common/coil_migration.py` | Dedicated-branch checks; controller holding/restore; bounded preview differences; both plant membership/supply checks; independent whole-model connection graph |
| `skills/sdk_scripts/common/water_coil.py` | Existing edit/attach behavior retained; explicit migration dispatch; no-op sizing only permitted internally when topology changes |
| `skills/sdk_scripts/references/water_coil_connection.schema.json` | Distinct attach/migrate input forms; no implicit plant or class change |
| `skills/openstudio_water_coil_connector.md` and its connection reference | Review choices, controller lifecycle, handle effects and sizing boundary |
| `harness/asset_manifest.yaml` | Migration module travels with both independent water-coil bundles; local import closure verified |
| `tests/test_water_coil_migration.py` | Saved identity/reference/branch checks; rejection/mutation/hash tests; native sizing and independently moved exports |

The pinned SDK probe confirmed that `removeDemandBranchWithComponent` removes the
owned controller. Migration therefore temporarily redirects the existing controller
to an unpublished holding coil, moves the branch, removes the newly created
disposable controller, restores the original owner, then sets sensor to air outlet
and actuator to the new water inlet. Only maximum flow is reset; other raw scalar
fields remain unchanged, including fields using implicit SDK defaults. No holding
coil or disposable controller survives publication.

Coil/controller handles, incoming EMS/cost references, metadata, air boundary
nodes and air connections remain stable. Water nodes and demand connection handles
can change. The SDK also compacts source mixer/splitter ports, rebuilding connection
records for preserved branches; the semantic connections remain checked. External
references to removed water nodes make preflight unready. Apply reports old/new
water-node handles and all removed handles so later inventories/plans can be rebuilt.
The source plant remains, including when it has no remaining served coil.
The impact now reports remaining source coils and demand equipment separately;
zero coils produces a retention/cleanup warning. Active retained water-temperature
mismatches point to an explicit follow-up with the in-place editor. See J1–J4 below.

The private preview rejects changes outside the two demand graphs, selected coil
water fields, explicit sizing fields and controller control-node links. Saved checks
use independent getters, raw protected-field fingerprints, identity/type deltas,
exact air order, both supply orders, demand component membership, controller nodes
and the whole-model connection graph. That graph normalizes only newly generated
coil water-node UUIDs, so serialized plans remain deterministic. Shared transaction
checks bind source/configuration/companions, reload the saved model and translate
before publication. An unapproved name, rating, node, controller identity, other
coil, added object or incorrect result mapping prevents publication.

### Local migration trial

Re-export and refresh the selected host plugin. After doctor verifies the pinned
OpenStudio executable, inventory the model and build this configuration from the
user's actual request:

```json
{
  "output_model_path": "/absolute/path/migrated.osm",
  "operation": "migrate_plant",
  "coil": {"name": "Office Main Heating Coil"},
  "plant_loop": {"name": "New Office HW"},
  "sizing": "Autosize"
}
```

```text
<verified-cli> execute_python_script <connector>/scripts/connect_water_coil.py --input <input.osm> --report <inventory.json>
<verified-cli> execute_python_script <connector>/scripts/connect_water_coil.py --input <input.osm> --config <config.json> --report <plan.json>
<verified-cli> execute_python_script <connector>/scripts/connect_water_coil.py --plan <plan.json> --report <apply.json>
```

Review the compact `impact` before apply. Keep the output with its `<stem>/`
companion and request sizing separately. Migration does not resize supply equipment,
change air-system/terminal strategy, establish ventilation adequacy or certify annual
performance. Glycol, serial demand components, custom sensor/actuator locations,
OA/unitary/terminal coils and air relocation remain outside this increment.

Initial phase-6a verification passed **304 distinct targeted tests**: 121 migration/review/preflight,
129 existing non-native coil cases and 54 import/manifest/export checks. The 121
include **43 migration cases**, four native design-day runs (VAV/CAV × heating/
cooling) and two independently relocated host bundles. All native runs had positive
selected-coil capacity and no Severe/Fatal errors. Seven affected exported skill
instances passed skill-creator validation across their configured hosts; three
changed Python files passed formatting, and staged/unstaged diffs passed whitespace
checks. This is targeted verification; the full CI suite was not rerun.

| Native case | Selected migrated coil capacity |
| --- | --- |
| VAV heating | 81.007989824 W |
| VAV cooling | 32,430.776104890 W |
| CAV heating | 20,881.687788432 W |
| CAV cooling | 74,311.969592274 W |

These are design-day fixture results, not an annual performance or savings claim.
Repeat the focused checks with:

```bash
.venv/bin/python -m pytest -q tests/test_water_coil_migration.py \
  tests/test_sdk_review_regressions.py tests/test_vav_preflight.py \
  --disable-warnings --maxfail=1
.venv/bin/python -m pytest -q tests/test_water_coil_operations.py \
  -k 'not native' --disable-warnings --maxfail=1
.venv/bin/python -m pytest -q tests/test_sdk_import_closure.py \
  tests/test_harness_asset_manifest.py tests/test_skill_resource_exports.py \
  tests/test_openstudio_claude_code_adapter.py tests/test_openstudio_codex_adapter.py \
  --disable-warnings --maxfail=1
```

Native tests skip without the pinned CLI. Local native evidence is retained under
ignored `outputs/water-coil-phase6-review/`. No commit, push, installation or release
is part of this development increment.

### Review follow-up: J1–J4

| Finding | Change | Verification |
| --- | --- | --- |
| J1: empty source plant hidden | Impact exposes remaining coils, remaining demand equipment and whether the source will be unserved. A zero-coil warning states that equipment/pumps and existing sizing settings remain. It names the HVAC remover's current plant-deletion exclusion rather than directing an unsupported deletion. | Five remaining heating/reheat coils; zero remaining cooling coils with warning propagation through apply; heat exchanger demand counted separately so a used plant is not called unserved |
| J2: migration sizing parity unproven | Paired native baseline/migrated models use exactly matching source/destination supply temperatures and deltas. The baseline comes from the same source model; no thermal settings are edited between runs. | VAV/CAV × heating/cooling, two runs per case; heating capacity/UA/water flow and cooling capacity/air/water flow match within 1e-9 relative, 1e-12 absolute tolerance. CAV heating is above 10 kW. |
| J3: native lifecycle dependency not pinned by tests | Minimal direct SDK probes assert that removing a branch clears/deletes its controller and attaching creates a distinct controller owned by that coil. These tests deliberately avoid the 3.11-only fixture so future installed SDKs exercise the assumption. | Heating and cooling probes pass on 3.11.0; failure messages name the observed SDK release and changed hand-off assumption |
| J4: retained fixed water conditions lack an action | Impact lists active fixed cooling inlet-water or NominalCapacity heating inlet/outlet-water mismatches, with retained and destination values. A warning names `openstudio-water-coil-editor` for explicitly selected changes on the copied output before sizing when needed. Migration still preserves ratings. | Fixed cooling and NominalCapacity warning/getter checks pass; Autosize cooling and informational UA metadata do not produce the active-rating follow-up warning |

The current remover supports selected air-loop/VRF/zone equipment removal and
explicitly preserves plants. Migration does not authorize removal of an unserved
source plant. A plant with no coils can still serve non-coil demand devices, which
the new impact identifies separately. Review retention/cleanup intentionally.
Manufacturer ratings may intentionally differ from operating plant temperatures;
the follow-up warning does not automatically align those values or grant approval.

Matched native before/after evidence (identical values in each pair):

| Case | Capacity W | Heating UA W/K | Water flow m3/s | Cooling air flow m3/s |
| --- | --- | --- | --- | --- |
| VAV heating | 81.007989824 | 1.269892030 | 0.000001771874822 | — |
| CAV heating | 20,881.687788432 | 330.609163014 | 0.000456741821685 | — |
| VAV cooling | 32,430.776104890 | — | 0.001376948158838 | 1.431015907960 |
| CAV cooling | 74,311.969592274 | — | 0.003155142799506 | 1.431015907960 |

The VAV heating fixture's small capacity remains a limitation of that fixture;
the substantial CAV heating pair supplies the stronger heating check. Cooling
UA is not reported in ComponentSizes for this coil contract; the cooling comparisons
use design coil load and air/water flow rather than claiming a cooling-UA check.
Every paired run completed without Severe/Fatal errors. The source model bytes
remain unchanged after sizing both copies. Per-case `matched-sizing-evidence.json`,
CLI/EnergyPlus logs and the consolidated evidence are retained under ignored
`outputs/water-coil-review-j1-j4/`.

J1–J4 verification passed **188 distinct targeted tests**: 134 migration/review/
preflight checks and 54 import/manifest/host-export checks. This includes **56
migration cases**, 13 new cases, 12 native design-day runs (eight paired plus four
existing positive-capacity runs) and both relocated host bundles. Both affected
connector skill exports passed skill validation; two changed Python files and
staged/unstaged diffs passed formatting/whitespace checks. The historical 129
non-native edit/attach cases were not repeated because their code was unchanged;
the prior 304-check run remains historical. Full CI was not rerun. Re-export and
regenerate migration plans so their reviewed impact includes the new information.

## Phases 6b and 6c — implementation contracts

Implement these as separate reviewed transactions, with the shared equipment
functions below the skills. Existing skill names remain stable.

| Phase | Initial coverage | User choices and preserved state | Review evidence |
| --- | --- | --- | --- |
| 6b | Genuine class conversion: main-supply `CoilHeatingWater` to `CoilHeatingElectric`, through a new `openstudio-coil-replacer` skill | Select coil, electric efficiency, preserved outlet temperature control, Autosize and reference policy. Preserve availability and air boundary nodes; report new coil identity and removed controller/water branch. Retain metadata. External references to removed equipment/nodes require separate coverage. Source plant remains with a remaining-demand warning when appropriate. | Saved independent scalar/topology/control checks, native positive-capacity sizing and control traces, both independently relocated host exports |
| 6c | Move an existing main-supply water heating/cooling coil immediately upstream of an explicitly selected supply outlet, on the same or another unsplit air loop, through the existing connector | Select coil, destination loop/outlet and Autosize. Preserve coil/controller identities, plant branch, availability, ratings, metadata and incoming equipment references. Reset sizing for the new location; update the controller sensor. One old interior air node is removed to keep a contiguous EnergyPlus branch. Reject interior-node dependencies and custom controller locations. | Same-loop and cross-loop topology checks, protected plant graph, saved translation and native sizing |

Neither contract covers coils embedded in OA/unitary/terminal equipment, arbitrary
interior destination nodes, gas/DX conversion or automatic plant cleanup. Same-class
settings changes continue to use the in-place editor. The old same-class cloning
primitive stays unexported. Plan impact must expose all affected zones, sizing
resets, identity/reference effects and retained source equipment. No ad hoc scripts
are generated to bypass unsupported cases.

### Implementation and review map

| Concern | Implementation / evidence |
| --- | --- |
| Separate operation routing | New `openstudio-coil-replacer` / `replace_coil.py` owns 6b. Existing connector / `connect_water_coil.py` owns `relocate_air` for 6c. Editor and connector names remain stable; NLR remains preferred. |
| Shared equipment/topology boundary | `common/coil_conversion.py` and `common/coil_relocation.py` own their operation contracts. `common/coil_topology.py` freezes scoped raw-field changes, identity/type deltas and the independent connection graph. Parent operations use the shared transaction for source/config/companion binding and saved translation. |
| 6b controls | Explicit `temperature_control: Preserve` retains existing outlet managers and SDK-generated supply-air/fan compensation. No new manager or temperature schedule is created. Before/after translated manager fields must match, including after saving. Efficiency is explicit and capacity autosized. Fixed-setpoint changes are separate coverage; controller metadata removal is disclosed. |
| Reference handling | 6b's explicit `Reject` policy blocks EMS, costs, removed water-node dependencies and named references, including case-insensitive keys. Coil metadata is reparented; references inside its feature values are also checked. 6c retains equipment references but blocks source interior-node dependencies and fan-control references requiring retargeting at the destination. |
| Air relocation integrity | Explicit rewiring preserves the plant branch. Native testing showed adjacent air nodes produced mismatched EnergyPlus branch names despite successful translation. The corrected removal merges the old location into one shared node, removes one interior node and inserts one new destination inlet node. Original loop boundary nodes remain; movement from a source supply outlet has regression coverage. |
| 6c control disclosure | Preview reports before/after translated managers, position relative to supply fans and control reference. The warning explains draw-through/blow-through and fan heat compensation/direct supply-outlet tracking changes where applicable. Saved translation must match the reviewed destination context. |
| Independent saved validation | Scalar getters, controller ownership/control nodes, protected object fingerprints, exact object deltas, both supply orders and whole-model edges verify the built model against its reviewed plan. Mutation tests affect apply only, after fresh preflight, to exercise saved rejection rather than merely private-preview rejection. |
| Remaining effects | Original air-system sizing, terminals, zone assignments and plant supply equipment stay unchanged. Sizing resets apply to the moved/replaced coil and water-controller maximum flow. Fixed rating metadata is retained for relocation. Review source and destination conditioning; annual performance and ventilation adequacy are not established. |

### Local review commands

Re-export both plugins through the existing export commands, refresh the host's
plugin, and run doctor before executing the scripts. Use the schemas/examples in
`scripts/references/coil_conversion.md` and `water_coil_connection.md`; values in
examples are choices, not defaults. Inventory, preflight, review impact and apply
use the same three commands with the appropriate entrypoint:

```text
<verified-cli> execute_python_script <replacer>/scripts/replace_coil.py --input <input.osm> --config <conversion.json> --report <conversion-plan.json>
<verified-cli> execute_python_script <replacer>/scripts/replace_coil.py --plan <conversion-plan.json> --report <conversion-apply.json>
<verified-cli> execute_python_script <connector>/scripts/connect_water_coil.py --input <input.osm> --config <relocation.json> --report <relocation-plan.json>
<verified-cli> execute_python_script <connector>/scripts/connect_water_coil.py --plan <relocation-plan.json> --report <relocation-apply.json>
```

Each operation starts from its explicitly selected input; compose operations only
when requested, passing the first copied output into the next. Keep each OSM with
its `<stem>/` companions, regenerate plans after a change, and request sizing
separately. 6b requires a dedicated single-coil demand branch; 6c rejects an empty
destination supply path or relocation of the only source supply component.

### Verification — October 7, 2026

Historical capacity/topology verification; superseded for conversion control by
the K1–K3 correction below. Positive sizing did not validate the fixed setpoint.

**319 distinct targeted tests passed:** 90 new conversion/relocation cases,
175 existing non-native water-coil/edit/attach/plant-migration regressions, and
54 import-closure, tracked-manifest, resource and host-adapter checks. The 90
include six native design-day runs and four independently relocated bundles
(each operation on Claude and Codex). Saved mutation checks, stale-plan rejection,
named/UUID references, interior destination rejection, source-outlet relocation,
weather hydration/readiness and protected plant/equipment identities are covered.
Seven affected exported skill instances passed skill validation; seven Python
files passed Black with Python 3.10 syntax targeting. Staged/unstaged whitespace
checks passed. The full CI suite and legacy native cases were not rerun.

| Native case | Selected coil capacity W |
| --- | --- |
| 6b VAV heating-water to electric | 81.007989824 |
| 6b CAV heating-water to electric | 20,881.687788432 |
| 6c CAV heating, same loop | 20,881.687788432 |
| 6c CAV cooling, same loop | 74,345.142209024 |
| 6c CAV heating, destination's two zones | 8,670.585018246 |
| 6c CAV cooling, destination's two zones | 30,517.267083987 |

Every native run completed without Severe/Fatal errors. The small VAV heating
fixture remains a limitation; the substantial CAV electric result supplies the
stronger heating check. Relocation changes equipment order/load context, so these
are positive-capacity and integrity checks, not a claim of sizing or energy parity.
No annual performance, ventilation compliance or live-agent token savings are
established. CLI/EnergyPlus logs, per-case sizing JSON, relocated host artifacts,
review exports and consolidated `evidence.json` are under ignored
`outputs/coil-phase6bc-review/`.

```bash
.venv/bin/python -m pytest -q tests/test_coil_conversion.py \
  tests/test_coil_relocation.py --disable-warnings --maxfail=1
.venv/bin/python -m pytest -q tests/test_water_coil_operations.py \
  tests/test_water_coil_migration.py -k 'not native' --disable-warnings --maxfail=1
.venv/bin/python -m pytest -q tests/test_sdk_import_closure.py \
  tests/test_harness_asset_manifest.py tests/test_skill_resource_exports.py \
  tests/test_openstudio_claude_code_adapter.py tests/test_openstudio_codex_adapter.py \
  --disable-warnings --maxfail=1
```

Native tests skip without the pinned executable. The new source files are staged
so tracked-manifest checks include them. Development remains on
`enhance_skills_scripts`; no commit, push, installation or release is included.
Review the initial contracts before expanding to gas/DX or arbitrary air locations.

### K1–K3 follow-up — October 8, 2026

K1 was confirmed by translating the source and converted fixtures: the new
scheduled outlet manager displaced MixedAir supply-air tracking with fan heat
compensation. The initial capacity-only native evidence could not detect that.
Conversion now requires `temperature_control: Preserve` and creates no outlet
manager or temperature schedule. Existing temperature managers retain their
identities/fields; otherwise the translator generates the original control.
Before/preview/saved translated manager fields must agree. Controllers with
custom strategies, minimum flow or sensor/actuator locations outside the
supported normal Temperature/Flow arrangement are rejected. Old
`outlet_temperature_c` configs must be regenerated. Fixed preheat control is
separate future coverage; there is no recommended fixed-temperature example.
K2 is resolved by removing that schedule entirely.

K3 is exposed in relocation impact and warnings: fan-relative placement and
translated control reference are shown before and after. In the reviewed
fixtures, relocation changes draw-through to blow-through and MixedAir fan heat
compensation to direct supply-outlet tracking. Saved translation verifies the
destination control context rather than asserting control stayed unchanged.

**328 distinct targeted checks passed:** 99 conversion/relocation cases, 175
existing non-native coil regressions and 54 manifest/import/resource/adapter
checks. The first group includes eight native design-day runs and four relocated
operation/host bundles. The three test commands above were rerun; the first used
`--basetemp outputs/coil-review-k1-k3/final`. Full CI and legacy native cases were
not rerun. The user's separate Linux review results are not included in this count.
Seven affected skill instances in refreshed Claude/Codex exports passed skill
validation. Five changed Python files passed Black targeting Python 3.10;
staged/unstaged whitespace checks passed.

The two added native runs instrument a separate model copy and inspect EnergyPlus
SQL at zone timesteps after warmup. With active airflow, the coil outlet target
must equal the supply target minus actual fan heat within 0.02 K. Heating and
electricity must be below 0.1 W when inlet air needs no heating. When inlet air
already matches the target, actual coil outlet and supply temperatures must
track their corresponding targets within 0.02 K. Each check requires qualifying
timesteps, so zero-data runs cannot pass.

| Control evidence | VAV | CAV |
| --- | --- | --- |
| Active timesteps | 432 | 432 |
| No-heating-needed timesteps | 432 | 288 |
| Maximum unneeded heating/electricity W | 0 | 0 |
| Maximum fan-compensation error K | 0.013276 | 0.001406 |
| Conditioned-air tracking timesteps | 432 | 263 |
| Maximum conditioned-air temperature error K | 0.013277 | 0.000169 |

New saved-model tests independently inspect translated manager fields, preserve
existing scheduled-manager identity and reject control mutations after fresh
preflight. Source files remain unchanged. Native environment remains OpenStudio
3.11.0/EnergyPlus 25.2.0, embedded Python 3.12; local SDK tests use Python 3.13.
These short design-day traces establish the exercised control behavior; they do
not establish annual energy, ventilation compliance or performance on all models.
Evidence, final SQL/logs and refreshed review exports are under ignored
`outputs/coil-review-k1-k3/`. Re-export plugins and regenerate old plans before use.

### Equipment backlog beyond coils

The standards `model_add_hvac` recipes justify these shared equipment families.
They are recorded for future sequencing; this increment implements 6b/6c only.

| Family | Existing coverage | Planned independent operations / later recipe consumers |
| --- | --- | --- |
| Fans | VAV/CAV creation and in-place main-supply performance edits | Genuine constant/variable-volume replacement, curve/terminal/sizing contract; exhaust, return, relief and unitary fan coverage |
| Pumps | Plant-creator supply pumping | In-place performance/control edits, genuine constant/variable-speed replacement |
| Outdoor air and controls | VAV/CAV outdoor-air assembly | Economizer/DCV/minimum-airflow and schedule edits with ventilation/sizing cross-checks |
| Zone terminals and reheat | VAV/CAV terminal creation | In-place airflow/reheat edits; terminal topology replacement |
| Heat recovery | Future assembly dependency | ERV/heat-exchanger attachment and performance edits |
| Plant equipment | Boiler/chiller/tower/district and condenser-loop creation | Independent equipment performance edits and real replacements; intentional unused-plant cleanup |
| Unitary and zone equipment | Removal coverage for selected supported equipment | PSZ, unitary, fan-coil, PTAC/PTHP, unit-heater and water-source heat-pump recipes using shared equipment modules |

Prioritize independent fan replacement and pump operations after the coil topology
contracts are reviewed. Settle detailed coverage before each later implementation.

## Phase 7 — genuine supply-fan class replacement

K1–K3 review is completed and approved. This increment implements the next
equipment operation: `openstudio-supply-fan-replacer` / `replace_supply_fan.py`.
Pump operations remain the following phase, after review of this fan contract.

### Contract and source trace

Coverage is the sole directly connected `FanConstantVolume` or
`FanVariableVolume` on an unsplit main supply path, changing to the opposite
class. Same-class performance requests continue through the in-place editor.
Return, relief, exhaust, embedded/unitary and other fan classes remain deferred.

Require explicit new total/motor efficiency and pressure, fan `sizing: Autosize`,
`terminal_policy: Preserve`, `system_sizing_policy: Preserve` and
`reference_policy: Reject`. Variable-volume targets additionally require five
power coefficients and a minimum-power flow fraction. Constant-volume targets
must omit the variable-volume inputs. Missing choices remain unready for user
discussion; no prototype profile or curve is inferred.

The standards source supports the separation of these fields. At
`Prototype.Fan.rb:130–183`, `create_fan_by_name` dispatches constant/variable
classes with common performance fields and separate variable-volume coefficients.
At `Prototype.FanVariableVolume.rb:169–180`, JSON lookup fills missing fields
before construction, including the exact assignment
`fan_power_coefficient_1 ||= fan_json['fan_power_coefficient_1']`.
Our independent replacement requires those choices explicitly instead of importing
building/template lookup defaults. Shared pressure conversion uses the already
verified OpenStudio SI factor. Source root/commit are recorded above.

For native power evidence, EnergyPlus 25.2.0 `simulateConstant` and `simulateVAV`
calculate power from flow/pressure/efficiency or a bounded flow-fraction polynomial,
respectively. The VAV power calculation applies the minimum-power flow floor.
See [the versioned EnergyPlus fan implementation](https://github.com/NREL/EnergyPlus/blob/v25.2.0/src/EnergyPlus/Fans.cc#L1492).
The test compares detailed simulated electricity with those independent formulas;
it requires actual part-load timesteps rather than accepting positive sizing alone.

### Review map and effects

| File / concern | Review focus |
| --- | --- |
| `common/fan_class_replacement.py` | Explicit choices, efficiency relationships, complete coefficient/minimum-power inputs, polynomial extrema/full-flow normalization and no source-class clone |
| Class topology | Construct the opposite class, retain both boundary nodes and exact position, replace only the fan/two connections; new fan identity is reported |
| Protected state | Reuse existing topology/graph/preservation helpers; terminals, sizing, coils, plants, OA controls and all unrelated raw fields remain protected |
| References / metadata | Reject direct UUID and unsupported fan-name references, including EMS/cost/metadata. Preserve compatible name-keyed output variables/custom electricity meters and list them in impact. Reparent existing metadata with stable identity and feature values |
| Temperature controls | No new manager or schedule. Compare all before/preview/saved translated setpoint-manager and NodeList fields, including generated MixedAir |
| Independent saved validation | Check SDK performance/curve/flow getters, class/name/availability/metadata owner, node identities, supply order, exact object deltas, graph, protected objects and reported mapping |
| Input/schema/skill | `references/fan_replacement.schema.json` / `.md`, `openstudio_supply_fan_replacer.md`; only `Fraction` power-minimum method is covered initially |
| Integration | `replace_supply_fan.py`, manifest and three routing files; NLR priority and SDK version pin retained; bundled import closure and relocated hosts verified separately |

Fan maximum flow is reset to Autosize; motor heat fraction, availability and
existing metadata are retained. The end-use label is retained unless an explicit
`end_use_subcategory` is selected; retained old-type labels warn. Variable-volume replacement sets
the unused fixed-power minimum flow explicitly to zero. The minimum-power fraction
does not set terminal or ventilation minimum airflow. Curve bounds are checked
at endpoints and all real interior derivative roots over [0,1], with full-flow
normalization and a coefficient-magnitude limit. Other power methods/ranges need
separate coverage.

Impact contains affected-zone/terminal counts and terminal classes; full terminal
references are saved under `plan.preserved_terminals`, keeping stdout bounded.
Existing terminal minimum airflow, zone assignments, OA controls and system sizing
stay unchanged under the explicit preservation policies. Fan class replacement
does not convert the entire system to VAV/CAV. In particular, a constant-volume
fan can remain on an air path with variable terminal airflow; its power formula
changes while terminal controls remain. The impact explicitly states terminal-driven
flow and linear power for a constant-volume target; changing fan class does not
enforce constant airflow. System/terminal changes, sizing and annual
simulation remain separate reviewable operations. The previous same-class
clone/reconnect primitive remains unexported.

### Local review commands

Re-export both plugins, refresh the host and run doctor. Use the explicit example
in the new skill's `scripts/references/fan_replacement.md` and inventory the input:

```text
<verified-cli> execute_python_script <fan-replacer>/scripts/replace_supply_fan.py --input <input.osm> --report <inventory.json>
<verified-cli> execute_python_script <fan-replacer>/scripts/replace_supply_fan.py --input <input.osm> --config <config.json> --report <plan.json>
<verified-cli> execute_python_script <fan-replacer>/scripts/replace_supply_fan.py --plan <plan.json> --report <apply.json>
```

Review the new fan class, curve, terminal/system-sizing preservation, source
maximum flow reset, changed identities and blocked references before apply. Keep
the copied output with its `<stem>/` companions; request sizing separately.

### Verification — October 8, 2026

Initial phase-7 verification; current L1–L3 follow-up is recorded below.

**163 distinct targeted checks passed:** 57 new class-replacement cases, 52 existing
fan-performance cases and 54 import/manifest/resource/host-adapter cases. Native
coverage includes four distinct design-day cases (two new replacements and two
existing in-place edits, including CSV companions) plus four relocated host bundles
(both fan operations on Claude/Codex). The new native power tests were additionally
rerun with a 0.5 power-flow floor to require below-floor operation. Source models
and validated outputs are preserved; native instrumentation uses separate copies.

| Latest native power evidence | Constant-volume target | Variable-volume target |
| --- | --- | --- |
| Autosized maximum flow m³/s | 1.431015908 | 1.431015908 |
| Active/part-load detailed timesteps | 577 / 577 | 577 / 577 |
| Minimum observed flow fraction | 0.312034012 | 0.312034012 |
| Timesteps below chosen power-flow floor | Not applicable | 144 (floor 0.5) |
| Maximum normalized power error | 1.49e-16 | 2.98e-16 |

Every design-day case completed without Severe/Fatal errors. Power evidence is
normalized to design fan power and compared with independent versioned EnergyPlus
formulas. These traces establish the exercised power behavior; they do not establish
annual savings, ventilation adequacy, curve suitability for a real fan or whole-system
conversion. Existing upstream coil/system code was unchanged; its full suites and
full CI were not repeated. Prior approved coil evidence remains historical.

Seven changed skill instances in refreshed exports passed skill validation; both
new exported bundles passed pinned doctor. Three Python files passed Black targeting
Python 3.10; staged/unstaged whitespace checks passed. Native SDK/CLI 3.11.0,
EnergyPlus 25.2.0, local Python 3.13 and embedded Python 3.12. Consolidated evidence,
native SQL/logs, power measurements, relocated bundles and review exports are under
ignored `outputs/fan-class-phase7-review/`; latest power evidence is under `floor/`.
No live agent, commit, push, installation or release is included.

```bash
.venv/bin/python -m pytest -q tests/test_supply_fan_replacement.py \
  tests/test_supply_fan_performance.py \
  --basetemp outputs/fan-class-phase7-review/final --disable-warnings --maxfail=1
.venv/bin/python -m pytest -q tests/test_sdk_import_closure.py \
  tests/test_harness_asset_manifest.py tests/test_skill_resource_exports.py \
  tests/test_openstudio_claude_code_adapter.py tests/test_openstudio_codex_adapter.py \
  --disable-warnings --maxfail=1
.venv/bin/python -m pytest -q tests/test_supply_fan_replacement.py \
  -k 'native_fan_class_change' --basetemp outputs/fan-class-phase7-review/floor \
  --disable-warnings --maxfail=1
```

### L1–L3 review follow-up — October 8, 2026

L1 removes the blanket fan-name rejection for compatible reporting. Native output
dictionaries for both pinned classes establish five common variables: electricity
rate/energy, air-temperature rise, heat gain to air and air mass flow. Name-keyed
`OutputVariable` requests for these remain intact, including case-insensitive keys.
`MeterCustom` / `MeterCustomDecrement` energy groups keyed to the fan remain intact,
along with their exact-name `OutputMeter` requests. Check each key individually;
one compatible group cannot exempt an unsupported group or UUID reference.
Object names alone are not equipment references. Direct references such as EMS
actuators and costs remain blocked, as do unsupported variable keys. Saved checks
retain reporting-object identities and raw fields and verify the reviewed list.
Impact includes up to eight retained reporting objects and the total count; full
details are in `plan.retained_output_references` to bound agent context.

L2 adds optional explicit `end_use_subcategory`. Omission retains the old value
and warns when recognizable CAV/VAV or constant/variable-volume text names the
source type. Explicit changes are bound to the plan and independently checked on
the saved fan. A label change warns about subcategory meter names; those requests
require separate review. No reporting label is silently renamed.

L3 adds `impact.airflow_behavior`: the class change does not enforce constant
airflow. Existing terminal controls can vary flow; the constant-volume fan follows
that flow with proportional power at fixed pressure/efficiency. Variable-volume
impact describes the chosen curve and minimum-power flow floor separately from
terminal airflow controls. Both directions continue protecting terminals/sizing.

**185 distinct targeted checks passed:** 79 replacement, 52 existing fan edits and
54 packaging/adapter cases. This includes four native design-day cases and four
independently relocated operation/host bundles. The first two test commands above
were rerun; the fan suite used `--basetemp outputs/fan-review-l1-l3/final`.
Twenty-two added cases cover all common outputs in both directions, custom/decrement
meter requests, mixed/UUID meter keys, explicit/retained/invalid reporting labels
and saved label mutation. Existing direct-reference rejection remains verified.

Both new native runs now start with fan-name keyed rate/energy requests and a
custom electricity meter in the source, and explicitly change the reporting label.
The copied output retains those requests; a separate instrumented copy supplies
the native power trace. Custom-meter totals match the fan-variable totals exactly:
218,930,888.435 J (constant-volume target) and 100,600,606.190 J (variable-volume
target). Each trace has 577 qualifying part-load timesteps, minimum flow fraction
0.312034012; the variable-volume floor is exercised for 144 timesteps. All native
cases complete without Severe/Fatal errors. Totals are fixture evidence of
resolution and power behavior, not an annual-savings comparison.

Both changed skill exports passed validation; two Python files passed Black
targeting Python 3.10 and whitespace checks passed. Environment remains SDK/CLI
3.11.0, EnergyPlus 25.2.0, local Python 3.13/embedded Python 3.12. Evidence/exports/
native SQL and logs are under ignored `outputs/fan-review-l1-l3/`. Full CI and
upstream coil/system suites were not rerun. User review/probe files remain unchanged;
they describe the pre-fix behavior. Re-export both hosts and regenerate plans for
the revised impact/config contract. No commit/push/install/release is included.

Phase 7/L1–L3 are now reviewed and approved. Phase 8 below adds independent
in-place pump performance/control edits; genuine pump-class replacement follows
its own contract and review.

## Phase 8 — independent in-place pump performance/control editing

Phase 7 and L1–L3 are reviewed and approved. Phase 8 adds
`openstudio-pump-performance-editor`; genuine pump-class replacement follows a
separate contract and review. Source/reference trace used the existing standards
commit above, plus the pinned SDK's getters, setters and IDD fields:

- `Prototype.hvac_systems.rb:92–109`: HW class choice, 60 ftH2O default or
  requested head, motor efficiency and operating mode. Exact source:
  `hw_pump.setPumpControlType('Intermittent')`.
- `Prototype.hvac_systems.rb:257–298`: CHW constant-primary and primary/secondary
  layouts. A `PumpVariableSpeed` with linear power coefficients is used for
  constant-primary operation; secondary pump sits on the demand inlet. This is
  why selection includes both plant sides and does not require a sole pump.
- `Standards.PumpVariableSpeed.rb:11–54`: four explicit cubic coefficient profiles
  (Constant Flow, Riding Curve, VSD No Reset, VSD DP Reset), with an accompanying
  Intermittent setting. Generic edits do not silently apply that extra setter.
- `Prototype.PumpVariableSpeed.rb:12–76` and `Standards.Pump.rb:12–98`: profile
  selection and motor/head calculations depend on template, served area/capacity
  and sized motor horsepower. Those compliance decisions stay outside this edit.
- [EnergyPlus 25.2 Pumps.cc](https://github.com/NatLabRockies/EnergyPlus/blob/v25.2.0/src/EnergyPlus/Pumps.cc):
  autosized pressure-based power depends on head and motor efficiency; fixed
  power and flow-only sizing do not recalculate rated power from those settings.

### Contract and review map

The selected plant and pump use exact name/handle selectors. Supported targets
are existing single `PumpConstantSpeed` and `PumpVariableSpeed`, directly connected
between plant nodes on either supply or demand side. Multiple pumps are supported
by explicit individual selection. Headered and condensate pumps are inventoried
but edits are refused. The user selects settings; there is no defaults profile or
inferred reset.

Explicit patch fields cover head plus Pa/ftH2O units, motor efficiency, fraction
of motor loss to fluid, Continuous/Intermittent control, fixed electric power or
Autosize, both design-power sizing methods and their factors, and four
variable-speed power coefficients. Cubic minima are checked analytically over
flow fraction [0,1], with positive full-flow power required; non-unit full-flow
fractions warn. Fixed flow/head/power combinations cannot exceed motor output.
Preflight reports before/after, selected plant side and retained flow policy,
warning about fixed power, inactive factors, continuous operation and retained
pressure/VFD controls. Coefficients describe power versus flow; they do not install
pressure-reset controls or change the plant flow arrangement.

Apply calls setters on the same pump. It preserves class/name, pump/node/
connection/metadata handles, incoming references (including cost/EMS), unrequested
flow/minimum-flow/schedule/curve fields, both plant component graphs, sizing,
supply equipment and all other protected objects. It uses the existing hash-bound
transaction, portable companions, saved validation and EnergyPlus translation
before publishing a new copy. It does not rewire or clone a pump.

| File | Review focus |
|---|---|
| `skills/openstudio_pump_performance_editor.md` | User-selected settings, provider priority, power-method discussion and bounded operation |
| `skills/sdk_scripts/references/pump_performance.schema.json` and `.md` | Strict partial inputs, units, fixed versus autosized power, explicit limitations |
| `skills/sdk_scripts/common/pump_edit.py` | Selection, planning, analytic curve check, in-place setters, independent saved getters and protected raw state |
| `skills/sdk_scripts/edit_pump_performance.py` | Direct skill-local entrypoint using shared transaction/report handling |
| `tests/test_pump_performance.py` | Identity/reference preservation, supply/demand and multiple pumps, each editable field, invalid/stale plans, mutation rejection, native power and relocated exports |
| `harness/asset_manifest.yaml`, prompts and routing skills | Complete independently relocatable resources for both hosts; covered edits routed to bundled script |

### Verification and native evidence

Targeted suite: **108 checks** (54 pump cases and 54 manifest/import/export/adapter
checks). The pump suite includes six before/after native comparisons (**12
EnergyPlus design-day runs**) and independently relocated Claude/Codex skill
bundles with doctor, inventory, preflight and apply. Regressions retain LifeCycleCost
and EMS raw references, detect unrequested curve/flow/metadata/connection/plant
changes, reject zero-power and negative-interior curves, and enforce the exact SDK
version before accessing a model. The scalar setter cases include Continuous
control and all power-sizing inputs; the four coefficients are checked after saving.

Native five-zone hydronic VAV fixture, CHW pump: head 60→30 kPa and motor
0.90→0.95, with class and control unchanged. Rated flow is autosized; its design
value remains 0.001376948 m³/s in every case. For the pressure method, rated power
117.688→55.747 W agrees with the independent sizing equation. The flow method uses
200,000 W/(m³/s); fixed-power cases retain 1,000 W. Actual electricity is read from
`Pump Electricity Energy` in SQL, not inferred from sizing or an unweighted rate sum.

| Power policy | Pump class | Peak electric power before→after (W) | After/before electricity energy |
|---|---|---:|---:|
| Autosize, PowerPerFlowPerPressure | ConstantSpeed | 117.688→55.747 | 0.473684 |
| Autosize, PowerPerFlowPerPressure | VariableSpeed (linear curve) | 109.232→51.663 | 0.473416 |
| Autosize, PowerPerFlow | ConstantSpeed | 275.390→275.390 | 1.000000 |
| Autosize, PowerPerFlow | VariableSpeed (linear curve) | 256.652→256.755 | 1.000160 |
| Fixed rated power | ConstantSpeed | 1000.000→1000.000 | 1.000000 |
| Fixed rated power | VariableSpeed (linear curve) | 966.334→973.325 | 1.001047 |

All native comparisons complete without Severe/Fatal errors. Pressure-based power
and energy ratios agree with 0.5×0.90/0.95 within 2%; retained flow is within 2%.
Small variable-speed differences reflect coupled fluid heat/load/flow behavior.
These are fixture checks, not annual savings or pressure-reset/continuous-control
performance evidence. Advanced pressure/VFD controls, annual schedules and every
polynomial profile have not been simulated here. Fixed and flow-only cases
illustrate why a head-only efficiency proposal must discuss the existing power policy.

Checks and artifacts:

```bash
mkdir -p outputs/pump-phase8
.venv/bin/python -m pytest -q tests/test_pump_performance.py \
  tests/test_harness_asset_manifest.py tests/test_sdk_import_closure.py \
  tests/test_skill_resource_exports.py tests/test_openstudio_claude_code_adapter.py \
  tests/test_openstudio_codex_adapter.py \
  --basetemp outputs/pump-phase8/final --disable-warnings --maxfail=1
.venv/bin/python -m black --check --target-version py310 \
  skills/sdk_scripts/common/pump_edit.py skills/sdk_scripts/edit_pump_performance.py \
  tests/test_pump_performance.py
git diff --check
```

SDK/CLI 3.11.0, EnergyPlus 25.2.0, local Python 3.13 and embedded Python 3.12.
Evidence/native SQL/logs and export-validation artifacts live in ignored
`outputs/pump-phase8/`. Full CI and unchanged coil/fan/system suites were not
rerun. User review/probe files remain unchanged. Re-export hosts for local trials;
regenerate plans for this new operation. No commit, push, installation or release.

Next review: approve this in-place pump contract before class replacement or
plant-flow/control redesign. The broader equipment backlog above remains intact.

### M1–M2 pump review follow-up — October 8, 2026

M1 is addressed with an explicit deferred-feasibility warning when rated electric
power is fixed and design flow is autosized. Preflight remains editable; it cannot
establish hydraulic efficiency without sizing and does not reset power implicitly.
The warning supplies the post-sizing check
`flow × head / (rated power × motor efficiency) ≤1` and the maximum feasible design
flow. It persists into apply reports. Regressions reproduce the review's 50 W /
600 ftH2O case for both single-pump classes, verify the numeric flow limit, saved
fixed power and warning propagation, and check the equivalent Pa request. Fixed
flow/power impossibilities continue to fail preflight. This is warning coverage;
no post-sizing validator is added to this edit operation.

M2 adds a **10 MPa** explicit bundle input ceiling (equivalently
3345.5256331296855 ftH2O) and `minItems: 4`, `maxItems: 4` for coefficients. This
conservative ceiling bounds the input contract and is not a design recommendation
or an SDK hardware limit. The shared bounded-schema validator now handles
`if`/`then`/`else` and `maxItems`, providing unit-specific pressure limits and
nested field errors before pump inventory. Tests check exact/over-limit values
in both units, 3/4/5-item arrays, conditional branches and partial inputs. Earlier
schema tests for huge head and excess coefficients now expect schema errors.

The native sizing/power experiment from phase 8 remains unchanged; the review
fix changes warning and input validation behavior. Both independently relocated
host bundles are rechecked with the revised resources. Final verification: **181 targeted checks passed** (62 pump, 65 preflight/schema,
54 packaging/adapters), including 12 native EnergyPlus runs. Four changed Python
files pass Black targeting Python 3.10; whitespace checks pass. Results and
limits are also recorded in HANDOFF.md; evidence/native SQL are in ignored
`outputs/pump-review-m1-m2/`. Full CI was not rerun.
User-owned review/probe artifacts remain unchanged. Re-export hosts and regenerate
existing pump plans because warnings/schema are bound into fresh preflight.

## Phase 9 — genuine single-pump class replacement

Phase 8/M1–M2 review is complete. This increment adds the independent
`openstudio-pump-replacer` skill for one connected `PumpConstantSpeed` ↔
`PumpVariableSpeed`, on either plant side. Existing multi-pump and primary/secondary
common-pipe arrangements are supported through exact individual selection.
Same-class head/motor/control changes remain in-place in the performance editor.
Combined class/performance requests compose those two reviewed copied outputs.

### Contract and source assumptions

The user chooses target class, rated-flow and rated-power policies (independently
Preserve or Autosize), plant Preserve and reference Reject. VariableSpeed additionally
requires an explicit fixed minimum flow and four power coefficients; no standards
profile, VFD or pressure reset is inferred. Missing choices stay unready. Fixed-flow
minimum checks, analytical polynomial minima and the phase 8 motor-feasibility
warning are shared. Positive minimum flow with autosized rated flow warns to verify
the sized design flow. No sizing or power reset is implied by Preserve.

The new pump retains name, label (unless explicitly changed), head, motor values,
operating mode, power-sizing method/factors, flow schedule and effective zone heat
loss split. ConstantSpeed's blank radiation fraction means zero in EnergyPlus;
VariableSpeed defaults to 0.5. Explicitly copying the effective fraction avoids a
silent thermal change. ConstantSpeed discards the VS polynomial/minimum-flow fields
and uses full rated electric power whenever running. Existing demand, valve and
schedule controls determine flow; class replacement does not redesign a plant.

Source trace at standards commit `8bad404ef113019661fc0c14274a3554234219f7`:
`Prototype.hvac_systems.rb:92–109` sets HW pump class/head/control; `:257–298`
uses a variable-speed object with linear power for constant-primary CHW and
constant supply/variable demand pumps for primary/secondary CHW. The latter
has explicit `[0, 0.0205, 0.4101, 0.5753]` coefficients. Thus object class alone
does not identify variable-flow operation. `Standards.PumpVariableSpeed.rb:11–54`
defines four profiles and sets Intermittent; this replacement retains the existing
operating mode. [EnergyPlus 25.2 Pumps.cc](https://github.com/NatLabRockies/EnergyPlus/blob/v25.2.0/src/EnergyPlus/Pumps.cc)
sets the simple constant-speed running-power fraction to 1.

Only the selected pump and its two connections get new handles. Water boundary
nodes, position, other pumps, equipment, branches, plant sizing, fluid, schedules
and controls remain. Metadata keeps its handle/features with its owner remapped.
Compatible pump-name output variables and custom/decrement electricity meters
remain, with bounded impact summaries and full report detail. Direct pointers,
EMS/cost references and unsupported name references block under Reject.
Pressure curves, impeller/RPM/VFD fields, active plant pressure simulation, banks
and condensate pumps require another contract rather than silently dropping fields.

Preview and saved-model validation independently check raw protected state,
object deltas, complete connections, component order, scalar/curve settings,
metadata, reporting and translated controls. In a component-setpoint operation,
only the equipment-class field paired with this exact pump's name may change;
nodes, design flow and operation values stay identical. Regression coverage includes
inlet, outlet and supply-equipment-branch placement, with boundary setpoints.
Any other translated control difference blocks readiness. Hash-bound apply reloads
and translates the staged model before exclusively publishing its copied output
and portable companions. Reports come directly from scripts.

### Review map

| File | Review focus |
|---|---|
| `skills/openstudio_pump_replacer.md` | Explicit choices, NLR priority, bounded replacement and direct execution |
| `skills/sdk_scripts/references/pump_replacement.md` and `.schema.json` | Policies, effective defaults, strict fields, curve/minimum flow and reference limits |
| `skills/sdk_scripts/common/pump_class_replacement.py` | Preview, exact reference allowance, low-level node-preserving replacement and independent saved checks |
| `skills/sdk_scripts/common/pump_edit.py` | Shared power-feasibility checks; existing in-place behavior retained |
| `skills/sdk_scripts/replace_pump.py` | Skill-local transaction/report entrypoint |
| `tests/test_pump_replacement.py` | Both classes/sides, branch setpoints, identities/metadata, sizing choices, references, mutation rejection, native power traces and relocated exports |
| Manifest, prompts and routing skills | Complete resource closure and specific-skill routing for both hosts |

### Native evidence and limits

Six paired comparisons run twelve native EnergyPlus design-day simulations:
both replacement directions on VAV supply, VAV common-pipe demand and CAV supply.
Destination variable-speed pumps explicitly use the cubic `[0, 0, 0, 1]` curve,
zero minimum flow, and retained Autosize/head/motor values. This tests the contract,
not the example DP-reset curve or annual savings. Both directions preserve design
flow and rated electric power to relative tolerance 1e-6. Every run completes
without Severe/Fatal errors. Actual electricity comes from SQL energy totals.

| Arrangement | Design rated power before/after (W) | VS/CV design-day electricity ratio | Part-load timesteps checked |
|---|---:|---:|---:|
| VAV supply pump | 117.688 | 0.235154 | 433 |
| VAV common-pipe demand pump | 117.688 | 0.235196 | 433 |
| CAV supply pump | 269.670 | 0.372908 | 385 |

Each direction checks actual part-load power against flow fraction cubed at these
timesteps (1.5% relative tolerance); the constant-speed peak equals rated power.
These results confirm equipment behavior with unchanged sizing and controls in
these fixtures. They do not guarantee savings for another curve, fixed power,
nonzero minimum flow, annual conditions or different plant arrangements.
Headered pumps, pressure/VFD control and plant redesign remain unimplemented.

Verification: **195 targeted checks passed** (79 replacement, 62 existing pump
editor, 54 packaging/adapters). This includes the twelve new native runs and twelve
existing editor native runs, plus four independently relocated operation/host
bundles with doctor, inventory, preflight and apply. Seven exported skills (three on both hosts and the Codex-only
orchestrator) pass the skill validator. All four changed Python
files pass Black targeting Python 3.10; staged and unstaged whitespace checks pass.

Verification commands and review artifacts:

```bash
.venv/bin/python -m pytest -q tests/test_pump_replacement.py \
  tests/test_pump_performance.py tests/test_harness_asset_manifest.py \
  tests/test_sdk_import_closure.py tests/test_skill_resource_exports.py \
  tests/test_openstudio_claude_code_adapter.py tests/test_openstudio_codex_adapter.py \
  --basetemp outputs/pump-phase9/final --disable-warnings --maxfail=1
.venv/bin/python -m black --check --target-version py310 \
  skills/sdk_scripts/common/pump_edit.py \
  skills/sdk_scripts/common/pump_class_replacement.py \
  skills/sdk_scripts/replace_pump.py tests/test_pump_replacement.py
git diff --check
git diff --cached --check
```

Environment: OpenStudio SDK/CLI 3.11.0, EnergyPlus 25.2.0, local Python 3.13 and
embedded Python 3.12. Ignored evidence is in `outputs/pump-phase9/`, including
native SQL/logs, JSON evidence and independently relocated Claude/Codex bundles.
Consolidated local verification: `outputs/pump-phase9/evidence.json`.
User-owned review/probe files remain unchanged. Re-export hosts and regenerate
plans for this new operation. Full CI and unrelated system/coil/fan suites are
outside this increment. Next checkpoint is review of the single-pump replacement
contract before additional equipment or plant-control work.

### N1 pump-replacement follow-up — October 8, 2026

N1 is addressed with a warning and an explicit bypass impact, without a new
approval/policy field. Constant-speed supply replacement remains available under
Preserve. The planner examines entire parallel demand paths from splitter to
mixer; known pipe-only and empty paths are uncontrolled. Inlet/outlet pipes and
pipes in series with controlled coils do not count. Other passive equipment is
not classified, so a missing verified path calls for review rather than proving
an invalid loop. Path presence also does not establish hydraulic adequacy.

`plan.demand_bypass` and its bounded impact show the explicit OSM status/count,
branch inlet references, actual translated uncontrolled branches/count, common-pipe
mode and whether constant-speed supply review applies. Saved validation recomputes
both OSM and translated status. A missing explicit OSM bypass warns only for the
constant-speed supply target, and the warning survives apply. No bypass is added
to the published OSM. Common-pipe mode makes primary/secondary context visible;
those arrangements may decouple flows and still need flow review.

The native check uncovered a distinction absent from the review probe:
**OpenStudio 3.11.0 synthesizes a demand bypass during translation even when the
OSM has none.** The impact verifies this actual workspace behavior rather than
assuming that a missing OSM pipe means no EnergyPlus bypass. The warning states
when translation provides a path and explains the risk if later measures remove
it. The [EnergyPlus 25.2 flow-resolver reference](https://bigladdersoftware.com/epx/docs/25-2/engineering-reference/plant-condenser-loops.html)
explains routing excess flow to bypass/passive branches and then active loads.
Its rule is: “When there is extra flow, the excess flow is sent through any bypass
branch first”.

Two single-HW-coil VAV fixtures, with/without an explicit bypass, each run before
and after constant-speed supply replacement. They use Continuous control,
6 kPa head, all-outdoor-air sizing/operation and electric zone reheat to exercise
no-load circulation without excessive heat accumulation in this small loop.
Heating design capacity is 4.246 kW, with unchanged sized flow/power. Both output
IDFs include a translated bypass. During the 577 reported timesteps, the
constant-speed pump circulates throughout; the coil receives 0–100% of pump flow
and the bypass takes flow when the coil is closed.

A fifth diagnostic simulation removes only the synthesized HW bypass and its
connector/list references from a separate IDF. It leaves the published OSM intact
and uses the same weather and native EnergyPlus 25.2 executable. The sole coil
receives 100% of nonzero pump flow; the pump has flow in 144 timesteps and zero
flow in 433, despite retained Continuous control. All five runs finish with no
Severe/Fatal errors. No specific excess-flow warning appears. This fixture exposes
changed flow resolution, not a measured controller-request mismatch or universal
over-delivery diagnosis. It demonstrates why successful translation/simulation
alone cannot establish bypass/flow adequacy. No annual or common-pipe hydraulic
validation is claimed.

Tests cover all target-class/side/bypass combinations, warning propagation,
saved status, pipe-plus-coil exclusion, empty paths and the translator's generated
bypass behavior. User review/probe files are unchanged; round-17 P3 intentionally
asserts the old missing-warning behavior and is superseded by these regressions.
Re-export both host plugins and regenerate reviewed pump plans because preflight
now includes hash-bound bypass status and warnings.

Verification: **145 targeted checks passed** (91 replacement, 54 packaging/adapters),
including **17 native design-day runs** (the twelve phase 9 comparison runs and
five bypass diagnostics). Both independently relocated host bundles pass doctor,
inventory, preflight and apply; both affected exported skills pass validation.
The two changed Python files pass Black targeting Python 3.10, and whitespace
checks pass. Full CI and unrelated equipment suites were not rerun.
Evidence: `outputs/pump-review-n1/evidence.json`, `final/` native SQL/IDFs/logs.

```bash
.venv/bin/python -m pytest -q tests/test_pump_replacement.py \
  tests/test_harness_asset_manifest.py tests/test_sdk_import_closure.py \
  tests/test_skill_resource_exports.py tests/test_openstudio_claude_code_adapter.py \
  tests/test_openstudio_codex_adapter.py \
  --basetemp outputs/pump-review-n1/final --disable-warnings --maxfail=1
```

### Round 18 lookup safeguards — October 8, 2026

The translated PlantLoop connector-list field now uses IDD lookup by the name
`Demand Side Connector List Name`. A missing/empty field raises
`Cannot verify translated demand bypass` with field context. Missing PlantLoop,
ConnectorList, splitter or branch objects raise that same ValueError prefix with
their type/name, instead of bare StopIteration; a missing splitter-list entry is
also diagnosed explicitly. These checks leave valid model behavior unchanged.

Eight new regressions simulate a moved field, missing/empty fields, each missing
translated object type and a missing splitter entry. **122 focused checks passed**
(91 non-native pump replacement cases, 31 manifest/import/resource-export cases);
the eight native cases were deselected. Both relocated host bundles execute with
the revised helper. Changed-file Black and whitespace checks pass. The prior N1
native evidence remains the physical-behavior evidence; EnergyPlus and full CI
were not rerun for this lookup-only change. Artifacts:
`outputs/pump-review-lookups/final/`. Re-export to use the revised helper.

## Phase 10a — in-place economizer control editing, October 9, 2026

Phase 9 and its N1/round-18 fixes are approved. The next family in the standards
backlog is outdoor air. Phase 10a adds the independent
`openstudio-economizer-editor`; minimum OA/DCV changes (10b) and OA topology/heat
recovery (10c) have separate contracts and review checkpoints. Terminals/reheat,
plant equipment and unitary/zone recipes remain on the broader backlog.

### Source and scope decisions

The reference remains local standards commit
`8bad404ef113019661fc0c14274a3554234219f7`.
`prototypes/common/objects/Prototype.hvac_systems.rb:1944–1964` and `2656–2671` create the VAV/CAV
OA controller, minimum-OA controls, mechanical ventilation and OA assembly.
`standards/Standards.AirLoopHVAC.rb:1030–1099` lists the economizer types and its
climate/template policy. Its comment says “Reset the limits” before clearing all
four optional cutoffs and selecting new template values. This partial editor
requires explicit resets and does not infer template/climate compliance.
`Standards.AirLoopHVAC.rb:1151–1183` chooses integration/lockout, including the
comment “LockoutWithCompressor doesn't work with hydronic” followed by “coils”.
Our warning identifies that retained limitation without inventing a supply-air
cutoff or changing system control strategy.

The [EnergyPlus 25.2 Controller:OutdoorAir reference](https://bigladdersoftware.com/epx/docs/25-2/input-output-reference/group-controllers.html)
confirms that nonblank cutoffs can act together, maximum-fraction schedules can
override ventilation bounds, and a positive time-of-day economizer schedule
forces maximum OA. It also distinguishes MinimumFlowWithBypass from normal
modulation. The preview reports these retained controls instead of treating
selection of an economizer type as proof that free cooling will occur.

### Contract and review map

Only explicitly supplied `control_type`, `lockout_type`, `maximum_dry_bulb_c`,
`maximum_enthalpy_j_kg`, `maximum_dewpoint_c` and `minimum_dry_bulb_c` change.
A null cutoff explicitly resets it. The plan exposes effective before/after
values. Fixed types require their relevant limits, active dry-bulb limits must be
ordered, and ElectronicEnthalpy requires an existing quadratic/cubic curve.
No-op or unresolved edits remain unready; unsupported fields/types fail schema
validation. Existing references are preserved rather than rejected unnecessarily.

| Files | Reviewer focus |
| --- | --- |
| `skills/openstudio_economizer_editor.md` and `references/economizer.md` | Independent operation, explicit choices, effective limits/overrides, NLR priority, pinned doctor and direct script execution; no ad hoc fallback |
| `common/economizer_equipment.py` | Canonical six field mappings, setters and explicit optional resets; no constructors or node rewiring |
| `common/air_loop_components.py` | VAV/CAV delegate their existing type/minimum-limit reset to the same setter; existing recipe settings stay intact |
| `common/economizer_edit.py` | Unsplit directly owned OA selection; full protected-model fingerprints; before/after effective values, retained ventilation context and independent saved checks |
| `edit_economizer.py`, `references/economizer.schema.json` | Strict partial contract, guarded inventory/preflight/apply and canonical report files |
| Manifest and agent/orchestrator/SDK-editor routing | Self-contained exports for both hosts, dynamic doctor probe included, shared setters exported to both parent bundles |
| `tests/test_economizer.py` | Saved VAV/CAV edits, every input field/type/reset, references/curves, overrides, corruption rejection, stale/tampered plans, translated disabling and native control evidence |

Preserve controller/OA-system/MV, node/connection, metadata and reference handles;
all other fields and objects stay protected, including ventilation/DCV, schedule
contents, action/staging, heat-recovery bypass, equipment and sizing. Whole-model
fingerprints permit only requested controller fields and the transaction's
existing weather/external-file relocation allowances. Seven independent saved
checks precede forward translation and publication of the copied model. Original
input bytes are retained. Incoming EMS references remain connected, although
external controls can still override runtime behavior.

Plans warn on retained nonblank limits, electronic curves, minimum fraction 1.0,
maximum caps, nonconstant fraction schedules, force schedules, high-humidity
control and bypass action. An unmatched 100% OA/sizing combination or conflicting/
zero flow/fraction bounds sets `simulation_ready: false` while allowing the scoped
edit. This is a context warning, not a ventilation or model-wide readiness audit.
Cooling equipment lists in the compact impact are bounded to eight plus count;
full preservation data stays in the report. No schedules are enumerated.

### Native evidence and verification

VAV and CAV each run before and after NoEconomizer → FixedDryBulb at 24 °C in
five-zone hydronic fixtures. Minimum OA is explicitly selected without a 100%
fraction schedule; availability is fixed on. A mild, sunny cooling design day
(20 °C maximum, 6 K range, 13 °C maximum wet bulb) exercises free cooling. Fixture
setup explicitly clears other cutoffs; the editor itself changes only type and
maximum dry-bulb. Instrumentation is added only to separate simulation copies.

Native OpenStudio 3.11.0 / EnergyPlus 25.2.0 runs all complete with no Severe/Fatal
errors. Economizer status is zero before and positive in 368 reported timesteps
after, in both fixtures. OA fraction is computed from reported OA/mixed-air mass
flow. Maximum fraction rises from about 0.4943 to 1.0; the largest increase at a
matched reported timestep is 0.723737 for VAV and 0.723603 for CAV. This checks
actual control response, not sizing-only parity or annual energy savings.

Operational evidence is retained under `outputs/oa-phase10/native-fixed/` as
`native_evidence.json`, SQL, IDF and logs. The final verification run and commands
are recorded below. Exported bundles execute doctor, inventory, preflight and
apply after moving the skill and deleting the exported source tree. The input
model uses explicit settings; no model-account/token evaluation is performed.

Verification: **185 targeted checks passed** (50 economizer, 81 VAV/CAV,
54 manifest/import/resource/host-adapter checks), including the four economizer
before/after native runs and two existing CAV design-day sizing runs. Both new
host bundles run after relocation, and both affected parent bundles also pass
existing relocation checks. Six exported skill validations pass (economizer,
VAV, CAV × Claude/Codex). Changed Python passes Black targeting Python 3.10;
whitespace checks pass. Full CI, annual performance and unrelated equipment
suites were not rerun. Final artifacts: `outputs/oa-phase10/final/`; combined
summary: `outputs/oa-phase10/evidence.json`. Review exports:
`outputs/oa-phase10/review-exports/{claude,codex}/`.

```bash
.venv/bin/python -m pytest -q tests/test_economizer.py \
  tests/test_vav_apply.py tests/test_cav_system.py \
  tests/test_harness_asset_manifest.py tests/test_sdk_import_closure.py \
  tests/test_skill_resource_exports.py tests/test_openstudio_claude_code_adapter.py \
  tests/test_openstudio_codex_adapter.py \
  --basetemp outputs/oa-phase10/recheck --disable-warnings --maxfail=1
```

Re-export both plugins to use the new route/shared helper. Regenerate any reviewed
plans after bundle changes. Phase 10a is ready for review; phase 10b will cover
explicit minimum OA/DCV changes, schedule roles, occupancy/design ventilation and
sizing cross-checks. Phase 10c will separately settle OA attachment/heat-recovery
rewiring and control. No commit, push, installation or release is included.

### E1–E2 review follow-up — October 9, 2026

E1 is addressed with a translated-control readiness check. Preflight clones the
model while preserving handles, applies the explicit requested economizer patch
to that preview, and inspects its translated `Controller:OutdoorAir` using the
named `Mixed Air Node Name` field. The same node-manager collector used by coil
conversion/relocation is extracted to `common/temperature_control.py`; coil
behavior is unchanged. All six owning skill bundles explicitly export the helper.

`retained_context.mixed_air_control` and the compact impact record the translated
mixed-air node, temperature managers and `temperature_setpoint_verified`. Generated
MixedAir managers and direct temperature managers qualify; matching expands
NodeLists and checks target fields rather than incidental reference-node fields.
Humidity-only and Scheduled:DualSetpoint managers do not supply the single
`TempSetPoint` required by this economizer. NoEconomizer skips this requirement.
The saved model's translated control context is checked again against the preview.

When no source is verified, the scoped edit remains ready but a specific warning
sets plan, companion and published `simulation_ready: false`. It does not add or
rewire managers or invent a supply setpoint. Custom/EMS control must be verified
separately; manager presence alone is not a reference-chain or runtime EMS audit.
The [EnergyPlus 25.2 source](https://github.com/NatLabRockies/EnergyPlus/blob/v25.2.0/src/EnergyPlus/MixedAir.cc#L2389-L2419)
checks the mixed-air single temperature setpoint for continuous-fan economizers,
reports “Missing temperature setpoint for economizer controller”, and allows an
EMS-managed node temperature setpoint. Our static check conservatively flags
sources it cannot verify rather than claiming every absent-manager case must fail.

E2 is addressed for saved and reported requested settings: numeric values use
`rel_tol=1e-9` and `abs_tol=1e-9`, matching the fan/pump editors. Nulls, enums,
identities and protected raw fields remain exact; source/plan hashes and fresh
preflight comparison are unchanged. Tiny rounding does not authorize changes to
unrequested fields.

Seventeen new regressions cover missing control in VAV/CAV with newly enabled or
already active economizers; propagation through apply; direct and generated
managers; humidity-only/dual-setpoint rejection; disabled economizers; NodeLists
versus reference nodes; a load-controlled unitary case; and tiny versus material
numeric changes, nulls and enums. The user's review/probe files remain unchanged;
round-19 P1 intentionally asserts the earlier silent-readiness behavior and is
superseded by these new regressions.

Verification: **283 distinct targeted checks passed** across two batches:
225 selected economizer/coil-conversion/coil-relocation/fan-replacement regressions
(20 native/relocation cases deselected), and 121 economizer/packaging/host-adapter
checks (67 economizer, 54 packaging; 63 economizer cases overlap the first batch).
This includes all 17 new regressions, four native economizer before/after runs,
and doctor/inventory/preflight/apply in independently relocated Claude/Codex
bundles. Both exported economizer skills pass validation. Changed-file Black
(Python 3.10 target) and whitespace checks pass. Full CI and the deselected
coil/fan native cases were not rerun.

Evidence: `outputs/economizer-review-e1/evidence.json`; new native SQL/IDF/logs and
relocated bundles: `outputs/economizer-review-e1/final/`. The native VAV/CAV OA
response agrees with the original phase 10a evidence, with no Severe/Fatal errors.

```bash
.venv/bin/python -m pytest -q tests/test_economizer.py \
  tests/test_coil_conversion.py tests/test_coil_relocation.py \
  tests/test_supply_fan_replacement.py \
  -k 'not native and not relocated and not bundle' --maxfail=1
mkdir -p outputs/economizer-review-e1
.venv/bin/python -m pytest -q tests/test_economizer.py \
  tests/test_harness_asset_manifest.py tests/test_sdk_import_closure.py \
  tests/test_skill_resource_exports.py tests/test_openstudio_claude_code_adapter.py \
  tests/test_openstudio_codex_adapter.py \
  --basetemp outputs/economizer-review-e1/recheck --disable-warnings --maxfail=1
```

Re-export affected plugins and regenerate reviewed economizer plans: the control
context is now part of the fresh-plan comparison. E1/E2 are addressed and ready
for review. No commit, push, installation or release is included.

## Phase 10b — minimum outdoor-air and ZoneSum DCV editing, October 9, 2026

Phase 10a/E1–E2 has progressed through review. This phase adds the independent
`openstudio-ventilation-editor` with direct skill-bound execution. It changes
explicit settings on the existing OA/MV controllers. Zone OA definitions, People,
occupancy schedules, sizing, economizer, equipment, topology, metadata and incoming
references stay protected. Phase 10c will settle OA attachment/heat-recovery
rewiring separately; terminals/reheat, broader system recipes and the equipment
backlog remain on the list.

### Standards trace and explicit choices

Reference: local `openstudio-standards` commit
`8bad404ef113019661fc0c14274a3554234219f7`, under
`/Users/xuwe123/github/openstudio-standards/lib/openstudio-standards/`.
`standards/Standards.AirLoopHVAC.rb:2459–2463` does both:

```ruby
controller_oa.setMinimumOutdoorAirFlowRate(0.0)
controller_mv.setDemandControlledVentilation(true)
```

This partial editor exposes those as independent choices. A DCV-only request
retains the old minimum and warns about masking floors; no reset or zoning policy
is inferred. The helper's comments discuss converting non-DCV zone OA to area-only;
this bundle preserves all zone definitions and makes no claim to implement that
whole template policy. The multizone optimization helper at 1940–1960 changes the
MV method to VRP; method redesign is outside this ZoneSum contract. The damper
helper at 2830–2910 distinguishes occupancy-based minimum-flow scheduling from a
minimum OA fraction.

`thermal_zone/thermal_zone.rb:633–697` computes per-person, area, fixed and ACH
terms, combined by each space's Sum/Maximum method. The review evidence follows
that nominal calculation, resolves inherited SpaceType OA/People and applies
zone multipliers once. It excludes schedule coincidence, distribution
effectiveness and exhaust. It is not a ventilation-compliance calculation.

The [EnergyPlus 25.2 controller reference](https://bigladdersoftware.com/epx/docs/25-2/input-output-reference/group-controllers.html)
explains independent controller floors, ZoneSum occupancy-based requests and
fraction/max-flow overrides. The plan reports schedule roles, rather than treating
minimum-flow and minimum-fraction schedules as interchangeable. Existing MV
availability, force-economizer/high-humidity controls and OA/MV EMS actuators are
visible as retained controls; program execution is not inferred.

### Contract and review map

| File | Review focus |
| --- | --- |
| `skills/openstudio_ventilation_editor.md`, `references/ventilation.md` | Independent operation, explicit user choices, NLR priority, exact-release doctor, readiness warnings and direct execution |
| `references/ventilation.schema.json`, `edit_ventilation.py` | Strict partial flow/schedule/DCV contract; canonical inventory/plan/apply report files |
| `common/ventilation_equipment.py` | Shared explicit flow/limit/schedule/DCV setters; no constructor, implicit floor reset or node rewiring |
| `common/outdoor_air.py` | Shared direct-OA selection, controller context and translated mixed-air setpoint check; read MV UUID from raw IDF reference |
| `common/ventilation_context.py` | Bounded schedule ranges including explicit special days; inherited OA/People, nominal space terms and zone multipliers |
| `common/ventilation_edit.py` | Preview/protected-state check, effective floors/caps, occupancy/sizing/control warnings and seven independent saved checks |
| `common/air_loop_components.py` | VAV/CAV use the canonical ventilation setters inside the existing parent transaction, retaining recipe defaults |
| `harness/asset_manifest.yaml`, prompt/orchestrator/SDK-editor skills | Self-contained relocated bundles and routing; no substitute scripts or runtime dependency |
| `tests/test_ventilation.py` | Every field, explicit schedule resets/Autosize/DCV disable, occupancy/sizing/cap warnings, corruption rejection, source/hash protection, native behavior and relocated hosts |

Supported settings are minimum/maximum OA flow (m³/s or Autosize), FixedMinimum/
ProportionalMinimum, three existing schedule references (null explicitly resets),
and a DCV boolean on an existing uniquely owned ZoneSum MV controller. Flow/
schedule-only edits preserve other MV methods. Shared/dedicated OA, split supply,
CO2/IAQ/VRP DCV policy and OA/heat-recovery rewiring require separate coverage.

Selected schedules must already have compatible dimensionless type limits and
be Constant/Ruleset with every value in [0,1], including rules and explicit holiday,
custom and design days. SDK setters attach type limits to untyped schedules; the
plan refuses that unrequested mutation. A cloned preview additionally catches
SDK side effects before readiness. Schedule contents and type limits remain
unchanged. Full details stay in the saved report; console inventory caps each
category at eight, impact caps zone rows at six and EMS references at four.

A ready edit can still be unready to simulate. Specific warnings propagate through
plan, companion and apply for conflicting/zero caps, fixed OA/supply limits below
nominal zone requirements, a floor above fixed design OA, 100% fraction OA with
incompatible sizing flags, missing/unverified DCV occupancy/OA schedules, occupancy
above design counts, and missing enabled-economizer temperature control. Nonzero/
autosized floors, fractional caps, constant occupancy and MV availability also
receive review warnings. Sizing is preserved and must be reviewed separately.

All requested setters run in place. Saved getters must match the effective plan;
identities, raw protected fields/objects, ownership, supply order, zone/occupancy/
sizing and translated-control context are independently rechecked. Numeric saved
comparisons use 1e-9 relative/absolute tolerance; hashes, enums and raw protected
state remain exact. Geometry aggregates use 12 significant digits to suppress
last-bit SDK summation changes across reloads. Thirty repeated native-fixture
preflights produced identical reports. Translation precedes publication of the
copied OSM/companion. Stale/tampered plans and unrelated mutations do not publish.

The shared OA extraction also fixes the mechanical-ventilation context lookup:
OpenStudio `getString()` returns a referenced object's name, whereas UUID lookup
needs `idfObject().getString()`. Economizer plans now show their retained MV
controller/method/DCV instead of a missing context. Re-export affected bundles and
regenerate plans for that corrected report contract.

### Native evidence and verification

Five-zone hydronic VAV and CAV cases use Sum OA, positive people/area requirements,
explicit People with 10%/100% occupancy periods, NoEconomizer and a zero controller
floor. Each paired design-day run changes only DCV; output variables are added to
separate disposable instrumented copies. SQL excludes warmup, compares aligned
hourly requested/actual OA and verifies equal full-occupancy MV requests.

| Case | Low / full occupancy hours | Minimum low-occupancy request ratio | Minimum actual OA ratio | Severe/Fatal |
| --- | --- | --- | --- | --- |
| VAV | 36 / 36 | 0.118033 | 0.219791 | 0 / 0 |
| CAV | 36 / 36 | 0.118033 | 0.118033 | 0 / 0 |

Ratios compare DCV with the unchanged non-DCV baseline at corresponding hours.
They are fixture observations, not annual savings or proof of ventilation
compliance. Actual OA need not equal the MV request because other controls and
flow resolution remain active. No plant, zone, coil, sizing or economizer change
was used to produce this comparison.

**259 distinct targeted checks passed:** 57 ventilation, 67 economizer, 81 VAV/CAV
and 54 manifest/import/resource/host-adapter checks. The first batch passed 257;
two additional boundary/reference regressions passed, followed by all 57 final
ventilation tests after the warning refinement. Included are four DCV and four
economizer before/after native runs, two existing CAV sizing runs, and independent
relocated operation bundles for both hosts. Eight exported skills (ventilation,
economizer, VAV and CAV for both hosts) pass skill validation. Changed-file Black
and whitespace checks pass. Full CI, Linux/Windows native execution, annual
performance, whole-building ventilation adequacy and live-agent token savings
were not tested in this phase.

Evidence is under `outputs/ventilation-phase10b/`: `final/` contains the combined
regression/native run, `verification/` contains the final ventilation suite and
native SQL/IDF/logs, `exports/` has reviewable host plugins, and `evidence.json`
summarizes counts and native observations. Regenerate local exports before
agent trials; installed cached plugins do not update automatically.

```bash
mkdir -p outputs/ventilation-phase10b
.venv/bin/python -m pytest -q tests/test_ventilation.py tests/test_economizer.py \
  tests/test_vav_apply.py tests/test_cav_system.py \
  tests/test_harness_asset_manifest.py tests/test_sdk_import_closure.py \
  tests/test_skill_resource_exports.py tests/test_openstudio_claude_code_adapter.py \
  tests/test_openstudio_codex_adapter.py \
  --basetemp outputs/ventilation-phase10b/recheck --maxfail=1
```

Phase 10b is ready for review. Next is 10c OA topology/heat recovery with a separate
attachment/rewiring contract. Existing user review/probe files remain untouched;
no commit, push, installation or release is included.

## Phase 10b V1 — explicit DCV floor effectiveness, October 9, 2026

The review asked for a direct ineffective-DCV warning and an impact flag when the
controller floor prevents OA reductions. Added both, with a correction established
by native evidence: OpenStudio 3.11.0 translates an OSM Autosize minimum to zero
when its mechanical-ventilation controller has DCV enabled. An unchanged Autosize
floor therefore does not by itself prevent DCV in these VAV/CAV cases. The first
native test expecting unchanged actual OA failed, prompting inspection of the
actual IDF rather than weakening that assertion's tolerance.

For the same OSM Autosize field, the generated `Controller:OutdoorAir` field is:

```text
Before DCV: Autosize,  !- Minimum Outdoor Air Flow Rate {m3/s}
After DCV:  0,         !- Minimum Outdoor Air Flow Rate {m3/s}
```

A direct host SDK forward-translation probe also returns zero with Autosize/DCV
and preserves an explicitly fixed numeric minimum. The editor keeps the OSM
minimum unchanged and records the translated value; it does not run an implicit
minimum-flow setter. The standards helper's explicit zero remains a valid explicit
choice, but its use alone cannot establish that this pinned SDK needs it.

`common/ventilation_edit.py` now resolves the selected translated OA controller and
reads **Minimum Outdoor Air Flow Rate** by field name. Missing/ambiguous objects,
missing fields or invalid numbers produce a descriptive verification error.
`retained_context.translated_minimum_flow_m3_s` is recomputed after save/reload.
The bounded impact exposes `dcv_effective` and `dcv_floor`, including declared and
translated minima, the schedule's lower bound, nominal design OA and minimum type.

| Effective condition | Report |
| --- | --- |
| FixedMinimum scheduled floor at/above positive nominal ZoneSum design OA | `dcv_effective: false`; “DCV will have no effect on outdoor-air reductions”; explicitly name `minimum_flow_m3_s` (for example 0) to allow reductions |
| Positive floor below nominal design OA | Keep the qualified “can mask DCV” warning; no assertion that all reductions are blocked |
| Retained Autosize translated to zero | State both values and that this controller floor does not block reductions; other controls remain relevant |
| Varying/unverified schedule or ProportionalMinimum | Do not assert a persistent blocking floor; retain qualified warnings |
| DCV off | `dcv_effective: false` with before/after DCV showing disabled |
| Other enabled cases | `dcv_effective: null` means effectiveness is not established; it does not promise a benefit |

The flag is a scoped controller-floor diagnostic, not an annual-performance or
whole-ventilation certificate. Fraction schedules, caps, exhaust and EMS still
matter. No additional readiness gate, floor reset, sizing change or approval is
introduced. Existing source/model preservation and fresh-plan binding apply.
The skill/reference document the diagnostic and the SDK translation exception.

Verification: **108 distinct targeted checks passed**: all 77 ventilation checks
(including 20 additional parameterized cases) and 31 manifest/import/resource
checks. This is 102 non-native checks plus six native cases, totaling twelve
paired design-day simulations. Both independently relocated host bundles execute
inventory/preflight/apply; both exported ventilation skills validate and their
changed resources match source. Changed-file Black and whitespace checks pass.
Full CI, surrounding equipment native suites and annual performance were not rerun.

Each native case compares DCV-off/on, 36 low-occupancy and 36 full-occupancy hours,
with identical full-occupancy MV requests and no Severe/Fatal errors:

| Floor retained in OSM | VAV minimum actual OA ratio | CAV minimum actual OA ratio | Impact effectiveness |
| --- | --- | --- | --- |
| Zero | 0.219791 | 0.118033 | null |
| Autosize | 0.219791 | 0.118033 | null; translated minimum is zero |
| Fixed nominal design OA | 1.000000 | 1.000000 | false |

Low-occupancy MV requests reach 0.118033 of the baseline in all six cases. With a
fixed design floor, actual OA matches before/after at every compared hour despite
that smaller request. Zero and Autosize cases show reductions; the assertions
check actual airflow rather than only the requested value. Native inputs, IDFs,
SQL and logs are in `outputs/ventilation-review-v1/native-verified/`;
`evidence.json` records results and `exports/` holds current host plugins.

```bash
mkdir -p outputs/ventilation-review-v1
.venv/bin/python -m pytest -q tests/test_ventilation.py \
  tests/test_sdk_import_closure.py tests/test_harness_asset_manifest.py \
  tests/test_skill_resource_exports.py \
  --basetemp outputs/ventilation-review-v1/recheck --maxfail=1
```

Re-export the ventilation skill and regenerate reviewed ventilation plans for
this added translated context/impact. User review/probe files remain untouched;
round-20 P2's old generic Autosize-warning assertion is superseded by these
regressions. V1 is addressed with the verified Autosize correction. Phase 10c
remains the next checkpoint; no commit/push/install/release is included.

## Phase 10c — direct OA attachment and heat recovery, October 9, 2026

Phase 10b/V1 has progressed through review. This increment adds independent
`openstudio-outdoor-air-connector` and `openstudio-heat-recovery-editor` skills.
It keeps the earlier split between in-place equipment edits and topology changes.
Configured compatible NLR remains preferred; local scripts bind directly to each
skill and require the package's exact OpenStudio release.

### Source trace and deliberate differences

Reference: local standards commit `8bad404ef113019661fc0c14274a3554234219f7`,
under `lib/openstudio-standards/`:

| Source | What was traced | Bundle decision |
| --- | --- | --- |
| `standards/Standards.AirLoopHVAC.rb:1809` | ERV attachment uses `erv.addToNode(oa_system.outboardOANode.get)`; later supplies frost, lockout, bypass and pretreat controls | Use this SDK attachment only on empty direct OA/relief paths; verify both streams and all connection changes |
| `Standards.AirLoopHVAC.rb:1845` and `1862` | `erv.setSupplyAirOutletTemperatureControl(true)` and `spm_oa_pretreat.setReferenceSetpointNode(mixed_air_node)` | Outlet control is explicit. False adds no manager; true creates pretreat with explicit limits and a verified translated mixed-air reference, rather than a fixed hot SAT |
| `Standards.AirLoopHVAC.rb:1777`, `1849`, `1879`, `1902` | Generic rotary type, ExhaustOnly frost parameters, bypass selected by all-OA sizing flags, template efficiency hook | Require explicit choices; no hidden template or climate policy |
| `hvac/components/create.rb:25`, `103` and `modify.rb:15` | HX factory and four normalized effectiveness tables for SDK >=3.8; legacy 75% setters for older SDK | Use four 100% scalars plus four tables in 3.11; no deprecated 75% setters |
| `create.rb:142` | Independent-variable interpolation/extrapolation are Linear | Explicit two-point policy interpolates between .75 and 1, with Constant extrapolation outside. This intentionally avoids effectiveness outside [0,1] from extrapolation |
| `prototypes/common/objects/Prototype.HeatExchangerAirToAirSensibleAndLatent.rb:15` | Prototype power selects nominal/autosized/minimum OA and uses assumed fan efficiency 0.5; line 67 estimates pressure-loss/wheel power | Require explicit nominal power; preserve existing fan pressure, explain pressure-loss energy and double counting |
| `Prototype.hvac_systems.rb:1944` and `2656` | VAV/CAV OA controller, ZoneSum MV and OA-system construction | Reuse ventilation setters/review for independent intake attachment; do not change parent builders or zone OA policy |

EnergyPlus documents a required outlet setpoint when HX temperature control is
active, frost taking priority and economizer lockout affecting recovery.
[EnergyPlus 25.2 heat recovery reference](https://bigladdersoftware.com/epx/docs/25-2/input-output-reference/group-heat-recovery.html).
The translated managers, not just the OSM manager list, are checked. OpenStudio
can generate a MixedAir outlet setpoint when a supply-temperature source exists.
Removing only a pretreat manager therefore does not necessarily remove control.

### Supported operations and review boundaries

| Operation | Explicit input / retained state | Verification |
| --- | --- | --- |
| Attach direct OA intake | Served unsplit loop without OA, inlet directly followed by fan/coil; explicit complete ventilation choices, MV availability, ZoneSum, NoEconomizer and bypass | Retain equipment/loop/terminal/node handles, loads and sizing; change only two boundary fields; freeze new OA/controller/MV fields and whole graph |
| Attach sensible/latent HX | Existing uniquely owned direct OA; nodes only on intake and relief paths; explicit type, availability, flow/power, eight effectiveness values, part-load policy, frost, lockout, bypass and outlet-control choice | One HX joins both streams; two new nodes, four tables and variable lists, one independent variable, optional pretreat; all created fields and connections must match preview |
| Edit existing HX | Exact selected sensible/latent HX on both streams; explicit partial settings | Preserve HX, curves, controls, nodes, connections, metadata, costs and EMS references. 100% effectiveness edits scale retained curves; show those curves and reject known table effectiveness outside [0,1] |

The new intake starts with the explicitly chosen NoEconomizer, ModulateFlow and
NoLockout; its SDK cutoff fields are inactive. Economizer enablement is a later
independent editor operation, including translated-control review. OA schedules
reference existing typed Constant/Ruleset [0,1] objects; null explicitly clears a
controller reference. Zone OA/People, schedule contents and system sizing are
retained. DCV never silently zeroes its floor; the phase-10b occupancy, cap, floor
and sizing review is reused.

In-place HX edits add no OSM managers or curves. Missing effective outlet control
or an enabled economizer's mixed-air setpoint marks simulation unready; a bounded
copied edit can still proceed with the warning. New pretreat attachment requires
its reference to be verified before readiness. Both inlet and relief topology
are inspected, rather than assuming that primary attachment alone worked.

All operations use the existing hash-bound transaction and companion packaging.
New-object UUIDs and connection identities are normalized by named roles and
edge endpoints so two previews compare exactly. New fields, retained permitted
boundary/controller fields, object counts, removed objects and the full graph
are independently checked after saving. Unrequested fans, curves, bypass changes,
zone/People/sizing edits and metadata changes prevent publication. Workflow-only
weather may fill empty climate metadata, independently checked against the
hash-bound EPW. Forward translation precedes exclusive publication of a new OSM
and `<stem>/` companion; source bytes stay unchanged.

Shared/dedicated OA, zone ERVs, embedded equipment, extra OA-path coils/fans,
replacing an existing HX, pressure networks and ventilation/code policy remain
outside this bounded increment. No automatic fan-pressure adjustment or resizing
is implied. Availability, relief-flow limits and frost strategy affect performance;
frost recirculation interrupts outdoor ventilation. Part-load data and power must
come from the intended equipment, rather than treating test values as recommended.

### Review map and reproduction

- Skills: `skills/openstudio_outdoor_air_connector.md`,
  `skills/openstudio_heat_recovery_editor.md`.
- Entrypoints: `skills/sdk_scripts/attach_outdoor_air.py`,
  `skills/sdk_scripts/manage_heat_recovery.py`.
- Contracts/schemas: `skills/sdk_scripts/references/outdoor_air_attach.*` and
  `heat_recovery.*`.
- Mechanics: `common/outdoor_air_attach.py`, `heat_recovery.py`,
  `outdoor_air_topology.py` under `skills/sdk_scripts/`; existing scoped graph,
  model preservation, translated control and ventilation helpers are reused.
- Routing: manifest, agent prompt, orchestrator, SDK editor and existing OA editors.
- Tests: `tests/test_outdoor_air_attach.py`, `tests/test_heat_recovery.py`.

```bash
.venv/bin/python -m pytest -q tests/test_heat_recovery.py \
  tests/test_outdoor_air_attach.py tests/test_sdk_import_closure.py \
  tests/test_harness_asset_manifest.py tests/test_skill_resource_exports.py \
  tests/test_openstudio_claude_code_adapter.py \
  tests/test_openstudio_codex_adapter.py \
  --basetemp outputs/heat-recovery-phase10c/recheck --maxfail=1
```

Initial verification: **109 targeted checks passed**, including 55 new operation checks,
31 import/manifest/resource checks and 23 host-adapter checks. Eight new checks
run native design-day simulations, and six independently relocate an owning
Claude/Codex skill before doctor, inventory, preflight and apply. Each moved
bundle runs after the original export is deleted. Four exported new skills
(two per host) pass skill validation. Host Python is 3.13.7; embedded Python 3.12,
OpenStudio 3.11.0 and EnergyPlus 25.2 remain unchanged.

| Native mode, both VAV/CAV | Maximum sensible heating recovery, VAV / CAV | Maximum sensible cooling recovery | Maximum HX electricity |
| --- | --- | --- | --- |
| Outlet control off | 3,143 / 3,052 W | 2,038 / 2,037 W | 100 W |
| OutdoorAirPretreat | 6.60 / 6.60 W | 2,038 / 2,037 W | 100 W |
| Forced economizer, HX lockout enabled | 0 / 0 W | 0 / 0 W | 0 W |
| Newly attached intake, then HX without outlet control | 3,143 / 3,052 W | 2,038 / 2,037 W | 100 W |

All eight runs have no Severe/Fatal errors. Recovered watts alone do not measure
useful recovery or savings. Pretreat limits recovery to the mixed-air setpoint's
need. W1's paired coil-energy checks below show that nearly all additional winter
heat recovered with outlet control off is removed by downstream cooling. The
uncontrolled option therefore causes heat-then-cool in these fixtures; its larger
recovery rate is not a benefit. Review explicit control and bypass choices.
Lockout checks require economizer status active and both thermal recovery and
HX power zero. The two new-intake cases exercise sequential independent operations.
These are design-day operational checks; annual savings, defrost operation under
cold-climate weather, air balance and compliance remain unverified. Full CI and
Linux/Windows native runs were not repeated.

Artifacts: `outputs/heat-recovery-phase10c/verification/` retains models, reports,
IDFs, SQL, native evidence and CLI logs; `evidence.json` summarizes the native
runs and checks; `exports/` contains current full host plugins. Re-export hosts
for the new skills and regenerate plans after script/contract changes. User review
and probe files are untouched. Phase 10c is ready for review; terminals/reheat and
plant-equipment operations remain on the equipment backlog. No commit, push,
plugin installation or release is included.

### Phase 10c W1 — uncontrolled recovery and coil-energy comparison

The original peak-recovery comparison was insufficient to judge performance.
With a 12.8 °C supply target and downstream cooling, recovering more heat can
add cooling load. The warning now uses the effective settings on attachment and
in-place edits, including a power-only edit that retains outlet control off.
A downstream cooling coil, or a verified scheduled supply range below verified
served-zone heating-setpoint minima, triggers a heat-then-cool warning when HX
outlet control is off. The schedule-range screen does not prove coincident hours.
Impact records `uncontrolled_recovery_cooling_risk` and its equipment/schedule
context; saved validation rechecks that context. Review explicit pretreat and
bypass/economizer choices. No control is changed implicitly, no extra approval is
required, and the warning adds no simulation-readiness gate.

The native comparison now requests summed coil/recovery energy, HX electricity
and mixed-air temperature/setpoint. It separates each design day and excludes
warmup. Both cases use the same fixture parameters, each with its own sizing run.
These are **thermal loads in kWh**, rather than fuel/input energy or net HVAC
energy. Central heating and zone reheat are separately reported.

| Winter design-day case | Sensible heating recovered | Central cooling load | Central heating load | Zone reheat load | HX electricity |
| --- | ---: | ---: | ---: | ---: | ---: |
| VAV, outlet control off | 75.432 | 82.632 | 0.000 | 246.315 | 2.400 |
| VAV, pretreat | 0.076 | 7.275 | 0.000 | 246.314 | 2.400 |
| CAV, outlet control off | 73.114 | 89.172 | 0.000 | 230.172 | 2.400 |
| CAV, pretreat | 0.076 | 16.133 | 0.000 | 230.172 | 2.400 |

Additional cooling with outlet control off is **75.357 kWh (VAV)** and
**73.039 kWh (CAV)**, almost exactly the additional recovered heat. Heating and
reheat remain essentially unchanged; HX electricity stays 2.4 kWh. Maximum
mixed-air temperature above its setpoint falls from 6.315 to 0.556 K (VAV) and
6.841 to 1.248 K (CAV). Pretreat avoids the unnecessary recovery and associated
cooling load in this comparison; residual cooling remains. This does not establish
annual savings, plant electricity/fuel use or universal optimal controls.

Sixteen new regressions cover VAV/CAV attachment/edit, uncontrolled cooling,
cool-target-only loops, warm heating-only loops and enabled outlet control. Two
paired native checks explicitly assert that additional cooling matches additional
recovery, with essentially unchanged heating/reheat. Four other native checks
retain economizer lockout and new-intake composition coverage: six native checks,
eight simulations in total. Coil energy is collected in every native case.

Verification: **100 targeted checks passed** (69 operation and 31
manifest/import/resource checks), including six moved owning-bundle checks and
the six native checks. Both host exports/resources and their two affected skills
validate. Formatting/whitespace checks pass. Full CI and annual/Linux/Windows
native runs were not repeated. The earlier 109-check batch remains the initial
phase verification; this follow-up does not rerun unchanged host-adapter tests.

```bash
mkdir -p outputs/heat-recovery-review-w1
.venv/bin/python -m pytest -q tests/test_heat_recovery.py \
  tests/test_outdoor_air_attach.py tests/test_sdk_import_closure.py \
  tests/test_harness_asset_manifest.py tests/test_skill_resource_exports.py \
  --basetemp outputs/heat-recovery-review-w1/recheck --maxfail=1
```

Artifacts: `outputs/heat-recovery-review-w1/evidence.json`, `verification/` and
`exports/`. The original phase-10c evidence is retained. Regenerate reviewed
heat-recovery plans for the added warning/control context and refresh both host
exports. User review/probe files are unchanged; round-21 P1's original
no-warning assertion is superseded by the new regressions. W1 is addressed.
No commit, push, installation or release is included.

## Remaining limits and next review

The integration pause has been addressed by increments A–D and their requested
review fixes; equipment development is ready to resume. The October 9
[integration review](SDK_INTEGRATION_SUMMARY.md#status-and-development-rules) reproduces the original-model
removal mismatch, measures exported resource duplication and proposes these
increments before resuming the backlog: reported model preparation/load repairs,
one plugin-local SDK library, automatic reproducible failure reporting to the
harness GitHub repository, then a read-only HVAC visualizer. All four increments
are implemented as recorded below, including Q1/Q2, C1/C2 and D1–D3. The latest
visualizer/export checks cover 100 unique passing cases with no skips. Large VRF
views still require scrolling; pagination is a future presentation enhancement.

The original five-zone result (central HW capacity zero) was caused by the
outdoor-air/sizing mismatch and is superseded by the F1 correction above. Both
corrected native CAV cooling cases require positive central HW and all five zone
reheat capacities. Sizing/report review remains necessary for real models; annual
performance, ventilation adequacy and template/building compliance are unverified.

The equipment functions have VAV/CAV and independent equipment consumers.
Supply-fan performance editing is phase 4; main-supply water-coil operations are
phase 5. Plant migration is phase 6a; phases 6b/6c and phase 7 are implemented
and reviewed. Phase 8 pump performance editing and M1–M2 are reviewed;
phase 9 single-pump class replacement and its follow-ups are approved. Phase 10a
and 10b/V1 have progressed through review. Phase 10c direct intake/recovery
attachment and in-place recovery editing is implemented for review. The
broader equipment backlog above remains intact.
Do not expose unattached component creation as a generally valid published model
operation. Broad PSZ/DOAS/zone-equipment recipes remain future
work. No live-agent token savings have been measured.

No commit, push, plugin installation or release is included in this work.

## Integration increment A — stable prepared copies (October 9, 2026)

Implemented the centralized old/current-unstable model gate, bundled
`prepare_model`, lineage reports, full saved-copy identity/field verification,
and bounded apply mismatch diagnostics. All 16 owning skills and both host
exports can reach the preparation operation. Exact plan/hash/cascade/snapshot
checks, OpenStudio 3.11.0 and NLR-first routing remain intact.

The [increment A review guide](SDK_INTEGRATION_SUMMARY.md#a--deterministic-inputs-and-explicit-preparation) records the
contract, detection rules, prepared-copy report format, genuine fixture
provenance, guard timing, verification counts/native evidence and exact reviewer
commands. A and Q1/Q2 are reviewed; the following integration increment is B.


## Integration increment B — shared SDK packaging (October 9, 2026)

Both hosts now export one plugin-local `sdk/` library and 66 fixed launchers
across the 16 owning SDK skills. Canonical sources remain `skills/sdk_scripts/`.
Launchers verify the library identity and payload hashes and return bounded
`plugin_incomplete` diagnostics if detached or damaged. The complete Git-distributed
plugin remains the install/copy unit; setup/doctor commands gain packaging guidance
without another installation dependency. OpenStudio 3.11.0, NLR-first routing,
preparation gates and exact modeling transactions remain unchanged.

The [increment B review guide](SDK_INTEGRATION_SUMMARY.md#b--shared-sdk-packaging) records the
manifest scope, distribution contract, 1 MiB budget, measured byte accounting and
exact reviewer commands. SDK resources decrease from 2,445,693 comparable
owner-copy bytes to 686,836 bytes before the small size report: **71.9%**.
This is a packaging measurement, not measured AI-token savings.

**272 unique targeted checks passed**: 236 packaging/manifest/import/doctor/
preparation/adapter/CLI/archive checks and 36 native relocated modeling checks.
Both exports and all 32 owning-skill documents validate. The archive test required
network-enabled isolated build dependency resolution after its sandboxed attempt
failed; its rerun passed and the built wheel includes the new shared-export module.
Full equipment/simulation suites were not repeated because SDK modeling Python
sources and their transaction contracts did not change. No Linux/Windows or live
agent-session testing was performed. Logs/evidence are in ignored
`outputs/shared-sdk-increment-b/`.

B is ready for review. C (automatic reproducible failure reporting) follows after
review; D (read-only HVAC visualization) remains on the list. No commit, push,
plugin installation or release; user files under `docs/reviews/` are untouched.


## Integration increment C — automatic failure reporting (October 9, 2026)

Increment B is approved. Both hosts now export `report-openstudio-failure` with
an independent stdlib helper and event schema. The selected policy automatically
submits sanitized, allowlisted diagnostics to `pnnl/openstudio-ai-harness` using
existing GitHub CLI authentication. Issues are created under your own
authenticated GitHub account. Models/companions/transcripts are excluded;
uncertain, offline, disabled or security-sensitive incidents retain local state.
Standard Markdown templates and labels are mapped; unmapped forms stay local.

Shared SDK transaction, VAV and preparation error boundaries persist local
receipts before recovery without changing exact model checks. Both orchestrator
routes and all 16 owning SDK skills invoke reporting for unexpected failures;
resume checks pending receipts. Expected readiness/preparation/input outcomes
remain excluded. Reporter errors never recursively report or gate modeling.
Setup/doctor describe the automatic destination, opt-out and optional readiness.

The [increment C review guide](SDK_INTEGRATION_SUMMARY.md#c--automatic-failure-reporting) records the
contract, bounded data fields, private-input reproduction gaps, receipt and
submission states, failure/duplicate handling, limitations and exact commands.
**451 unique targeted checks passed**, including 45 reporter cases, 170 modeling
regressions, both host adapters and distribution archives. Native fault injection
through each host's public remover launcher retains the original error, records
3.11.0/source/bundle identity and preserves source hashes. Both exported reporters
also operate after `sdk/` is deleted. Both exports and 34 affected skill documents
validate. GitHub writes were mocked; no live issues were submitted.

No full unrelated equipment/annual/native Linux/Windows/live-provider suite was
rerun. Logs/exports/native evidence are in `outputs/failure-reporting-increment-c/`.
New manifest sources are staged for tracking validation, with no commit, push,
plugin installation or release. User `docs/reviews/` remains untouched. C is ready
for review; D (read-only HVAC visualization) is next, then the equipment backlog.

### Increment C review follow-up: C1/C2

Public error messages now use fixed codes/templates, with original messages and
tracebacks held separately in private local evidence. Public stack locations
contain only source-verified plugin file/function/line fields. Legacy receipts
are held before network access, including uncertain/submitted identities.
The automatic reporting instructions and doctor now state that issues are
created under the user's own authenticated GitHub account.

**242 follow-up tests passed, no skips:** 60 reporter and 182 packaging/doctor/
adapter/manifest/resource/import/CLI cases. Five real bundled error paths prove
unquoted company/address/email names stay local. Both native exported remover
fault-injection cases preserve source hashes; both fresh exports and nine changed
SKILL documents validate. Shared resources remain within the 1 MiB budget.
No live issue, commit, push, installation or release. Transaction logic is
unchanged; prior model/archive and full unrelated suites were not repeated.
See the [C1/C2 contract and reviewer commands](SDK_INTEGRATION_SUMMARY.md#c--automatic-failure-reporting)
and `outputs/failure-reporting-c1-c2/evidence.json`. Stop for review; D remains next.


## Integration increment D — read-only HVAC visualization (October 11, 2026)

C and its C1/C2 fixes are reviewed. The new openstudio-hvac-visualizer skill is
implemented for D review, with a single shared SDK graph/renderer and fixed public
launchers for both hosts. JSON records actual connection handles/ports, source
hash/version, SDK, per-zone memberships and coverage. Mermaid/Markdown provide an
overview, complete zone index and selectable air/plant/VRF/zone views. Separate
coil/recovery circuits preserve shared identities; stored controls, containment
and service membership remain distinct from physical flow. Embedded internal air
paths remain unexpanded and warn. Legacy translated port indices are retained;
explicit connection references identify current fields and discrepancies warn.

Read-only inspection preserves source/companions, checks exact in-memory state
and input hash, and requires neither weather nor simulation. Shared preparation,
NLR-first routing, the exact 3.11.0 pin and all transaction comparisons remain
unchanged. Graphs contain private labels and are excluded from public reporting.

317 unique targeted checks passed, no skips: 136 graph/reporting/packaging/
manifest/resource/import, 98 preparation/doctor, 82 adapters/CLI, one archive.
The 21-case visualizer suite includes both relocated native exported launchers.
Both final exports and five affected SKILL documents validate. Original 1.10.0
integration input went through bundled preparation; both exports produced identical
42-zone graphs with all 522 native connections and unchanged source/prepared hashes.
Shared resources remain within 1 MiB. Native inspection records coverage warnings
rather than certifying model validity. See the [D review guide](SDK_INTEGRATION_SUMMARY.md#d--read-only-hvac-visualization)
for the full contract, evidence, limits and exact commands. Logs and local private
artifacts: outputs/hvac-visualizer-increment-d/.

No live host-agent, SVG rendering, annual simulation or native Linux/Windows check;
full unrelated equipment/MCP suites were not repeated. Archive dependency download
failed under restricted network, then passed in an isolated network-enabled retry.
No commit, push, plugin installation, release or live issue submission. User
files under docs/reviews/ are untouched. Stop for D review before equipment E.


### D review refinement — equipment and color views (October 11, 2026)

Diagrams now show equipment and zones, hiding SDK routing objects and controls.
Thermal zones are green, air/secondary equipment blue, water/primary equipment
orange. Directed paths contract only intervening routing objects and retain
parallel branches and separate coil/recovery circuits. equipment_graph.json records
original-edge evidence; full graph.json keeps all handles, ports, controls and
warnings. Overview-only containment folding keeps detailed equipment in per-system
views. The same NLR priority, preparation gates and 3.11.0 pin remain in force.

82 affected tests passed (27 visualizer, 55 packaging/manifest/resource/import),
no skips. Both fresh native exports produce identical equipment views and a full
graph byte-identical to earlier D output; all 522 original connections and source
hash remain intact. Sample loop: 131 → 24 boxes. Updated samples and evidence:
outputs/hvac-visualizer-equipment-review/. See the [D review guide](SDK_INTEGRATION_SUMMARY.md#d--read-only-hvac-visualization).
Unchanged prior preparation/doctor/adapter/archive checks were not repeated. No
commit, push, installation, release, live issue or edits to docs/reviews/.

### D review refinement — airflow direction (October 11, 2026)

Supply/intake now reads left to right above a separate right-to-left return/
relief/exhaust lane. Connected boundaries identify fan roles; actual model order,
including blow-through fans, remains unchanged. Repeated OA/zone boxes are views
of the same model objects. All physical arrows retain original edge evidence.

85 affected checks passed, no skips (30 visualizer, 55 packaging/resources/imports),
with all 30 visualizer cases rerun after fixing lane stacking. Both final exports
validate and yield identical diagrams/equipment JSON. Detailed JSON is unchanged,
all 522 native connections intact. A local Mermaid 11.12.0 render verified all
32 sample airflow directions and supply-above-return placement; PNG inspected.
No new plugin dependency. Final samples: outputs/hvac-visualizer-direction-review/final/.
See the [D airflow review details](SDK_INTEGRATION_SUMMARY.md#d--read-only-hvac-visualization).
Prior unchanged preparation/doctor/adapter/archive batches were not repeated.
No commit, push, installation, release, live issue or edits to docs/reviews/.

### D connected air/DHW refinement — October 12, 2026

The current drawing replaces split lanes with a connected air view: supply left,
one box per zone in the middle, return/exhaust right. OA port views and recovery
streams retain the same assembly handles; open outdoor arrows have native path
evidence. The floating DHW line was a supply/demand bypass route, not district
water. Routing-only bypasses remain in JSON and are omitted with a note; one water
use view and the pump/heater/use/return path remain explicit.

88 affected tests passed, no skips; final corrections reran all 33 visualizer
cases. Both exports and sources validate; native rendering checks 136 air/boundary
and three DHW positions. All 522 raw connections and source hashes remain intact;
the obsolete opaque WaterUseConnections warning clears. Current review gallery:
outputs/hvac-visual-refinement-20261012/review/inspection.html. See the
[D connected-view contract](SDK_INTEGRATION_SUMMARY.md#d--read-only-hvac-visualization).
No new runtime dependency, commit, push, installation, release, live issue or
docs/reviews/ edits. Unchanged prep/doctor/adapter/archive checks were not repeated.

### Increment D review follow-up D1–D3 — October 12, 2026

OA/MV controller ownership is assigned through stored references; hidden-only
groups no longer generate empty diagrams. VRF-contained coils/fans without
external flow fold into indoor-unit labels while both JSON graphs retain them.
Default type names are compact and shared air-loop/VRF zones name other systems.
100 unique affected tests pass, no skips (45 final visualizer + 55 export/resource/
manifest/import); both native exports validate and preserve all 522 connections.
Nine samples render with 139 direction/position checks. Nine-unit VRF height falls
5,366 → 1,742 px; the synthetic 40-unit view still needs vertical scrolling.
Full contract, limitations and reproduction commands:
[Increment D, D1–D3 follow-up](SDK_INTEGRATION_SUMMARY.md#d--read-only-hvac-visualization).
Current gallery: outputs/hvac-visual-review-d1-d3-20261012/review/inspection.html.
No pin, NLR priority, transaction or preparation contract changes; no commits,
pushes, installations, releases, live issues or edits under docs/reviews/.
Stop for visual approval before resuming equipment development.
