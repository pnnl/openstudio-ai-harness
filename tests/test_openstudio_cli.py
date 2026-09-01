from __future__ import annotations

import json
import stat
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
    monkeypatch.setattr(
        cli,
        "resolve_openstudio_executable_with_source",
        lambda: ("/fake/openstudio", "OPENSTUDIO_PATH"),
    )

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
    assert payload["core_ready"] is True
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
    assert payload["sdk_docs"]["ok"] is True
    assert payload["sdk_docs"]["source"] == "bundled"
    assert payload["sdk_docs"]["selected_version"] == "3.10.0"
    assert payload["sdk_docs"]["document_probe"]["class_count"] == 863
    assert (
        payload["sdk_docs"]["document_probe"]["documented_openstudio_version"]
        == "3.10.0"
    )
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


def test_cli_configure_openstudio_persists_confirmed_executable(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    executable = tmp_path / "openstudio"
    executable.write_text("#!/bin/sh\necho 3.0.0-rc1+baflkdhsia\n", encoding="utf-8")
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    data_dir = tmp_path / "runtime-data"
    monkeypatch.setenv("OPENSTUDIO_AI_DATA_DIR", str(data_dir))

    assert main(["configure-openstudio", "--path", str(executable)]) == 0

    config = json.loads((data_dir / "runtime.json").read_text(encoding="utf-8"))
    assert config["openstudio_path"] == str(executable.resolve())
    assert "Saved OpenStudio executable" in capsys.readouterr().out


def test_cli_configure_openstudio_resolves_relative_path_before_probing(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    executable = tmp_path / "openstudio"
    executable.write_text("#!/bin/sh\necho 3.10.0\n", encoding="utf-8")
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    data_dir = tmp_path / "runtime-data"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENSTUDIO_AI_DATA_DIR", str(data_dir))

    assert main(["configure-openstudio", "--path", "openstudio"]) == 0

    config = json.loads((data_dir / "runtime.json").read_text(encoding="utf-8"))
    assert config["openstudio_path"] == str(executable.resolve())
    assert str(executable.resolve()) in capsys.readouterr().out


def test_cli_configure_openstudio_rejects_unrecognized_executable(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    executable = tmp_path / "not-openstudio"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    data_dir = tmp_path / "runtime-data"
    monkeypatch.setenv("OPENSTUDIO_AI_DATA_DIR", str(data_dir))

    assert main(["configure-openstudio", "--path", str(executable)]) == 2

    assert not (data_dir / "runtime.json").exists()
    assert "recognized OpenStudio version" in capsys.readouterr().err


def test_cli_configure_openstudio_reports_configuration_write_failure(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    executable = tmp_path / "openstudio"
    executable.write_text("#!/bin/sh\necho 3.10.0\n", encoding="utf-8")
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(
        cli,
        "set_openstudio_path",
        lambda _: (_ for _ in ()).throw(OSError("read-only filesystem")),
    )

    assert main(["configure-openstudio", "--path", str(executable)]) == 2

    assert "Could not save" in capsys.readouterr().err


def test_cli_install_codex_creates_managed_agents_guidance(
    tmp_path: Path, capsys
) -> None:
    assert (
        main(
            [
                "install",
                "codex",
                "--target-dir",
                str(tmp_path),
                "--workspace-root",
                str(Path(".").resolve()),
            ]
        )
        == 0
    )

    assert "Wrote" in capsys.readouterr().out
    instructions = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "openstudio-modeling-orchestrator" in instructions
    assert "## SDK Script Gate" in instructions


def test_cli_doctor_text_output_reports_checks(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    data_dir = tmp_path / "runtime-data"
    (data_dir / "workspace").mkdir(parents=True)
    monkeypatch.setenv("OPENSTUDIO_AI_DATA_DIR", str(data_dir))
    monkeypatch.setenv("OPENSTUDIO_PATH", "/fake/openstudio")
    monkeypatch.setattr(
        cli,
        "resolve_openstudio_executable_with_source",
        lambda: ("/fake/openstudio", "OPENSTUDIO_PATH"),
    )

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
    assert "Core plugin readiness: ready" in output
    assert "OpenStudio execution status: ready" in output
    assert "Checks:" in output
    assert "- runtime assets: ok" in output
    assert "- runtime storage: ok" in output
    assert "- python openstudio sdk: ok" in output
    assert "- sdk docs lookup: ok" in output


def test_cli_doctor_falls_back_from_invalid_sdk_docs_override(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    data_dir = tmp_path / "runtime-data"
    (data_dir / "workspace").mkdir(parents=True)
    monkeypatch.setenv("OPENSTUDIO_AI_DATA_DIR", str(data_dir))
    monkeypatch.setenv("OPENSTUDIO_SDK_DOCS_DIR", str(tmp_path / "missing-sdk-docs"))
    monkeypatch.setenv("OPENSTUDIO_PATH", "/fake/openstudio")
    monkeypatch.setattr(
        cli,
        "resolve_openstudio_executable_with_source",
        lambda: ("/fake/openstudio", "OPENSTUDIO_PATH"),
    )

    def fake_command_available(command: str) -> dict:
        return {"command": command, "available": True, "path": command}

    def fake_run_probe(command: list[str], *, timeout_seconds: int = 10) -> dict:
        stdout = "3.10.0+test" if "--version" in command else "help"
        return {"ok": True, "returncode": 0, "stdout": stdout, "stderr": ""}

    monkeypatch.setattr(cli, "_command_available", fake_command_available)
    monkeypatch.setattr(cli, "_run_probe", fake_run_probe)

    assert main(["doctor", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mcp_ready"] is True
    assert payload["sdk_docs"]["ok"] is True
    assert payload["sdk_docs"]["source"] == "bundled_fallback"
    assert payload["sdk_docs"]["path"].endswith("openstudio_mcp/sdk_docs/docs")
    assert payload["sdk_docs"]["override_path"] == str(tmp_path / "missing-sdk-docs")
    assert (
        "using the bundled SDK documentation" in payload["sdk_docs"]["override_warning"]
    )
    assert not any(
        item["code"] == "sdk_docs_unavailable" for item in payload["diagnostics"]
    )


def test_cli_doctor_text_reports_missing_openstudio_sdk(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    data_dir = tmp_path / "runtime-data"
    (data_dir / "workspace").mkdir(parents=True)
    monkeypatch.setenv("OPENSTUDIO_AI_DATA_DIR", str(data_dir))
    monkeypatch.setenv("OPENSTUDIO_PATH", "/fake/openstudio")
    monkeypatch.setattr(
        cli,
        "resolve_openstudio_executable_with_source",
        lambda: ("/fake/openstudio", "OPENSTUDIO_PATH"),
    )

    def fake_command_available(command: str) -> dict:
        return {"command": command, "available": True, "path": command}

    def fake_run_probe(command: list[str], *, timeout_seconds: int = 10) -> dict:
        stdout = "3.10.0+test" if "--version" in command else "help"
        return {"ok": True, "returncode": 0, "stdout": stdout, "stderr": ""}

    monkeypatch.setattr(cli, "_command_available", fake_command_available)
    monkeypatch.setattr(cli, "_run_probe", fake_run_probe)
    monkeypatch.setattr(
        cli,
        "_python_openstudio_probe",
        lambda: {"ok": False, "error": "No module named openstudio"},
    )

    assert main(["doctor"]) == 1
    output = capsys.readouterr().out
    assert "MCP runtime status: ready" in output
    assert "Core plugin readiness: not ready" in output
    assert "OpenStudio execution status: not ready" in output
    assert "- python openstudio sdk: failed" in output
    assert "native OpenStudio application" in output
    assert "[openstudio_python_sdk_unavailable]" in output
    assert "Technical detail: No module named openstudio" in output


def test_cli_doctor_reports_plugin_runtime_contract_mismatch(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    data_dir = tmp_path / "runtime-data"
    (data_dir / "workspace").mkdir(parents=True)
    monkeypatch.setenv("OPENSTUDIO_AI_DATA_DIR", str(data_dir))
    monkeypatch.setenv("OPENSTUDIO_PATH", "/fake/openstudio")
    monkeypatch.setattr(
        cli,
        "resolve_openstudio_executable_with_source",
        lambda: ("/fake/openstudio", "OPENSTUDIO_PATH"),
    )

    def fake_command_available(command: str) -> dict:
        return {"command": command, "available": True, "path": command}

    def fake_run_probe(command: list[str], *, timeout_seconds: int = 10) -> dict:
        stdout = "3.10.0+test" if "--version" in command else "help"
        return {"ok": True, "returncode": 0, "stdout": stdout, "stderr": ""}

    monkeypatch.setattr(cli, "_command_available", fake_command_available)
    monkeypatch.setattr(cli, "_run_probe", fake_run_probe)

    assert (
        main(
            [
                "doctor",
                "--json",
                "--plugin-version",
                "9.9.9",
                "--plugin-contract-version",
                "999",
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["mcp_ready"] is True
    assert payload["core_ready"] is False
    assert payload["plugin_ready"] is False
    assert payload["plugin_compatibility"]["ok"] is False
    assert payload["plugin_compatibility"]["status"] == "incompatible"
    assert any(
        item["code"] == "plugin_runtime_incompatible" for item in payload["diagnostics"]
    )
    assert (
        next(
            item
            for item in payload["diagnostics"]
            if item["code"] == "plugin_runtime_incompatible"
        )["severity"]
        == "error"
    )


def test_cli_doctor_blocks_core_readiness_when_openstudio_is_missing(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    data_dir = tmp_path / "runtime-data"
    (data_dir / "workspace").mkdir(parents=True)
    monkeypatch.setenv("OPENSTUDIO_AI_DATA_DIR", str(data_dir))
    monkeypatch.delenv("OPENSTUDIO_PATH", raising=False)
    monkeypatch.setattr(
        cli, "resolve_openstudio_executable_with_source", lambda: (None, None)
    )

    def fake_command_available(command: str) -> dict:
        if command == "openstudio":
            return {"command": command, "available": False, "path": None}
        return {"command": command, "available": True, "path": command}

    monkeypatch.setattr(cli, "_command_available", fake_command_available)
    monkeypatch.setattr(
        cli,
        "_run_probe",
        lambda command, *, timeout_seconds=10: {
            "ok": True,
            "returncode": 0,
            "stdout": "3.10.0+test" if "--version" in command else "help",
            "stderr": "",
        },
    )
    monkeypatch.setattr(cli, "_python_openstudio_probe", lambda: {"ok": True})

    assert main(["doctor", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["mcp_ready"] is True
    assert payload["simulation_ready"] is False
    assert payload["core_ready"] is False
    assert payload["plugin_ready"] is True
    assert payload["ready"] is False
    diagnostic = next(
        item
        for item in payload["diagnostics"]
        if item["code"] == "openstudio_command_unavailable"
    )
    assert diagnostic["severity"] == "error"
    assert "configure-openstudio" in diagnostic["remediation"]


def test_optional_nlr_capability_does_not_block_core_readiness(monkeypatch) -> None:
    monkeypatch.setattr(
        cli,
        "_docker_status",
        lambda: {"installed": False, "running": False, "command": {}},
    )
    monkeypatch.setattr(cli, "_nlr_mcp_status", lambda: {"configured": False})

    capability = cli._optional_capabilities()["nlr_openstudio"]

    assert capability["blocking"] is False
    assert capability["status"] == "unavailable"
    assert "Docker is not installed" in capability["message"]


def test_configured_nlr_reports_missing_docker_without_claiming_it_is_stopped(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "_docker_status",
        lambda: {"installed": False, "running": False, "command": {}},
    )
    monkeypatch.setattr(cli, "_nlr_mcp_status", lambda: {"configured": True})

    capability = cli._optional_capabilities()["nlr_openstudio"]

    assert capability["status"] == "unavailable"
    assert capability["message"] == (
        "NLR OpenStudio-MCP is configured, but Docker is not installed."
    )


def test_nlr_status_ignores_unrelated_mentions(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.Path, "home", staticmethod(lambda: tmp_path))
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    (codex_dir / "config.toml").write_text(
        '# nlr_openstudio is optional\nlabel = "nlr_openstudio"\n',
        encoding="utf-8",
    )
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"other": {"description": "nlr_openstudio"}}}),
        encoding="utf-8",
    )

    status = cli._nlr_mcp_status()

    assert status["configured"] is False


def test_nlr_status_skips_project_scan_when_working_directory_is_unavailable(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(
        cli.Path,
        "cwd",
        staticmethod(lambda: (_ for _ in ()).throw(OSError("directory removed"))),
    )

    status = cli._nlr_mcp_status()

    assert status["configured"] is False


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


def test_cli_export_paired_marketplace_includes_provenance(tmp_path: Path) -> None:
    assert (
        main(
            [
                "export",
                "marketplace",
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

    claude_plugin = tmp_path / "openstudio-ai"
    codex_plugin = tmp_path / "plugins" / "openstudio-ai"
    assert (claude_plugin / ".claude-plugin" / "plugin.json").exists()
    assert (codex_plugin / ".codex-plugin" / "plugin.json").exists()
    assert (tmp_path / ".claude-plugin" / "marketplace.json").exists()
    assert (tmp_path / ".agents" / "plugins" / "marketplace.json").exists()
    assert not (tmp_path / "INSTALL.md").exists()

    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "INSTALL.claude.md" in readme
    assert "INSTALL.codex.md" in readme
    assert (
        (tmp_path / "INSTALL.claude.md")
        .read_text(encoding="utf-8")
        .startswith("# Install OpenStudio AI In Claude Code")
    )
    assert (
        (tmp_path / "INSTALL.codex.md")
        .read_text(encoding="utf-8")
        .startswith("# Install OpenStudio AI In Codex")
    )

    provenance = json.loads((tmp_path / ".generated.json").read_text(encoding="utf-8"))
    assert provenance["schema_version"] == 1
    assert provenance["generator"] == "openstudio-ai export marketplace"
    assert provenance["package"]["name"] == "openstudio-ai"
    assert provenance["plugin"] == {
        "name": "openstudio-ai",
        "mcp_interface_contract_version": "2",
        "runtime_mode": "marketplace",
    }
    assert set(provenance["source"]) == {"revision", "dirty"}


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
    (
        plugin_dir / "skills" / "setup-openstudio-ai" / "scripts" / "doctor_runtime.py"
    ).unlink()
    assert (
        main(["validate-export", str(plugin_dir), "--runtime-mode", "marketplace"]) == 1
    )


def test_cli_validate_export_rejects_missing_compatibility_metadata(
    tmp_path: Path,
) -> None:
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
    mcp_path = plugin_dir / ".mcp.json"
    mcp_config = json.loads(mcp_path.read_text(encoding="utf-8"))
    del mcp_config["mcpServers"]["openstudio_ai"]["env"]
    mcp_path.write_text(json.dumps(mcp_config), encoding="utf-8")

    assert (
        main(["validate-export", str(plugin_dir), "--runtime-mode", "marketplace"]) == 1
    )


def test_cli_validate_export_allows_historical_metadata_unless_strict(
    tmp_path: Path,
) -> None:
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
    mcp_path = plugin_dir / ".mcp.json"
    mcp_config = json.loads(mcp_path.read_text(encoding="utf-8"))
    mcp_config["mcpServers"]["openstudio_ai"]["env"][
        "OPENSTUDIO_AI_PLUGIN_VERSION"
    ] = "0.0.1"
    mcp_path.write_text(json.dumps(mcp_config), encoding="utf-8")

    assert (
        main(["validate-export", str(plugin_dir), "--runtime-mode", "marketplace"]) == 0
    )
    assert (
        main(
            [
                "validate-export",
                str(plugin_dir),
                "--runtime-mode",
                "marketplace",
                "--strict-runtime-version",
            ]
        )
        == 1
    )
