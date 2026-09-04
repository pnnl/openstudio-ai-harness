from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters.claude_code_adapter import (
    GENERATED_START,
    ClaudeCodeAdapter,
)
from adapters.contracts import HostAdapterConfig
from openstudio_mcp.compatibility import plugin_mcp_environment


def _adapter() -> ClaudeCodeAdapter:
    return ClaudeCodeAdapter(
        HostAdapterConfig(
            host_name="claude_code",
            workspace_root=Path(".").resolve(),
        )
    )


def _adapter_with_runtime_mode(runtime_mode: str) -> ClaudeCodeAdapter:
    return ClaudeCodeAdapter(
        HostAdapterConfig(
            host_name="claude_code",
            workspace_root=Path(".").resolve(),
            runtime_mode=runtime_mode,
        )
    )


def test_claude_code_adapter_dry_run_generates_project_files(tmp_path: Path) -> None:
    result = _adapter().install(tmp_path, dry_run=True)

    assert result.dry_run is True
    assert {action.path.name for action in result.actions} == {".mcp.json", "CLAUDE.md"}
    assert not (tmp_path / ".mcp.json").exists()
    assert not (tmp_path / ".claude" / "CLAUDE.md").exists()


def test_claude_code_adapter_writes_mcp_config_and_instructions(tmp_path: Path) -> None:
    result = _adapter().install(tmp_path, dry_run=False)

    assert result.dry_run is False
    mcp_config = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    server = mcp_config["mcpServers"]["openstudio_ai"]
    assert server["args"][:3] == ["-m", "openstudio_mcp.server", "--transport"]
    assert server["args"][3] == "stdio"
    assert "OPENSTUDIO_AI_ROOT" in server["env"]

    instructions = (tmp_path / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert GENERATED_START in instructions
    assert "OpenStudio AI Harness" in instructions
    assert "openstudio_hvac_air_loop_creator.md" in instructions
    assert "HVAC_CHILD_SKILL_MANAGEMENT.md" not in instructions


def test_claude_code_adapter_preserves_other_mcp_servers(tmp_path: Path) -> None:
    existing = {"mcpServers": {"other": {"command": "node", "args": ["server.js"]}}}
    (tmp_path / ".mcp.json").write_text(json.dumps(existing), encoding="utf-8")

    _adapter().install(tmp_path, dry_run=False)

    mcp_config = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert "other" in mcp_config["mcpServers"]
    assert "openstudio_ai" in mcp_config["mcpServers"]


def test_claude_code_adapter_refuses_unmanaged_instructions_without_force(
    tmp_path: Path,
) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "CLAUDE.md").write_text(
        "# Existing project instructions\n", encoding="utf-8"
    )

    with pytest.raises(FileExistsError):
        _adapter().install(tmp_path, dry_run=True)


