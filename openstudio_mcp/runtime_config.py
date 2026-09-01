"""User-local runtime configuration shared by the CLI and MCP server."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

_OPENSTUDIO_VERSION_RE = re.compile(
    r"^\s*(?:openstudio\s+)?(?P<version>\d+\.\d+\.\d+(?:[+-][0-9A-Za-z.-]+)?)\s*$",
    re.IGNORECASE,
)


def openstudio_version_from_output(output: str) -> str | None:
    """Return a recognized OpenStudio CLI version from `openstudio --version` output."""
    match = _OPENSTUDIO_VERSION_RE.match(output)
    return match.group("version") if match else None


def user_data_dir() -> Path:
    """Return the platform-specific OpenStudio AI data directory."""
    override = os.getenv("OPENSTUDIO_AI_DATA_DIR")
    if override:
        return Path(override).expanduser()
    try:
        from platformdirs import user_data_path

        return Path(
            user_data_path(appname="OpenStudioAI", appauthor="PNNL", roaming=False)
        )
    except ImportError:
        pass
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "OpenStudioAI"
    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "PNNL" / "OpenStudioAI"
    return (
        Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        / "openstudio-ai"
    )


def config_path() -> Path:
    """Return the user-local JSON configuration path."""
    return user_data_dir() / "runtime.json"


def configured_openstudio_path() -> str | None:
    """Read a user-confirmed OpenStudio executable path, if configured."""
    path = config_path()
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(config, dict):
        return None
    value = config.get("openstudio_path")
    return value.strip() if isinstance(value, str) and value.strip() else None


def resolve_openstudio_executable_with_source() -> tuple[str | None, str | None]:
    """Resolve the native executable using the runtime's canonical precedence."""
    explicit_path = os.getenv("OPENSTUDIO_PATH", "").strip()
    if explicit_path:
        candidate = Path(explicit_path).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve()), "OPENSTUDIO_PATH"
        return None, None

    saved_path = configured_openstudio_path()
    if saved_path:
        candidate = Path(saved_path).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve()), "runtime configuration"

    discovered_path = shutil.which("openstudio")
    if discovered_path:
        return str(Path(discovered_path).resolve()), "PATH"
    return None, None


def set_openstudio_path(path: Path) -> Path:
    """Persist a confirmed executable path without modifying host plugin files."""
    destination = config_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps({"openstudio_path": str(path.resolve())}, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination
