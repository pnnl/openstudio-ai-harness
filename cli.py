from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

from adapters.claude_code_adapter import ClaudeCodeAdapter
from adapters.codex_adapter import CodexAdapter
from adapters.contracts import RUNTIME_MODES, HostAdapterConfig


DIST_NAME = "openstudio-ai"
FALLBACK_VERSION = "0.1.0"


def _version() -> str:
    """Return the installed package version, falling back during source checkout use."""
    try:
        return metadata.version(DIST_NAME)
    except metadata.PackageNotFoundError:
        return FALLBACK_VERSION


def _default_root() -> Path:
    """Return the harness root for source checkout or installed flat-package use."""
    return Path(__file__).resolve().parent


def _user_data_dir() -> Path:
    """Return a cross-platform local data directory without adding a dependency."""
    override = os.getenv("OPENSTUDIO_AI_DATA_DIR")
    if override:
        return Path(override).expanduser()

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "OpenStudioAI"
    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "PNNL" / "OpenStudioAI"
    return Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "openstudio-ai"


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


def _doctor_payload() -> dict[str, Any]:
    """Collect runtime readiness checks without mutating user models or projects."""
    data_dir = _user_data_dir()
    workspace_dir = data_dir / "workspace"
    checks: dict[str, Any] = {
        "version": _version(),
        "python": {
            "executable": sys.executable,
            "version": sys.version.split()[0],
        },
        "paths": {
            "harness_root": str(_default_root()),
            "data_dir": str(data_dir),
            "workspace_dir": str(workspace_dir),
        },
        "commands": {
            "openstudio_ai_mcp": _command_available("openstudio-ai-mcp"),
            "openstudio": _command_available("openstudio"),
        },
        "imports": {},
        "writable_runtime_storage": False,
    }

    try:
        from openstudio_mcp.server import create_server  # noqa: F401

        checks["imports"]["openstudio_mcp"] = {"ok": True}
    except Exception as exc:  # pragma: no cover - exact import failure is environment-specific.
        checks["imports"]["openstudio_mcp"] = {"ok": False, "error": str(exc)}

    try:
        workspace_dir.mkdir(parents=True, exist_ok=True)
        probe = workspace_dir / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks["writable_runtime_storage"] = True
    except OSError as exc:
        checks["writable_runtime_storage"] = False
        checks["storage_error"] = str(exc)

    checks["ready"] = (
        checks["imports"].get("openstudio_mcp", {}).get("ok") is True
        and checks["writable_runtime_storage"] is True
    )
    return checks


def _print_json_or_text(payload: dict[str, Any], *, as_json: bool) -> None:
    """Print command output as JSON for automation or text for users."""
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=True))
        return

    print(f"OpenStudio AI {payload.get('version', _version())}")
    if "ready" in payload:
        status = "ready" if payload["ready"] else "not ready"
        print(f"Runtime status: {status}")
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
    if "imports" in payload:
        print("\nRuntime imports:")
        for name, result in payload["imports"].items():
            print(f"- {name}: {'ok' if result.get('ok') else 'failed'}")
    if payload.get("ready") is False:
        print(
            "\nOpenStudio AI can still provide planning, skills, and SDK guidance, "
            "but runtime setup must be fixed before full MCP execution is reliable."
        )


def _cmd_doctor(args: argparse.Namespace) -> int:
    payload = _doctor_payload()
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
    print("OpenStudio AI runtime installer")
    print("The runtime package is already installed if this command is available.")
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
        print(f"{'Would export' if result.dry_run else 'Exported'} Claude plugin: {result.plugin_dir}")
        return 0
    if args.host == "codex":
        result = CodexAdapter(config).export_plugin(
            args.output_dir,
            plugin_name=args.plugin_name,
            dry_run=args.dry_run,
            force=args.force,
        )
        print(f"{'Would export' if result.dry_run else 'Exported'} Codex plugin: {result.plugin_dir}")
        return 0
    raise ValueError(f"Unsupported export host: {args.host}")


def _cmd_validate_export(args: argparse.Namespace) -> int:
    plugin_dir = args.path.resolve()
    if not plugin_dir.exists():
        print(f"Export path does not exist: {plugin_dir}", file=sys.stderr)
        return 1

    required = [
        ".mcp.json",
        "README.md",
        "CONNECTORS.md",
        "skills",
        "knowledge",
        "instructions",
        "learning",
        "blackboard",
    ]
    missing = [item for item in required if not (plugin_dir / item).exists()]
    if missing:
        print("Export is missing required files or directories:")
        for item in missing:
            print(f"- {item}")
        return 1

    mcp_config = json.loads((plugin_dir / ".mcp.json").read_text(encoding="utf-8"))
    server = mcp_config.get("mcpServers", {}).get("openstudio_ai")
    if not isinstance(server, dict):
        print("Export .mcp.json does not define mcpServers.openstudio_ai", file=sys.stderr)
        return 1

    print(f"Export looks valid: {plugin_dir}")
    print(f"MCP command: {server.get('command')}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Create the OpenStudio AI CLI parser."""
    parser = argparse.ArgumentParser(prog="openstudio-ai", description="OpenStudio AI runtime CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Check runtime readiness.")
    doctor.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    doctor.set_defaults(func=_cmd_doctor)

    paths = subparsers.add_parser("paths", help="Print runtime paths.")
    paths.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    paths.set_defaults(func=_cmd_paths)

    version = subparsers.add_parser("version", help="Print installed OpenStudio AI version.")
    version.set_defaults(func=_cmd_version)

    install_runtime = subparsers.add_parser("install-runtime", help="Validate or complete runtime installation.")
    install_runtime.set_defaults(func=_cmd_install_runtime)

    repair = subparsers.add_parser("repair", help="Run non-destructive runtime repair checks.")
    repair.set_defaults(func=_cmd_repair)

    export = subparsers.add_parser("export", help="Export host plugin packages.")
    export.add_argument("host", choices=["claude", "codex"], help="Host plugin format to export.")
    export.add_argument("--output-dir", type=Path, required=True, help="Directory to write the export into.")
    export.add_argument("--plugin-name", default="openstudio-ai", help="Plugin folder/name.")
    export.add_argument(
        "--workspace-root",
        type=Path,
        default=_default_root(),
        help="Harness root containing skills, knowledge, prompts, and MCP files.",
    )
    export.add_argument("--runtime-mode", choices=sorted(RUNTIME_MODES), default="installed")
    export.add_argument("--dry-run", action="store_true", help="Preview files without writing.")
    export.add_argument("--force", action="store_true", help="Replace an existing plugin folder.")
    export.set_defaults(func=_cmd_export)

    validate = subparsers.add_parser("validate-export", help="Validate an exported plugin directory.")
    validate.add_argument("path", type=Path, help="Plugin directory containing .mcp.json.")
    validate.set_defaults(func=_cmd_validate_export)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the `openstudio-ai` console script."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
