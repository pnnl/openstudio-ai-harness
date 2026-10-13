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
| 5 | Water-coil ratings, attachment and controller lifecycle | Separate in-place edits from node/controller rewiring; explicit placement/plant/ratings; saved identity/topology and native sizing | Implemented and verified |

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

## Phase 5: water-coil operations and controller lifecycle

Two directly bound skills expose three separate contracts:

| Operation | Skill / entrypoint | Identity and connection contract |
| --- | --- | --- |
| Edit ratings | `openstudio-water-coil-ratings-editor` / `edit_water_coil_ratings.py` | Only requested rating setters; coil, four ports, controller, metadata, availability and incoming references keep their handles/settings |
| Attach | `openstudio-water-coil-connector` / `connect_water_coil.py`, `operation: attach` | New coil/controller on an explicit main-supply outlet node and compatible plant demand branch; existing branches/components protected |
| Replace | Same connector, `operation: replace` | Explicit new identity, same water-coil class/air loop/plant, four boundary nodes retained, old controller removed, new controller retargeted/finalized; reference migration excluded |

Initial coverage is CoilHeatingWater/CoilCoolingWater directly on a single unsplit
main supply path. OA streams, unitary equipment, terminal/reheat locations, other
coil classes, plant migration and class conversion remain separate coverage. Rating
changes must not route to replacement. LifeCycleCost and EMS references remain
valid for in-place edits; replacement rejects references needing migration.

Attachment selects a main-supply node with an incoming connection and Temperature
setpoint manager; insertion is immediately upstream. The supply inlet is excluded
because native SDK insertion there has different semantics. The plant must match
Heating/Cooling and have supply equipment, an actual pump, outlet setpoint manager,
finite design supply and positive delta. Both first-demand and additional-demand
attachment are covered. Unselected plant supply and existing demand components are
preserved. Availability is explicit: an existing Availability schedule or builtin.
No plant creation, schedule drafting, system-sizing change or terminal conversion
is implied; compose the independent plant skill when the user requests a plant.

Heating construction requires all four rated water/air temperatures. Cooling
requires inlet-water/inlet-air/outlet-air temperatures, inlet/outlet humidity,
heat-exchanger configuration and analysis method; supported conditions can
explicitly use Autosize. `sizing: Autosize` is the only initial construction sizing
contract, with UA/capacity/water flow (heating) or air/water flow (cooling) reset.
Conflicting manual size fields reject rather than being silently ignored. Partial
rating edits support fixed sizes or Autosize and check the heating performance
method explicitly; there is no automatic method switch or defaults approval flag.
All effective conditions, inferred construction settings and warnings appear in
the saved plan and bounded review summary.

Temperature controller settings are explicit: minimum flow 0, convergence positive
numeric or Autosize, and autosized maximum flow. Heating action is Normal, cooling
Reverse, actuator Flow. Sensor is the coil air outlet; actuator node is water inlet.
Finalization occurs after both connections. This contract uses dry-bulb control;
humidity control and creation of setpoint managers are excluded.

### Source/API trace and graph checks

`Prototype.CoilHeatingWater.rb:31–34` and `Prototype.CoilCoolingWater.rb:27–30`
attach plant demand before the air node. Heating's line 87 warns exactly:
"These inputs will get overwritten if addToNode or addDemandBranchForComponent is
called on the htg_coil object after this". Both routines then finalize the owned
controller. Their temperature setters and CrossFlow/control choices inform the
shared module; inputs remain explicit in the independent connection contract.

Pinned native probes confirmed that manual Model.connect restores coil air/plant
membership but creates no ControllerWaterCoil, and that the controller has no
public standalone model constructor. Replacement therefore clones the owned
controller, retargets its IDD `Water Coil Name` field, preserves all four boundary
nodes through port operations, then verifies its target, ownership, sensor/action/
actuator/flow/convergence after saved reload. A future class/location conversion
must settle a new lifecycle/reference contract before being exposed.

Attachment projects only SDK topology on an isolated handle-preserving model copy.
Existing changes are limited to graph links and connector extensions; non-connection
removal rejects preflight. Saved checks independently require original identities,
exact supply order, original plant supply order, preserved demand components,
expected additions/removals and controller/rating getters. Protected raw-field
fingerprints catch unrequested changes to neighboring equipment, plant sizing,
thermostats, schedules, setpoint managers and metadata. Resource hashes still bind
external files; if workflow weather fills an originally empty OSM WeatherFile, its
metadata must match the bound EPW. Missing weather warns without blocking edits.

### Phase 5 review map and local trial

