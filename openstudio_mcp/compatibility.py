"""Shared plugin-to-runtime compatibility contract for OpenStudio AI."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib import metadata
import os
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

PACKAGE_NAME = "openstudio-ai"
PACKAGE_VERSION_FALLBACK = "0.2.1"
PLUGIN_VERSION_ENV = "OPENSTUDIO_AI_PLUGIN_VERSION"
PLUGIN_CONTRACT_ENV = "OPENSTUDIO_AI_PLUGIN_CONTRACT_VERSION"
# Contract 2 adds runtime_openstudio_status, which the simulation skill requires
# before any model lifecycle or simulation tool call.
PLUGIN_CONTRACT_VERSION = "2"


@dataclass(frozen=True)
class CompatibilityResult:
    """Result of evaluating a plugin's declared MCP interface contract."""

    ok: bool
    status: str
    plugin_version: str | None
    plugin_contract_version: str | None
    runtime_version: str
    runtime_contract_version: str
    message: str | None = None
    remediation: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return the stable JSON-safe representation used by CLI and MCP callers."""
        return asdict(self)


def package_version() -> str:
    """Return the installed distribution version or the source-checkout fallback."""
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    if pyproject_path.is_file():
        with pyproject_path.open("rb") as handle:
            project = tomllib.load(handle).get("project", {})
        version = project.get("version")
        if isinstance(version, str):
            return version
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        return PACKAGE_VERSION_FALLBACK


def plugin_mcp_environment() -> dict[str, str]:
    """Return MCP environment metadata emitted by host plugin exports."""
    return {
        PLUGIN_VERSION_ENV: package_version(),
        PLUGIN_CONTRACT_ENV: PLUGIN_CONTRACT_VERSION,
    }


def evaluate_plugin_compatibility(
    *,
    plugin_version: str | None = None,
    plugin_contract_version: str | None = None,
) -> CompatibilityResult:
    """Check whether a plugin targets this runtime's MCP interface contract.

    Package versions identify releases. The contract version changes only when a
    plugin would require a different MCP tool surface or argument schema.
    """
    plugin_version = plugin_version or os.getenv(PLUGIN_VERSION_ENV) or None
    plugin_contract_version = (
        plugin_contract_version or os.getenv(PLUGIN_CONTRACT_ENV) or None
    )
    runtime_version = package_version()

    if plugin_contract_version is None:
        return CompatibilityResult(
            ok=True,
            status="not_declared",
            plugin_version=plugin_version,
            plugin_contract_version=None,
            runtime_version=runtime_version,
            runtime_contract_version=PLUGIN_CONTRACT_VERSION,
            message=(
                "The plugin did not declare an MCP interface contract. "
                "Compatibility cannot be verified."
            ),
            remediation="Re-export or reinstall the OpenStudio AI plugin.",
        )

    if plugin_contract_version != PLUGIN_CONTRACT_VERSION:
        return CompatibilityResult(
            ok=False,
            status="incompatible",
            plugin_version=plugin_version,
            plugin_contract_version=plugin_contract_version,
            runtime_version=runtime_version,
            runtime_contract_version=PLUGIN_CONTRACT_VERSION,
            message=(
                "The installed OpenStudio AI runtime does not support the MCP "
                f"interface contract required by this plugin ({plugin_contract_version})."
            ),
            remediation=(
                "Run the OpenStudio AI setup workflow to upgrade the runtime, "
                "then reload or reconnect the plugin."
            ),
        )

    return CompatibilityResult(
        ok=True,
        status="compatible",
        plugin_version=plugin_version,
        plugin_contract_version=plugin_contract_version,
        runtime_version=runtime_version,
        runtime_contract_version=PLUGIN_CONTRACT_VERSION,
    )
