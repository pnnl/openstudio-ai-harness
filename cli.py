from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from adapters.claude_code_adapter import ClaudeCodeAdapter
from adapters.codex_adapter import CodexAdapter
from adapters.contracts import RUNTIME_MODES, HostAdapterConfig
from openstudio_mcp.compatibility import (
    PLUGIN_CONTRACT_VERSION,
    evaluate_plugin_compatibility,
    package_version,
    plugin_mcp_environment,
)


def _version() -> str:
    """Return the installed package version, falling back during source checkout use."""
    return package_version()


def _default_root() -> Path:
    """Return the harness root for source checkout or installed flat-package use."""
    return Path(__file__).resolve().parent


def _user_data_dir() -> Path:
    """Return a cross-platform local data directory."""
    override = os.getenv("OPENSTUDIO_AI_DATA_DIR")
    if override:
        return Path(override).expanduser()

    try:
        from platformdirs import user_data_path

        return Path(
            user_data_path(
                appname="OpenStudioAI",
                appauthor="PNNL",
                roaming=False,
            )
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


def _command_available(command: str) -> dict[str, Any]:
    """Return simple command availability information for doctor output."""
    path = shutil.which(command)
    if path is None:
        executable_dir = Path(sys.executable).parent
        candidates = [executable_dir / command]
        if os.name == "nt":
            candidates.append(executable_dir / f"{command}.exe")
        for candidate in candidates:
            if candidate.exists():
                path = str(candidate)
                break
    return {"command": command, "available": path is not None, "path": path}


def _run_probe(command: list[str], *, timeout_seconds: int = 10) -> dict[str, Any]:
    """Run a bounded command probe and return JSON-safe status details."""
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError:
        return {"ok": False, "error": "command not found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timed out after {timeout_seconds} seconds"}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": stdout[:2000],
        "stderr": stderr[:2000],
    }


def _python_openstudio_probe() -> dict[str, Any]:
    """Check whether the current Python can import the OpenStudio SDK."""
    try:
        import openstudio

        version = None
        if hasattr(openstudio, "openStudioVersion"):
            version = str(openstudio.openStudioVersion())
        return {"ok": True, "version": version}
    except (
        Exception
    ) as exc:  # pragma: no cover - import failures depend on environment.
        return {"ok": False, "error": str(exc)}


def _sdk_docs_probe() -> dict[str, Any]:
    """Verify the configured SDK YAML bundle has a readable metadata header."""
    configured_dir = os.getenv("OPENSTUDIO_SDK_DOCS_DIR", "").strip()
    try:
        from openstudio_mcp.sdk_docs import OpenStudioSdkDocLookup

        lookup = OpenStudioSdkDocLookup.from_env()
        docs_dir = lookup.docs_dir
        result: dict[str, Any] = {
            "ok": False,
            "configured": docs_dir is not None,
            "source": lookup.source,
            "path": str(docs_dir) if docs_dir else None,
            "selected_version": lookup.selected_version(),
        }
        if lookup.override_path is not None:
            result["override_path"] = str(lookup.override_path)
            result["override_warning"] = lookup.override_warning
        if not lookup.available():
            result["available"] = False
            result["error"] = "The configured SDK documentation bundle is unavailable."
            return result

        result.update(
            {
                "ok": True,
                "available": True,
                "document_probe": lookup.health_probe(),
            }
        )
        return result
    except Exception as exc:  # pragma: no cover - filesystem and YAML failures vary.
        return {
            "ok": False,
            "available": False,
            "configured": bool(configured_dir),
            "source": "environment" if configured_dir else "bundled",
            "path": configured_dir or None,
            "selected_version": None,
            "error": str(exc),
        }


def _check_runtime_assets(root: Path) -> dict[str, Any]:
    """Check package assets that the MCP runtime and exports depend on."""
    required_files = {
        "measure_registry": root / "policy" / "measure_registry.yaml",
        "sdk_recipes": root / "knowledge" / "openstudio_sdk_recipes.md",
        "blackboard_schema": root
        / "blackboard"
        / "schemas"
        / "workflow_state.schema.json",
    }
    required_dirs = {
        "skills": root / "skills",
        "knowledge": root / "knowledge",
        "sdk_index": root / "sdk_index",
        "approved_measures": root / "measures" / "approved",
    }
    files = {
        name: {"path": str(path), "exists": path.is_file()}
        for name, path in required_files.items()
    }
    dirs = {
        name: {"path": str(path), "exists": path.is_dir()}
        for name, path in required_dirs.items()
    }
    missing_files = [name for name, item in files.items() if not item["exists"]]
    missing_dirs = [name for name, item in dirs.items() if not item["exists"]]
    ok = not missing_files and not missing_dirs
    result: dict[str, Any] = {
        "ok": ok,
        "files": files,
        "directories": dirs,
        "missing_files": missing_files,
        "missing_directories": missing_dirs,
    }
    if not ok:
        result["message"] = (
            "Packaged runtime assets are missing. Reinstall openstudio-ai, or run "
            "`openstudio-ai repair` if this is an editable development checkout."
        )
    return result


