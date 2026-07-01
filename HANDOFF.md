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
- `openstudio>=3.10.0` is a required runtime dependency because the MCP server
  depends on the OpenStudio Python package.
- `openstudio-ai` CLI added with `doctor`, `paths`, `version`,
  `install-runtime`, `repair`, `export`, and `validate-export`.
- `openstudio-ai-mcp` console script remains the MCP runtime entrypoint.
- Runtime assets, skills, knowledge, prompts, resources, and docs are included
  in the wheel while local folders such as `.venv`, `.git`, `.idea`, and
  runtime workspaces are excluded.
- PyPI/TestPyPI release instructions added in `docs/RELEASE.md`.

Documentation cleanup completed:

- Long-form docs and diagrams moved under `docs/`.
- Root `blackboard_schema.json` removed because active exported schemas live in
  `blackboard/schemas/`.
- `docs/README.md` documents the current docs map and schema decision.

## Verification

Last verified from this repository root with the BEM-AI development virtual
environment:

```bash
/Users/xuwe123/github/BEM-AI/.venv/bin/python -m py_compile $(find . -name '*.py' -print)
/Users/xuwe123/github/BEM-AI/.venv/bin/python -m pytest -q tests
```

Result:

- `py_compile`: passed.
- `pytest`: `54 passed, 2 skipped, 5 warnings`.
- The skipped tests require `OPENSTUDIO_PATH` to point to a valid OpenStudio
  executable.
- `python -m build`: produced `dist/openstudio_ai-0.1.0.tar.gz` and
  `dist/openstudio_ai-0.1.0-py3-none-any.whl`.
- `twine check dist/*`: passed in a temporary smoke-test environment.
- Fresh wheel install smoke test: `openstudio-ai`, `openstudio-ai-mcp`, and
  marketplace plugin exports worked.

## Notes

- `pyproject.toml` is a first standalone package scaffold. It explicitly
  includes the harness tree so skills, prompts, resources, knowledge files, and
  diagrams are distributed with the package.
- Runtime state and generated caches are ignored by Git.
- The root README now describes the migrated standalone harness and the current
  developer commands.

## Next Steps

1. Decide the long-term dependency source for `automa_ai` before publishing.
2. Add CI that runs `py_compile` and the focused pytest suite.
3. Test `pip install -e ".[dev]"` in a fresh environment once package
   dependencies are settled.
4. Add an OpenStudio-installed verification pass with `OPENSTUDIO_PATH`
   configured.
5. Continue packaging work for MCP distribution and marketplace-oriented
   agentic installation.
