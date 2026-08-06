# OpenStudio AI PyPI Release Guide

This guide describes how to build and publish the `openstudio-ai` Python
package.

## Release Prerequisites

1. Confirm the package name is available on PyPI.

   ```bash
   python -m pip index versions openstudio-ai
   ```

   If the name is already owned by another project, change `project.name` in
   `pyproject.toml` before publishing.

2. Create accounts and API tokens:

   - TestPyPI: https://test.pypi.org/
   - PyPI: https://pypi.org/

3. Install build tools in a clean environment:

   ```bash
   python -m pip install --upgrade pip
   python -m pip install build twine
   ```

4. Verify the working tree is clean except for the intended release changes:

   ```bash
   git status --short
   ```

## Local Verification

Run the source checks:

```bash
python -m py_compile $(find . -path './.venv' -prune -o -name '*.py' -print)
python -m pytest -q tests
```

The OpenStudio simulation tests require `OPENSTUDIO_PATH`. If it is not set,
those tests should be skipped and reported in the release notes.

Run CLI smoke checks:

```bash
python -m cli version
python -m cli paths --json
python -m cli install-runtime
python -m cli doctor --json
python -m openstudio_mcp.server --help
```

`doctor` may return a non-zero code if runtime pieces such as the OpenStudio
Python SDK or OpenStudio CLI are not available. Inspect the JSON and confirm the
failure is expected before release.

## Marketplace Release Tree

Create the generated repository tree for the Claude Code and Codex marketplace
release:

```bash
openstudio-ai export marketplace \
  --output-dir /tmp/openstudio-ai-plugins \
  --runtime-mode marketplace \
  --force
```

The command validates both plugin packages before completing. Review
`/tmp/openstudio-ai-plugins/.generated.json` and confirm its package version,
MCP interface contract, and source revision match the release being published.
The tree includes separate `INSTALL.claude.md` and `INSTALL.codex.md` files;
do not edit generated plugin files directly in the marketplace repository.

## Build Artifacts

Remove old builds:

```bash
rm -rf dist build *.egg-info
```

Build source distribution and wheel:

```bash
python -m build
```

Validate metadata:

```bash
python -m twine check dist/*
```

Inspect wheel and source-distribution contents:

```bash
python - <<'PY'
from pathlib import Path
import tarfile
import zipfile

wheel = next(Path("dist").glob("*.whl"))
with zipfile.ZipFile(wheel) as zf:
    names = zf.namelist()
    metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
    metadata = zf.read(metadata_name).decode()

blocked = [
    name
    for name in names
    if name.startswith(
        (
            ".git/",
            ".venv/",
            ".idea/",
            "resource/",
            "tests/",
            "evals/",
            "measures/candidates/",
        )
    )
]
if blocked:
    raise SystemExit(f"Blocked paths found in wheel: {blocked[:10]}")

required = [
    "cli.py",
    "openstudio_mcp/server.py",
    "adapters/claude_code_adapter.py",
    "adapters/codex_adapter.py",
    "skills/openstudio_vav_reheat_system_creator.md",
    "knowledge/openstudio_sdk_recipes.md",
    "prompts/openstudio_agent.md",
]
missing = [name for name in required if name not in names]
if missing:
    raise SystemExit(f"Missing required files: {missing}")

forbidden = [
    "resource/sample.osm",
    "resource/USA_FL_Tampa.Intl.AP.722110_TMY3.epw",
    "tests/fixtures/sample.osm",
    "tests/fixtures/USA_FL_Tampa.Intl.AP.722110_TMY3.epw",
]
included_forbidden = [name for name in forbidden if name in names]
if included_forbidden:
    raise SystemExit(f"Release wheel includes local test fixtures: {included_forbidden}")

sdist = next(Path("dist").glob("*.tar.gz"))
with tarfile.open(sdist) as archive:
    sdist_names = [member.name.partition("/")[2] for member in archive.getmembers()]

blocked_sdist = [
    name
    for name in sdist_names
    if name.startswith(("resource/", "tests/fixtures/", "measures/candidates/"))
]
if blocked_sdist:
    raise SystemExit(f"Blocked paths found in source distribution: {blocked_sdist[:10]}")

base_openstudio = [
    line
    for line in metadata.splitlines()
    if line.startswith("Requires-Dist: openstudio") and "; extra ==" not in line
]
if not base_openstudio:
    raise SystemExit("OpenStudio Python package must be a required dependency")

print(f"Wheel looks complete: {wheel}")
PY
```

## TestPyPI Release

Upload to TestPyPI first:

```bash
python -m twine upload --repository testpypi dist/*
```

Create a clean virtual environment and install from TestPyPI:

```bash
python -m venv /tmp/openstudio-ai-testpypi
/tmp/openstudio-ai-testpypi/bin/python -m pip install --upgrade pip
/tmp/openstudio-ai-testpypi/bin/python -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  openstudio-ai
```

Windows PowerShell equivalent:

```powershell
py -m venv $env:TEMP\openstudio-ai-testpypi
& $env:TEMP\openstudio-ai-testpypi\Scripts\python -m pip install --upgrade pip
& $env:TEMP\openstudio-ai-testpypi\Scripts\python -m pip install `
  --index-url https://test.pypi.org/simple/ `
  --extra-index-url https://pypi.org/simple/ `
  openstudio-ai
```

Smoke test the installed commands:

```bash
openstudio-ai version
openstudio-ai paths
openstudio-ai install-runtime
openstudio-ai doctor
openstudio-ai-mcp --help
openstudio-ai export claude --output-dir /tmp/openstudio-ai-claude --runtime-mode marketplace
openstudio-ai export codex --output-dir /tmp/openstudio-ai-codex --runtime-mode marketplace
openstudio-ai install codex --target-dir /tmp/openstudio-ai-codex-project
```

Model editing, measure execution, and simulation readiness require two
OpenStudio pieces:

- the PyPI `openstudio` Python package, installed as a required dependency of
  `openstudio-ai`;
- the native OpenStudio application/CLI, visible through `OPENSTUDIO_PATH` or
  `PATH`.

## Production PyPI Release

After TestPyPI is validated, upload to PyPI:

```bash
python -m twine upload dist/*
```

Then verify from a clean environment:

```bash
python -m venv /tmp/openstudio-ai-pypi
/tmp/openstudio-ai-pypi/bin/python -m pip install --upgrade pip
/tmp/openstudio-ai-pypi/bin/python -m pip install openstudio-ai
/tmp/openstudio-ai-pypi/bin/openstudio-ai version
/tmp/openstudio-ai-pypi/bin/openstudio-ai doctor
```

## Release Notes

For the first release, call out:

- Package name and version.
- Supported Python versions.
- Whether OpenStudio simulation tests were run or skipped.
- Whether TestPyPI install succeeded on macOS and Windows.
- Known limitation: `openstudio-ai doctor` validates runtime scaffolding, but
  full simulation readiness still depends on the user installing OpenStudio.