def test_claude_code_adapter_exports_plugin_package(tmp_path: Path) -> None:
    result = _adapter().export_plugin(tmp_path, dry_run=False)

    plugin_dir = tmp_path / "openstudio-ai"
    assert result.marketplace_dir == tmp_path.resolve()
    assert result.plugin_dir == plugin_dir.resolve()
    assert (tmp_path / ".claude-plugin" / "marketplace.json").exists()
    assert (tmp_path / "INSTALL.md").exists()
    assert (plugin_dir / ".claude-plugin" / "plugin.json").exists()
    assert (plugin_dir / ".mcp.json").exists()
    assert (plugin_dir / "README.md").exists()
    assert (plugin_dir / "CONNECTORS.md").exists()
    assert (plugin_dir / "settings.json").exists()
    assert (plugin_dir / "agents" / "openstudio-modeler.md").exists()
    assert (plugin_dir / "monitors" / "monitors.json").exists()
    assert (plugin_dir / "bin" / "openstudio-ai-learning-monitor").exists()
    assert (plugin_dir / "skills" / "add-vav-reheat" / "SKILL.md").exists()
    assert (plugin_dir / "skills" / "propose-measure" / "SKILL.md").exists()
    assert (plugin_dir / "skills" / "capture-session-lesson" / "SKILL.md").exists()
    assert (plugin_dir / "skills" / "view-openstudio-geometry" / "SKILL.md").exists()
    simulate_skill = (plugin_dir / "skills" / "simulate" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "## Executable Recovery" in simulate_skill
    assert (
        "Do not immediately retry or automatically edit marketplace" in simulate_skill
    )
    assert "## MCP-Only Boundary" in simulate_skill
    assert "Never invoke `openstudio`, EnergyPlus" in simulate_skill
    assert "local SQL result extraction as a fallback" in simulate_skill
    assert "do not use a local CLI fallback" in simulate_skill
    assert "runtime_openstudio_status" in simulate_skill
    assert "Before suggesting installation, use read-only discovery" in simulate_skill
    assert "Only when discovery finds no executable" in simulate_skill
    assert (
        plugin_dir / "skills" / "openstudio-hvac-air-loop-creator" / "SKILL.md"
    ).exists()
    delegated_nlr_skill = plugin_dir / "skills" / "delegated-nlr-modeling" / "SKILL.md"
    assert delegated_nlr_skill.exists()
    assert "NLR Skill Guidance" in delegated_nlr_skill.read_text(encoding="utf-8")
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
    sdk_index_ref = (
        plugin_dir
        / "skills"
        / "openstudio-sdk-model-editor"
        / "references"
        / "sdk_wiki"
        / "sdk_index.md"
    ).read_text(encoding="utf-8")
    assert not sdk_index_ref.startswith("---\n")
    assert sdk_index_ref.startswith("# OpenStudio SDK Wiki Index")
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
        / "blackboard_contract.md"
    ).exists()
    blackboard_contract = (
        plugin_dir
        / "skills"
        / "openstudio-workflow-state"
        / "references"
        / "blackboard_contract.md"
    ).read_text(encoding="utf-8")
    assert not blackboard_contract.startswith("---\n")
    assert blackboard_contract.startswith("# Blackboard Contract")
    assert not (
        plugin_dir
        / "skills"
        / "openstudio-vav-reheat-system-creator"
        / "references"
        / "workflow_state.schema.json"
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
        / "capture-session-lesson"
        / "references"
        / "session_lesson.schema.json"
    ).exists()
    assert not (plugin_dir / "commands").exists()
    assert not (plugin_dir / "knowledge").exists()
    assert not (plugin_dir / "instructions").exists()
    assert not (plugin_dir / "learning").exists()
    assert not (plugin_dir / "blackboard").exists()

    plugin_json = json.loads(
        (plugin_dir / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert plugin_json["name"] == "openstudio-ai"
    settings_json = json.loads(
        (plugin_dir / "settings.json").read_text(encoding="utf-8")
    )
    assert settings_json["agent"] == "openstudio-modeler"
    agent_prompt = (plugin_dir / "agents" / "openstudio-modeler.md").read_text(
        encoding="utf-8"
    )
    assert "model: sonnet\n" not in agent_prompt
    assert "do not rely on host-native blackboard features" in agent_prompt
    assert "Never promote them" in agent_prompt
    assert "## SDK Script Gate" in agent_prompt
    assert "do not retry an SDK method name from memory" in agent_prompt
    assert "bundled 3.x" in agent_prompt
    assert "./.venv/bin/python" in agent_prompt
    assert "./nlr-workspace/runs/<suffix>" in agent_prompt
    readme = (plugin_dir / "README.md").read_text(encoding="utf-8")
    assert "activating it as the main Claude Code thread" in readme
    assert "does not automatically read arbitrary plugin instruction files" in readme
    mcp_json = json.loads((plugin_dir / ".mcp.json").read_text(encoding="utf-8"))
    assert "openstudio_ai" in mcp_json["mcpServers"]
    marketplace_json = json.loads(
        (tmp_path / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    assert marketplace_json["name"] == "openstudio-ai-local"
    assert marketplace_json["plugins"][0]["source"] == "./openstudio-ai"


def test_claude_code_adapter_installed_mode_uses_runtime_command(
    tmp_path: Path,
) -> None:
    _adapter_with_runtime_mode("installed").export_plugin(tmp_path, dry_run=False)

    mcp_json = json.loads(
        (tmp_path / "openstudio-ai" / ".mcp.json").read_text(encoding="utf-8")
    )
    server = mcp_json["mcpServers"]["openstudio_ai"]
    assert server["command"] == "openstudio-ai-mcp"
    assert server["args"] == ["--transport", "stdio"]
    assert server["env"] == plugin_mcp_environment()
    assert not (
        tmp_path / "openstudio-ai" / "skills" / "setup-openstudio-ai" / "SKILL.md"
    ).exists()


def test_claude_code_adapter_marketplace_mode_exports_runtime_setup(
    tmp_path: Path,
) -> None:
    _adapter_with_runtime_mode("marketplace").export_plugin(tmp_path, dry_run=False)

    plugin_dir = tmp_path / "openstudio-ai"
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
    assert "/reload-plugins" in setup
    installer = (
        plugin_dir / "skills" / "setup-openstudio-ai" / "scripts" / "install_runtime.py"
    ).read_text(encoding="utf-8")
    assert "OPENSTUDIO_AI_PACKAGE_SPEC" in installer
    assert '"pip", "install", "--upgrade"' in installer
    assert 'runtime_cli, "install-runtime"' in installer
    assert "run /reload-plugins" in installer
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


def test_claude_code_adapter_exports_workflow_skill_frontmatter(tmp_path: Path) -> None:
    _adapter().export_plugin(tmp_path, dry_run=False)

    skill = (
        tmp_path / "openstudio-ai" / "skills" / "add-vav-reheat" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert skill.startswith("---\n")
    assert "name: add-vav-reheat\n" in skill
    assert (
        "description: Plan and execute a phased OpenStudio VAV reheat workflow.\n"
        in skill
    )
    assert "\n---\n\n# Add VAV Reheat" in skill
    propose_measure = (
        tmp_path / "openstudio-ai" / "skills" / "propose-measure" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "name: propose-measure\n" in propose_measure
    assert "references/candidate_measure.schema.json" in propose_measure


def test_claude_code_adapter_exports_skill_frontmatter(tmp_path: Path) -> None:
    _adapter().export_plugin(tmp_path, dry_run=False)

    skill = (
        tmp_path
        / "openstudio-ai"
        / "skills"
        / "openstudio-hvac-air-loop-creator"
        / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert skill.startswith("---\n")
    assert "name: openstudio-hvac-air-loop-creator\n" in skill
    assert "description: Create or confirm the parent AirLoopHVAC object" in skill
    assert "version: 0.2.1\n" in skill
    assert "\n---\n\n## Scope" in skill


def test_claude_code_adapter_export_plugin_dry_run_does_not_write(
    tmp_path: Path,
) -> None:
    result = _adapter().export_plugin(tmp_path, dry_run=True)

    assert result.dry_run is True
    assert result.marketplace_dir == tmp_path.resolve()
    assert result.plugin_dir == (tmp_path / "openstudio-ai").resolve()
    assert tmp_path / ".claude-plugin" / "marketplace.json" in result.files
    assert any(path.name == "plugin.json" for path in result.files)
    assert not (tmp_path / "openstudio-ai").exists()


def test_claude_code_adapter_export_plugin_requires_force_for_existing_dir(
    tmp_path: Path,
) -> None:
    plugin_dir = tmp_path / "openstudio-ai"
    plugin_dir.mkdir()

    with pytest.raises(FileExistsError):
        _adapter().export_plugin(tmp_path, dry_run=False)