def _runtime_storage_status(workspace_dir: Path) -> dict[str, Any]:
    """Return user runtime storage status without creating directories."""
    data_dir = workspace_dir.parent
    status: dict[str, Any] = {
        "initialized": workspace_dir.is_dir(),
        "data_dir_exists": data_dir.exists(),
        "workspace_dir": str(workspace_dir),
        "writable": None,
        "ok": False,
    }
    if not workspace_dir.exists():
        status["message"] = (
            "Runtime storage is not initialized yet. Run `openstudio-ai install-runtime` "
            "to create user-local storage."
        )
        return status
    if not workspace_dir.is_dir():
        status["message"] = (
            f"Runtime workspace path exists but is not a directory: {workspace_dir}"
        )
        return status
    try:
        probe = workspace_dir / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        status["writable"] = True
        status["ok"] = True
    except OSError as exc:
        status["writable"] = False
        status["error"] = str(exc)
        status["message"] = f"Runtime storage is not writable: {workspace_dir}"
    return status


def _sqlite_registry_probe() -> dict[str, Any]:
    """Check SQLite support in a temporary directory without touching user data."""
    try:
        with tempfile.TemporaryDirectory(prefix="openstudio-ai-doctor-") as tmp:
            db_path = Path(tmp) / "doctor_registry_probe.sqlite"
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS doctor_probe (id INTEGER PRIMARY KEY)"
                )
                conn.execute("INSERT INTO doctor_probe DEFAULT VALUES")
                conn.execute("SELECT COUNT(*) FROM doctor_probe").fetchone()
        return {"ok": True}
    except (OSError, sqlite3.Error) as exc:
        return {"ok": False, "error": str(exc)}


def _diagnostic(
    code: str,
    severity: str,
    message: str,
    remediation: str,
    detail: str | None = None,
) -> dict[str, str]:
    """Create a stable, user-facing doctor diagnostic."""
    result = {
        "code": code,
        "severity": severity,
        "message": message,
        "remediation": remediation,
    }
    if detail:
        result["detail"] = detail[:1000]
    return result


