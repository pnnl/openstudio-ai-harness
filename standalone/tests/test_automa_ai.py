import re
from pathlib import Path

from automa_ai.config.agent_spec import YamlAgentSpec
from automa_ai.skills.manager import SkillManager

from standalone.agent import (
    build_openstudio_ai_mcp_config,
    env_path as agent_env_path,
    load_openstudio_agent_spec,
    repo_root,
)
from standalone.ui import TELEMETRY_LOG_PATH, env_path as ui_env_path


def test_standalone_uses_repository_environment_and_telemetry_paths(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OSSTD_LLM_API", "test-api-key")
    spec = load_openstudio_agent_spec()
    telemetry_path = Path(spec.to_factory_kwargs()["telemetry_config"]["path"])

    assert agent_env_path == repo_root / ".env"
    assert ui_env_path == repo_root / ".env"
    assert telemetry_path.resolve() == repo_root / "logs" / "telemetry.jsonl"
    assert TELEMETRY_LOG_PATH == repo_root / "logs" / "telemetry.jsonl"


def test_openstudio_agent_yaml_loads_as_a_local_agent(monkeypatch) -> None:
    monkeypatch.setenv("OSSTD_LLM_API", "test-api-key")
    mcp_config = build_openstudio_ai_mcp_config()
    spec = load_openstudio_agent_spec(mcp_config)
    factory_kwargs = spec.to_factory_kwargs()

    assert spec.agent is not None
    assert spec.agent.name == "OpenStudio AI Model Workspace Agent"
    assert spec.agent_card is None
    assert spec.a2a is None
    assert spec.resolve_instructions().startswith(
        (repo_root / "prompts" / "openstudio_agent.md").read_text(encoding="utf-8").rstrip()
    )
    assert spec.mcp is not None
    assert spec.mcp.servers["openstudio_ai_mcp"].host == mcp_config.host
    assert spec.mcp.servers["openstudio_ai_mcp"].port == mcp_config.port
    assert factory_kwargs["tools_config"]["tools"][0]["type"] == "run_python"
    assert Path(factory_kwargs["tools_config"]["tools"][0]["config"]["workspace_root"]).resolve() == Path(".").resolve()
    skill_manager = SkillManager.from_config(factory_kwargs["skills_config"])
    assert set(skill_manager.available_skills()) >= {
        path.stem for path in Path("skills").glob("*.md")
    }
    assert "surface_azimuth_degrees(surface)" in skill_manager.load("openstudio_sdk_model_editor")
    instructions = spec.resolve_instructions()
    assert "## MCP Tool Routing" in instructions
    assert "Use `openstudio_workflow_state`" in instructions


def test_openstudio_agent_uses_mcp_blackboard(monkeypatch) -> None:
    monkeypatch.setenv("OSSTD_LLM_API", "test-api-key")
    spec = load_openstudio_agent_spec(build_openstudio_ai_mcp_config())
    factory_kwargs = spec.to_factory_kwargs()

    assert factory_kwargs["blackboard_config"] is None
    skill_manager = SkillManager.from_config(factory_kwargs["skills_config"])
    workflow_state_skill = skill_manager.load("openstudio_workflow_state")
    assert "blackboard_initialize_workflow" in workflow_state_skill
    assert "AUTOMA-AI native blackboard" in workflow_state_skill


def test_prompt_skill_references_load_in_standalone(monkeypatch) -> None:
    """Every skill the shared prompt tells the model to load must resolve.

    The prompt uses frontmatter names (e.g. ``delegated-nlr-modeling``) while
    automa-ai resolves directory skills by file stem.
    """
    monkeypatch.setenv("OSSTD_LLM_API", "test-api-key")
    spec = load_openstudio_agent_spec()
    skill_manager = SkillManager.from_config(spec.to_factory_kwargs()["skills_config"])
    prompt = (repo_root / "prompts" / "openstudio_agent.md").read_text(encoding="utf-8")
    referenced = set(
        re.findall(r"(?:[Ll]oad|directed by) `([A-Za-z0-9_.-]+)`", prompt)
        + re.findall(r"Use `([A-Za-z0-9_.-]+)`\s+(?:for|when)", prompt)
    )

    assert {"delegated-nlr-modeling", "hvac_sizing_assistant", "openstudio_workflow_state"} <= referenced
    for name in referenced:
        assert not skill_manager.load(name).startswith("SKILL_ERROR"), name
        assert f"SKILL: {name}" in skill_manager.load(name), name


def test_standalone_prompt_lists_skill_catalog(monkeypatch) -> None:
    monkeypatch.setenv("OSSTD_LLM_API", "test-api-key")
    instructions = load_openstudio_agent_spec().resolve_instructions()
    catalog = instructions.split("## Available Skills", 1)[1]

    assert "- `delegated-nlr-modeling`: Use NLR OpenStudio-MCP" in catalog
    assert "- `hvac_sizing_assistant`:" in catalog
    assert "- `openstudio_workflow_state`:" in catalog


def test_developer_learning_agent_yaml_matches_automa_ai_spec() -> None:
    spec = YamlAgentSpec.from_yaml_file(
        Path("learning/developer_agent/developer_learning_agent.yaml")
    )
    instructions = spec.resolve_instructions()

    assert spec.agent_card["name"] == "OpenStudio Developer Learning Agent"
    assert spec.runtime.agent_type.value == "langgraph-chat"
    assert "Create candidates only." in instructions
    assert "Do not promote trusted assets." in instructions
    assert "review queue" in instructions
