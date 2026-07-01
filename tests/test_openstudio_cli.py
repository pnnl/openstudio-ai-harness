from __future__ import annotations

import json
from pathlib import Path

from cli import main


def test_cli_version_prints_version(capsys) -> None:
    assert main(["version"]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip()


def test_cli_paths_json_reports_runtime_paths(capsys) -> None:
    assert main(["paths", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "harness_root" in payload["paths"]
    assert "data_dir" in payload["paths"]
    assert "workspace_dir" in payload["paths"]


def test_cli_export_claude_marketplace(tmp_path: Path) -> None:
    assert (
        main(
            [
                "export",
                "claude",
                "--output-dir",
                str(tmp_path),
                "--workspace-root",
                str(Path(".").resolve()),
                "--runtime-mode",
                "marketplace",
            ]
        )
        == 0
    )

    plugin_dir = tmp_path / "openstudio-ai"
    mcp_json = json.loads((plugin_dir / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp_json["mcpServers"]["openstudio_ai"]["command"] == "openstudio-ai-mcp"
    assert (plugin_dir / "commands" / "setup-openstudio-ai.md").exists()
    assert (plugin_dir / "installers" / "doctor_runtime.py").exists()


def test_cli_validate_export(tmp_path: Path) -> None:
    assert (
        main(
            [
                "export",
                "codex",
                "--output-dir",
                str(tmp_path),
                "--workspace-root",
                str(Path(".").resolve()),
                "--runtime-mode",
                "marketplace",
            ]
        )
        == 0
    )

    plugin_dir = tmp_path / "plugins" / "openstudio-ai"
    assert main(["validate-export", str(plugin_dir)]) == 0
