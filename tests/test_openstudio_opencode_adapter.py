from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters.contracts import HostAdapterConfig
from adapters.opencode_adapter import OpenCodeAdapter


def _adapter() -> OpenCodeAdapter:
    return OpenCodeAdapter(
        HostAdapterConfig(host_name="opencode", workspace_root=Path(".").resolve())
    )


def test_opencode_adapter_dry_run_does_not_write(tmp_path: Path) -> None:
    result = _adapter().export_plugin(tmp_path, dry_run=True)

    assert result.dry_run is True
    assert result.plugin_dir == (tmp_path / "openstudio-ai").resolve()
    assert result.plugin_dir / "index.mjs" in result.files
    assert not result.plugin_dir.exists()


def test_opencode_adapter_exports_self_contained_module(tmp_path: Path) -> None:
    result = _adapter().export_plugin(
        tmp_path, plugin_name="openstudio-ai-lbnl-dev", dry_run=False
    )

    package = json.loads((result.plugin_dir / "package.json").read_text(encoding="utf-8"))
    module = (result.plugin_dir / "index.mjs").read_text(encoding="utf-8")
    readme = (result.plugin_dir / "README.md").read_text(encoding="utf-8")

    assert package["name"] == "openstudio-ai-lbnl-dev"
    assert package["type"] == "module"
    assert "experimental.chat.system.transform" in module
    assert "openstudio_ai" in module
    assert "bem-calibration" in module
    assert "lbnl_bem_calibration" in module
    assert "file:///absolute/path/to/openstudio-ai-lbnl-dev/index.mjs" in readme


def test_opencode_adapter_refuses_unsafe_plugin_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _adapter().export_plugin(tmp_path, plugin_name="../other", dry_run=True)