def _doctor_diagnostics(checks: dict[str, Any]) -> list[dict[str, str]]:
    """Translate low-level checks into actionable user-facing failures."""
    diagnostics: list[dict[str, str]] = []
    compatibility = checks["plugin_compatibility"]
    if not compatibility["ok"]:
        diagnostics.append(
            _diagnostic(
                "plugin_runtime_incompatible",
                "warning",
                compatibility["message"],
                compatibility["remediation"],
                (
                    "Plugin contract "
                    f"{compatibility['plugin_contract_version']}; runtime contract "
                    f"{compatibility['runtime_contract_version']}."
                ),
            )
        )
    elif compatibility["status"] == "not_declared":
        diagnostics.append(
            _diagnostic(
                "plugin_contract_not_declared",
                "warning",
                compatibility["message"],
                compatibility["remediation"],
            )
        )

    mcp_command = checks["commands"]["openstudio_ai_mcp"]
    if not mcp_command["available"]:
        diagnostics.append(
            _diagnostic(
                "mcp_command_missing",
                "error",
                "The OpenStudio AI MCP command is not available to this Python environment.",
                "Run the OpenStudio AI setup workflow to install or repair the runtime, then reload or reconnect the plugin.",
            )
        )
    elif not mcp_command["help_probe"].get("ok"):
        probe = mcp_command["help_probe"]
        diagnostics.append(
            _diagnostic(
                "mcp_command_failed",
                "error",
                "The OpenStudio AI MCP command was found but could not start cleanly.",
                "Run the OpenStudio AI setup workflow to reinstall the runtime, then reload or reconnect the plugin.",
                str(
                    probe.get("stderr") or probe.get("error") or "unknown startup error"
                ),
            )
        )

    mcp_startup = checks["mcp_startup"]
    if not mcp_startup["ok"]:
        diagnostics.append(
            _diagnostic(
                "mcp_startup_failed",
                "error",
                "The OpenStudio AI MCP runtime could not initialize its services.",
                "Run the OpenStudio AI setup workflow to repair the runtime. If the issue remains, share the technical detail with your support contact.",
                str(mcp_startup.get("error") or "unknown startup error"),
            )
        )

    storage = checks["runtime_storage"]
    if not storage["ok"]:
        diagnostics.append(
            _diagnostic(
                "runtime_storage_not_ready",
                "error",
                storage.get("message", "OpenStudio AI runtime storage is not ready."),
                "Run `openstudio-ai install-runtime` to initialize user-local storage.",
                storage.get("error"),
            )
        )

    if not checks["assets"]["ok"]:
        diagnostics.append(
            _diagnostic(
                "runtime_assets_missing",
                "error",
                checks["assets"]["message"],
                "Reinstall openstudio-ai, then run `openstudio-ai repair` if the issue remains.",
                ", ".join(
                    checks["assets"]["missing_files"]
                    + checks["assets"]["missing_directories"]
                ),
            )
        )

    if not checks["python_openstudio"]["ok"]:
        diagnostics.append(
            _diagnostic(
                "openstudio_python_sdk_unavailable",
                "warning",
                "The OpenStudio Python SDK is unavailable, so model editing and measures are not ready.",
                "Install the native OpenStudio application, then reinstall openstudio-ai and rerun doctor.",
                str(checks["python_openstudio"].get("error") or "SDK import failed"),
            )
        )

    sdk_docs = checks["sdk_docs"]
    if not sdk_docs.get("ok"):
        diagnostics.append(
            _diagnostic(
                "sdk_docs_unavailable",
                "warning",
                "The OpenStudio SDK documentation bundle cannot answer SDK lookups.",
                "Remove or correct OPENSTUDIO_SDK_DOCS_DIR. The MCP runtime remains available; when a selected versioned gzip is unavailable, SDK lookup falls back to the available default bundle.",
                str(sdk_docs.get("error") or "SDK docs probe failed"),
            )
        )

    if not checks["openstudio"]["ok"]:
        diagnostics.append(
            _diagnostic(
                "openstudio_command_unavailable",
                "warning",
                "The native OpenStudio command is unavailable, so simulations are not ready.",
                "Install OpenStudio or set OPENSTUDIO_PATH, then rerun doctor.",
                str(
                    checks["openstudio"].get("error")
                    or "OpenStudio version probe failed"
                ),
            )
        )
    return diagnostics


