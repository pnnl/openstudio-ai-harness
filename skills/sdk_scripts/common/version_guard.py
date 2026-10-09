"""Compatibility checks shared by skill-local SDK scripts (stdlib only)."""

from __future__ import annotations

import importlib
import json
import re
import sys
from pathlib import Path
from common.diagnostics import DiagnosticError, handle_changes


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


class PreparationRequired(DiagnosticError):
    """A planner must not operate on a translated or load-unstable input."""


def model_version(path):
    """Sniff the version without importing older fields into the current IDD."""
    with path.open("rb") as stream:
        header = stream.read(8192).decode("utf-8", errors="replace")
    match = re.search(r"OS:Version\s*,(.*?);", header, flags=re.S | re.I)
    version = re.search(r"\b(\d+\.\d+\.\d+)\b", match.group(1)) if match else None
    if version is None:
        raise DiagnosticError(
            "Cannot determine OSM version from its header", status="invalid_model"
        )
    return version[1]


def object_types(model):
    return {
        str(x.handle()): x.iddObjectType().valueName() for x in model.modelObjects()
    }


def preparation_required(path, source_version, target_version, reason, changes=None):
    details = dict(
        status="requires_preparation",
        requires_preparation=True,
        input_model_path=str(path),
        source_version=source_version,
        target_version=target_version,
        reason=reason,
        next_action=dict(
            operation="prepare_model",
            script="scripts/prepare_model.py",
            input_model_path=str(path),
            output_requirement="Choose a new absolute .osm path; preserve the original",
            then=["re-inventory prepared copy", "re-preflight prepared copy"],
        ),
    )
    if changes is not None:
        details["handle_changes"] = changes
    return PreparationRequired(
        "Input requires bundled model preparation before planning", **details
    )


def _load_translated(sdk, path):
    translator = sdk.osversion.VersionTranslator()
    translator.setAllowNewerVersions(False)
    loaded = translator.loadModel(str(path))
    if not loaded.is_initialized():
        messages = [str(item.logMessage())[:240] for item in translator.errors()][:8]
        raise DiagnosticError(
            f"SDK {sdk.openStudioVersion()} could not load input model",
            status="invalid_model",
            translator_errors=messages,
        )
    model = loaded.get()
    # Check raw ownership before any planner calls availabilityManagers(), which
    # throws on a current-version OSM whose assignment list is missing. The VT
    # does not repair that case. Do not manufacture a replacement list here.
    missing = []
    for loop in [*model.getAirLoopHVACs(), *model.getPlantLoops()]:
        index = next(
            i
            for i in range(loop.numFields())
            if loop.iddObject().getField(i).get().name()
            == "Availability Manager List Name"
        )
        target = loop.getTarget(index)
        if (
            not target.is_initialized()
            or target.get().iddObject().name() != "OS:AvailabilityManagerAssignmentList"
        ):
            missing.append(
                dict(handle=str(loop.handle()), type=loop.iddObjectType().valueName())
            )
    if missing:
        raise DiagnosticError(
            "Loop AvailabilityManagerAssignmentList reference is missing or invalid; the translator cannot repair this current-version input",
            status="invalid_model",
            invalid_reference_count=len(missing),
            invalid_references=missing[:8],
        )
    return model, translator


def load_model(sdk, path, *, allow_preparation=False, check_stability=True):
    """Gate every planner; preparation alone may explicitly translate old input.

    The optional two-load handle guard is ON by default. It never normalizes or
    filters a handle; both sets include all model-object classes.
    """
    path = Path(path)
    version = model_version(path)
    actual = release_version(str(sdk.openStudioVersion()))
    source = tuple(map(int, version.split(".")))
    target = tuple(map(int, actual.split(".")))
    if source > target:
        raise CompatibilityError(
            f"Input model version {version} is newer than this package's SDK {actual}. "
            "Keep it with the compatible NLR provider or use a plugin/package release tested for that SDK. "
            "The local bundle cannot downgrade this model."
        )
    if source < target and not allow_preparation:
        raise preparation_required(path, version, actual, "older_model_version")
    model, translator = _load_translated(sdk, path)
    if check_stability:
        second, _ = _load_translated(sdk, path)
        before, after = object_types(model), object_types(second)
        if before.keys() != after.keys():
            raise preparation_required(
                path,
                version,
                actual,
                "load_handle_instability",
                handle_changes(before, after),
            )
    return model, translator
