"""Shared marketplace runtime launch commands and setup guidance for host adapters."""

from __future__ import annotations

import shlex
from pathlib import Path

from openstudio_ai_mcp.compatibility import PLUGIN_CONTRACT_VERSION, package_version

# Marketplace plugins launch the runtime through `uvx` with an exact package spec,
# so the plugin, MCP server, and SDK-script interpreter all come from one pinned,
# isolated environment.
RUNTIME_PYTHON_VERSION = ">=3.10,<3.14"
# Keep in step with the `openstudio` version in uv.lock (enforced by tests).
OPENSTUDIO_PYTHON_SDK_VERSION = "3.11.0"


def runtime_uvx_options(*, version: str | None = None) -> list[str]:
    """Return the `uvx` options that select the pinned runtime environment.

    The spec is always exact: `version` defaults to this package's version, and
    export validation passes the version a plugin declares so historical exports
    can be checked exactly.
    """
    return [
        "--python",
        RUNTIME_PYTHON_VERSION,
        "--from",
        f"openstudio-ai=={version or package_version()}",
        "--with",
        f"openstudio=={OPENSTUDIO_PYTHON_SDK_VERSION}",
    ]


def runtime_uvx_args(command: str, *, version: str | None = None) -> list[str]:
    """Return `uvx` arguments that run a runtime console script from the pinned spec."""
    return [*runtime_uvx_options(version=version), command]


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

MCP_LAUNCHER_PATH = Path(__file__).with_name("mcp_launcher.py")


def mcp_launcher_source() -> str:
    """Return the standard-library launcher that prefers uv's cache."""
    return MCP_LAUNCHER_PATH.read_text(encoding="utf-8")


def marketplace_mcp_args(*, version: str | None = None) -> list[str]:
    """Return the complete marketplace `uv` argument list for the MCP server.

    `uv run` finds an in-range Python for the launcher (downloading one only if
    none exists); `-I` keeps modules in the host's working directory from
    shadowing the standard library. The launcher then runs the pinned
    `uv tool run` spec offline when cached, online otherwise. `version` is
    optional only because it defaults to this package's exact version.
    """
    return [
        "run",
        "--no-project",
        "--python",
        RUNTIME_PYTHON_VERSION,
        "python",
        "-I",
        "-c",
        mcp_launcher_source(),
        *runtime_uvx_options(version=version),
        "--",
        "openstudio-ai-mcp",
        "--transport",
        "stdio",
    ]


def marketplace_runtime_spec(args: list[str]) -> list[str]:
    """Return the pinned `uv tool run` options embedded in marketplace MCP args."""
    return list(args[args.index("-c") + 2 : args.index("--")])


def marketplace_mcp_server_config(env: dict[str, str]) -> dict[str, object]:
    """Return the marketplace MCP server launch config shared by all hosts."""
    return {"command": "uv", "args": marketplace_mcp_args(), "env": env}


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
    """Explain when the marketplace launch and setup commands need the network."""
    return (
        "Explain that after setup has filled uv's cache, the MCP server starts from that "
        "cache without network access; it needs the network only for the first download "
        "and after a plugin upgrade. The `uvx` setup and doctor commands still recheck "
        "the package index about every 10 minutes, so when the user runs them offline, "
        "suggest prefixing them with `UV_OFFLINE=1`. Organizations with an internal "
        "package mirror can set `UV_DEFAULT_INDEX` in the environment that launches "
        f"{host}. Do not edit `.mcp.json` for this.\n"
    )