def _doctor_payload(
    *, plugin_version: str | None = None, plugin_contract_version: str | None = None
) -> dict[str, Any]:
    """Collect runtime readiness checks without mutating user models or projects."""
    harness_root = _default_root()
    data_dir = _user_data_dir()
    workspace_dir = data_dir / "workspace"
    checks: dict[str, Any] = {
        "version": _version(),
        "python": {
            "executable": sys.executable,
            "version": sys.version.split()[0],
        },
        "paths": {
            "harness_root": str(harness_root),
            "data_dir": str(data_dir),
            "workspace_dir": str(workspace_dir),
        },
        "commands": {
            "openstudio_ai_mcp": _command_available("openstudio-ai-mcp"),
            "openstudio": _command_available("openstudio"),
        },
        "imports": {},
        "assets": _check_runtime_assets(harness_root),
        "runtime_storage": _runtime_storage_status(workspace_dir),
        "sqlite_registry": _sqlite_registry_probe(),
        "mcp_startup": {"ok": False},
        "sdk_docs": {},
        "measures": {"ok": False},
        "plugin_compatibility": evaluate_plugin_compatibility(
            plugin_version=plugin_version,
            plugin_contract_version=plugin_contract_version,
        ).to_dict(),
        "python_openstudio": _python_openstudio_probe(),
        "openstudio": {
            "ok": False,
            "required_for": ["model edits", "simulations", "measure execution"],
        },
    }

    try:
        from openstudio_mcp.server import BASE_DIR, OpenStudioService, create_server

        checks["imports"]["openstudio_mcp"] = {"ok": True, "base_dir": str(BASE_DIR)}
    except (
        Exception
    ) as exc:  # pragma: no cover - exact import failure is environment-specific.
        checks["imports"]["openstudio_mcp"] = {"ok": False, "error": str(exc)}
        OpenStudioService = None  # type: ignore[assignment]
        create_server = None  # type: ignore[assignment]

    if create_server is not None:
        try:
            with tempfile.TemporaryDirectory(
                prefix="openstudio-ai-mcp-startup-"
            ) as tmp:
                create_server(workspace_root=Path(tmp) / "workspace")
            checks["mcp_startup"] = {"ok": True}
        except (
            Exception
        ) as exc:  # pragma: no cover - environment-specific startup failures.
            checks["mcp_startup"] = {"ok": False, "error": str(exc)}

    mcp_command = checks["commands"]["openstudio_ai_mcp"]
    if mcp_command["available"]:
        mcp_probe = _run_probe([mcp_command["path"] or "openstudio-ai-mcp", "--help"])
        mcp_command["help_probe"] = mcp_probe
    else:
        mcp_command["help_probe"] = {"ok": False, "error": "command not found"}

    checks["sdk_docs"] = _sdk_docs_probe()

    if OpenStudioService is not None:
        try:
            with tempfile.TemporaryDirectory(prefix="openstudio-ai-service-") as tmp:
                service = OpenStudioService(workspace_root=Path(tmp) / "workspace")
                public_measures = service.measure_registry.list_public_specs()
                missing_entrypoints = [
                    spec.measure_id
                    for spec in service.measure_registry._measures.values()
                    if spec.allowed and not spec.entrypoint.exists()
                ]
            checks["measures"] = {
                "ok": bool(public_measures) and not missing_entrypoints,
                "count": len(public_measures),
                "missing_entrypoints": missing_entrypoints,
            }
        except (
            Exception
        ) as exc:  # pragma: no cover - environment-specific service failures.
            checks["measures"] = {"ok": False, "error": str(exc)}

    configured_openstudio = os.getenv("OPENSTUDIO_PATH", "").strip()
    openstudio_command = configured_openstudio or "openstudio"
    openstudio_status = _command_available(openstudio_command)
    checks["openstudio"].update(openstudio_status)
    if openstudio_status["available"]:
        version_probe = _run_probe(
            [openstudio_status["path"] or openstudio_command, "--version"]
        )
        checks["openstudio"]["version_probe"] = version_probe
        checks["openstudio"]["ok"] = version_probe["ok"]
    else:
        checks["openstudio"]["error"] = (
            "OpenStudio command not found. Set OPENSTUDIO_PATH or add openstudio to PATH "
            "before running model edits or simulations."
        )

    checks["mcp_ready"] = (
        checks["imports"].get("openstudio_mcp", {}).get("ok") is True
        and checks["assets"].get("ok") is True
        and checks["runtime_storage"].get("ok") is True
        and checks["sqlite_registry"].get("ok") is True
        and checks["mcp_startup"].get("ok") is True
        and checks["commands"]["openstudio_ai_mcp"].get("help_probe", {}).get("ok")
        is True
        and checks["measures"].get("ok") is True
    )
    checks["plugin_ready"] = (
        checks["mcp_ready"] and checks["plugin_compatibility"].get("ok") is True
    )
    checks["simulation_ready"] = (
        checks["mcp_ready"]
        and checks["python_openstudio"].get("ok") is True
        and checks["openstudio"].get("ok") is True
    )
    checks["ready"] = checks["mcp_ready"]
    checks["diagnostics"] = _doctor_diagnostics(checks)
    return checks


