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

## Verification

Last verified from this repository root with the BEM-AI development virtual
environment:

```bash
/Users/xuwe123/github/BEM-AI/.venv/bin/python -m py_compile $(find . -name '*.py' -print)
/Users/xuwe123/github/BEM-AI/.venv/bin/python -m pytest -q tests
```

Result:

- `py_compile`: passed.
- `pytest`: `46 passed, 2 skipped, 1 warning`.
- The skipped tests require `OPENSTUDIO_PATH` to point to a valid OpenStudio
  executable.

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
