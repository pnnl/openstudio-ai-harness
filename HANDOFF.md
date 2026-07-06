# OpenStudio AI Harness Handoff

## Current Status

The initial standalone repository migration has started. The OpenStudio AI
example from `BEM-AI/examples/openstudio_ai` now lives in a flattened,
root-level harness layout in this repository.

Migrated components:

- OpenStudio MCP runtime and tools.
- Claude Code and Codex plugin adapters.
- Skills, generated HVAC child skills, knowledge packs, and SDK index modules.
- Learning pipeline modules, policies, prompts, and docs.
- Local blackboard modules and MCP-backed blackboard tools.
- Focused regression tests from the BEM-AI repository.

First packaging phase completed:

- Runtime installation contract documented in `docs/RUNTIME_INSTALLATION_CONTRACT.md`.
- Claude and Codex adapters support `--runtime-mode local`, `installed`, and
  `marketplace`.
- Installed and marketplace exports point `.mcp.json` at `openstudio-ai-mcp`.
- Marketplace exports include setup/doctor/repair command files and
  `installers/install_runtime.py` plus `installers/doctor_runtime.py`.
- Energy-modeler marketplace setup guide added in `docs/MARKETPLACE_INSTALL_GUIDE.md`.

Pip release baseline completed:

- Distribution name set to `openstudio-ai`.
- `openstudio>=3.10.0` is a required runtime dependency because generated
  scripts, measures, and SDK-backed model operations assume the OpenStudio
  Python package.
- `openstudio-ai` CLI added with `doctor`, `paths`, `version`,
  `install-runtime`, `repair`, `export`, and `validate-export`.
- `openstudio-ai-mcp` console script remains the MCP runtime entrypoint.
- Runtime assets, skills, knowledge, prompts, and docs are included in the wheel
  while local folders such as `.venv`, `.git`, `.idea`, runtime workspaces, and
  local sample resource files are excluded.
- PyPI/TestPyPI release instructions added in `docs/RELEASE.md`.

Documentation cleanup completed:

- Long-form docs and diagrams moved under `docs/`.
- Root `blackboard_schema.json` removed because active exported schemas live in
  `blackboard/schemas/`.
- `docs/README.md` documents the current docs map and schema decision.

Current readiness hardening completed:

- `openstudio-ai doctor` now checks packaged runtime assets, initialized
  runtime storage, SQLite registry support, MCP server construction,
  `openstudio-ai-mcp --help`, measure registry entrypoints, SDK routing,
  OpenStudio Python SDK import/version, and OpenStudio CLI availability.
- `doctor` reports separate `mcp_ready`, `simulation_ready`, and `ready` fields
  without depending on packaged sample models.
- `doctor` no longer creates user data directories as a side effect;
  `openstudio-ai install-runtime` initializes user-local runtime storage.
- Marketplace `installers/install_runtime.py` now runs pip for
  `OPENSTUDIO_AI_PACKAGE_SPEC` or `openstudio-ai`, then runs
  `python -m cli install-runtime`.
- `validate-export` now enforces runtime-mode-specific MCP config, marketplace
  setup files, and hardcoded developer path rejection.
- `platformdirs` is now a runtime dependency for cross-platform user data paths.
- Roadmap docs were reconciled so installed and marketplace runtime modes are no
  longer described as future work.
- Installation docs now state the two-part OpenStudio requirement explicitly:
  the PyPI `openstudio` Python package plus the native OpenStudio application
  or CLI visible through `OPENSTUDIO_PATH` or `PATH`.
- AUTOMA-AI and Streamlit remain outside the base marketplace install. They are
  exposed through optional `automa`, `ui`, and user-facing `standalone` extras;
  developers should use `pip install -e ".[dev,standalone]"` for local
  AUTOMA-AI-backed harness testing.

## Verification

Latest verification from this repository root with `.venv/bin/python`:

```bash
.venv/bin/python -m py_compile $(find . -path './.venv' -prune -o -path './dist' -prune -o -path './build' -prune -o -name '*.py' -print)
OPENSTUDIO_PATH=/Applications/OpenStudio-3.10.0/bin/openstudio .venv/bin/python -m pytest -q tests
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
```

Result:

- `py_compile`: passed.
- `pytest` with OpenStudio 3.10.0 configured: `62 passed, 5 warnings`.
- `python -m build`: produced `dist/openstudio_ai-0.1.0.tar.gz` and
  `dist/openstudio_ai-0.1.0-py3-none-any.whl`.
- `twine check dist/*`: passed.
- Wheel content inspection passed for CLI, MCP server, adapters, skills,
  knowledge, prompts, policy, and blackboard schemas. Local sample OSM/EPW
  resources, `resource/`, and `measures/candidates/` are intentionally excluded
  from wheel and sdist release artifacts.
- Wheel metadata inspection passed: `openstudio` is a required base dependency
  and no `openstudio` optional extra is advertised.
- Fresh wheel install smoke test with required OpenStudio passed from
  `/tmp/openstudio-ai-required-smoke`: `pip install dist/*.whl` installed the
  PyPI `openstudio` package, `openstudio-ai install-runtime` initialized
  storage, `doctor --json` reported `python_openstudio.ok`, `mcp_ready`, and
  `simulation_ready` as true with
  `/Applications/OpenStudio-3.10.0/bin/openstudio`, and Codex marketplace export
  plus `validate-export` passed.
- Fresh wheel install smoke test passed from `/tmp/openstudio-ai-wheel-smoke`:
  `openstudio-ai version`, `paths`, `doctor`, `openstudio-ai-mcp --help`,
  Claude marketplace export, Codex marketplace export, and `validate-export`
  for both hosts.
- Fresh wheel install smoke test without packaged resources passed from
  `/tmp/openstudio-ai-no-resource-smoke`: `doctor`, Codex marketplace export,
  and `validate-export`.
- Fresh editable install smoke test passed from
  `/tmp/openstudio-ai-editable-smoke`: `pip install -e ".[dev]"`, `doctor`,
  Codex marketplace export, and `validate-export`.
- OpenStudio-gated MCP tests currently use local test fixtures under
  `resource/`. These fixtures are not part of the release package.

## Notes

- `pyproject.toml` is a first standalone package scaffold. It explicitly
  includes the harness tree so skills, prompts, knowledge files, and diagrams
  are distributed with the package while local sample resources are excluded.
- Runtime state and generated caches are ignored by Git.
- The root README now describes the migrated standalone harness and the current
  developer commands.

## Next Steps

1. Decide the long-term approved dependency source for optional `automa-ai`
   before publishing the standalone extra.
2. Add CI that runs `py_compile` and the focused pytest suite.
3. Add CI coverage for wheel content inspection, `openstudio-ai doctor`, and
   `validate-export --runtime-mode marketplace`.
4. Replace local sample-resource MCP tests with generated temporary models or
   fixture injection so release tests do not depend on package-bundled samples.
5. Continue packaging work for MCP distribution and marketplace-oriented
   agentic installation.