def _print_json_or_text(payload: dict[str, Any], *, as_json: bool) -> None:
    """Print command output as JSON for automation or text for users."""
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=True))
        return

    print(f"OpenStudio AI {payload.get('version', _version())}")
    if "mcp_ready" in payload:
        status = "ready" if payload["mcp_ready"] else "not ready"
        print(f"MCP runtime status: {status}")
        if "simulation_ready" in payload:
            sim_status = "ready" if payload["simulation_ready"] else "not ready"
            print(f"OpenStudio execution status: {sim_status}")
    if "paths" in payload:
        print("\nPaths:")
        for key, value in payload["paths"].items():
            print(f"- {key}: {value}")
    if "commands" in payload:
        print("\nCommands:")
        for item in payload["commands"].values():
            found = "found" if item["available"] else "missing"
            suffix = f" at {item['path']}" if item.get("path") else ""
            print(f"- {item['command']}: {found}{suffix}")
    print("\nChecks:")
    check_rows = [
        ("runtime assets", payload.get("assets", {}).get("ok")),
        ("runtime storage", payload.get("runtime_storage", {}).get("ok")),
        ("sqlite registry", payload.get("sqlite_registry", {}).get("ok")),
        ("mcp startup", payload.get("mcp_startup", {}).get("ok")),
        ("measure registry", payload.get("measures", {}).get("ok")),
        ("plugin compatibility", payload.get("plugin_compatibility", {}).get("ok")),
        ("python openstudio sdk", payload.get("python_openstudio", {}).get("ok")),
        ("sdk docs lookup", payload.get("sdk_docs", {}).get("ok")),
        ("openstudio command", payload.get("openstudio", {}).get("ok")),
    ]
    for name, ok in check_rows:
        if ok is True:
            status = "ok"
        elif name == "plugin compatibility":
            status = "attention required"
        elif ok is False:
            status = "failed"
        else:
            status = "not checked"
        print(f"- {name}: {status}")
    diagnostics = payload.get("diagnostics", [])
    if diagnostics:
        print("\nDiagnostics:")
        for diagnostic in diagnostics:
            print(f"- [{diagnostic['code']}] {diagnostic['message']}")
            print(f"  Next step: {diagnostic['remediation']}")
            if diagnostic.get("detail"):
                print(f"  Technical detail: {diagnostic['detail']}")
    if payload.get("ready") is False:
        print(
            "\nOpenStudio AI can still provide planning, skills, and SDK guidance, "
            "but runtime setup must be fixed before full MCP execution is reliable."
        )
        storage_message = payload.get("runtime_storage", {}).get("message")
        if storage_message:
            print(f"Runtime storage: {storage_message}")
        asset_message = payload.get("assets", {}).get("message")
        if asset_message:
            print(f"Runtime assets: {asset_message}")
    elif payload.get("plugin_ready") is False:
        print(
            "\nThe MCP runtime is available, but this plugin targets a different MCP "
            "interface version. Refresh the plugin or update openstudio-ai through pip."
        )
    elif payload.get("simulation_ready") is False:
        print(
            "\nThe MCP runtime is available, but OpenStudio execution is not ready. "
            "Install OpenStudio or set OPENSTUDIO_PATH before model edits and simulations."
        )
        sdk_error = payload.get("python_openstudio", {}).get("error")
        if sdk_error:
            print(
                "OpenStudio Python SDK: the `openstudio` Python package is a required "
                "dependency for model editing and measures. Reinstall openstudio-ai, "
                "confirm the native OpenStudio application is installed, and rerun doctor."
            )


def _cmd_doctor(args: argparse.Namespace) -> int:
    payload = _doctor_payload(
        plugin_version=args.plugin_version,
        plugin_contract_version=args.plugin_contract_version,
    )
    _print_json_or_text(payload, as_json=args.json)
    return 0 if payload["ready"] else 1


def _cmd_paths(args: argparse.Namespace) -> int:
    payload = {
        "version": _version(),
        "paths": {
            "harness_root": str(_default_root()),
            "data_dir": str(_user_data_dir()),
            "workspace_dir": str(_user_data_dir() / "workspace"),
        },
    }
    _print_json_or_text(payload, as_json=args.json)
    return 0


def _cmd_version(_: argparse.Namespace) -> int:
    print(_version())
    return 0


def _cmd_install_runtime(_: argparse.Namespace) -> int:
    data_dir = _user_data_dir()
    workspace_dir = data_dir / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    print("OpenStudio AI runtime installer")
    print("The runtime package is already installed if this command is available.")
    print(f"Initialized runtime workspace at: {workspace_dir}")
    print("Run `openstudio-ai doctor` to validate MCP readiness.")
    return 0


def _cmd_repair(_: argparse.Namespace) -> int:
    data_dir = _user_data_dir()
    (data_dir / "workspace").mkdir(parents=True, exist_ok=True)
    print("OpenStudio AI repair completed non-destructive checks.")
    print(f"Ensured runtime workspace exists at: {data_dir / 'workspace'}")
    print("Run `openstudio-ai doctor` for the current readiness report.")
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    if args.host == "marketplace":
        return _cmd_export_marketplace(args)

    config = HostAdapterConfig(
        host_name=args.host,
        workspace_root=args.workspace_root,
        runtime_mode=args.runtime_mode,
    )
    if args.host == "claude":
        result = ClaudeCodeAdapter(config).export_plugin(
            args.output_dir,
            plugin_name=args.plugin_name,
            dry_run=args.dry_run,
            force=args.force,
        )
        print(
            f"{'Would export' if result.dry_run else 'Exported'} Claude plugin: {result.plugin_dir}"
        )
        return 0
    if args.host == "codex":
        result = CodexAdapter(config).export_plugin(
            args.output_dir,
            plugin_name=args.plugin_name,
            dry_run=args.dry_run,
            force=args.force,
        )
        print(
            f"{'Would export' if result.dry_run else 'Exported'} Codex plugin: {result.plugin_dir}"
        )
        return 0
    raise ValueError(f"Unsupported export host: {args.host}")


