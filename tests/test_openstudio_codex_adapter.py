from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters.codex_adapter import AGENTS_GENERATED_START, CodexAdapter
from adapters.contracts import HostAdapterConfig
from openstudio_mcp.compatibility import plugin_mcp_environment


def _adapter() -> CodexAdapter:
    return CodexAdapter(
        HostAdapterConfig(
            host_name="codex",
            workspace_root=Path(".").resolve(),
        )
    )


def _adapter_with_runtime_mode(runtime_mode: str) -> CodexAdapter:
    return CodexAdapter(
        HostAdapterConfig(
            host_name="codex",
            workspace_root=Path(".").resolve(),
            runtime_mode=runtime_mode,
        )
    )


def test_codex_adapter_export_plugin_dry_run_does_not_write(tmp_path: Path) -> None:
    result = _adapter().export_plugin(tmp_path, dry_run=True)

    assert result.dry_run is True
    assert (
        result.marketplace_path
        == (tmp_path / ".agents" / "plugins" / "marketplace.json").resolve()
    )
    assert result.plugin_dir == (tmp_path / "plugins" / "openstudio-ai").resolve()
    assert result.marketplace_path in result.files
    assert not result.plugin_dir.exists()


def test_codex_adapter_guidance_install_dry_run_does_not_write(tmp_path: Path) -> None:
    result = _adapter().install(tmp_path, dry_run=True)

    assert result.dry_run is True
    assert [action.path.name for action in result.actions] == ["AGENTS.md"]
    assert not (tmp_path / "AGENTS.md").exists()


def test_codex_adapter_installs_shared_modeler_policy(tmp_path: Path) -> None:
    result = _adapter().install(tmp_path, dry_run=False)

    assert result.dry_run is False
    instructions = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert AGENTS_GENERATED_START in instructions
    assert "openstudio-modeling-orchestrator" in instructions
    assert "## SDK Script Gate" in instructions
    assert "Do not use host Python execution for simulation runs" in instructions


