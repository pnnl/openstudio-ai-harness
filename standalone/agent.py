import os
from pathlib import Path

from dotenv import load_dotenv

from automa_ai.common.mcp_registry import MCPServerConfig
from automa_ai.config.agent_spec import YamlAgentSpec, load_agent_factory_from_yaml
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


def build_openstudio_ai_mcp_config() -> MCPServerConfig:
    return MCPServerConfig(
        name="openstudio_ai_mcp",
        host=OPENSTUDIO_MCP_HOST,
        port=OPENSTUDIO_MCP_PORT,
        serve=serve,
        transport="sse",
    )


def load_openstudio_agent_spec(
    mcp_config: MCPServerConfig | None = None,
) -> YamlAgentSpec:
    """Load the local YAML agent spec and apply environment-specific settings."""
    spec = YamlAgentSpec.from_yaml_file(AGENT_SPEC_PATH)
    if not spec.model.name:
        spec.model.name = CHAT_BOT_MODEL_NAME
    if not spec.model.base_url:
        spec.model.base_url = CHAT_BOT_MODEL_BASE_URL

    if mcp_config is not None and spec.mcp is not None:
        server = spec.mcp.servers["openstudio_ai_mcp"]
        server.host = mcp_config.host
        server.port = mcp_config.port
        server.transport = mcp_config.transport
        server.timeout = mcp_config.timeout
        server.sse_read_timeout = mcp_config.sse_read_timeout

    return spec


def build_openstudio_agent():
    """Build the in-process agent used by the Streamlit standalone UI.

    The MCP endpoint is managed by the UI runtime before this factory is used;
    no A2A agent server or agent card is involved.
    """
    spec = load_openstudio_agent_spec(build_openstudio_ai_mcp_config())
    return load_agent_factory_from_yaml(spec).get_agent()