def _source_provenance(workspace_root: Path) -> dict[str, object]:
    """Return stable source provenance without embedding local paths or timestamps."""

    def git_output(*command: str) -> str | None:
        try:
            completed = subprocess.run(
                ["git", "-C", str(workspace_root), *command],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return None
        if completed.returncode != 0:
            return None
        value = completed.stdout.strip()
        return value or None

    revision = git_output("rev-parse", "HEAD")
    dirty_output = git_output("status", "--porcelain")
    return {
        "revision": revision,
        "dirty": bool(dirty_output) if dirty_output is not None else None,
    }


def _render_marketplace_readme(
    *, plugin_name: str, runtime_mode: str, provenance: dict[str, object]
) -> str:
    """Render the host-neutral release overview for a paired marketplace export."""
    revision = provenance["revision"] or "unavailable"
    return (
        "# OpenStudio AI Plugins\n\n"
        "This repository is a generated marketplace distribution for the OpenStudio AI "
        "runtime. Do not edit generated plugin files here; change the harness source and "
        "re-export instead.\n\n"
        "## Install\n\n"
        "- [Claude Code installation](INSTALL.claude.md)\n"
        "- [Codex installation](INSTALL.codex.md)\n\n"
        "## Contents\n\n"
        f"- Claude plugin: `{plugin_name}/`\n"
        f"- Codex plugin: `plugins/{plugin_name}/`\n"
        "- Runtime: install or update through the setup workflow after enabling a plugin.\n\n"
        "## Provenance\n\n"
        f"- Package version: `{_version()}`\n"
        f"- MCP interface contract: `{PLUGIN_CONTRACT_VERSION}`\n"
        f"- Runtime mode: `{runtime_mode}`\n"
        f"- Source revision: `{revision}`\n"
        "- Complete machine-readable metadata: [`.generated.json`](.generated.json)\n"
    )


def _cmd_export_marketplace(args: argparse.Namespace) -> int:
    """Export Claude and Codex packages into one publishable marketplace tree."""
    workspace_root = args.workspace_root.resolve()
    output_dir = args.output_dir.resolve()
    claude = ClaudeCodeAdapter(
        HostAdapterConfig(
            host_name="claude",
            workspace_root=workspace_root,
            runtime_mode=args.runtime_mode,
        )
    )
    codex = CodexAdapter(
        HostAdapterConfig(
            host_name="codex",
            workspace_root=workspace_root,
            runtime_mode=args.runtime_mode,
        )
    )

    if args.dry_run:
        claude.export_plugin(
            output_dir,
            plugin_name=args.plugin_name,
            dry_run=True,
            force=args.force,
        )
        codex.export_plugin(
            output_dir,
            plugin_name=args.plugin_name,
            dry_run=True,
            force=args.force,
        )
        print(f"Would export paired Claude and Codex marketplace: {output_dir}")
        return 0

    claude.export_plugin(
        output_dir,
        plugin_name=args.plugin_name,
        dry_run=False,
        force=args.force,
    )
    claude_install = (output_dir / "INSTALL.md").read_text(encoding="utf-8")

    codex.export_plugin(
        output_dir,
        plugin_name=args.plugin_name,
        dry_run=False,
        force=args.force,
    )
    codex_install = (output_dir / "INSTALL.md").read_text(encoding="utf-8")

    provenance = {
        "schema_version": 1,
        "generator": "openstudio-ai export marketplace",
        "package": {"name": "openstudio-ai", "version": _version()},
        "plugin": {
            "name": args.plugin_name,
            "mcp_interface_contract_version": PLUGIN_CONTRACT_VERSION,
            "runtime_mode": args.runtime_mode,
        },
        "source": _source_provenance(workspace_root),
    }
    (output_dir / "INSTALL.claude.md").write_text(claude_install, encoding="utf-8")
    (output_dir / "INSTALL.codex.md").write_text(codex_install, encoding="utf-8")
    (output_dir / "INSTALL.md").unlink()
    (output_dir / "README.md").write_text(
        _render_marketplace_readme(
            plugin_name=args.plugin_name,
            runtime_mode=args.runtime_mode,
            provenance=provenance["source"],
        ),
        encoding="utf-8",
    )
    (output_dir / ".generated.json").write_text(
        json.dumps(provenance, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    validate_args = argparse.Namespace(
        runtime_mode=args.runtime_mode,
        strict_runtime_version=True,
    )
    for plugin_dir in (
        output_dir / args.plugin_name,
        output_dir / "plugins" / args.plugin_name,
    ):
        validate_args.path = plugin_dir
        if _cmd_validate_export(validate_args) != 0:
            return 1

    print(f"Exported paired Claude and Codex marketplace: {output_dir}")
    return 0


def _cmd_install_host_guidance(args: argparse.Namespace) -> int:
    """Install host-specific project guidance without exporting a plugin again."""
    if args.host != "codex":
        raise ValueError(f"Unsupported project-guidance host: {args.host}")

    result = CodexAdapter(
        HostAdapterConfig(host_name="codex", workspace_root=args.workspace_root)
    ).install(args.target_dir, dry_run=args.dry_run, force=args.force)
    mode = "Would write" if result.dry_run else "Wrote"
    for action in result.actions:
        print(f"{mode} {action.path} ({action.action})")
        if result.dry_run:
            print(action.content)
    return 0


def _validate_no_developer_paths(plugin_dir: Path) -> list[str]:
    """Return text files in an export that contain hardcoded developer paths."""
    offenders: list[str] = []
    for path in plugin_dir.rglob("*"):
        if not path.is_file() or path.suffix not in {".json", ".md", ".py"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if "/Users/" in text or "\\Users\\" in text:
            offenders.append(str(path.relative_to(plugin_dir)))
    return offenders


def _cmd_validate_export(args: argparse.Namespace) -> int:
    plugin_dir = args.path.resolve()
    if not plugin_dir.exists():
        print(f"Export path does not exist: {plugin_dir}", file=sys.stderr)
        return 1

    is_claude = (plugin_dir / ".claude-plugin" / "plugin.json").exists()
    required = (
        [
            ".mcp.json",
            "README.md",
            "CONNECTORS.md",
            "skills",
            "agents",
            "settings.json",
            "monitors",
            "bin",
        ]
        if is_claude
        else [
            ".mcp.json",
            "README.md",
            "CONNECTORS.md",
            "skills",
            "skills/openstudio-modeling-orchestrator/SKILL.md",
            "skills/openstudio-sdk-model-editor/references/openstudio_sdk_recipes.md",
            "skills/openstudio-workflow-state/references/blackboard_contract.md",
            "skills/openstudio-workflow-state/references/workflow_state.schema.json",
            "skills/openstudio-workflow-state/references/state_patch.schema.json",
            "skills/propose-measure/references/candidate_measure.schema.json",
            "skills/capture-session-lesson/references/session_lesson.schema.json",
        ]
    )
    missing = [item for item in required if not (plugin_dir / item).exists()]
    if missing:
        print("Export is missing required files or directories:")
        for item in missing:
            print(f"- {item}")
        return 1

    mcp_config = json.loads((plugin_dir / ".mcp.json").read_text(encoding="utf-8"))
    server = mcp_config.get("mcpServers", {}).get("openstudio_ai")
    if not isinstance(server, dict):
        print(
            "Export .mcp.json does not define mcpServers.openstudio_ai", file=sys.stderr
        )
        return 1

    server_env = server.get("env")
    required_metadata = plugin_mcp_environment().keys()
    if not isinstance(server_env, dict) or any(
        not isinstance(server_env.get(key), str) or not server_env[key]
        for key in required_metadata
    ):
        print(
            "Export MCP configuration is missing the OpenStudio AI plugin compatibility metadata.",
            file=sys.stderr,
        )
        return 1

    if args.runtime_mode in {"installed", "marketplace"}:
        if server.get("command") != "openstudio-ai-mcp" or server.get("args") != [
            "--transport",
            "stdio",
        ]:
            print(
                "Installed/marketplace exports must point to openstudio-ai-mcp.",
                file=sys.stderr,
            )
            print(f"Actual: {server}", file=sys.stderr)
            return 1

    if args.strict_runtime_version and any(
        server_env.get(key) != value for key, value in plugin_mcp_environment().items()
    ):
        print(
            "Export compatibility metadata does not match the current runtime version.",
            file=sys.stderr,
        )
        return 1

    if args.runtime_mode == "local":
        args_list = server.get("args", [])
        if server.get("command") != sys.executable or args_list[:2] != [
            "-m",
            "openstudio_mcp.server",
        ]:
            print(
                "Local exports must start the source-checkout MCP module.",
                file=sys.stderr,
            )
            return 1

    if args.runtime_mode == "marketplace":
        marketplace_required = (
            [
                "skills/setup-openstudio-ai/SKILL.md",
                "skills/setup-openstudio-ai/scripts/install_runtime.py",
                "skills/setup-openstudio-ai/scripts/doctor_runtime.py",
                "skills/doctor-openstudio-ai/SKILL.md",
                "skills/repair-openstudio-ai/SKILL.md",
            ]
            if is_claude
            else [
                "skills/setup-openstudio-ai/SKILL.md",
                "skills/setup-openstudio-ai/scripts/install_runtime.py",
                "skills/setup-openstudio-ai/scripts/doctor_runtime.py",
                "skills/doctor-openstudio-ai/SKILL.md",
                "skills/repair-openstudio-ai/SKILL.md",
            ]
        )
        missing_marketplace = [
            item for item in marketplace_required if not (plugin_dir / item).exists()
        ]
        if missing_marketplace:
            print("Marketplace export is missing setup files:")
            for item in missing_marketplace:
                print(f"- {item}")
            return 1

        developer_paths = _validate_no_developer_paths(plugin_dir)
        if developer_paths:
            print("Marketplace export contains hardcoded developer paths:")
            for item in developer_paths:
                print(f"- {item}")
            return 1

    print(f"Export looks valid: {plugin_dir}")
    print(f"MCP command: {server.get('command')}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Create the OpenStudio AI CLI parser."""
    parser = argparse.ArgumentParser(
        prog="openstudio-ai", description="OpenStudio AI runtime CLI"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Check runtime readiness.")
    doctor.add_argument(
        "--json", action="store_true", help="Print machine-readable JSON."
    )
    doctor.add_argument(
        "--plugin-version",
        help="Plugin package version to include in this compatibility check.",
    )
    doctor.add_argument(
        "--plugin-contract-version",
        help="Plugin MCP interface contract version to check.",
    )
    doctor.set_defaults(func=_cmd_doctor)

    paths = subparsers.add_parser("paths", help="Print runtime paths.")
    paths.add_argument(
        "--json", action="store_true", help="Print machine-readable JSON."
    )
    paths.set_defaults(func=_cmd_paths)

    version = subparsers.add_parser(
        "version", help="Print installed OpenStudio AI version."
    )
    version.set_defaults(func=_cmd_version)

    install_runtime = subparsers.add_parser(
        "install-runtime", help="Validate or complete runtime installation."
    )
    install_runtime.set_defaults(func=_cmd_install_runtime)

    repair = subparsers.add_parser(
        "repair", help="Run non-destructive runtime repair checks."
    )
    repair.set_defaults(func=_cmd_repair)

    export = subparsers.add_parser("export", help="Export host plugin packages.")
    export.add_argument(
        "host",
        choices=["claude", "codex", "marketplace"],
        help="Host plugin format, or the paired Claude and Codex marketplace, to export.",
    )
    export.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory to write the export into.",
    )
    export.add_argument(
        "--plugin-name", default="openstudio-ai", help="Plugin folder/name."
    )
    export.add_argument(
        "--workspace-root",
        type=Path,
        default=_default_root(),
        help="Harness root containing skills, knowledge, prompts, and MCP files.",
    )
    export.add_argument(
        "--runtime-mode", choices=sorted(RUNTIME_MODES), default="installed"
    )
    export.add_argument(
        "--dry-run", action="store_true", help="Preview files without writing."
    )
    export.add_argument(
        "--force", action="store_true", help="Replace an existing plugin folder."
    )
    export.set_defaults(func=_cmd_export)

    install = subparsers.add_parser(
        "install", help="Install host-specific project guidance."
    )
    install.add_argument(
        "host", choices=["codex"], help="Host project guidance to install."
    )
    install.add_argument(
        "--target-dir",
        type=Path,
        required=True,
        help="Codex project directory where AGENTS.md should be created or updated.",
    )
    install.add_argument(
        "--workspace-root",
        type=Path,
        default=_default_root(),
        help="Harness root containing the shared modeler policy.",
    )
    install.add_argument(
        "--dry-run", action="store_true", help="Preview guidance without writing."
    )
    install.add_argument(
        "--force",
        action="store_true",
        help="Append to an existing unmanaged AGENTS.md.",
    )
    install.set_defaults(func=_cmd_install_host_guidance)

    validate = subparsers.add_parser(
        "validate-export", help="Validate an exported plugin directory."
    )
    validate.add_argument(
        "path", type=Path, help="Plugin directory containing .mcp.json."
    )
    validate.add_argument(
        "--runtime-mode",
        choices=sorted(RUNTIME_MODES),
        default="installed",
        help="Runtime mode contract to validate against.",
    )
    validate.add_argument(
        "--strict-runtime-version",
        action="store_true",
        help="Require exported compatibility metadata to match this runtime exactly.",
    )
    validate.set_defaults(func=_cmd_validate_export)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the `openstudio-ai` console script."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
