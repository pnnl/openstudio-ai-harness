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

OpenStudio 3.12 was discussed as an example, not a verified release selection.
The exact release and supported operating systems must be settled in phase 2.
Existing simulation/results MCP capabilities remain outside this SDK-edit scope.

## Review phases

| Phase | Deliverable | Acceptance check | Status |
| --- | --- | --- | --- |
| 1 | Manifest-driven skill resource export for both hosts, including nested scripts, shared helpers, and schemas | Export parity, dry-run accuracy, exact file preservation, execution from a relocated bundle without the runtime, and invalid resource rejection | Complete; ready for review |
| 2 | A standalone SDK doctor, one compatibility contract, and a shared version guard | Required release passes; missing, mismatched, unrecognized, and conflicting CLI/SDK versions block; scripts check again before editing | Pending |
| 3 | Script-bound VAV preflight and resolved input plan | Resolve objects deterministically; validate units and conditional inputs; list assumptions and conflicts; inspection never edits the input | Pending |
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
