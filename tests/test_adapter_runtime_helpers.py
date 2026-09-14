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
from openstudio_ai_mcp.compatibility import PLUGIN_CONTRACT_VERSION, package_version


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
    assert "def bem_calibration_mcp_status" in doctor
    assert '"bem_calibration": bem_calibration_status()' in doctor
    assert "lbnl_bem_calibration" in doctor
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
        (["nlr_openstudio"], None),
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
            '# openstudio-mcp is optional\n'
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
                name: {"description": "NLR OpenStudio-MCP"}
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


@pytest.mark.parametrize("implementation", ["cli", "exported"])
@pytest.mark.parametrize("host", ["codex", "claude", "claude_parent"])
@pytest.mark.parametrize(
    "names, expected",
    [
        (["bem-calibration"], "bem-calibration"),
        (["lbnl_bem_calibration"], None),
        (["lbnl_bem_calibration", "bem-calibration"], "bem-calibration"),
        (["other"], None),
        ([], None),
    ],
)
def test_bem_calibration_discovery_names(
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
            "\n".join(
                f'[mcp_servers."{name}"]\ncommand = "bem-calibration-mcp"'
                for name in names
            ),
            encoding="utf-8",
        )
    else:
        config_path = (tmp_path if host == "claude_parent" else project) / ".mcp.json"
        config_path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        name: {"command": "bem-calibration-mcp"} for name in names
                    }
                }
            ),
            encoding="utf-8",
        )
    if implementation == "cli":
        status = cli._bem_calibration_mcp_status()
    else:
        namespace = {"__name__": "test_doctor"}
        exec(
            compile(render_doctor_runtime_script(), "doctor_runtime.py", "exec"),
            namespace,
        )
        monkeypatch.setitem(namespace, "tomllib", cli.tomllib)
        status = namespace["bem_calibration_mcp_status"]()

    assert status["configured"] is (expected is not None)
    assert status["name"] == "bem-calibration"
    assert status["domain_service"] == "lbnl_bem_calibration"
    if expected is not None:
        assert status["source"] == str(config_path)
    assert "ready" not in status


def _exported_doctor_namespace(monkeypatch) -> dict:
    namespace = {"__name__": "test_doctor"}
    exec(compile(render_doctor_runtime_script(), "doctor_runtime.py", "exec"), namespace)
    monkeypatch.setitem(namespace, "tomllib", cli.tomllib)
    return namespace


def _discover(implementation: str, monkeypatch, name: str) -> dict:
    if implementation == "cli":
        return cli._find_host_mcp_declaration(name)
    return _exported_doctor_namespace(monkeypatch)["find_host_mcp_declaration"](name)


@pytest.mark.parametrize("implementation", ["cli", "exported"])
@pytest.mark.parametrize("name", ["openstudio-mcp", "bem-calibration"])
def test_codex_disabled_declaration_is_configured_but_not_enabled(
    monkeypatch, tmp_path: Path, implementation, name
) -> None:
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / ".codex" / "config.toml"
    config_path.parent.mkdir()
    config_path.write_text(
        f'[mcp_servers."{name}"]\ncommand = "docker"\nenabled = false\n',
        encoding="utf-8",
    )

    status = _discover(implementation, monkeypatch, name)

    assert status["configured"] is True
    assert status["enabled"] is False
    assert status["host"] == "codex"
    assert status["source"] == str(config_path)


@pytest.mark.parametrize("implementation", ["cli", "exported"])
@pytest.mark.parametrize("scope", ["user", "local"])
def test_claude_code_user_config_declarations_are_discovered(
    monkeypatch, tmp_path: Path, implementation, scope
) -> None:
    """``claude mcp add`` writes ~/.claude.json, not a project .mcp.json."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    declaration = {"bem-calibration": {"command": "bem-calibration-mcp"}}
    if scope == "user":
        config = {"mcpServers": declaration, "projects": {}}
    else:
        config = {"mcpServers": {}, "projects": {str(project): {"mcpServers": declaration}}}
    (tmp_path / ".claude.json").write_text(json.dumps(config), encoding="utf-8")

    status = _discover(implementation, monkeypatch, "bem-calibration")

    assert status["configured"] is True
    assert status["enabled"] is True
    assert status["host"] == f"claude_{scope}"
    assert status["source"].startswith(str(tmp_path / ".claude.json"))
    assert _discover(implementation, monkeypatch, "openstudio-mcp")["configured"] is False


@pytest.mark.parametrize("implementation", ["cli", "exported"])
def test_claude_code_local_scope_ignores_other_projects(
    monkeypatch, tmp_path: Path, implementation
) -> None:
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    config = {"projects": {str(tmp_path / "elsewhere"): {"mcpServers": {"bem-calibration": {}}}}}
    (tmp_path / ".claude.json").write_text(json.dumps(config), encoding="utf-8")

    assert _discover(implementation, monkeypatch, "bem-calibration")["configured"] is False


def test_exported_doctor_reports_disabled_calibration_declaration(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / ".codex" / "config.toml"
    config_path.parent.mkdir()
    config_path.write_text(
        '[mcp_servers."bem-calibration"]\ncommand = "bem-calibration-mcp"\nenabled = false\n',
        encoding="utf-8",
    )

    status = _exported_doctor_namespace(monkeypatch)["bem_calibration_status"]()

    assert status["blocking"] is False
    assert status["status"] == "configured_disabled"
    assert "disabled" in status["message"]


@pytest.mark.parametrize("implementation", ["cli", "exported"])
@pytest.mark.parametrize(
    "location",
    [
        Path("Library") / "Application Support" / "Claude",  # macOS
        Path("AppData") / "Roaming" / "Claude",  # Windows, via APPDATA
        Path(".config") / "Claude",  # Linux
    ],
)
def test_claude_desktop_config_declarations_are_discovered(
    monkeypatch, tmp_path: Path, implementation, location
) -> None:
    """The desktop app launches its Local MCP servers and injects them into hosted sessions."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    config_path = tmp_path / location / "claude_desktop_config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps({"mcpServers": {"bem-calibration": {"command": "uv", "args": ["run", "bem-calibration-mcp"]}}}),
        encoding="utf-8",
    )

    status = _discover(implementation, monkeypatch, "bem-calibration")

    assert status["configured"] is True
    assert status["enabled"] is True
    assert status["host"] == "claude_desktop"
    assert status["source"] == str(config_path)
    assert _discover(implementation, monkeypatch, "openstudio-mcp")["configured"] is False


@pytest.mark.parametrize("implementation", ["cli", "exported"])
def test_unreadable_claude_desktop_config_is_skipped(
    monkeypatch, tmp_path: Path, implementation
) -> None:
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("{not json", encoding="utf-8")

    status = _discover(implementation, monkeypatch, "bem-calibration")

    assert status["configured"] is False
    assert str(config_path) in status["checked_paths"]
