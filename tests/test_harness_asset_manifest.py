from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from harness import asset_manifest
from harness.asset_manifest import (
    agent_source_for_host,
    reference_exports_for_host,
    skill_exports_for_host,
    skill_ids_for_host,
)


def test_asset_manifest_registers_every_product_skill() -> None:
    workspace_root = Path(".").resolve()
    registered_sources = {
        export.source.relative_to(workspace_root)
        for host in ("claude", "codex")
        for export in skill_exports_for_host(workspace_root, Path("/tmp/plugin"), host)
    }
    source_skills = {
        path.relative_to(workspace_root)
        for path in (workspace_root / "skills").glob("*.md")
        if path.name != "HVAC_CHILD_SKILL_MANAGEMENT.md"
    }

    assert registered_sources == source_skills
    assert "openstudio-modeling-orchestrator" not in skill_ids_for_host(
        workspace_root, "claude"
    )
    assert "openstudio-modeling-orchestrator" in skill_ids_for_host(
        workspace_root, "codex"
    )


def test_asset_manifest_routes_references_by_owning_skill(tmp_path: Path) -> None:
    workspace_root = Path(".").resolve()
    plugin_dir = tmp_path / "openstudio-ai"

    exports = reference_exports_for_host(workspace_root, plugin_dir, "codex")
    by_target = {export.target.relative_to(plugin_dir): export for export in exports}
    sdk_geometry = Path(
        "skills/openstudio-sdk-model-editor/references/sdk_wiki/sdk_geometry.md"
    )

    assert sdk_geometry in by_target
    assert by_target[sdk_geometry].skill == "openstudio-sdk-model-editor"
    assert not any(target.name == "openstudio_agent.md" for target in by_target)


def test_asset_manifest_resolves_claude_agent(tmp_path: Path) -> None:
    workspace_root = Path(".").resolve()
    plugin_dir = tmp_path / "openstudio-ai"

    agent_source = agent_source_for_host(workspace_root, "claude", "openstudio-modeler")
    exports = reference_exports_for_host(workspace_root, plugin_dir, "claude")
    targets = {export.target.relative_to(plugin_dir) for export in exports}

    assert agent_source == workspace_root / "prompts" / "openstudio_agent.md"
    assert Path("agents/openstudio-modeler.md") not in targets
    assert (
        Path("skills/openstudio-workflow-state/references/blackboard_contract.md")
        in targets
    )


def test_asset_manifest_schema_documents_product_registry() -> None:
    schema = yaml.safe_load(
        Path("harness/asset_manifest.schema.json").read_text(encoding="utf-8")
    )

    assert schema["properties"]["version"]["enum"] == [3]
    assert set(schema["properties"]) == {
        "$schema",
        "version",
        "skills",
        "agents",
        "references",
    }
    assert set(schema["$defs"]) >= {
        "skill",
        "agent",
        "reference",
        "reference_owner",
    }


def test_asset_manifest_rejects_reference_owner_not_exported_to_host() -> None:
    with pytest.raises(ValueError, match="assigns hosts not exported"):
        asset_manifest._validate_manifest(
            {
                "version": 3,
                "skills": [
                    {
                        "id": "codex-only-skill",
                        "source": "skills/example.md",
                        "hosts": ["codex"],
                    }
                ],
                "agents": [],
                "references": [
                    {
                        "source": "prompts/example.md",
                        "owners": [
                            {
                                "hosts": ["claude"],
                                "skill": "codex-only-skill",
                            }
                        ],
                    }
                ],
            }
        )


def test_asset_manifest_rejects_unsafe_reference_subdirectory() -> None:
    with pytest.raises(ValueError, match="safe relative path"):
        asset_manifest._validate_manifest(
            {
                "version": 3,
                "skills": [
                    {
                        "id": "example-skill",
                        "source": "skills/example.md",
                        "hosts": ["claude", "codex"],
                    }
                ],
                "agents": [],
                "references": [
                    {
                        "source": "knowledge/example.md",
                        "owners": [
                            {
                                "hosts": ["claude", "codex"],
                                "skill": "example-skill",
                                "subdirectory": "../outside",
                            }
                        ],
                    }
                ],
            }
        )
