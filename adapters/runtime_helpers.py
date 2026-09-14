"""Shared marketplace runtime helper renderers for host adapters."""

from __future__ import annotations

from pathlib import Path

from openstudio_ai_mcp.compatibility import PLUGIN_CONTRACT_VERSION, package_version


def write_runtime_helpers(
    installers_dir: Path, *, post_install_guidance: str | None = None
) -> None:
    """Write common setup helpers with optional host-specific reload guidance."""
    installers_dir.mkdir(parents=True, exist_ok=True)
    (installers_dir / "doctor_runtime.py").write_text(
        render_doctor_runtime_script(), encoding="utf-8"
    )
    (installers_dir / "install_runtime.py").write_text(
        render_install_runtime_script(post_install_guidance=post_install_guidance),
        encoding="utf-8",
    )


def render_doctor_runtime_script() -> str:
    """Render the common marketplace runtime doctor helper."""
    return '''"""Check whether the OpenStudio AI runtime can be used by this plugin."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 compatibility for exported helpers
    tomllib = None

PLUGIN_VERSION = "__OPENSTUDIO_AI_PLUGIN_VERSION__"
PLUGIN_CONTRACT_VERSION = "__OPENSTUDIO_AI_PLUGIN_CONTRACT_VERSION__"


def command_status(command: str) -> dict[str, object]:
    path = shutil.which(command)
    return {"command": command, "available": path is not None, "path": path}


def _declared_in_codex_config(name: str, checked_paths: list[str]) -> dict[str, object] | None:
    """Return a Codex ``[mcp_servers.<name>]`` declaration, honoring ``enabled``."""
    codex_config = Path.home() / ".codex" / "config.toml"
    checked_paths.append(str(codex_config))
    if tomllib is None or not codex_config.is_file():
        return None
    try:
        config = tomllib.loads(codex_config.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    servers = config.get("mcp_servers") if isinstance(config, dict) else None
    if not isinstance(servers, dict) or name not in servers:
        return None
    entry = servers[name] if isinstance(servers[name], dict) else {}
    # ``enabled = false`` keeps the declaration but the host will not launch it.
    return {"source": str(codex_config), "host": "codex", "enabled": entry.get("enabled", True) is not False}


def _declared_in_claude_user_config(name: str, checked_paths: list[str], directories: list[Path]) -> dict[str, object] | None:
    """Return a ``claude mcp add`` declaration from ``~/.claude.json`` (user or local scope)."""
    claude_config = Path.home() / ".claude.json"
    checked_paths.append(str(claude_config))
    if not claude_config.is_file():
        return None
    try:
        config = json.loads(claude_config.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(config, dict):
        return None
    servers = config.get("mcpServers")
    if isinstance(servers, dict) and name in servers:
        return {"source": str(claude_config), "host": "claude_user", "enabled": True}
    projects = config.get("projects")
    if isinstance(projects, dict):
        for directory in directories:
            project = projects.get(str(directory))
            servers = project.get("mcpServers") if isinstance(project, dict) else None
            if isinstance(servers, dict) and name in servers:
                return {"source": f"{claude_config}#projects[{directory}]", "host": "claude_local", "enabled": True}
    return None


def _claude_desktop_config_paths() -> list[Path]:
    """Every location the Claude Desktop app stores its MCP config (all platforms checked)."""
    home = Path.home()
    paths = [home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"]
    appdata = os.getenv("APPDATA", "").strip()
    if appdata:
        paths.append(Path(appdata) / "Claude" / "claude_desktop_config.json")
    paths.append(home / ".config" / "Claude" / "claude_desktop_config.json")
    return paths


def _declared_in_claude_desktop_config(name: str, checked_paths: list[str]) -> dict[str, object] | None:
    """Return a Claude Desktop declaration; the app injects these into the sessions it hosts."""
    for desktop_config in _claude_desktop_config_paths():
        checked_paths.append(str(desktop_config))
        if not desktop_config.is_file():
            continue
        try:
            config = json.loads(desktop_config.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        servers = config.get("mcpServers") if isinstance(config, dict) else None
        if isinstance(servers, dict) and name in servers:
            return {"source": str(desktop_config), "host": "claude_desktop", "enabled": True}
    return None


def _declared_in_project_mcp_json(name: str, checked_paths: list[str], directories: list[Path]) -> dict[str, object] | None:
    """Return a project-scope ``.mcp.json`` declaration from cwd or a parent."""
    for directory in directories:
        mcp_config = directory / ".mcp.json"
        checked_paths.append(str(mcp_config))
        if not mcp_config.is_file():
            continue
        try:
            config = json.loads(mcp_config.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        servers = config.get("mcpServers") if isinstance(config, dict) else None
        if isinstance(servers, dict) and name in servers:
            return {"source": str(mcp_config), "host": "claude_project", "enabled": True}
    return None


def find_host_mcp_declaration(name: str) -> dict[str, object]:
    """Locate an optional host MCP connection without launching or changing it."""
    checked_paths: list[str] = []
    found = _declared_in_codex_config(name, checked_paths)
    if found is None:
        try:
            current_directory = Path.cwd()
        except OSError:
            directories: list[Path] = []
        else:
            directories = [current_directory, *current_directory.parents]
        found = _declared_in_claude_user_config(name, checked_paths, directories)
        if found is None:
            found = _declared_in_claude_desktop_config(name, checked_paths)
        if found is None:
            found = _declared_in_project_mcp_json(name, checked_paths, directories)
    if found is None:
        return {"configured": False, "checked_paths": checked_paths}
    return {
        "configured": True,
        "enabled": found["enabled"],
        "name": name,
        "source": found["source"],
        "host": found["host"],
        "checked_paths": checked_paths,
    }


def bem_calibration_mcp_status() -> dict[str, object]:
    """Find a separately configured optional LBNL Calibration-MCP declaration."""
    status = find_host_mcp_declaration("bem-calibration")
    status.update(
        {
            "name": "bem-calibration",
            "domain_service": "lbnl_bem_calibration",
            "command": command_status("bem-calibration-mcp"),
        }
    )
    return status


def bem_calibration_status() -> dict[str, object]:
    """Report optional service configuration without blocking core readiness."""
    mcp = bem_calibration_mcp_status()
    command = mcp["command"]
    if mcp["configured"] and mcp.get("enabled", True) is False:
        status = "configured_disabled"
        message = (
            "LBNL Calibration-MCP is declared as bem-calibration but disabled in the "
            f"host configuration ({mcp.get('source')}); enable it before calibration."
        )
    elif mcp["configured"]:
        status = "configured"
        message = (
            "LBNL Calibration-MCP is separately configured. Verify its version and the exposed "
            "tool inventory before starting calibration."
        )
    elif command["available"]:
        status = "available_not_configured"
        message = (
            "LBNL Calibration-MCP is installed but not configured as the separate "
            "bem-calibration host connection."
        )
    else:
        status = "not_installed"
        message = (
            "LBNL Calibration-MCP is optional and not installed. It is distributed "
            "separately; installing OpenStudio AI does not install it."
        )
    return {
        "blocking": False,
        "status": status,
        "message": message,
        "connector_name": "bem-calibration",
        "domain_service": "lbnl_bem_calibration",
        "command": command,
        "mcp": mcp,
    }


def nlr_mcp_status() -> dict[str, object]:
    """Report whether the optional NLR MCP server is configured locally."""
    status = find_host_mcp_declaration("openstudio-mcp")
    if not status["configured"]:
        status["name"] = "nlr_openstudio"
    return status


def main() -> int:
    report = {
        "python": {
            "executable": sys.executable,
            "version": sys.version.split()[0],
        },
        "openstudio_ai_mcp": command_status("openstudio-ai-mcp"),
        "openstudio_ai": command_status("openstudio-ai"),
        "bem_calibration": bem_calibration_status(),
        "nlr_openstudio": nlr_mcp_status(),
    }
    print(json.dumps(report, indent=2))

    if not report["openstudio_ai_mcp"]["available"] or not report["openstudio_ai"]["available"]:
        print(
            "\\nOpenStudio AI runtime commands are not fully available. "
            "Ask the user before running install_runtime.py."
        )
        return 2

    doctor = subprocess.run(
        [
            "openstudio-ai",
            "doctor",
            "--json",
            "--plugin-version",
            PLUGIN_VERSION,
            "--plugin-contract-version",
            PLUGIN_CONTRACT_VERSION,
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if doctor.stdout:
        print(doctor.stdout.strip())

    try:
        payload = json.loads(doctor.stdout)
    except json.JSONDecodeError:
        print("\\nThe runtime doctor returned an unreadable report. Run `openstudio-ai doctor` directly.")
        if doctor.stderr.strip():
            print(doctor.stderr.strip())
        return 2

    if payload.get("plugin_ready") is False:
        print(
            "\\nThe plugin requires a newer OpenStudio AI MCP interface than the "
            "running runtime provides. Ask the user before running "
            "install_runtime.py, then restart or reconnect the host before retrying."
        )
        if doctor.stderr.strip():
            print(doctor.stderr.strip())
        return doctor.returncode or 1

    if doctor.returncode != 0 or payload.get("core_ready") is not True:
        print("\\nOpenStudio AI is not ready for energy modeling. Resolve the blocking diagnostics, reconnect the host, and rerun setup.")
        if doctor.stderr.strip():
            print(doctor.stderr.strip())
        return doctor.returncode or 1

    print("\\nOpenStudio AI is ready for energy modeling.")
    nlr = payload.get("optional_capabilities", {}).get("nlr_openstudio", {})
    calibration = payload.get("optional_capabilities", {}).get("bem_calibration", {})
    if calibration:
        print(
            "LBNL Calibration-MCP: "
            f"{calibration.get('status', 'unknown')} — {calibration.get('message', '')}"
        )
    if nlr:
        print(f"NLR OpenStudio-MCP: {nlr.get('status', 'unknown')} — {nlr.get('message', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''.replace("__OPENSTUDIO_AI_PLUGIN_VERSION__", package_version()).replace(
        "__OPENSTUDIO_AI_PLUGIN_CONTRACT_VERSION__", PLUGIN_CONTRACT_VERSION
    )


def render_install_runtime_script(*, post_install_guidance: str | None = None) -> str:
    """Render the common approved package install or upgrade helper."""
    guidance = ""
    if post_install_guidance:
        guidance = f'    print("\\n{post_install_guidance}")\n'
    return '''"""Install or repair the OpenStudio AI runtime package for this plugin."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


DEFAULT_PACKAGE_SPEC = "openstudio-ai==__OPENSTUDIO_AI_PLUGIN_VERSION__"


def run(command: list[str]) -> int:
    print(f"\\n$ {' '.join(command)}")
    completed = subprocess.run(command, check=False)
    return completed.returncode


def runtime_command_path(command: str) -> str | None:
    """Find a console script for this interpreter after pip install."""
    path = shutil.which(command)
    if path:
        return path
    scripts_dir = Path(sys.executable).resolve().parent
    candidates = [scripts_dir / command]
    if os.name == "nt":
        candidates.extend(
            [
                scripts_dir / f"{command}.exe",
                scripts_dir / "Scripts" / command,
                scripts_dir / "Scripts" / f"{command}.exe",
            ]
        )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def runtime_cli_path() -> str | None:
    """Find the openstudio-ai console script for this interpreter."""
    return runtime_command_path("openstudio-ai")


def is_pipx_managed_runtime() -> bool:
    """Return whether the active OpenStudio AI command belongs to a pipx venv."""
    command = shutil.which("openstudio-ai")
    if command is None or shutil.which("pipx") is None:
        return False
    resolved = Path(command).resolve()
    return "pipx" in resolved.parts and "venvs" in resolved.parts


def main() -> int:
    print("OpenStudio AI runtime installer")
    print("===============================")
    print(f"Python executable: {sys.executable}")
    print(f"Python version: {sys.version.split()[0]}")

    if sys.version_info < (3, 10):
        print(
            "\\nOpenStudio AI requires Python 3.10 or newer. Install a supported "
            "Python version, then rerun setup."
        )
        return 2

    package_spec = os.getenv("OPENSTUDIO_AI_PACKAGE_SPEC", DEFAULT_PACKAGE_SPEC)
    if shutil.which("openstudio-ai") and shutil.which("openstudio-ai-mcp"):
        print("\\nOpenStudio AI commands are available. Checking for a compatible runtime update.")
    else:
        print("\\nOpenStudio AI runtime is not installed yet.")
    print(f"Installing or upgrading runtime package: {package_spec}")
    print(
        "Set OPENSTUDIO_AI_PACKAGE_SPEC to a wheel path, internal index spec, "
        "or pinned version if your organization does not install from PyPI."
    )
    if is_pipx_managed_runtime() and package_spec == DEFAULT_PACKAGE_SPEC:
        print(
            "The active runtime is managed by pipx; upgrading that environment "
            "so the MCP command used by the host is updated."
        )
        code = run(["pipx", "upgrade", "--install", "openstudio-ai"])
    elif is_pipx_managed_runtime():
        print(
            "\\nThe active runtime is managed by pipx and a custom package specification "
            "was requested. Update that pipx environment with your approved package, then "
            "rerun doctor."
        )
        return 2
    else:
        code = run([sys.executable, "-m", "pip", "install", "--upgrade", package_spec])
    if code != 0:
        print(
            "\\nRuntime package installation failed. Check Python permissions, "
            "network access, package index access, or ask your support contact "
            "for an approved OpenStudio AI package."
        )
        return code

    runtime_cli = runtime_cli_path()
    if runtime_cli is None:
        print("\\nInstalled package, but the openstudio-ai command was not found for this Python environment.")
        return 3
    code = run([runtime_cli, "install-runtime"])
    if code != 0:
        print("\\nInstalled package, but runtime initialization failed.")
        return code

    runtime_mcp = runtime_command_path("openstudio-ai-mcp")
    if not shutil.which("openstudio-ai-mcp"):
        print(
            "\\nThe package installed, but openstudio-ai-mcp is not on PATH in this shell."
        )
        if runtime_mcp:
            print(f"Installed MCP command: {runtime_mcp}")
            print(
                "Add its parent directory to the PATH used to launch the AI tool, then restart "
                "or reconnect the plugin. Keep marketplace .mcp.json configured with the "
                "portable command `openstudio-ai-mcp`; do not replace it with this absolute path."
            )
        else:
            print(
                "The MCP command was not found beside this Python interpreter. Reinstall the "
                "runtime with this same Python, then rerun doctor."
            )
        return 3

    print("\\nOpenStudio AI runtime installation completed.")
__POST_INSTALL_GUIDANCE__    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''.replace("__POST_INSTALL_GUIDANCE__", guidance).replace(
        "__OPENSTUDIO_AI_PLUGIN_VERSION__", package_version()
    )
