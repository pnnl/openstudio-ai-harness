# Skill-bound SDK scripts development plan

Updated: October 4, 2026. Development branch: `enhance_skills_scripts`.

## Agreed direction

Ship reviewed SDK scripts with their owning skills. Claude Code and Codex execute
them directly through host tools; model edits do not pass through the OpenStudio
AI MCP runtime or measure registry. Keep common helpers in one canonical source
location and copy them into skill bundles during export. Keep agent context small:
load the skill and argument contract, not implementation code during normal runs.

Require one explicitly tested OpenStudio release. Doctor may discover installed
executables but must select only the required version. Every executable SDK
script must independently verify its executing SDK before model mutation. Do not
fall back to an incompatible CLI, Python binding, or project environment.

The user selected OpenStudio **3.11.0** for phase 2. Build metadata is permitted;
prereleases and other patch releases are rejected. Discovery supports macOS,
Linux, and Windows; native execution has been verified on macOS only.
Existing simulation/results MCP capabilities remain outside this SDK-edit scope.

## Review phases

| Phase | Deliverable | Acceptance check | Status |
| --- | --- | --- | --- |
| 1 | Manifest-driven skill resource export for both hosts, including nested scripts, shared helpers, and schemas | Export parity, dry-run accuracy, exact file preservation, execution from a relocated bundle without the runtime, and invalid resource rejection | Complete; ready for review |
| 2 | A standalone SDK doctor, one compatibility contract, and a shared version guard | Required release passes; missing, mismatched, unrecognized, and conflicting CLI/SDK versions block; scripts check again before editing | Complete; ready for review |
| 3 | Script-bound VAV preflight and resolved input plan | Resolve objects deterministically; validate units and conditional inputs; list assumptions and conflicts; inspection never edits the input | Complete; ready for review |
| 4 | Tested VAV creation helpers, apply entrypoint, and independent topology validation | Preserve original; check SDK setter results and loop/zone connections; no published output after failure; duplicate execution has explicit behavior; sizing smoke check | Pending |
| 5 | Skill routing updates and end-to-end evaluation | Both hosts follow the scripts; no routine code drafting or incompatible fallback; compare total tokens, retries, elapsed time, topology, and sizing against the current workflow | Pending |

Each phase ends with a reviewable diff and focused checks. Stop at the phase
boundary so the user can steer the next phase. Do not edit generated marketplace
exports as sources or install OpenStudio during phase 1.

## Phase 1 design

Extend the canonical asset manifest with optional `resources` entries. Each entry
declares one source file and owning skills/hosts with an explicit destination
relative to the skill folder. Copy resources verbatim, preserving file modes and
nested paths. Shared files can declare multiple owners. Existing Markdown
reference handling remains separate because it removes YAML frontmatter.

Reject missing files, paths outside the source checkout, unsafe destination paths,
and collisions with skill documents, reference exports, or generated setup files.
Use fixture scripts to test exports; real SDK entrypoints arrive in phase 2.

## Verification and continuity

Phase 1 focused checks:

```bash
.venv/bin/python -m pytest -q tests/test_harness_asset_manifest.py
.venv/bin/python -m pytest -q tests/test_skill_resource_exports.py \
  tests/test_openstudio_codex_adapter.py tests/test_openstudio_claude_code_adapter.py
```

Record completed checks, limitations, and the next review step here and in
`HANDOFF.md`. Preserve unrelated working-tree changes.

### Phase 1 result

- Added optional resource declarations to manifest version 3; existing manifests
  without resources remain supported.
- Both adapters plan and copy resources with the same validation. No MCP runtime
  execution is involved in the exported fixture scripts.
- Focused verification: 51 tests passed across manifest, resource export, Codex
  adapter, and Claude Code adapter suites. Resources execute after relocation and
  deletion of their source tree using Python `-S` (installed packages excluded).
- Tests cover local/marketplace modes, shared ownership, bytes and modes, unsafe
  paths, missing files, symlink escapes, host restrictions, and collisions.
- Formatting completed; the final check explicitly targets supported Python 3.10
  syntax. Production SDK resources are not yet registered. No OpenStudio install,
  model edit, simulation, or live host invocation was performed.
- Next: review phase 1, then select the exact release and platforms for phase 2.

### Phase 2 result

- User selected exact release 3.11.0. `skills/sdk_scripts/compatibility.json`
  is the canonical contract, exported beside doctor and SDK scripts.
- `doctor.py` uses standard-library host Python and verifies both CLI identity
  and the selected CLI's embedded Python SDK/model binding. It returns structured
  JSON and exit 0 only when both pass. Failure returns exit 2 and installation
  guidance. No model editing, installation, configuration writes, MCP access,
  or OpenStudio AI runtime imports occur.
- `--openstudio` and `OPENSTUDIO_PATH` are authoritative; they never silently
  fall back. Automatic discovery considers version-specific locations and PATH,
  accepting only the exact contract release. Embedded probes remove inherited
  PYTHONPATH/PYTHONHOME and report the SDK module path for evidence.
- `common/version_guard.py` rechecks the executing SDK before every model
  operation. `sdk_probe.py` demonstrates this guard. Future preflight/apply
  entrypoints must call it before loading the user's model.
- Updated SDK skill instructions to replace permissive runtime recovery with
  this release gate. General model-edit routing remains transitional until
  phases 3–5; the legacy MCP setup doctor was not changed.
- Local check found that OpenStudio's embedded launcher does not prepend the
  script directory to sys.path. The probe now adds its own directory explicitly
  so bundled helpers work after export/relocation.
