from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest

import cli
from adapters.runtime_helpers import (
    OPENSTUDIO_PYTHON_SDK_VERSION,
    RUNTIME_PYTHON_VERSION,
    doctor_triage_guidance,
    marketplace_mcp_args,
    marketplace_runtime_spec,
    mcp_launcher_source,
    offline_guidance,
    prepare_runtime_guidance,
    runtime_doctor_command,
    runtime_uvx_args,
    runtime_uvx_command,
    runtime_uvx_options,
)
from openstudio_ai_mcp.compatibility import PLUGIN_CONTRACT_VERSION, package_version


@pytest.mark.parametrize("host", ["codex", "claude", "claude_parent"])
@pytest.mark.parametrize(
    "names, expected",
    [
        (["openstudio-mcp"], "openstudio-mcp"),
        (["nlr_openstudio"], None),
        (["nlr_openstudio", "openstudio-mcp"], "openstudio-mcp"),
        (["other"], None),
        ([], None),
    ],
)
def test_nlr_discovery_names(
    monkeypatch, tmp_path: Path, host, names, expected
) -> None:
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    if host == "codex":
        config_path = tmp_path / ".codex" / "config.toml"
        config_path.parent.mkdir()
        config_path.write_text(
            "# openstudio-mcp is optional\n"
            + "\n".join(
                f'[mcp_servers."{name}"]\ncommand = "docker"' for name in names
            ),
            encoding="utf-8",
        )
    else:
        config_path = (tmp_path if host == "claude_parent" else project) / ".mcp.json"
        config_path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        name: {"description": "NLR OpenStudio-MCP"} for name in names
                    }
                }
            ),
            encoding="utf-8",
        )

    status = cli._nlr_mcp_status()

    assert status["configured"] is (expected is not None)
    if expected is not None:
        assert status["name"] == expected
        assert status["source"] == str(config_path)
    assert "ready" not in status


def test_marketplace_uvx_pin_matches_lockfile() -> None:
    lock = (Path(__file__).resolve().parents[1] / "uv.lock").read_text(encoding="utf-8")
    assert f'name = "openstudio"\nversion = "{OPENSTUDIO_PYTHON_SDK_VERSION}"' in lock
    assert runtime_uvx_args("openstudio-ai-mcp")[-3:] == [
        "--with",
        f"openstudio=={OPENSTUDIO_PYTHON_SDK_VERSION}",
        "openstudio-ai-mcp",
    ]
    assert f"openstudio-ai=={package_version()}" in runtime_uvx_args("openstudio-ai")


def test_runtime_python_range_matches_requires_python() -> None:
    """uv may reuse any in-range interpreter, so the range must start at the
    package's `requires-python` floor and stop before Pythons without wheels."""
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert 'requires-python = ">=3.10"' in pyproject
    assert RUNTIME_PYTHON_VERSION == ">=3.10,<3.14"
    args = runtime_uvx_args("openstudio-ai")
    assert args[args.index("--python") + 1] == RUNTIME_PYTHON_VERSION
    # The copyable shell command must quote the range so `<` is not a redirect.
    assert "--python '>=3.10,<3.14'" in runtime_uvx_command("openstudio-ai", "doctor")


def test_marketplace_mcp_args_run_the_launcher_with_the_pinned_spec() -> None:
    args = marketplace_mcp_args()
    options = [
        "--python",
        RUNTIME_PYTHON_VERSION,
        "--from",
        f"openstudio-ai=={package_version()}",
        "--with",
        f"openstudio=={OPENSTUDIO_PYTHON_SDK_VERSION}",
    ]
    assert runtime_uvx_options() == options
    assert runtime_uvx_args("openstudio-ai-mcp") == [*options, "openstudio-ai-mcp"]
    assert args == [
        "run",
        "--no-project",
        "--python",
        RUNTIME_PYTHON_VERSION,
        "python",
        "-I",
        "-c",
        mcp_launcher_source(),
        *options,
        "--",
        "openstudio-ai-mcp",
        "--transport",
        "stdio",
    ]
    assert marketplace_runtime_spec(args) == options
    historical = marketplace_mcp_args(version="0.0.1")
    assert "openstudio-ai==0.0.1" in marketplace_runtime_spec(historical)


def test_marketplace_mcp_command_line_fits_windows_limits() -> None:
    """The launcher source is one argv entry. Stay under cmd.exe's 8191-character
    limit (stricter than CreateProcess's 32767) in case a host launches via a shell."""
    import subprocess

    command_line = subprocess.list2cmdline(["uv", *marketplace_mcp_args()])
    assert len(command_line) < 8191, len(command_line)


def test_inlined_launcher_is_standard_library_only() -> None:
    import ast
    import sys

    tree = ast.parse(mcp_launcher_source())
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert imported <= set(sys.stdlib_module_names), imported


def test_doctor_command_requests_json_with_plugin_contract() -> None:
    command = runtime_doctor_command()
    assert " doctor --json " in command
    assert f"--plugin-version {package_version()}" in command
    assert f"--plugin-contract-version {PLUGIN_CONTRACT_VERSION}" in command


