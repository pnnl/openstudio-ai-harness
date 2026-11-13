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


def relative_markdown_targets(text):
    """Inline/image links and reference definitions, including angle paths/spaces."""
    import re
    from urllib.parse import unquote, urlsplit

    targets = re.findall(r"!?\[[^\]\n]*\]\(\s*(<[^>]+>|[^\s)]+)", text)
    targets += re.findall(r"^\s{0,3}\[[^\]\n]+\]:\s*(<[^>]+>|\S+)", text, re.M)
    for target in targets:
        parsed = urlsplit(target.strip("<>"))
        if not parsed.scheme and not parsed.netloc and parsed.path:
            yield unquote(parsed.path)


def assert_plugin_links(document, plugin):
    targets = list(relative_markdown_targets(document.read_text()))
    for target in targets:
        resolved = (document.parent / target).resolve()
        assert resolved.is_relative_to(plugin.resolve()), (document, target)
        assert resolved.is_file(), (document, target)
    return len(targets)


def test_every_exported_skill_link_stays_inside_relocated_plugin(plugin):
    # The fixture has moved the full root to a directory containing spaces and
    # deleted the export directory. Applies to every skill, not only SDK owners.
    assert " " in str(plugin)
    skills = list(plugin.glob("skills/*/SKILL.md"))
    assert skills
    assert sum(assert_plugin_links(path, plugin) for path in skills) > 50
    assert any("../../sdk/" in path.read_text() for path in skills)
    for path in (plugin / "sdk").rglob("*.md"):
        assert_plugin_links(path, plugin)


def test_link_audit_supports_reference_links_and_encoded_spaces(plugin, tmp_path):
    document = plugin / "skills/openstudio-hvac-remover/SKILL.md"
    target = plugin / "sdk/references/a file.md"
    target.write_text("Shared reference")
    document.write_text(
        "[inline](<../../sdk/references/a file.md>)\n"
        '[reference][guide]\n[guide]: ../../sdk/references/a%20file.md#part "Guide"\n'
        "[remote](https://example.com/x)\n[anchor](#local)\n"
    )
    assert assert_plugin_links(document, plugin) == 2
    outside = tmp_path / "outside.md"
    outside.write_text("Outside")
    target.unlink()
    target.symlink_to(outside)
    with pytest.raises(AssertionError):
        assert_plugin_links(document, plugin)


def test_shared_references_are_single_hashed_files(plugin):
    import hashlib

    marker = json.loads((plugin / "sdk/bundle.json").read_text())
    for relative, expected in marker["files"].items():
        file = plugin / "sdk" / relative
        assert hashlib.sha256(file.read_bytes()).hexdigest() == expected
    assert "references/model_preparation.md" in marker["files"]
    assert "schemas/preparation_report.schema.json" in marker["files"]
    assert len(list(plugin.rglob("model_preparation.md"))) == 1
    assert len(list(plugin.rglob("preparation_report.schema.json"))) == 1
    for relative in marker["files"]:
        if relative.endswith(".md"):
            assert len(list(plugin.rglob(Path(relative).name))) == 1
    manifest = yaml.safe_load(asset_manifest.MANIFEST_PATH.read_text())
    for resource in manifest["resources"]:
        if resource.get("scope") == "plugin-sdk" and Path(
            resource["source"]
        ).suffix in {".md", ".json"}:
            relative = (
                Path(resource["source"]).relative_to("skills/sdk_scripts").as_posix()
            )
            assert (plugin / "sdk" / relative).read_bytes() == (
                ROOT / resource["source"]
            ).read_bytes()


