from __future__ import annotations

import json
from pathlib import Path

import cli
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


def test_cli_doctor_json_reports_mcp_readiness(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    data_dir = tmp_path / "runtime-data"
    (data_dir / "workspace").mkdir(parents=True)
    monkeypatch.setenv("OPENSTUDIO_AI_DATA_DIR", str(data_dir))
    monkeypatch.setenv("OPENSTUDIO_PATH", "/fake/openstudio")

    def fake_command_available(command: str) -> dict:
        return {"command": command, "available": True, "path": command}

    def fake_run_probe(command: list[str], *, timeout_seconds: int = 10) -> dict:
        stdout = "3.10.0+test" if command[0] == "/fake/openstudio" else "help"
        return {"ok": True, "returncode": 0, "stdout": stdout, "stderr": ""}

    monkeypatch.setattr(cli, "_command_available", fake_command_available)
    monkeypatch.setattr(cli, "_run_probe", fake_run_probe)

    exit_code = main(["doctor", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ready"] is True
    assert payload["mcp_ready"] is True
    assert payload["simulation_ready"] is True
    assert payload["assets"]["ok"] is True
    assert payload["runtime_storage"]["ok"] is True
    assert payload["runtime_storage"]["writable"] is True
    assert payload["sqlite_registry"]["ok"] is True
    assert payload["mcp_startup"]["ok"] is True
    assert payload["python_openstudio"]["ok"] is True
    assert payload["measures"]["ok"] is True
    assert payload["measures"]["count"] >= 1
    assert "route_probe" in payload["sdk_docs"]
    assert "openstudio" in payload


def test_cli_doctor_reports_uninitialized_storage_without_creating_it(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    data_dir = tmp_path / "runtime-data"
    monkeypatch.setenv("OPENSTUDIO_AI_DATA_DIR", str(data_dir))

    assert main(["doctor", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ready"] is False
    assert payload["runtime_storage"]["initialized"] is False
    assert payload["runtime_storage"]["ok"] is False
    assert not data_dir.exists()


def test_cli_install_runtime_initializes_storage(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    data_dir = tmp_path / "runtime-data"
    monkeypatch.setenv("OPENSTUDIO_AI_DATA_DIR", str(data_dir))

    assert main(["install-runtime"]) == 0
    captured = capsys.readouterr()
    assert "Initialized runtime workspace" in captured.out
    assert (data_dir / "workspace").is_dir()


def test_cli_doctor_text_output_reports_checks(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    data_dir = tmp_path / "runtime-data"
    (data_dir / "workspace").mkdir(parents=True)
    monkeypatch.setenv("OPENSTUDIO_AI_DATA_DIR", str(data_dir))
    monkeypatch.setenv("OPENSTUDIO_PATH", "/fake/openstudio")

    def fake_command_available(command: str) -> dict:
        return {"command": command, "available": True, "path": command}

    def fake_run_probe(command: list[str], *, timeout_seconds: int = 10) -> dict:
        stdout = "3.10.0+test" if command[0] == "/fake/openstudio" else "help"
        return {"ok": True, "returncode": 0, "stdout": stdout, "stderr": ""}

    monkeypatch.setattr(cli, "_command_available", fake_command_available)
    monkeypatch.setattr(cli, "_run_probe", fake_run_probe)

    assert main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert "MCP runtime status: ready" in output
    assert "OpenStudio execution status: ready" in output
    assert "Checks:" in output
    assert "- runtime assets: ok" in output
    assert "- runtime storage: ok" in output
    assert "- python openstudio sdk: ok" in output


def test_cli_doctor_text_reports_missing_openstudio_sdk(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    data_dir = tmp_path / "runtime-data"
    (data_dir / "workspace").mkdir(parents=True)
    monkeypatch.setenv("OPENSTUDIO_AI_DATA_DIR", str(data_dir))
    monkeypatch.setenv("OPENSTUDIO_PATH", "/fake/openstudio")

    def fake_command_available(command: str) -> dict:
        return {"command": command, "available": True, "path": command}

    def fake_run_probe(command: list[str], *, timeout_seconds: int = 10) -> dict:
        return {"ok": True, "returncode": 0, "stdout": "help", "stderr": ""}

    monkeypatch.setattr(cli, "_command_available", fake_command_available)
    monkeypatch.setattr(cli, "_run_probe", fake_run_probe)
    monkeypatch.setattr(
        cli,
        "_python_openstudio_probe",
        lambda: {"ok": False, "error": "No module named openstudio"},
    )

    assert main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert "MCP runtime status: ready" in output
    assert "OpenStudio execution status: not ready" in output
    assert "- python openstudio sdk: failed" in output
    assert "native OpenStudio application" in output


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
    assert (plugin_dir / "skills" / "setup-openstudio-ai" / "SKILL.md").exists()
    assert (
        plugin_dir / "skills" / "setup-openstudio-ai" / "scripts" / "doctor_runtime.py"
    ).exists()
    assert (
        main(["validate-export", str(plugin_dir), "--runtime-mode", "marketplace"]) == 0
    )


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


def test_cli_validate_export_rejects_missing_marketplace_setup(tmp_path: Path) -> None:
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
    (plugin_dir / "installers" / "doctor_runtime.py").unlink()
    assert (
        main(["validate-export", str(plugin_dir), "--runtime-mode", "marketplace"]) == 1
    )
