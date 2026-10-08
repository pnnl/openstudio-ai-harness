from __future__ import annotations

import json
from pathlib import Path

import pytest

import cli
from adapters.runtime_helpers import (
    OPENSTUDIO_PYTHON_SDK_VERSION,
    doctor_triage_guidance,
    marketplace_mcp_args,
    offline_guidance,
    prepare_runtime_guidance,
    runtime_doctor_command,
    runtime_uvx_args,
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


def test_marketplace_mcp_args_pin_an_explicit_release() -> None:
    assert marketplace_mcp_args() == [
        *runtime_uvx_args("openstudio-ai-mcp"),
        "--transport",
        "stdio",
    ]
    historical = marketplace_mcp_args(version="0.0.1")
    assert historical[historical.index("--from") + 1] == "openstudio-ai==0.0.1"


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


def test_offline_guidance_names_working_uv_settings() -> None:
    text = offline_guidance("Claude Code")
    assert "UV_OFFLINE=1" in text
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
