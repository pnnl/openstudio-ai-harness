# Contributing to OpenStudio AI

Use this repository, `openstudio-ai-harness`, for OpenStudio AI source changes.
Ask the PNNL repository maintainers for access before creating a branch or pull
request. The separate `openstudio-ai-plugins` repository contains generated
distribution artifacts: make source changes here, then export and review the
plugins rather than editing generated files directly.

## Start here

| If you are changing… | Start in… |
| --- | --- |
| MCP tools or runtime behavior | `openstudio_mcp/` |
| Plugin export or host setup behavior | `adapters/` |
| Skills, prompts, or reviewed knowledge | `skills/`, `prompts/`, or `knowledge/` |
| Plugin asset registration | `harness/asset_manifest.yaml` |
| Tests | `tests/` |
| Workflow state or learning | `blackboard/`, `learning/`, or `openstudio_mcp/runtime/` |

Read the [Developer Guide](docs/DEVELOPER_GUIDANCE.md) for setup details,
folder ownership, promotion rules, and validation guidance.

## Python versions

The shipped OpenStudio AI runtime supports Python 3.10 and newer. Keep runtime,
adapter, plugin-export, and packaging changes compatible with Python 3.10.

`standalone/` is a separate development application for AUTOMA-AI and Streamlit.
It requires Python 3.12 or newer and does not define the shipped runtime's
Python requirement.

## Example: change a skill

1. Edit the relevant `skills/*.md` source file.
2. If it is a new exported skill or needs a new reference, register it in
   `harness/asset_manifest.yaml`.
3. Run the focused checks:

   ```bash
   .venv/bin/python -m pytest -q \
     tests/test_harness_asset_manifest.py \
     tests/test_openstudio_codex_adapter.py \
     tests/test_openstudio_claude_code_adapter.py
   ```

4. Generate a temporary paired plugin export for review:

   ```bash
   .venv/bin/openstudio-ai export marketplace \
     --output-dir /tmp/openstudio-ai-plugins \
     --runtime-mode marketplace
   ```

Use the repository's `.venv/bin/openstudio-ai` for development exports so the
command uses the current source. For other types of work and full environment
setup, follow the [Developer Guide](docs/DEVELOPER_GUIDANCE.md).
