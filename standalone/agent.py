import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from automa_ai.common.mcp_registry import MCPServerConfig
from automa_ai.config.agent_spec import (
    InstructionsSpec,
    MCPConfigSpec,
    MCPServerSpec,
    YamlAgentSpec,
    load_agent_factory_from_yaml,
)
from openstudio_ai_mcp.server import serve

base_dir = Path(__file__).resolve().parent
repo_root = base_dir.parent
env_path = repo_root / ".env"
load_dotenv(dotenv_path=env_path)
# Keep demo-only learning records in the ignored MCP workspace instead of the
# host user-data directory, which may be unavailable to the UI child process.
os.environ.setdefault(
    "OPENSTUDIO_AI_DATA_DIR",
    str(repo_root / ".openstudio_ai_mcp_workspace" / "user_data"),
)

CHAT_BOT_MODEL_NAME = os.getenv("CHAT_BOT_MODEL_NAME", "llama3.1:8b")
CHAT_BOT_MODEL_BASE_URL = os.getenv("CHAT_BOT_MODEL_BASE_URL") or None
OPENSTUDIO_MCP_HOST = os.getenv("OPENSTUDIO_MCP_HOST", "127.0.0.1")
OPENSTUDIO_MCP_PORT = int(os.getenv("OPENSTUDIO_MCP_PORT", "10210"))
AGENT_SPEC_PATH = base_dir / "openstudio_agent.yaml"

# Optional NLR openstudio-mcp connection (externally started, streamable-http),
# e.g. via ``scripts/start_openstudio_mcp.sh --http 10220``. Unset by default so
# the standalone agent never depends on NLR.
NLR_MCP_SERVER_NAME = "openstudio-mcp"
NLR_MCP_HOST_ENV = "NLR_OPENSTUDIO_MCP_HOST"
NLR_MCP_PORT_ENV = "NLR_OPENSTUDIO_MCP_PORT"

# Registry entry whose skills are advertised to the model. automa-ai's
# load_skill exposes no catalog, unlike Claude Code / Codex, which show every
# skill's name and description; without it the model routes from the prompt
# bullets alone.
SKILL_CATALOG_REGISTRY = "openstudio_skills"


def _skill_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig")
    if not text.startswith("---"):
        return {}
    _, block, *_ = text.split("---", 2)
    data = yaml.safe_load(block)
    return data if isinstance(data, dict) else {}


def _catalog_skills(spec: YamlAgentSpec) -> list[tuple[str, str, Path]]:
    """Return (frontmatter name, description, path) for the catalog registry."""
    entry = ((spec.skills or {}).get("registry") or {}).get(SKILL_CATALOG_REGISTRY)
    if not entry:
        return []
    directory = spec._base_dir / entry["path"]
    skills = []
    for path in sorted(directory.glob("*.md")):
        meta = _skill_frontmatter(path)
        if meta.get("name") and meta.get("description"):
            skills.append((str(meta["name"]), " ".join(str(meta["description"]).split()), path))
    return skills


def apply_skill_frontmatter_names(spec: YamlAgentSpec) -> None:
    """Make skills loadable by frontmatter name and list them in the prompt.

    automa-ai resolves directory skills by file stem only, but the shared prompt
    and the exported Claude Code/Codex plugins use frontmatter names (for
    example ``delegated-nlr-modeling`` for ``delegated_nlr_modeling.md``).
    """
    skills = _catalog_skills(spec)
    if not skills:
        return
    registry = spec.skills["registry"]
    for name, _description, path in skills:
        if name != path.stem and name not in registry:
            registry[name] = {"path": str(path)}

    catalog = "\n".join(f"- `{name}`: {description}" for name, description, _ in skills)
    instructions = spec.resolve_instructions().rstrip()
    spec.instructions = InstructionsSpec(
        text=f"{instructions}\n\n## Available Skills\n\nLoad these by name with `load_skill`:\n\n{catalog}\n"
    )


def build_openstudio_ai_mcp_config() -> MCPServerConfig:
    return MCPServerConfig(
        name="openstudio_ai_mcp",
        host=OPENSTUDIO_MCP_HOST,
        port=OPENSTUDIO_MCP_PORT,
        serve=serve,
        transport="sse",
    )


def build_nlr_mcp_server_spec() -> MCPServerSpec | None:
    """Return the NLR openstudio-mcp connection when its port env var is set."""
    port = os.getenv(NLR_MCP_PORT_ENV)
    if not port:
        return None
    return MCPServerSpec(
        name=NLR_MCP_SERVER_NAME,
        host=os.getenv(NLR_MCP_HOST_ENV, "127.0.0.1"),
        port=int(port),
        transport="streamable-http",
    )


def load_openstudio_agent_spec(
    mcp_config: MCPServerConfig | None = None,
    *,
    spec_path: Path | None = None,
) -> YamlAgentSpec:
    """Load the local YAML agent spec and apply environment-specific settings."""
    spec = YamlAgentSpec.from_yaml_file(spec_path or AGENT_SPEC_PATH)
    if not spec.model.name:
        spec.model.name = CHAT_BOT_MODEL_NAME
    if not spec.model.base_url:
        spec.model.base_url = CHAT_BOT_MODEL_BASE_URL
    apply_skill_frontmatter_names(spec)

    if mcp_config is not None and spec.mcp is not None:
        server = spec.mcp.servers["openstudio_ai_mcp"]
        server.host = mcp_config.host
        server.port = mcp_config.port
        server.transport = mcp_config.transport
        server.timeout = mcp_config.timeout
        server.sse_read_timeout = mcp_config.sse_read_timeout

    nlr_server = build_nlr_mcp_server_spec()
    if nlr_server is not None:
        if spec.mcp is None:
            spec.mcp = MCPConfigSpec()
        spec.mcp.servers[NLR_MCP_SERVER_NAME] = nlr_server

    return spec


def build_openstudio_agent():
    """Build the in-process agent used by the Streamlit standalone UI.

    The MCP endpoint is managed by the UI runtime before this factory is used;
    no A2A agent server or agent card is involved.
    """
    spec = load_openstudio_agent_spec(build_openstudio_ai_mcp_config())
    return load_agent_factory_from_yaml(spec).get_agent()
