from __future__ import annotations

import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from adapters.claude_code_adapter import ClaudeCodeAdapter
from adapters.codex_adapter import CodexAdapter
from adapters.contracts import HostAdapterConfig
from harness import asset_manifest


@pytest.fixture
def resource_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    for directory in ("skills", "prompts"):
        shutil.copytree(Path(directory), root / directory)
    scripts = root / "skills" / "fixture_scripts"
    scripts.mkdir()
    (scripts / "probe.py").write_text(
        "import json\nfrom common.helper import value\n"
        "from pathlib import Path\n"
        "schema = Path(__file__).resolve().parents[1] / 'references/input.json'\n"
        "print(json.dumps({'value': value(), 'schema': json.loads(schema.read_text())}))\n",
        encoding="utf-8",
    )
    (scripts / "probe.py").chmod(0o755)
    (scripts / "helper.py").write_text(
        "def value():\n    return 42\n", encoding="utf-8"
    )
    (scripts / "input.json").write_text('{"type": "object"}\n', encoding="utf-8")
    (scripts / "notes.md").write_text("---\nkeep: true\n---\nNotes\n", encoding="utf-8")
    manifest = yaml.safe_load(asset_manifest.MANIFEST_PATH.read_text())
    manifest["references"] = []
    manifest["resources"] = [
        {
            "source": f"skills/fixture_scripts/{source}",
            "owners": [
                {"hosts": ["claude", "codex"], "skill": skill, "path": destination}
                for skill in ("openstudio-sdk-model-editor", "add-vav-reheat")
            ],
        }
        for source, destination in (
            ("probe.py", "scripts/probe.py"),
            ("helper.py", "scripts/common/helper.py"),
            ("input.json", "references/input.json"),
            ("notes.md", "references/notes.md"),
        )
    ]
    manifest_path = root / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    monkeypatch.setattr(asset_manifest, "MANIFEST_PATH", manifest_path)
    return root


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("runtime_mode", ["local", "marketplace"])
def test_exported_resources_execute_after_relocation_without_runtime(
    resource_workspace: Path, tmp_path: Path, host: str, runtime_mode: str
) -> None:
    adapter_type = ClaudeCodeAdapter if host == "claude" else CodexAdapter
    adapter = adapter_type(
        HostAdapterConfig(
            host_name="claude_code" if host == "claude" else host,
            workspace_root=resource_workspace,
            runtime_mode=runtime_mode,
        )
    )
    export_root = tmp_path / "export"
    preview = adapter.export_plugin(export_root, dry_run=True)
    assert not export_root.exists()
    result = adapter.export_plugin(export_root, dry_run=False)
    assert set(preview.files) == set(result.files)
    exports = asset_manifest.resource_exports_for_host(
        resource_workspace, result.plugin_dir, host
    )
    for export in exports:
        assert export.target in preview.files
        assert export.target.read_bytes() == export.source.read_bytes()
        assert stat.S_IMODE(export.target.stat().st_mode) == stat.S_IMODE(
            export.source.stat().st_mode
        )
    relocated = tmp_path / "relocated"
    shutil.move(str(result.plugin_dir), relocated)
    shutil.rmtree(resource_workspace)
    for skill in ("openstudio-sdk-model-editor", "add-vav-reheat"):
        # -S excludes installed packages, including the OpenStudio AI runtime.
        completed = subprocess.run(
            [
                sys.executable,
                "-S",
                str(relocated / "skills" / skill / "scripts/probe.py"),
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        assert completed.returncode == 0, completed.stderr
        assert json.loads(completed.stdout) == {
            "value": 42,
            "schema": {"type": "object"},
        }


def _update_resource(root: Path, **changes: object) -> None:
    path = root / "manifest.yaml"
    manifest = yaml.safe_load(path.read_text())
    manifest["resources"][0].update(changes)
    path.write_text(yaml.safe_dump(manifest), encoding="utf-8")


@pytest.mark.parametrize(
    "path", ["../outside", "/outside", ".", "scripts\\bad", "C:/bad"]
)
def test_reject_unsafe_resource_destination(
    resource_workspace: Path, path: str
) -> None:
    _update_resource(
        resource_workspace,
        owners=[{"hosts": ["codex"], "skill": "add-vav-reheat", "path": path}],
    )
    with pytest.raises(ValueError, match="safe destination"):
        asset_manifest.resource_exports_for_host(
            resource_workspace, Path("/tmp/plugin"), "codex"
        )


@pytest.mark.parametrize("source", ["../outside", "/outside", "skills/*.py", "C:/bad"])
def test_reject_unsafe_resource_source(resource_workspace: Path, source: str) -> None:
    _update_resource(resource_workspace, source=source)
    with pytest.raises(ValueError, match="safe source"):
        asset_manifest.resource_exports_for_host(
            resource_workspace, Path("/tmp/plugin"), "codex"
        )


def test_reject_missing_or_symlinked_external_resource(
    resource_workspace: Path, tmp_path: Path
) -> None:
    _update_resource(resource_workspace, source="missing.py")
    with pytest.raises(ValueError, match="file inside workspace"):
        asset_manifest.resource_exports_for_host(
            resource_workspace, tmp_path / "plugin", "codex"
        )
    outside = tmp_path / "outside.py"
    outside.write_text("print('outside')", encoding="utf-8")
    (resource_workspace / "external.py").symlink_to(outside)
    _update_resource(resource_workspace, source="external.py")
    with pytest.raises(ValueError, match="file inside workspace"):
        asset_manifest.resource_exports_for_host(
            resource_workspace, tmp_path / "plugin", "codex"
        )


@pytest.mark.parametrize(
    "skill,path",
    [
        ("add-vav-reheat", "SKILL.md"),
        ("add-vav-reheat", "scripts/common/helper.py"),
        ("add-vav-reheat", "scripts/common"),
    ],
)
def test_reject_resource_destination_collisions(
    resource_workspace: Path, skill: str, path: str
) -> None:
    _update_resource(
        resource_workspace, owners=[{"hosts": ["codex"], "skill": skill, "path": path}]
    )
    with pytest.raises(ValueError, match="destination collision"):
        asset_manifest.resource_exports_for_host(
            resource_workspace, Path("/tmp/plugin"), "codex"
        )


def test_resources_respect_host_ownership(
    resource_workspace: Path, tmp_path: Path
) -> None:
    _update_resource(
        resource_workspace,
        owners=[
            {"hosts": ["codex"], "skill": "add-vav-reheat", "path": "scripts/probe.py"}
        ],
    )
    claude = asset_manifest.resource_exports_for_host(
        resource_workspace, tmp_path / "plugin", "claude"
    )
    assert not any(export.source.name == "probe.py" for export in claude)


def test_reject_collision_with_reference_export(resource_workspace: Path) -> None:
    path = resource_workspace / "manifest.yaml"
    manifest = yaml.safe_load(path.read_text())
    manifest["references"] = [
        {
            "source": "skills/fixture_scripts/input.json",
            "owners": [{"hosts": ["codex"], "skill": "add-vav-reheat"}],
        }
    ]
    path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="destination collision"):
        asset_manifest.resource_exports_for_host(
            resource_workspace, Path("/tmp/plugin"), "codex"
        )


def test_reject_collision_with_generated_setup_helper(resource_workspace: Path) -> None:
    path = resource_workspace / "manifest.yaml"
    manifest = yaml.safe_load(path.read_text())
    manifest["skills"].append(
        {
            "id": "setup-openstudio-ai",
            "source": "skills/add_vav_reheat.md",
            "hosts": ["codex"],
        }
    )
    manifest["resources"][0]["owners"] = [
        {
            "hosts": ["codex"],
            "skill": "setup-openstudio-ai",
            "path": "scripts/doctor_runtime.py",
        }
    ]
    path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="destination collision"):
        asset_manifest.resource_exports_for_host(
            resource_workspace, Path("/tmp/plugin"), "codex"
        )


