from __future__ import annotations

import json
import py_compile
from pathlib import Path

import pytest

import cli

from adapters.runtime_helpers import (
    render_doctor_runtime_script,
    render_install_runtime_script,
)
from openstudio_mcp.compatibility import PLUGIN_CONTRACT_VERSION, package_version


def _compile_script(tmp_path: Path, filename: str, content: str) -> None:
    script_path = tmp_path / filename
    script_path.write_text(content, encoding="utf-8")
    py_compile.compile(str(script_path), doraise=True)


def test_rendered_runtime_helpers_are_executable_python(tmp_path: Path) -> None:
    doctor = render_doctor_runtime_script()
    installer = render_install_runtime_script()

    _compile_script(tmp_path, "doctor_runtime.py", doctor)
    _compile_script(tmp_path, "install_runtime.py", installer)

    assert PLUGIN_CONTRACT_VERSION in doctor
    assert "def nlr_mcp_status" in doctor
    assert '"nlr_openstudio": nlr_mcp_status()' in doctor
    assert "optional_capabilities" in doctor
    assert '"--plugin-contract-version"' in doctor
    assert "return doctor.returncode or 1" in doctor
    assert "return 2" in doctor
    assert "core_ready" in doctor
    assert "plugin_ready" in doctor
    assert "newer OpenStudio AI MCP interface" in doctor
    assert "ready for energy modeling" in doctor
    assert 'runtime_cli, "install-runtime"' in installer
    assert "def runtime_command_path(command: str)" in installer
    assert "def runtime_cli_path" in installer
    assert 'scripts_dir / "Scripts" / f"{command}.exe"' in installer
    assert 'runtime_mcp = runtime_command_path("openstudio-ai-mcp")' in installer
    assert "requires Python 3.10 or newer" in installer
    assert f"openstudio-ai=={package_version()}" in installer
    assert "def is_pipx_managed_runtime" in installer
    assert '["pipx", "upgrade", "--install", "openstudio-ai"]' in installer
    assert "do not replace it with this absolute path" in installer
    assert '"-m", "cli"' not in installer
    assert (
        'print("\\nOpenStudio AI runtime installation completed.")\n    return 0'
        in installer
    )


def test_rendered_installer_includes_only_requested_host_guidance() -> None:
    without_guidance = render_install_runtime_script()
    with_guidance = render_install_runtime_script(
        post_install_guidance="Reload the host plugin."
    )

    assert "Reload the host plugin." not in without_guidance
    assert 'print("\\nReload the host plugin.")\n    return 0' in with_guidance


@pytest.mark.parametrize("implementation", ["cli", "exported"])
@pytest.mark.parametrize("host", ["codex", "claude", "claude_parent"])
@pytest.mark.parametrize(
    "names, expected",
    [
        (["openstudio-mcp"], "openstudio-mcp"),
        (["nlr_openstudio"], "nlr_openstudio"),
        (["nlr_openstudio", "openstudio-mcp"], "openstudio-mcp"),
        (["other"], None),
        ([], None),
    ],
)
def test_nlr_discovery_names(
    monkeypatch, tmp_path: Path, implementation, host, names, expected
) -> None:
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    if host == "codex":
        config_path = tmp_path / ".codex" / "config.toml"
        config_path.parent.mkdir()
        config_path.write_text(
            '# openstudio-mcp and nlr_openstudio are optional\n'
            + "\n".join(
                f'[mcp_servers."{name}"]\ncommand = "docker"'
                for name in names
            ),
            encoding="utf-8",
        )
    else:
        config_path = (tmp_path if host == "claude_parent" else project) / ".mcp.json"
        config_path.write_text(
            json.dumps({"mcpServers": {
                name: {"description": "openstudio-mcp nlr_openstudio"}
                for name in names
            }}),
            encoding="utf-8",
        )
    if implementation == "cli":
        status = cli._nlr_mcp_status()
    else:
        namespace = {"__name__": "test_doctor"}
        exec(compile(render_doctor_runtime_script(), "doctor_runtime.py", "exec"), namespace)
        # Exercise discovery with a TOML parser even on Python 3.10.
        monkeypatch.setitem(namespace, "tomllib", cli.tomllib)
        status = namespace["nlr_mcp_status"]()

    assert status["configured"] is (expected is not None)
    if expected is not None:
        assert status["name"] == expected
        assert status["source"] == str(config_path)
    assert "ready" not in status