def test_prepare_guidance_discloses_persistent_writes_and_requires_approval() -> None:
    text = prepare_runtime_guidance("Codex")
    assert "install-runtime" in text
    assert "ask for approval" in text
    assert "user-local data folder" in text
    assert "uv's cache" in text
    assert "No approval is needed" not in text
    assert "Codex's startup timeout" in text


def test_triage_does_not_treat_fresh_storage_as_a_stale_runtime() -> None:
    text = doctor_triage_guidance()
    storage, rest = text.split("`runtime_storage_not_ready`", 1)[1].split(
        "`plugin_runtime_incompatible`", 1
    )
    assert "install-runtime" in storage and "--reinstall" not in storage
    assert "--reinstall" in rest


def test_offline_flag_precedes_the_console_script() -> None:
    argv = shlex.split(runtime_uvx_command("openstudio-ai", "doctor", offline=True))
    assert argv[:2] == ["uvx", "--offline"]
    assert argv.index("--offline") < argv.index("openstudio-ai")
    assert argv.count("--offline") == 1
    both = shlex.split(
        runtime_uvx_command("openstudio-ai", "install-runtime", offline=True, reinstall=True)
    )
    assert both[:3] == ["uvx", "--offline", "--reinstall"]
    assert "--offline" not in shlex.split(runtime_uvx_command("openstudio-ai", "doctor"))


def test_triage_tells_agent_to_retry_offline_when_uvx_cannot_start() -> None:
    text = doctor_triage_guidance()
    # Offline failures happen before the doctor can print remediation, so the
    # hint must not be tied to a diagnostic code.
    assert "before printing a result" in text
    assert runtime_doctor_command(offline=True) in text
    assert runtime_uvx_command("openstudio-ai", "install-runtime", offline=True) in text
    # A shell-specific prefix would fail in Windows cmd and PowerShell.
    assert "UV_OFFLINE" not in text


def test_offline_guidance_names_working_uv_settings() -> None:
    text = offline_guidance("Claude Code")
    assert runtime_doctor_command(offline=True) in text
    assert "UV_OFFLINE" not in text
    assert "UV_DEFAULT_INDEX" in text
    assert "UV_NO_INDEX" not in text


@pytest.mark.parametrize("launched_by_uvx", [False, True])
def test_doctor_hints_match_the_installation_mode(monkeypatch, launched_by_uvx) -> None:
    monkeypatch.setattr(cli, "_launched_by_uvx", lambda: launched_by_uvx)
    command = cli._runtime_command("install-runtime")
    if launched_by_uvx:
        assert command.startswith("uvx --python ")
        assert command.endswith(" openstudio-ai install-runtime")
        assert "--reinstall" in cli._reinstall_hint()
    else:
        assert command == "openstudio-ai install-runtime"


@pytest.mark.parametrize(
    "prefix, uv_env, expected",
    [
        ("/home/u/.cache/uv/archive-v0/AbC123", "/usr/bin/uv", True),
        ("/home/u/.cache/uv/archive-v0/AbC123", None, False),
        ("/home/u/.local/pipx/venvs/openstudio-ai", "/usr/bin/uv", False),
    ],
)
def test_uvx_launch_detection(monkeypatch, prefix, uv_env, expected) -> None:
    monkeypatch.setattr(cli.sys, "prefix", prefix)
    if uv_env:
        monkeypatch.setenv("UV", uv_env)
    else:
        monkeypatch.delenv("UV", raising=False)
    assert cli._launched_by_uvx() is expected


def _checks(sdk_version: str, cli_version: str) -> dict:
    return {
        "python": {"supported": True},
        "plugin_compatibility": {"ok": True, "status": "compatible"},
        "commands": {
            "openstudio_ai_mcp": {"available": True, "help_probe": {"ok": True}}
        },
        "mcp_startup": {"ok": True},
        "runtime_storage": {"ok": True},
        "assets": {"ok": True},
        "python_openstudio": {"ok": True, "version": sdk_version},
        "sdk_docs": {"ok": True},
        "openstudio": {
            "ok": True,
            "version_probe": {"openstudio_version": cli_version},
        },
    }


@pytest.mark.parametrize(
    "sdk_version, cli_version, expect_warning",
    [
        ("3.11.0", "3.10.0", True),
        ("3.11.0", "3.11.0", False),
        ("3.11.0", "3.12.1", False),
    ],
)
def test_doctor_warns_when_sdk_is_newer_than_native_cli(
    sdk_version, cli_version, expect_warning
) -> None:
    diagnostics = cli._doctor_diagnostics(_checks(sdk_version, cli_version))
    mismatch = [
        d for d in diagnostics if d["code"] == "openstudio_sdk_cli_version_mismatch"
    ]
    assert bool(mismatch) is expect_warning
    if mismatch:
        assert mismatch[0]["severity"] == "warning"
        assert "3.11" in mismatch[0]["remediation"]
