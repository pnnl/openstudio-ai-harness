from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from harness import asset_manifest
from harness.asset_manifest import reference_exports_for_host


def test_asset_manifest_maps_codex_prompt_and_knowledge_references(
    tmp_path: Path,
) -> None:
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
    assert by_target[orchestrator_prompt].kind == "agent_prompt"
    assert "agent" in by_target[orchestrator_prompt].labels
    assert sdk_geometry in by_target
    assert by_target[sdk_geometry].kind == "knowledge_reference"
    assert "sdk" in by_target[sdk_geometry].labels


def test_asset_manifest_skips_generated_claude_agent_prompt(tmp_path: Path) -> None:
    workspace_root = Path(".").resolve()
    plugin_dir = tmp_path / "openstudio-ai"

    exports = reference_exports_for_host(workspace_root, plugin_dir, "claude")
    targets = {export.target.relative_to(plugin_dir) for export in exports}

    assert Path("agents/openstudio-modeler.md") not in targets
    assert (
        Path("skills/openstudio-workflow-state/references/blackboard_contract.md")
        in targets
    )
    assert Path("skills/propose-measure/references/learning_contract.md") in targets


def test_asset_manifest_schema_documents_enums() -> None:
    schema = yaml.safe_load(
        Path("harness/asset_manifest.schema.json").read_text(encoding="utf-8")
    )
    kind_enum = set(schema["$defs"]["asset"]["properties"]["kind"]["enum"])
    role_enum = set(schema["$defs"]["host_target"]["properties"]["role"]["enum"])

    assert "agent_prompt" in kind_enum
    assert "knowledge_reference" in kind_enum
    assert "learning_schema" in kind_enum
    assert role_enum == {"agent_template", "skill_reference"}


def test_asset_manifest_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unsupported kind"):
        asset_manifest._validate_manifest(
            {
                "version": 1,
                "assets": [
                    {
                        "path": "prompts/example.md",
                        "kind": "unknown",
                        "labels": ["prompt"],
                        "hosts": {
                            "claude": {
                                "role": "skill_reference",
                                "targets": ["skills/example/references/example.md"],
                            }
                        },
                    }
                ],
            }
        )