def test_size_categories_match_actual_disjoint_files(plugin):
    report_path = plugin / "sdk/PACKAGING.json"
    report = json.loads(report_path.read_text())
    assert report["schema_version"] == 2
    actual = {
        key: dict(files=0, bytes=0)
        for key in ("payload", "launchers", "references", "metadata")
    }
    for file in (plugin / "sdk").rglob("*"):
        if not file.is_file() or file == report_path:
            continue
        relative = file.relative_to(plugin / "sdk")
        if file.name == "bundle.json":
            group = "metadata"
        elif relative.parts[0] in {"references", "schemas"}:
            group = "references"
        else:
            group = "payload"
        actual[group]["files"] += 1
        actual[group]["bytes"] += file.stat().st_size
    for script in plugin.glob("skills/*/scripts/*.py"):
        if "runpy.run_path" in script.read_text():
            actual["launchers"]["files"] += 1
            actual["launchers"]["bytes"] += script.stat().st_size
    assert actual == report["categories"]
    assert (
        sum(x["bytes"] for x in actual.values())
        == report["resource_bytes_excluding_report"]
    )
    assert actual["launchers"]["files"] == report["launchers"] == 99
    assert (
        report["resource_bytes_excluding_report"] + report_path.stat().st_size
        < 1_114_005
    )


@pytest.mark.parametrize("damage", ["missing", "content", "symlink"])
def test_markdown_damage_fails_before_any_entrypoint_runs(plugin, tmp_path, damage):
    file = plugin / "sdk/references/model_preparation.md"
    original = file.read_bytes()
    if damage == "content":
        file.write_bytes(original + b"\nChanged documentation\n")
    else:
        file.unlink()
        if damage == "symlink":
            outside = tmp_path / "copied guide.md"
            outside.write_bytes(original)
            file.symlink_to(outside)
    run = invoke(
        plugin / "skills/openstudio-hvac-remover/scripts/doctor.py", tmp_path, "--help"
    )
    assert run.returncode == 2 and not run.stderr
    assert json.loads(run.stdout)["status"] == "plugin_incomplete"


def test_doc_only_edit_changes_bundle_and_rejects_old_launcher(tmp_path):
    from harness.plugin_sdk import write_resources

    source = tmp_path / "private source"
    shutil.copytree(ROOT / "skills/sdk_scripts", source / "skills/sdk_scripts")
    manifest = yaml.safe_load(asset_manifest.MANIFEST_PATH.read_text())
    from harness.plugin_sdk import plan_resources
    from harness.asset_manifest import ResourceExport

    dest = tmp_path / "private complete plugin"
    before = plan_resources(
        manifest["resources"],
        source,
        dest,
        "codex",
        manifest["sdk_library"]["max_bytes"],
        ResourceExport,
    )
    old_marker = json.loads(
        next(e.content for e in before if e.target.name == "bundle.json")
    )
    old_script = next(
        e.content
        for e in before
        if e.target == dest / "skills/openstudio-hvac-remover/scripts/doctor.py"
    )
    guide = source / "skills/sdk_scripts/references/model_preparation.md"
    guide.write_text(guide.read_text() + "\nDocumentation-only edit.\n")
    after = plan_resources(
        manifest["resources"],
        source,
        dest,
        "codex",
        manifest["sdk_library"]["max_bytes"],
        ResourceExport,
    )
    new_marker = json.loads(
        next(e.content for e in after if e.target.name == "bundle.json")
    )
    assert old_marker["bundle_id"] != new_marker["bundle_id"]
    changed = [
        p
        for p in old_marker["files"]
        if old_marker["files"][p] != new_marker["files"][p]
    ]
    assert changed == ["references/model_preparation.md"]
    write_resources(after, dest)
    script = dest / "skills/openstudio-hvac-remover/scripts/doctor.py"
    script.write_text(old_script)
    run = invoke(script, tmp_path, "--help")
    assert (
        run.returncode == 2 and json.loads(run.stdout)["status"] == "plugin_incomplete"
    )


def test_skill_validator_accepts_cross_skill_folder_references(plugin):
    import os

    validator = Path(
        os.environ.get(
            "CODEX_SKILL_VALIDATOR",
            "~/.codex/skills/.system/skill-creator/scripts/quick_validate.py",
        )
    ).expanduser()
    if not validator.is_file():
        pytest.skip("Optional Codex skill-creator validator is unavailable")
    for skill in plugin.glob("skills/*"):
        if not (skill / "SKILL.md").is_file():
            continue
        # Validate the SDK owners whose cross-folder references changed here.
        if "../../sdk/" not in (skill / "SKILL.md").read_text():
            continue
        run = subprocess.run(
            [sys.executable, str(validator), str(skill)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert run.returncode == 0, str(skill) + run.stdout + run.stderr
