from __future__ import annotations

import py_compile
from pathlib import Path

from adapters.runtime_helpers import (
    render_doctor_runtime_script,
    render_install_runtime_script,
)
from openstudio_mcp.compatibility import PLUGIN_CONTRACT_VERSION


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
    assert '"--plugin-contract-version"' in doctor
    assert "return 1" in doctor
    assert 'runtime_cli, "install-runtime"' in installer
    assert "def runtime_command_path(command: str)" in installer
    assert "def runtime_cli_path" in installer
    assert 'scripts_dir / "Scripts" / f"{command}.exe"' in installer
    assert 'runtime_mcp = runtime_command_path("openstudio-ai-mcp")' in installer
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
