"""Tests for OpenStudio executable resolution used by the MCP service."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import openstudio_mcp.server as mcp_server
import openstudio_mcp.runtime_config as runtime_config
from openstudio_mcp.runtime_config import (
    configured_openstudio_path,
    openstudio_version_from_output,
)
from openstudio_mcp.server import OpenStudioService


def _executable(path: Path) -> Path:
    path.write_text("#!/bin/sh\necho 3.10.0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_openstudio_path_override_has_priority(monkeypatch, tmp_path: Path) -> None:
    configured = _executable(tmp_path / "configured-openstudio")
    discovered = _executable(tmp_path / "path-openstudio")
    monkeypatch.setenv("OPENSTUDIO_PATH", str(configured))
    monkeypatch.setattr(runtime_config.shutil, "which", lambda _: str(discovered))

    assert OpenStudioService._resolve_openstudio_executable() == str(
        configured.resolve()
    )


def test_openstudio_path_falls_back_to_path_discovery(
    monkeypatch, tmp_path: Path
) -> None:
    discovered = _executable(tmp_path / "openstudio")
    monkeypatch.delenv("OPENSTUDIO_PATH", raising=False)
    monkeypatch.setenv("OPENSTUDIO_AI_DATA_DIR", str(tmp_path / "runtime-data"))
    monkeypatch.setattr(runtime_config.shutil, "which", lambda _: str(discovered))

    service = OpenStudioService(workspace_root=tmp_path / "workspace")

    assert service.openstudio_path == str(discovered.resolve())
    assert service._openstudio_executable_or_none() == str(discovered.resolve())
    status = service.runtime_openstudio_status()
    assert status["available"] is True
    assert status["path"] == str(discovered.resolve())
    assert status["source"] == "PATH"


def test_openstudio_status_explains_missing_cli(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENSTUDIO_PATH", raising=False)
    monkeypatch.setenv("OPENSTUDIO_AI_DATA_DIR", str(tmp_path / "runtime-data"))
    monkeypatch.setattr(runtime_config.shutil, "which", lambda _: None)

    status = OpenStudioService(
        workspace_root=tmp_path / "workspace"
    ).runtime_openstudio_status()

    assert status["available"] is False
    assert status["checks"] == [
        "OPENSTUDIO_PATH",
        "runtime configuration",
        "shutil.which('openstudio')",
    ]
    assert "read-only platform-specific discovery" in status["recommendation"]
    assert "--path <confirmed-executable>" in status["recommendation"]


def test_invalid_openstudio_path_does_not_select_a_different_installation(
    monkeypatch, tmp_path: Path
) -> None:
    discovered = _executable(tmp_path / "path-openstudio")
    monkeypatch.setenv("OPENSTUDIO_PATH", str(tmp_path / "missing-openstudio"))
    monkeypatch.setattr(runtime_config.shutil, "which", lambda _: str(discovered))

    assert OpenStudioService._resolve_openstudio_executable() is None


def test_saved_openstudio_path_is_used_when_environment_is_unset(
    monkeypatch, tmp_path: Path
) -> None:
    configured = _executable(tmp_path / "configured-openstudio")
    monkeypatch.delenv("OPENSTUDIO_PATH", raising=False)
    monkeypatch.setenv("OPENSTUDIO_AI_DATA_DIR", str(tmp_path / "runtime-data"))
    from openstudio_mcp.runtime_config import set_openstudio_path

    set_openstudio_path(configured)
    monkeypatch.setattr(runtime_config.shutil, "which", lambda _: None)

    service = OpenStudioService(workspace_root=tmp_path / "workspace")

    assert service.openstudio_path == str(configured.resolve())
    assert service.openstudio_path_source == "runtime configuration"


def test_non_object_runtime_configuration_is_ignored(
    monkeypatch, tmp_path: Path
) -> None:
    data_dir = tmp_path / "runtime-data"
    data_dir.mkdir()
    (data_dir / "runtime.json").write_text("null\n", encoding="utf-8")
    monkeypatch.setenv("OPENSTUDIO_AI_DATA_DIR", str(data_dir))

    assert configured_openstudio_path() is None


def test_openstudio_version_parser_accepts_prerelease_build_metadata() -> None:
    assert openstudio_version_from_output("3.0.0-rc1+baflkdhsia") == (
        "3.0.0-rc1+baflkdhsia"
    )


def test_invalid_saved_path_falls_back_to_path_discovery(
    monkeypatch, tmp_path: Path
) -> None:
    discovered = _executable(tmp_path / "openstudio")
    data_dir = tmp_path / "runtime-data"
    data_dir.mkdir()
    (data_dir / "runtime.json").write_text(
        '{"openstudio_path": "/missing/openstudio"}\n', encoding="utf-8"
    )
    monkeypatch.delenv("OPENSTUDIO_PATH", raising=False)
    monkeypatch.setenv("OPENSTUDIO_AI_DATA_DIR", str(data_dir))
    monkeypatch.setattr(runtime_config.shutil, "which", lambda _: str(discovered))

    assert runtime_config.resolve_openstudio_executable_with_source() == (
        str(discovered.resolve()),
        "PATH",
    )
