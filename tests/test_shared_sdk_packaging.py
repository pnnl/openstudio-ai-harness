"""Plugin-local SDK deduplication, integrity, growth and deployment contracts."""

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml
from adapters.claude_code_adapter import ClaudeCodeAdapter
from adapters.codex_adapter import CodexAdapter
from adapters.contracts import HostAdapterConfig
from harness import asset_manifest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=["claude", "codex"])
def plugin(tmp_path, request):
    host = request.param
    adapter = (ClaudeCodeAdapter if host == "claude" else CodexAdapter)(
        HostAdapterConfig(
            host_name=host, workspace_root=ROOT, runtime_mode="marketplace"
        )
    )
    output = tmp_path / "original export"
    preview = adapter.export_plugin(output, dry_run=True)
    assert not output.exists()
    result = adapter.export_plugin(output, dry_run=False)
    assert set(preview.files) == set(result.files)
    moved = tmp_path / "moved complete plugin"
    shutil.move(str(result.plugin_dir), moved)
    shutil.rmtree(output)
    return moved


def invoke(script, tmp_path, *args):
    return subprocess.run(
        [sys.executable, "-I", "-S", str(script), *args],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_single_payload_and_size_report(plugin, tmp_path):
    assert list(plugin.rglob("version_guard.py")) == [
        plugin / "sdk/common/version_guard.py"
    ]
    assert list(plugin.rglob("compatibility.json")) == [
        plugin / "sdk/compatibility.json"
    ]
    report = json.loads((plugin / "sdk/PACKAGING.json").read_text())
    assert report["reduction_fraction"] > 0.60
    assert (
        report["resource_bytes_excluding_report"]
        + (plugin / "sdk/PACKAGING.json").stat().st_size
        <= report["max_bytes"]
    )
    assert (
        report["plugin_excluding_report"]["duplicate_bytes"]
        == report["plugin_excluding_report"]["total_bytes"]
        - report["plugin_excluding_report"]["unique_content_bytes"]
    )
    assert report["plugin_excluding_report"]["total_bytes"] == sum(
        p.stat().st_size
        for p in plugin.rglob("*")
        if p.is_file() and p != plugin / "sdk/PACKAGING.json"
    )
    assert not any(plugin.glob("skills/*/scripts/common"))
    assert not list((plugin / "sdk").rglob("*.osm"))
    assert not list((plugin / "sdk").rglob("*.pyc"))
    script = plugin / "skills/openstudio-hvac-remover/scripts/doctor.py"
    run = invoke(script, tmp_path, "--openstudio", str(tmp_path / "missing-cli"))
    assert run.returncode == 2, run.stdout + run.stderr
    result = json.loads(run.stdout)
    assert result["required_openstudio_version"] == "3.11.0"
    assert result["status"] == "required_openstudio_unavailable"


@pytest.mark.parametrize(
    "damage", ["directory", "entrypoint", "helper", "contract", "marker"]
)
def test_incomplete_or_mismatched_library_fails_closed(plugin, tmp_path, damage):
    script = plugin / "skills/openstudio-hvac-remover/scripts/doctor.py"
    if damage == "directory":
        shutil.rmtree(plugin / "sdk")
    else:
        relative = {
            "entrypoint": "doctor.py",
            "helper": "common/version_guard.py",
            "contract": "compatibility.json",
            "marker": "bundle.json",
        }[damage]
        file = plugin / "sdk" / relative
        if damage in {"entrypoint", "helper"}:
            file.unlink()
        elif damage == "contract":
            file.write_text(file.read_text().replace("3.11.0", "3.10.0"))
        else:
            marker = json.loads(file.read_text())
            marker["files"].pop("doctor.py")
            file.write_text(json.dumps(marker))
    run = invoke(script, tmp_path, "--help")
    assert run.returncode == 2 and not run.stderr
    result = json.loads(run.stdout)
    assert result["status"] == "plugin_incomplete" and not result["ready"]
    assert "complete" in result["next_action"]
    assert len(run.stdout) < 1500


def test_detached_skill_cannot_search_for_another_library(
    plugin, tmp_path, monkeypatch
):
    skill = plugin / "skills/openstudio-hvac-remover"
    alone = tmp_path / "detached/skills/openstudio-hvac-remover"
    shutil.copytree(skill, alone)
    monkeypatch.setenv("PYTHONPATH", str(plugin / "sdk"))
    monkeypatch.setenv("OPENSTUDIO_SDK_LIBRARY", str(plugin / "sdk"))
    run = invoke(alone / "scripts/doctor.py", tmp_path, "--help")
    assert run.returncode == 2
    assert json.loads(run.stdout)["status"] == "plugin_incomplete"


@pytest.mark.parametrize("change", ["budget", "scope", "source", "destination"])
def test_shared_resource_configuration_rejects_invalid_layout(
    tmp_path, monkeypatch, change
):
    manifest = yaml.safe_load(asset_manifest.MANIFEST_PATH.read_text())
    resource = manifest["resources"][0]
    if change == "budget":
        manifest["sdk_library"]["max_bytes"] = 1
    elif change == "scope":
        resource["scope"] = "unknown"
    elif change == "source":
        resource["source"] = "skills/openstudio_hvac_remover.md"
    else:
        resource["owners"][0]["path"] = "../sdk/escape.py"
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(manifest))
    monkeypatch.setattr(asset_manifest, "MANIFEST_PATH", path)
    with pytest.raises(ValueError):
        asset_manifest.resource_exports_for_host(ROOT, tmp_path / "export", "claude")