@pytest.mark.parametrize("skill", ["unknown-skill", "openstudio-modeling-orchestrator"])
def test_reject_unknown_or_unsupported_owner(
    resource_workspace: Path, skill: str
) -> None:
    _update_resource(
        resource_workspace,
        owners=[{"hosts": ["claude"], "skill": skill, "path": "scripts/probe.py"}],
    )
    with pytest.raises(ValueError, match="unknown skill|assigns hosts not exported"):
        asset_manifest.resource_exports_for_host(
            resource_workspace, Path("/tmp/plugin"), "claude"
        )


def test_sdk_reference_paths_rewrite_both_alias_forms_without_touching_other_paths():
    from harness.plugin_sdk import rewrite_reference_paths

    target = "../../sdk/references/guide.md"
    aliases = {
        "references/guide.md": target,
        "scripts/references/guide.md": target,
        "./references/guide.md": target,
    }
    before = "[guide](scripts/references/guide.md#section)\n[ref]: ./references/guide.md\n`references/guide.md`"
    after = rewrite_reference_paths(before, aliases)
    assert after == f"[guide]({target}#section)\n[ref]: {target}\n`{target}`"
    assert rewrite_reference_paths(after, aliases) == after
    untouched = "other/references/guide.md references/guide.md.backup https://x/references/guide.md"
    assert rewrite_reference_paths(untouched, aliases) == untouched