def test_codex_adapter_refuses_unmanaged_agents_without_force(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(
        "# Existing project instructions\n", encoding="utf-8"
    )

    with pytest.raises(FileExistsError):
        _adapter().install(tmp_path, dry_run=True)


def test_codex_adapter_force_preserves_unmanaged_agents(tmp_path: Path) -> None:
    existing = "# Existing project instructions\n\nKeep these instructions.\n"
    (tmp_path / "AGENTS.md").write_text(existing, encoding="utf-8")

    _adapter().install(tmp_path, dry_run=False, force=True)

    instructions = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert instructions.startswith(existing.rstrip())
    assert AGENTS_GENERATED_START in instructions


def test_codex_adapter_updates_only_its_managed_agents_block(tmp_path: Path) -> None:
    _adapter().install(tmp_path, dry_run=False)
    agents_path = tmp_path / "AGENTS.md"
    agents_path.write_text(
        "Project guidance before.\n\n"
        + agents_path.read_text(encoding="utf-8")
        + "\nProject guidance after.\n",
        encoding="utf-8",
    )

    _adapter().install(tmp_path, dry_run=False)

    instructions = agents_path.read_text(encoding="utf-8")
    assert instructions.startswith("Project guidance before.")
    assert instructions.rstrip().endswith("Project guidance after.")
    assert instructions.count(AGENTS_GENERATED_START) == 1


def test_codex_adapter_exports_plugin_package(tmp_path: Path) -> None:
    result = _adapter().export_plugin(tmp_path, dry_run=False)

    plugin_dir = tmp_path / "plugins" / "openstudio-ai"
    assert result.plugin_dir == plugin_dir.resolve()
    assert (tmp_path / ".agents" / "plugins" / "marketplace.json").exists()
    assert (tmp_path / "INSTALL.md").exists()
    assert (plugin_dir / ".codex-plugin" / "plugin.json").exists()
    assert (plugin_dir / "assets" / "openstudio-ai-icon.png").exists()
    assert (plugin_dir / ".mcp.json").exists()
    assert (plugin_dir / "README.md").exists()
    assert (plugin_dir / "CONNECTORS.md").exists()
    assert (
        plugin_dir / "skills" / "openstudio-modeling-orchestrator" / "SKILL.md"
    ).exists()
    delegated_nlr_skill = (
        plugin_dir / "skills" / "delegated-nlr-modeling" / "SKILL.md"
    )
    assert delegated_nlr_skill.exists()
    assert "SDK Fallback Boundary" in delegated_nlr_skill.read_text(encoding="utf-8")
    assert (plugin_dir / "skills" / "add-vav-reheat" / "SKILL.md").exists()
    assert (plugin_dir / "skills" / "propose-measure" / "SKILL.md").exists()
    assert (plugin_dir / "skills" / "view-openstudio-geometry" / "SKILL.md").exists()
    assert (plugin_dir / "skills" / "capture-session-lesson" / "SKILL.md").exists()
    simulate_skill = (plugin_dir / "skills" / "simulate" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "## MCP-Only Boundary" in simulate_skill
    assert "do not use a local CLI fallback" in simulate_skill
    assert (
        plugin_dir / "skills" / "openstudio-hvac-air-loop-creator" / "SKILL.md"
    ).exists()
    assert (plugin_dir / "skills" / "openstudio-workflow-state" / "SKILL.md").exists()
    assert not (
        plugin_dir / "skills" / "openstudio-hvac-workflow-state" / "SKILL.md"
    ).exists()
    assert not (
        plugin_dir / "skills" / "HVAC-CHILD-SKILL-MANAGEMENT" / "SKILL.md"
    ).exists()
    assert (
        plugin_dir
        / "skills"
        / "openstudio-sdk-model-editor"
        / "references"
        / "openstudio_sdk_recipes.md"
    ).exists()
    assert (
        plugin_dir
        / "skills"
        / "openstudio-sdk-model-editor"
        / "references"
        / "sdk_wiki"
        / "sdk_index.md"
    ).exists()
    assert (
        plugin_dir
        / "skills"
        / "openstudio-workflow-state"
        / "references"
        / "workflow_state.schema.json"
    ).exists()
    assert (
        plugin_dir
        / "skills"
        / "openstudio-workflow-state"
        / "references"
        / "state_patch.schema.json"
    ).exists()
    assert (
        plugin_dir
        / "skills"
        / "openstudio-workflow-state"
        / "references"
        / "blackboard_contract.md"
    ).exists()
    assert (
        plugin_dir
        / "skills"
        / "propose-measure"
        / "references"
        / "candidate_measure.schema.json"
    ).exists()
    assert (
        plugin_dir
        / "skills"
        / "propose-measure"
        / "references"
        / "candidate_recipe.schema.json"
    ).exists()
    assert (
        plugin_dir
        / "skills"
        / "propose-measure"
        / "references"
        / "learning_contract.md"
    ).exists()
    assert (
        plugin_dir / "skills" / "propose-measure" / "references" / "promotion_rules.md"
    ).exists()
    assert (
        plugin_dir
        / "skills"
        / "capture-session-lesson"
        / "references"
        / "session_lesson.schema.json"
    ).exists()
    assert (
        plugin_dir
        / "skills"
        / "capture-session-lesson"
        / "references"
        / "runtime_learning.md"
    ).exists()
    orchestrator = (
        plugin_dir / "skills" / "openstudio-modeling-orchestrator" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "# OpenStudio Modeling Orchestrator" in orchestrator
    assert "MCP blackboard tools" in orchestrator
    assert "openstudio_agent.md" not in orchestrator
    assert (
        plugin_dir
        / "skills"
        / "capture-session-lesson"
        / "references"
        / "learning_contract.md"
    ).exists()
    sdk_index = (
        plugin_dir
        / "skills"
        / "openstudio-sdk-model-editor"
        / "references"
        / "sdk_wiki"
        / "sdk_index.md"
    ).read_text(encoding="utf-8")
    blackboard_contract = (
        plugin_dir
        / "skills"
        / "openstudio-workflow-state"
        / "references"
        / "blackboard_contract.md"
    ).read_text(encoding="utf-8")
    source_skill = (
        plugin_dir / "skills" / "openstudio-hvac-air-loop-creator" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert not sdk_index.startswith("---\n")
    assert not blackboard_contract.startswith("---\n")
    assert "name: openstudio-hvac-air-loop-creator\n" in source_skill
    assert not (plugin_dir / "commands").exists()
    assert not (plugin_dir / "installers").exists()
    assert not (plugin_dir / "instructions").exists()
    assert not (plugin_dir / "knowledge").exists()
    assert not (plugin_dir / "blackboard").exists()
    assert not (plugin_dir / "learning").exists()
    install_doc = (tmp_path / "INSTALL.md").read_text(encoding="utf-8")
    assert f"codex plugin marketplace add {tmp_path}" in install_doc
    assert "openstudio-ai install codex --target-dir <path-to-project>" in install_doc
    assert "$setup-openstudio-ai" in install_doc
    assert "/setup-openstudio-ai` is not a Codex CLI skill command" in install_doc
    assert "openstudio-ai-codex-export install" not in install_doc


def test_codex_adapter_exports_valid_manifest_and_marketplace(tmp_path: Path) -> None:
    _adapter().export_plugin(tmp_path, dry_run=False)

    plugin_dir = tmp_path / "plugins" / "openstudio-ai"
    plugin_json = json.loads(
        (plugin_dir / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert plugin_json["name"] == "openstudio-ai"
    assert "model" not in plugin_json
    assert plugin_json["skills"] == "./skills/"
    assert plugin_json["mcpServers"] == "./.mcp.json"
    assert plugin_json["interface"]["displayName"] == "OpenStudio AI"
    assert plugin_json["interface"]["defaultPrompt"]
    assert plugin_json["interface"]["composerIcon"] == "./assets/openstudio-ai-icon.png"
    assert plugin_json["interface"]["logo"] == "./assets/openstudio-ai-icon.png"

    marketplace_json = json.loads(
        (tmp_path / ".agents" / "plugins" / "marketplace.json").read_text(
            encoding="utf-8"
        )
    )
    assert marketplace_json["name"] == "openstudio-ai-local"
    assert marketplace_json["plugins"][0]["source"]["path"] == "./plugins/openstudio-ai"
    assert marketplace_json["plugins"][0]["policy"]["installation"] == "AVAILABLE"


def test_codex_adapter_exports_mcp_config(tmp_path: Path) -> None:
    _adapter().export_plugin(tmp_path, dry_run=False)

    mcp_json = json.loads(
        (tmp_path / "plugins" / "openstudio-ai" / ".mcp.json").read_text(
            encoding="utf-8"
        )
    )
    server = mcp_json["mcpServers"]["openstudio_ai"]
    assert server["args"][:3] == ["-m", "openstudio_mcp.server", "--transport"]
    assert server["args"][3] == "stdio"
    assert "OPENSTUDIO_AI_ROOT" in server["env"]


def test_codex_adapter_installed_mode_uses_runtime_command(tmp_path: Path) -> None:
    _adapter_with_runtime_mode("installed").export_plugin(tmp_path, dry_run=False)

    mcp_json = json.loads(
        (tmp_path / "plugins" / "openstudio-ai" / ".mcp.json").read_text(
            encoding="utf-8"
        )
    )
    server = mcp_json["mcpServers"]["openstudio_ai"]
    assert server["command"] == "openstudio-ai-mcp"
    assert server["args"] == ["--transport", "stdio"]
    assert server["env"] == plugin_mcp_environment()
    assert not (
        tmp_path / "plugins" / "openstudio-ai" / "skills" / "setup-openstudio-ai"
    ).exists()


def test_codex_adapter_marketplace_mode_exports_runtime_setup(tmp_path: Path) -> None:
    _adapter_with_runtime_mode("marketplace").export_plugin(tmp_path, dry_run=False)

    plugin_dir = tmp_path / "plugins" / "openstudio-ai"
    mcp_json = json.loads((plugin_dir / ".mcp.json").read_text(encoding="utf-8"))
    server = mcp_json["mcpServers"]["openstudio_ai"]
    assert server == {
        "command": "openstudio-ai-mcp",
        "args": ["--transport", "stdio"],
        "env": plugin_mcp_environment(),
    }
    assert (plugin_dir / "skills" / "setup-openstudio-ai" / "SKILL.md").exists()
    assert (plugin_dir / "skills" / "doctor-openstudio-ai" / "SKILL.md").exists()
    assert (plugin_dir / "skills" / "repair-openstudio-ai" / "SKILL.md").exists()
    assert (
        plugin_dir / "skills" / "setup-openstudio-ai" / "scripts" / "install_runtime.py"
    ).exists()
    assert (
        plugin_dir / "skills" / "setup-openstudio-ai" / "scripts" / "doctor_runtime.py"
    ).exists()
    assert not (plugin_dir / "commands").exists()
    assert not (plugin_dir / "installers").exists()

    setup = (plugin_dir / "skills" / "setup-openstudio-ai" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "python --version" in setup
    assert "python3 --version" in setup
    assert "openstudio-ai-mcp --help" in setup
    assert "energy-modeler language" in setup
    assert "diagnose command discovery before editing plugin files" in setup
    assert "do not replace it with an absolute `.venv/bin` path" in setup
    assert "--runtime-mode local" in setup
    assert "restart Codex" in setup
    assert "plugin_ready: false" in setup
    assert "new tool cannot appear in the current session" in setup
    repair = (plugin_dir / "skills" / "repair-openstudio-ai" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "plugin_ready: false" in repair
    assert "restart Codex or reconnect the MCP server" in repair
    assert "current project's `AGENTS.md`" in setup
    assert "required part of setup" in setup
    assert "openstudio-ai install codex --target-dir . --dry-run --force" in setup
    assert "openstudio-ai install codex --target-dir . --force" in setup
    assert "unmanaged" in setup
    installer = (
        plugin_dir / "skills" / "setup-openstudio-ai" / "scripts" / "install_runtime.py"
    ).read_text(encoding="utf-8")
    assert "OPENSTUDIO_AI_PACKAGE_SPEC" in installer
    assert '"pip", "install", "--upgrade"' in installer
    assert '["pipx", "upgrade", "--install", "openstudio-ai"]' in installer
    assert 'runtime_cli, "install-runtime"' in installer
    assert "Placeholder installer" not in installer
    doctor = (
        plugin_dir / "skills" / "setup-openstudio-ai" / "scripts" / "doctor_runtime.py"
    ).read_text(encoding="utf-8")
    assert '"--plugin-contract-version"' in doctor

    exported_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in tmp_path.rglob("*")
        if path.is_file() and path.suffix in {".md", ".json", ".py"}
    )
    assert "/Users/" not in exported_text


def test_codex_adapter_export_requires_force_for_existing_plugin(
    tmp_path: Path,
) -> None:
    plugin_dir = tmp_path / "plugins" / "openstudio-ai"
    plugin_dir.mkdir(parents=True)

    with pytest.raises(FileExistsError):
        _adapter().export_plugin(tmp_path, dry_run=False)
