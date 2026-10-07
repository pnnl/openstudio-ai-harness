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
| Follow-on | Equipment attach/replace skill interfaces | Define target locations, ownership, protected state and supported replacement before exposing independent mutation | Deferred until system reuse is proven |

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

## Remaining limits and next review

The original five-zone result (central HW capacity zero) was caused by the
outdoor-air/sizing mismatch and is superseded by the F1 correction above. Both
corrected native CAV cooling cases require positive central HW and all five zone
reheat capacities. Sizing/report review remains necessary for real models; annual
performance, ventilation adequacy and template/building compliance are unverified.

The equipment functions now have two system consumers. Independent attach/replace
skills are the next review checkpoint: start with supply-fan replacement, define
supported parent locations and protected state, then water-coil attachment and
controller lifecycle. Do not expose unattached component creation as a generally
valid published model operation. Broad PSZ/DOAS/zone-equipment recipes remain future
work. No live-agent token savings have been measured.

No commit, push, plugin installation or release is included in this work.