| Files | Review focus |
| --- | --- |
| `skills/openstudio_water_coil_ratings_editor.md`, `openstudio_water_coil_connector.md` | Intent, provider/version selection, operation split and supported boundaries |
| `skills/sdk_scripts/references/water_coil_ratings.md`, `water_coil_connection.md`, matching schemas | Units, effective rating checks, explicit design/controller/Autosize choices |
| `skills/sdk_scripts/common/coil_equipment.py` | Canonical rating getter/setter vocabulary and controller finalization |
| `skills/sdk_scripts/common/hvac_equipment.py` | VAV/CAV reuse rating/controller setters while retaining parent topology/control behavior |
| `skills/sdk_scripts/common/model_preservation.py` | Shared raw-field identity snapshots; fan editor now consumes this neutral helper |
| `skills/sdk_scripts/common/water_coil.py` | Inventory, separate planners, graph projection, in-place mutation, attachment/replacement and independent saved checks |
| `tests/test_water_coil_operations.py` | Scoped state/ref preservation, plant/design rejection, hostile mutations, stale plans, VAV/CAV fixtures, relocated exports/doctor and native positive sizing |
| `harness/asset_manifest.yaml`, agent/orchestrator/SDK editor | Transitive exports and precise routing; configured compatible NLR still takes priority |

Regenerate the host export, then run the owning skill's doctor and use its verified
executable. Existing fan bundles must also be re-exported because preservation and
coil setters are now explicit transitive resources. Each entrypoint has inventory,
config preflight and reviewed-plan apply modes with its own `--report` file:

```text
<verified-cli> execute_python_script <skill>/scripts/edit_water_coil_ratings.py --input <input.osm> --config <ratings.json> --report <ratings-plan.json>
<verified-cli> execute_python_script <skill>/scripts/edit_water_coil_ratings.py --plan <ratings-plan.json> --report <ratings-apply.json>
<verified-cli> execute_python_script <skill>/scripts/connect_water_coil.py --input <input.osm> --config <connection.json> --report <connection-plan.json>
<verified-cli> execute_python_script <skill>/scripts/connect_water_coil.py --plan <connection-plan.json> --report <connection-apply.json>
```

Omit `--config` in input mode for inventory. Node candidates are flat and stdout
shows at most eight per category; complete candidates/fingerprints stay on disk.
Source hashes, fresh-plan equality, resources, saved validation and EnergyPlus
translation are checked before exclusive publication of an output copy. Keep its
OSM and `<stem>/` companion together; simulation is a separate requested workflow.

Phase 5 verification: **386 combined tests passed**, including **97** water-coil
cases. Twelve native design-day runs cover Heating/Cooling × edit/attach/replace ×
VAV/CAV; every selected coil has positive design capacity, with no Severe/Fatal
errors. Both independently relocated Claude/Codex bundles passed pinned doctor,
preflight and apply. Saved tests cover identity/reference preservation, metadata,
first/additional demand branches, incompatible SDK, explicit rating methods,
input conflicts, stale/tampered/cross-operation plans, unrequested mutations,
bounded inventory and weather absence/hydration. Existing VAV/CAV/fan/plant/removal,
manifest tracking, import closure, reports and host exports also pass.

All four phase-5 edited/new skills passed exported skill validation; 17 changed
Python files passed formatting, and staged/unstaged changes passed whitespace
checks. Native evidence and CLI/EnergyPlus logs are retained locally under the
ignored `outputs/water-coil-phase5-review/`; `evidence.json` records all twelve
cases and their capacities. Attachment fixtures use explicitly fixed cooling
air/humidity design conditions, while edit/replacement fixtures retain their
autosized conditions; their capacities are not matched before/after comparisons.
For actual system design-day sizing, prefer explicit Autosize air/humidity inputs
unless fixed design conditions were requested, and review outdoor-air compatibility. The earlier VAV-only probe artifacts remain under
`outputs/water-coil-phase5-native/`. Fixtures demonstrate correctness of these
bounded operations, without an annual-performance or savings claim.

```bash
.venv/bin/python -m pytest -q tests/test_water_coil_operations.py \
  tests/test_supply_fan_performance.py tests/test_cav_system.py \
  tests/test_sdk_import_closure.py tests/test_vav_apply.py \
  tests/test_vav_preflight.py tests/test_vav_sizing.py \
  tests/test_plant_and_removal_bundles.py tests/test_harness_asset_manifest.py \
  tests/test_skill_resource_exports.py tests/test_openstudio_claude_code_adapter.py \
  tests/test_openstudio_codex_adapter.py tests/test_skill_sdk_report.py \
  tests/test_skill_vav_evaluation.py --disable-warnings --maxfail=1
```

The next review should assess these three contracts and placement/sizing choices.
Further location coverage and migrations require a new checkpoint; annual savings,
manufacturer validation and Linux/Windows native execution remain unverified.

## Remaining limits and next review

The original five-zone result (central HW capacity zero) was caused by the
outdoor-air/sizing mismatch and is superseded by the F1 correction above. Both
corrected native CAV cooling cases require positive central HW and all five zone
reheat capacities. Sizing/report review remains necessary for real models; annual
performance, ventilation adequacy and template/building compliance are unverified.

The equipment functions have VAV/CAV and independent equipment consumers.
Supply-fan performance editing is phase 4; main-supply water-coil operations are
phase 5. Review the bounded contracts before adding more locations or migrations.
Do not expose unattached component creation as a generally valid published model
operation. Broad PSZ/DOAS/zone-equipment recipes remain future
work. No live-agent token savings have been measured.

No commit, push, plugin installation or release is included in this work.
