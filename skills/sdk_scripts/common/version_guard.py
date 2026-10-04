"""Compatibility checks shared by skill-local SDK scripts (stdlib only)."""

from __future__ import annotations

import importlib
import json
import re
import sys
from pathlib import Path


class CompatibilityError(RuntimeError):
    """Execution must stop before loading or changing a user's model."""


def release_version(value: str) -> str | None:
    """Accept a stable release with optional build metadata, never a prerelease."""
    match = re.fullmatch(
        r"(?:OpenStudio\s+)?(\d+\.\d+\.\d+)(?:\+[0-9A-Za-z.-]+)?",
        value.strip(),
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else None


def load_contract(path: Path | None = None) -> dict:
    """Read the bundled contract; there is no environment/version override."""
    path = path or Path(__file__).resolve().parents[1] / "compatibility.json"
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CompatibilityError(
            f"Cannot read bundled compatibility contract: {exc}"
        ) from exc
    if not isinstance(contract, dict) or contract.get("schema_version") != 1:
        raise CompatibilityError("Unsupported compatibility contract schema")
    required = contract.get("required_openstudio_version")
    if not isinstance(required, str) or release_version(required) != required:
        raise CompatibilityError(
            "Contract must pin one exact stable OpenStudio release"
        )
    platforms = contract.get("platforms")
    if (
        not isinstance(platforms, list)
        or not platforms
        or any(item not in ("darwin", "linux", "win32") for item in platforms)
    ):
        raise CompatibilityError("Contract must declare supported platforms")
    return contract


def require_sdk(contract: dict | None = None):
    """Import and recheck the executing SDK before any model operation."""
    contract = contract if contract is not None else load_contract()
    if sys.platform not in contract["platforms"]:
        raise CompatibilityError("Platform not supported by this bundle")
    required = contract["required_openstudio_version"]
    try:
        sdk = importlib.import_module("openstudio")
        actual = str(sdk.openStudioVersion())
    except Exception as exc:
        raise CompatibilityError(f"OpenStudio SDK is unavailable: {exc}") from exc
    if release_version(actual) != required:
        raise CompatibilityError(
            f"OpenStudio SDK {required} is required; executing SDK reports {actual!r}. "
            "Run through the verified OpenStudio executable; do not fall back to another Python."
        )
    return sdk
