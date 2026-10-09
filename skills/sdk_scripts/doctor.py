"""Find only the pinned OpenStudio CLI and verify its embedded Python SDK."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from common.version_guard import CompatibilityError, load_contract, release_version

PROBE_PREFIX = "OPENSTUDIO_SKILL_SDK_PROBE="
PROBE_TIMEOUT_SECONDS = 30


def discover_candidates(required: str) -> list[Path]:
    """Check version-specific locations and PATH, without selecting other releases."""
    if sys.platform == "darwin":
        candidates = [Path(f"/Applications/OpenStudio-{required}/bin/openstudio")]
    elif sys.platform == "win32":
        candidates = [Path(f"C:/openstudio-{required}/bin/openstudio.exe")]
        program_files = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        candidates.append(
            program_files / f"OpenStudio-{required}" / "bin/openstudio.exe"
        )
    else:
        candidates = [
            Path(f"/usr/local/openstudio-{required}/bin/openstudio"),
            Path(f"/opt/OpenStudio-{required}/bin/openstudio"),
            Path(f"/opt/openstudio-{required}/bin/openstudio"),
        ]
    on_path = shutil.which("openstudio")
    if on_path:
        candidates.append(Path(on_path))
    return list(dict.fromkeys(path.expanduser().resolve() for path in candidates))


def run_probe(command: list[str]) -> subprocess.CompletedProcess:
    # Avoid inheriting a host virtualenv's binding search paths in embedded Python.
    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=PROBE_TIMEOUT_SECONDS,
        env=env,
    )


def probe_candidate(path: Path, required: str) -> dict:
    report = {"path": str(path), "ok": False}
    if not path.is_file():
        return {**report, "status": "missing", "error": "Executable file not found"}
    try:
        cli = run_probe([str(path), "--version"])
        output = (cli.stdout or cli.stderr).strip()
        actual = release_version(output)
        report["cli_version"] = output
        if cli.returncode != 0 or actual != required:
            return {
                **report,
                "status": "cli_incompatible",
                "error": f"Required CLI {required}; reported {output!r} (exit {cli.returncode})",
            }
        probe_path = Path(__file__).resolve().with_name("sdk_probe.py")
        result = run_probe([str(path), "execute_python_script", str(probe_path)])
        records = [
            line.removeprefix(PROBE_PREFIX)
            for line in result.stdout.splitlines()
            if line.startswith(PROBE_PREFIX)
        ]
        payload = json.loads(records[-1]) if records else {}
        if not isinstance(payload, dict):
            payload = {}
        report["sdk_probe"] = payload
        if (
            result.returncode != 0
            or payload.get("ok") is not True
            or release_version(str(payload.get("sdk_version", ""))) != required
        ):
            return {
                **report,
                "status": "sdk_incompatible",
                "error": payload.get("error")
                or "Embedded SDK probe failed or reported a different version",
                "stderr": result.stderr[-2000:],
            }
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return {**report, "status": "probe_failed", "error": str(exc)}
    return {**report, "ok": True, "status": "ready"}


def diagnose(explicit_path: str | None = None) -> dict:
    contract = load_contract()
    required = contract["required_openstudio_version"]
    report = {
        "ok": False,
        "required_openstudio_version": required,
        "platform": sys.platform,
        "candidates": [],
        "installation_url": f"https://github.com/NatLabRockies/OpenStudio/releases/tag/v{required}",
    }
    if sys.platform not in contract["platforms"]:
        return {
            **report,
            "status": "unsupported_platform",
            "error": "Platform not supported by this bundle",
        }
    # An explicit user path is authoritative, including a stale OPENSTUDIO_PATH.
    selected = (
        explicit_path
        if explicit_path is not None
        else os.environ.get("OPENSTUDIO_PATH")
    )
    candidates = (
        [Path(selected).expanduser().resolve()]
        if selected is not None
        else discover_candidates(required)
    )
    for candidate in candidates:
        checked = probe_candidate(candidate, required)
        report["candidates"].append(checked)
        if checked["ok"]:
            return {
                **report,
                "ok": True,
                "status": "ready",
                "openstudio_executable": checked["path"],
                "sdk_version": checked["sdk_probe"]["sdk_version"],
            }
    return {
        **report,
        "status": "required_openstudio_unavailable",
        "error": f"Install OpenStudio {required}, or provide the path to that exact release. "
        "No compatible CLI and embedded SDK were verified; model edits are blocked.",
    }


def main() -> int:
    global PROBE_TIMEOUT_SECONDS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--openstudio", help="Explicit executable path; no fallback if incompatible"
    )
    parser.add_argument(
        "--probe-timeout",
        type=int,
        default=PROBE_TIMEOUT_SECONDS,
        help="Positive timeout in seconds per native CLI/SDK probe (default: 30)",
    )
    args = parser.parse_args()
    if args.probe_timeout < 1:
        parser.error("--probe-timeout must be positive")
    PROBE_TIMEOUT_SECONDS = args.probe_timeout
    try:
        report = diagnose(args.openstudio)
    except CompatibilityError as exc:
        report = {"ok": False, "status": "invalid_contract", "error": str(exc)}
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