def test_sdk_reference_aliases_reject_conflicting_sources_and_respect_hosts(tmp_path):
    from harness.plugin_sdk import reference_aliases

    resources = [
        {
            "scope": "plugin-sdk",
            "source": f"skills/sdk_scripts/references/{name}.md",
            "owners": [
                {"hosts": ["codex"], "skill": "fixture", "path": "references/guide.md"}
            ],
        }
        for name in ("first", "second")
    ]
    assert reference_aliases(resources, tmp_path, "claude") == {}
    aliases = reference_aliases(resources[:1], tmp_path, "codex")["fixture"]
    assert set(aliases.values()) == {"../../sdk/references/first.md"}
    assert "scripts/references/guide.md" in aliases
    with pytest.raises(ValueError, match="Conflicting shared SDK reference alias"):
        reference_aliases(resources, tmp_path, "codex")


@pytest.mark.parametrize("suffix", [".", ",", ";", ":", "!", "?", "...", "\n"])
def test_sdk_reference_sentence_punctuation_is_rewritten(suffix):
    from harness.plugin_sdk import rewrite_reference_paths

    aliases = {"references/x.md": "../../sdk/references/x.md"}
    assert rewrite_reference_paths(f"See references/x.md{suffix}", aliases) == (
        f"See ../../sdk/references/x.md{suffix}"
    )


def test_export_rejects_unrewritten_bare_reference(tmp_path, monkeypatch):
    from harness import plugin_sdk

    skill = tmp_path / "skills/example/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("See references/x.md.")
    monkeypatch.setattr(plugin_sdk, "rewrite_reference_paths", lambda text, _: text)
    with pytest.raises(ValueError, match="Unrewritten SDK reference alias"):
        plugin_sdk.write_resources(
            [],
            tmp_path,
            aliases={"example": {"references/x.md": "../../sdk/references/x.md"}},
        )
    assert skill.read_text() == "See references/x.md."


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.slow
def test_export_rejects_alias_collision_in_adapter_copied_files(
    tmp_path, monkeypatch, host
):
    from adapters import claude_code_adapter, codex_adapter

    module = claude_code_adapter if host == "claude" else codex_adapter
    original = module._write_skill_references

    def copy_extra_reference(skills_dir, workspace_root):
        original(skills_dir, workspace_root)
        # Simulate a local skill file / host-specific reference not in the manifest.
        path = skills_dir / "openstudio-economizer-editor/references/economizer.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Distinct local reference; must not be silently shadowed.")

    monkeypatch.setattr(module, "_write_skill_references", copy_extra_reference)
    adapter = (ClaudeCodeAdapter if host == "claude" else CodexAdapter)(
        HostAdapterConfig(
            host_name=host, workspace_root=Path.cwd(), runtime_mode="marketplace"
        )
    )
    with pytest.raises(ValueError, match="SDK reference alias destination collision"):
        adapter.export_plugin(tmp_path / "export with spaces", dry_run=False)
