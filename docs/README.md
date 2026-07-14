# OpenStudio AI Docs

This folder contains planning, release, architecture, and developer-facing
documentation. Root-level files are kept to operational entry points only:
`README.md`, `HANDOFF.md`, `LICENSE`, `pyproject.toml`, and executable modules.

## Current Docs

- `HARNESS_DETAILS.md`: detailed product architecture and local development map.
- `DEVELOPER_GUIDANCE.md`: developer ownership, module boundaries, and roadmap.
- `PACKAGING_NORTHSTAR.md`: packaging and distribution roadmap.
- `RUNTIME_INSTALLATION_CONTRACT.md`: runtime command contract for plugins.
- `MARKETPLACE_INSTALL_GUIDE.md`: no-code install flow for energy modelers.
- `RELEASE.md`: PyPI/TestPyPI release checklist.
- `ADVANCED_USER_GUIDE.md`: advanced workflow and policy usage.
- `architecture_diagram.md`: sponsor-oriented architecture diagram.

## Schema Notes

The active blackboard schemas live under `blackboard/schemas/` and are exported
by the Claude and Codex adapters. The old root-level `blackboard_schema.json`
was removed because it described an earlier session-level schema and was not
used by runtime code or package exports.