def test_every_public_entrypoint_resolves_after_complete_relocation(plugin, tmp_path):
    scripts = [
        p
        for p in plugin.glob("skills/*/scripts/*.py")
        if "runpy.run_path" in p.read_text()
    ]
    # Plant source replacement adds four launchers; cleanup adds one.
    assert len(scripts) == 99
    for script in scripts:
        if script.name == "sdk_probe.py":
            continue  # Probe has no argparse; the separate native case executes it.
        run = invoke(script, tmp_path, "--help")
        assert run.returncode == 0, str(script) + run.stdout + run.stderr


def test_native_probe_uses_relocated_library(plugin, tmp_path):
    import os

    executable = Path(
        os.environ.get(
            "OPENSTUDIO_SKILL_TEST_EXE",
            "/Applications/OpenStudio-3.11.0/bin/openstudio",
        )
    )
    if not executable.is_file():
        pytest.skip("Native 3.11.0 CLI unavailable")
    script = plugin / "skills/openstudio-sdk-model-editor/scripts/sdk_probe.py"
    run = subprocess.run(
        [str(executable), "execute_python_script", str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    record = next(
        line.split("=", 1)[1]
        for line in run.stdout.splitlines()
        if line.startswith("OPENSTUDIO_SKILL_SDK_PROBE=")
    )
    assert json.loads(record)["sdk_version"].split("+")[0] == "3.11.0"


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_export_runs_after_its_source_workspace_is_deleted(tmp_path, monkeypatch, host):
    source = tmp_path / "temporary source checkout"
    source.mkdir()
    for folder in ["skills", "prompts"]:
        shutil.copytree(ROOT / folder, source / folder)
    manifest = yaml.safe_load(asset_manifest.MANIFEST_PATH.read_text())
    manifest["references"] = []
    path = source / "manifest.yaml"
    path.write_text(yaml.safe_dump(manifest))
    monkeypatch.setattr(asset_manifest, "MANIFEST_PATH", path)
    adapter = (ClaudeCodeAdapter if host == "claude" else CodexAdapter)(
        HostAdapterConfig(
            host_name=host, workspace_root=source, runtime_mode="marketplace"
        )
    )
    result = adapter.export_plugin(tmp_path / "export", dry_run=False)
    moved = tmp_path / "relocated complete plugin"
    shutil.move(str(result.plugin_dir), moved)
    shutil.rmtree(source)
    run = invoke(
        moved / "skills/openstudio-hvac-remover/scripts/remove_hvac.py",
        tmp_path,
        "--help",
    )
    assert run.returncode == 0, run.stdout + run.stderr
