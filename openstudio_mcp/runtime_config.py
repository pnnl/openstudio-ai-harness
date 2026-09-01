"""User-local runtime configuration shared by the CLI and MCP server."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path


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
    configured_path = os.getenv("OPENSTUDIO_PATH", "").strip()
    source = "OPENSTUDIO_PATH"
    if not configured_path:
        configured_path = configured_openstudio_path() or ""
        source = "runtime configuration"
    if configured_path:
        candidate = Path(configured_path).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve()), source
        return None, None

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
