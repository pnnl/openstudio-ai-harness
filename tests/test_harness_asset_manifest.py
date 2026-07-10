from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from harness import asset_manifest
from harness.asset_manifest import agent_source_for_host, reference_exports_for_host


def test_asset_manifest_routes_references_by_owning_skill(tmp_path: Path) -> None:
    workspace_root = Path(".").resolve()
    plugin_dir = tmp_path / "openstudio-ai"

    exports = reference_exports_for_host(workspace_root, plugin_dir, "codex")
    by_target = {export.target.relative_to(plugin_dir): export for export in exports}

    orchestrator_prompt = Path(
        "skills/openstudio-modeling-orchestrator/references/openstudio_agent.md"
    )
    sdk_geometry = Path(
        "skills/openstudio-sdk-model-editor/references/sdk_wiki/sdk_geometry.md"
    )

    assert orchestrator_prompt in by_target
    assert by_target[orchestrator_prompt].skill == "openstudio-modeling-orchestrator"
    assert sdk_geometry in by_target
    assert by_target[sdk_geometry].skill == "openstudio-sdk-model-editor"


def test_asset_manifest_resolves_claude_agent_and_skips_it_as_reference(
    tmp_path: Path,
) -> None:
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
    assert Path("skills/propose-measure/references/learning_contract.md") in targets


def test_asset_manifest_schema_documents_skill_references_and_agents() -> None:
    schema = yaml.safe_load(
        Path("harness/asset_manifest.schema.json").read_text(encoding="utf-8")
    )

    assert schema["properties"]["version"]["enum"] == [2]
    asset_properties = schema["$defs"]["asset"]["properties"]
    assert set(asset_properties) == {"path", "agent", "references"}
    reference_properties = schema["$defs"]["reference"]["properties"]
    assert set(reference_properties) == {"hosts", "skill", "subdirectory"}


def test_asset_manifest_rejects_legacy_path_routing_fields() -> None:
    with pytest.raises(ValueError, match="unsupported fields"):
        asset_manifest._validate_manifest(
            {
                "version": 2,
                "assets": [
                    {
                        "path": "prompts/example.md",
                        "kind": "legacy",
                        "references": [
                            {
                                "hosts": ["claude"],
                                "skill": "example-skill",
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
                "version": 2,
                "assets": [
                    {
                        "path": "knowledge/example.md",
                        "references": [
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
