"""Shared marketplace runtime launch commands and setup guidance for host adapters."""

from __future__ import annotations

import shlex

from openstudio_ai_mcp.compatibility import PLUGIN_CONTRACT_VERSION, package_version

# Marketplace plugins launch the runtime through `uvx` with an exact spec, so the
# plugin, MCP server, and SDK-script interpreter all come from one pinned
# environment. `openstudio` publishes wheels for this Python on every platform.
RUNTIME_PYTHON_VERSION = "3.12"
# Keep in step with the `openstudio` version in uv.lock (enforced by tests).
OPENSTUDIO_PYTHON_SDK_VERSION = "3.11.0"


def runtime_uvx_args(command: str, *, version: str | None = None) -> list[str]:
    """Return `uvx` arguments that run a runtime console script from the pinned spec.

    `version` defaults to this package's version; export validation passes the
    version a plugin declares so historical exports can be checked exactly.
    """
    return [
        "--python",
        RUNTIME_PYTHON_VERSION,
        "--from",
        f"openstudio-ai=={version or package_version()}",
        "--with",
        f"openstudio=={OPENSTUDIO_PYTHON_SDK_VERSION}",
        command,
    ]


def runtime_uvx_command(command: str, *args: str, reinstall: bool = False) -> str:
    """Return a copyable shell command for a runtime console script via `uvx`."""
    options = ["--reinstall"] if reinstall else []
    return shlex.join(["uvx", *options, *runtime_uvx_args(command), *args])


def runtime_doctor_command() -> str:
    """Return the doctor command that checks this plugin against its runtime."""
    return runtime_uvx_command(
        "openstudio-ai",
        "doctor",
        "--json",
        "--plugin-version",
        package_version(),
        "--plugin-contract-version",
        PLUGIN_CONTRACT_VERSION,
    )


def marketplace_mcp_args(*, version: str | None = None) -> list[str]:
    """Return the complete marketplace `uvx` argument list for the MCP server."""
    return [*runtime_uvx_args("openstudio-ai-mcp", version=version), "--transport", "stdio"]


def marketplace_mcp_server_config(env: dict[str, str]) -> dict[str, object]:
    """Return the marketplace MCP server launch config shared by all hosts."""
    return {"command": "uvx", "args": marketplace_mcp_args(), "env": env}


def prepare_runtime_guidance(host: str) -> str:
    """Setup-skill text for the runtime preparation step, including its side effects."""
    install = runtime_uvx_command("openstudio-ai", "install-runtime")
    return (
        f"Prepare the runtime with `{install}`. Before running it, tell the user what "
        "it changes and ask for approval: it downloads about 100 MB (the pinned runtime "
        "and its own Python) into uv's cache, and it creates OpenStudio AI's user-local "
        "data folder, which holds model workspaces and simulation runs; the command "
        "prints that folder's location. It does not change project files or any other "
        "Python environment. Use a long command timeout. Filling uv's cache lets the MCP "
        f"server start within {host}'s startup timeout.\n"
    )


def doctor_triage_guidance() -> str:
    """How to act on `plugin_ready: false` without misreading a fresh machine."""
    install = runtime_uvx_command("openstudio-ai", "install-runtime")
    rebuild = runtime_uvx_command("openstudio-ai", "install-runtime", reinstall=True)
    return (
        "If the doctor reports `plugin_ready: false`, read its `diagnostics` codes "
        "before acting. `runtime_storage_not_ready` means the runtime has not been "
        f"prepared yet: with approval, run `{install}`. "
        "`plugin_runtime_incompatible` (or `plugin_compatibility.ok: false`) means uv's "
        "cached runtime is stale or damaged: explain that in normal energy-modeler "
        f"language and ask before rebuilding it with `{rebuild}`. For any other code, "
        "follow that diagnostic's `remediation`.\n"
    )


def offline_guidance(host: str) -> str:
    """Explain the network dependency of the pinned `uvx` launch."""
    return (
        "Explain that uv rechecks the package index about every 10 minutes, even for "
        "this exact pinned runtime, so the MCP server needs network access to start. If "
        "the user works offline or on a restricted network, after setup succeeds suggest "
        f"setting `UV_OFFLINE=1` in the environment that launches {host} (this also "
        "affects their other uv commands); organizations with an internal package mirror "
        "can set `UV_DEFAULT_INDEX` instead. Do not edit `.mcp.json` for this.\n"
    )
