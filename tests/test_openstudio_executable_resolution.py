"""Tests for OpenStudio executable resolution used by the MCP service."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import openstudio_mcp.server as mcp_server
from openstudio_mcp.server import OpenStudioService


def _executable(path: Path) -> Path:
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_openstudio_path_override_has_priority(monkeypatch, tmp_path: Path) -> None:
    configured = _executable(tmp_path / "configured-openstudio")
    discovered = _executable(tmp_path / "path-openstudio")
    monkeypatch.setenv("OPENSTUDIO_PATH", str(configured))
    monkeypatch.setattr(mcp_server.shutil, "which", lambda _: str(discovered))

    assert OpenStudioService._resolve_openstudio_executable() == str(
        configured.resolve()
    )


def test_openstudio_path_falls_back_to_path_discovery(
    monkeypatch, tmp_path: Path
) -> None:
    discovered = _executable(tmp_path / "openstudio")
    monkeypatch.delenv("OPENSTUDIO_PATH", raising=False)
    monkeypatch.setattr(mcp_server.shutil, "which", lambda _: str(discovered))

    service = OpenStudioService(workspace_root=tmp_path / "workspace")

    assert service.openstudio_path == str(discovered.resolve())
    assert service._openstudio_executable_or_none() == str(discovered.resolve())


def test_invalid_openstudio_path_does_not_select_a_different_installation(
    monkeypatch, tmp_path: Path
) -> None:
    discovered = _executable(tmp_path / "path-openstudio")
    monkeypatch.setenv("OPENSTUDIO_PATH", str(tmp_path / "missing-openstudio"))
    monkeypatch.setattr(mcp_server.shutil, "which", lambda _: str(discovered))

    assert OpenStudioService._resolve_openstudio_executable() is None
