# OpenStudio AI Harness

The harness is the host-agnostic package boundary for OpenStudio AI. It collects
the assets needed by an agent host:

- MCP server entrypoint;
- prompt contracts;
- skill files;
- knowledge base roots;
- SDK index roots;
- blackboard schema;
- learning-event log path.

Host-specific details belong in `adapters/`. The harness should remain portable
across Codex, Claude Code, and future agent shells.

## Skill resources

`asset_manifest.yaml` accepts an optional `resources` list in manifest version 3.
Each entry names one source file and one or more skill owners. Both adapters copy
these files verbatim, preserving nested destinations and file modes; Markdown
resources retain their frontmatter. Existing `references` exports still strip
Markdown frontmatter.

Example declaration (for an actual file when phase 2 adds SDK scripts):

```yaml
resources:
  - source: skills/sdk_scripts/common/version_guard.py
    owners:
      - hosts: [claude, codex]
        skill: add-vav-reheat
        path: scripts/common/version_guard.py
```

Sources must be individual files inside the source checkout. Owner paths are
relative to the exported skill folder. Exports reject invalid hosts/owners,
unsafe paths, missing sources, external symlink targets, and destinations that
collide with skill documents, references, resources, or generated setup helpers.
Both dry runs and real exports use the same resource planning checks.

Run the focused verification from the repository root:

```bash
.venv/bin/python -m pytest -q tests/test_harness_asset_manifest.py \
  tests/test_skill_resource_exports.py
```