- Focused checks: **96 tests passed** across SDK doctor, manifest, resource export,
  and both adapter suites. Both exported SDK skills passed skill-creator's
  frontmatter validator. SDK skill version/output metadata moved under `metadata`
  for that validator; values are preserved.
- Native exported-bundle checks: Claude and Codex marketplace bundles each ran
  doctor under host Python `-S`; both accepted 3.11.0 and blocked installed 3.8.0.
  Accepted CLI: 3.11.0+241b8abb4d; embedded SDK: 3.11.0; Python: 3.12.2. Test
  exports used temporary directories. No existing model or installation changed.
- Limits: Linux/Windows discovery is unit-tested, not natively verified. This
  readiness report verifies SDK execution, not HVAC correctness or simulations.
  The existing SDK documentation index is 3.10.0; phase 3 development must verify
  APIs against the selected 3.11.0 SDK rather than assuming the old index matches.
- Next review phase: VAV preflight, strict inputs, and a resolved plan. No VAV
  creation entrypoint exists yet.

Phase 2 focused command:

```bash
.venv/bin/python -m pytest -q tests/test_skill_sdk_doctor.py \
  tests/test_harness_asset_manifest.py tests/test_skill_resource_exports.py \
  tests/test_openstudio_codex_adapter.py tests/test_openstudio_claude_code_adapter.py
```

Run the source doctor without OpenStudio AI installed in its host interpreter:

```bash
python3 skills/sdk_scripts/doctor.py --openstudio /absolute/path/to/openstudio
```

Use the JSON report's verified absolute executable for future SDK scripts. The
required release cannot be overridden by a CLI option or environment variable.

### Phase 3 result

- Added `vav_preflight.py`, bundled with the VAV parent skill along with doctor,
  compatibility contract, shared helpers, and `vav_input.schema.json`. It runs
  directly through the verified 3.11.0 CLI without OpenStudio AI runtime calls.
- Every invocation checks the executing SDK before reading/loading the input.
  Inspection inventories zone spaces, thermostats, plenum status, existing HVAC,
  plant loop types, schedules/type limits, and served-zone relationships.
- Configurations may be partial. A bounded standard-library schema validator
  rejects unknown fields, invalid enums/types, booleans as numbers, nonfinite
  values, empty/ambiguous selectors, and range violations. JSON parsing rejects
  duplicate keys and nonfinite constants. Model resolution uses exact names or
  handles and never auto-selects zones.
- Configured plans block on missing references, duplicate names/zone selections,
  preexisting HVAC, missing thermostats/spaces, incompatible plant loops,
  unapproved DX fallback, unsuitable schedule limits, or occupied/invalid output
  paths. This pilot adds systems to unserved zones; HVAC replacement is excluded.
- Explicit `prototype_vav_v1` approval supplies generic prototype defaults with
  one assumption entry for each supplied value. Pressure conversion uses the
  3.11.0 SDK's verified 249.08891 Pa per inH2O. User-supplied pressure values
  cannot inherit missing units from the profile. The profile is not an ASHRAE
  compliance claim; only three verified economizer options are exposed initially.
- Output includes sorted object candidates, resolved handles, SI values,
  assumptions, missing inputs/conflicts, expected object counts, and the input
  SHA-256. Rehashing at completion detects input changes during preflight.
  No output model or directories are created. The state patch records readiness
  and hash only; it does not mark any creation phases complete.
- SDK methods were checked against installed 3.11.0 bindings. The initially
  guessed economizer enumeration accessor was absent; the exposed enum subset
  was verified by setter acceptance in a disposable in-memory model.
- Focused verification: **150 tests passed** across VAV preflight, SDK doctor,
  asset manifest, resource export, both adapters, and HVAC skill generation.
  Both exported VAV parent skills passed skill frontmatter validation. Native
  exported preflight ran from unrelated working directories for Claude and
  Codex, produced ready plans, preserved input bytes, and created no output OSM.
  Repeated 3.11.0 fixture and older 3.10.0 sample inspections were identical.
- Tests caught and fixed sibling-rule validation after `oneOf`. Shared profile
  merging preserves explicit schedule selectors; unit pairing and finite
  conversion results are tested. Native Linux/Windows execution remains unverified.
- Limits: readiness is a preflight result, not HVAC topology/simulation validation.
  Schedule limits are checked, not all time-series values. The approved profile
  is required for this initial operation; custom control profiles and equipment
  replacement need a separately scoped implementation.
- Next review phase: create the system from the resolved plan, reject stale input
  hashes, stage output atomically, independently validate topology, and verify a
  suitable sizing fixture. Preserve preflight's original-model invariant.

Phase 3 focused checks add `tests/test_vav_preflight.py` and
`tests/test_openstudio_hvac_skill_generation.py` to the phase 2 command. Native
export tests use the installed macOS 3.11.0 CLI, or `OPENSTUDIO_SKILL_TEST_EXE`
on other development machines; they skip if the CLI is unavailable.

Example configuration after inspecting candidate names/handles:

```json
{
  "system_name": "New VAV",
  "output_model_path": "/absolute/path/to/new-vav.osm",
  "target_zones": [{"name": "Zone 1"}],
  "defaults_profile": "prototype_vav_v1",
  "central_heating": {"type": "Electricity"},
  "central_cooling": {"type": "DXTwoSpeed", "dx_approved": true},
  "reheat": {"type": "Electricity"}
}
```

Run from the exported skill using the doctor-selected executable:

```text
<verified-executable> execute_python_script <skill-dir>/scripts/vav_preflight.py --input <absolute-model.osm> --config <absolute-config.json>
```

The final stdout line is JSON. Inventory-only calls exit 0 on successful
inspection with `ready: false`; configured plans exit 2 until ready. In either
case, do not proceed to model editing merely because inspection succeeded.
