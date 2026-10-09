from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path("skills/sdk_scripts").resolve()


@pytest.fixture
def doctor(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "skill_sdk_doctor", SCRIPTS / "doctor.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.delenv("OPENSTUDIO_PATH", raising=False)
    return module


def fake_cli(tmp_path: Path) -> Path:
    path = tmp_path / "openstudio"
    path.write_text("test executable", encoding="utf-8")
    return path


def fake_probe(doctor, monkeypatch, cli="3.11.0+build", sdk="3.11.0", sdk_ok=True):
    commands = []

    def run(command):
        commands.append(command)
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, cli, "")
        payload = {"ok": sdk_ok, "sdk_version": sdk}
        return subprocess.CompletedProcess(
            command, 0, "native log\n" + doctor.PROBE_PREFIX + json.dumps(payload), ""
        )

    monkeypatch.setattr(doctor, "run_probe", run)
    return commands


@pytest.mark.parametrize(
    "value", ["3.11.0", "3.11.0+241b8abb4d", "OpenStudio 3.11.0\n"]
)
def test_accept_stable_release_identity(doctor, value):
    assert doctor.release_version(value) == "3.11.0"


@pytest.mark.parametrize("value", ["3.11", "3.11.0-rc1", "garbage", "3.11.0\n3.10.0"])
def test_reject_unrecognized_or_prerelease_identity(doctor, value):
    assert doctor.release_version(value) is None


def test_verify_cli_and_sdk_before_ready(doctor, monkeypatch, tmp_path):
    path = fake_cli(tmp_path)
    commands = fake_probe(doctor, monkeypatch)
    report = doctor.diagnose(str(path))
    assert report["ok"] is True
    assert report["openstudio_executable"] == str(path.resolve())
    assert commands == [
        [str(path), "--version"],
        [str(path), "execute_python_script", str(SCRIPTS / "sdk_probe.py")],
    ]


@pytest.mark.parametrize(
    "version", ["3.10.0", "3.11.1", "3.12.0", "4.0.0", "3.11.0-rc1", "unknown"]
)
def test_incompatible_cli_never_launches_sdk(doctor, monkeypatch, tmp_path, version):
    commands = fake_probe(doctor, monkeypatch, cli=version)
    report = doctor.diagnose(str(fake_cli(tmp_path)))
    assert report["ok"] is False
    assert report["candidates"][0]["status"] == "cli_incompatible"
    assert len(commands) == 1


@pytest.mark.parametrize("version", ["3.10.0", "3.11.1", "3.11.0-rc1", "unknown"])
def test_matching_cli_cannot_hide_mismatched_sdk(
    doctor, monkeypatch, tmp_path, version
):
    fake_probe(doctor, monkeypatch, sdk=version)
    report = doctor.diagnose(str(fake_cli(tmp_path)))
    assert report["ok"] is False
    assert report["candidates"][0]["status"] == "sdk_incompatible"


@pytest.mark.parametrize("source", ["argument", "environment"])
def test_explicit_path_has_no_fallback(doctor, monkeypatch, tmp_path, source):
    fake_probe(doctor, monkeypatch, cli="3.10.0")
    path = fake_cli(tmp_path)

    def unexpected_discovery(required):
        pytest.fail("Explicit path must not trigger discovery")

    monkeypatch.setattr(doctor, "discover_candidates", unexpected_discovery)
    if source == "environment":
        monkeypatch.setenv("OPENSTUDIO_PATH", str(path))
        report = doctor.diagnose()
    else:
        report = doctor.diagnose(str(path))
    assert report["ok"] is False
    assert len(report["candidates"]) == 1


def test_missing_explicit_path_blocks(doctor, tmp_path):
    report = doctor.diagnose(str(tmp_path / "missing"))
    assert report["ok"] is False
    assert report["candidates"][0]["status"] == "missing"
    assert "3.11.0" in report["error"]


def test_discovery_selects_only_verified_release(doctor, monkeypatch, tmp_path):
    wrong = tmp_path / "wrong"
    right = tmp_path / "right"
    wrong.touch()
    right.touch()
    monkeypatch.setattr(doctor, "discover_candidates", lambda required: [wrong, right])
    fake_probe(doctor, monkeypatch)
    original = doctor.run_probe
    monkeypatch.setattr(
        doctor,
        "run_probe",
        lambda cmd: (
            subprocess.CompletedProcess(cmd, 0, "3.8.0", "")
            if cmd[0] == str(wrong)
            else original(cmd)
        ),
    )
    report = doctor.diagnose()
    assert report["ok"] is True
    assert report["openstudio_executable"] == str(right)
    assert report["candidates"][0]["ok"] is False


@pytest.mark.parametrize("platform", ["darwin", "linux", "win32"])
def test_platform_discovery_includes_pinned_locations(doctor, monkeypatch, platform):
    monkeypatch.setattr(doctor.sys, "platform", platform)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    paths = doctor.discover_candidates("3.11.0")
    assert paths
    assert all("3.11.0" in str(path) for path in paths)


@pytest.mark.parametrize(
    "failure",
    ["timeout", "permission", "invalid_json", "empty", "sdk_failure", "cli_exit"],
)
def test_probe_failures_block(doctor, monkeypatch, tmp_path, failure):
    fake_probe(doctor, monkeypatch)
    original = doctor.run_probe

    def run(cmd):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(cmd, 15)
        if failure == "permission":
            raise PermissionError("denied")
        if cmd[-1] == "--version":
            if failure == "cli_exit":
                return subprocess.CompletedProcess(cmd, 1, "3.11.0", "failed")
            return original(cmd)
        if failure == "invalid_json":
            return subprocess.CompletedProcess(cmd, 0, doctor.PROBE_PREFIX + "bad", "")
        if failure == "empty":
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(
            cmd,
            1,
            doctor.PROBE_PREFIX + '{"ok":false,"error":"import failed"}',
            "failed",
        )

    monkeypatch.setattr(doctor, "run_probe", run)
    assert doctor.diagnose(str(fake_cli(tmp_path)))["ok"] is False


def test_probe_removes_host_python_search_paths(doctor, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "foreign-sdk")
    monkeypatch.setenv("PYTHONHOME", "foreign-python")

    def run(cmd, **kwargs):
        assert "PYTHONPATH" not in kwargs["env"]
        assert "PYTHONHOME" not in kwargs["env"]
        assert kwargs["timeout"] == doctor.PROBE_TIMEOUT_SECONDS
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(doctor.subprocess, "run", run)
    doctor.run_probe(["fake", "--version"])


def test_guard_rechecks_sdk_before_each_operation(doctor, monkeypatch):
    from common.version_guard import CompatibilityError, require_sdk

    sdk = SimpleNamespace(openStudioVersion=lambda: "3.11.0")
    monkeypatch.setitem(sys.modules, "openstudio", sdk)
    assert require_sdk() is sdk
    sdk.openStudioVersion = lambda: "3.10.0"
    with pytest.raises(CompatibilityError, match="executing SDK"):
        require_sdk()


def test_guard_blocks_model_mutation_with_wrong_sdk(doctor, tmp_path):
    marker = tmp_path / "model_mutated"
    script = (
        "import sys, types\n"
        f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
        "sys.modules['openstudio'] = types.SimpleNamespace(openStudioVersion=lambda: '3.10.0')\n"
        "from common.version_guard import require_sdk\n"
        "require_sdk()\n"
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('mutated')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-S", "-c", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode != 0
    assert "executing SDK" in completed.stderr
    assert not marker.exists()


@pytest.mark.parametrize(
    "change",
    [
        {"required_openstudio_version": "3.11"},
        {"required_openstudio_version": "3.11.0-rc1"},
        {"schema_version": 2},
        {"platforms": []},
    ],
)
def test_invalid_contract_blocks(doctor, tmp_path, change):
    from common.version_guard import CompatibilityError, load_contract

    path = tmp_path / "contract.json"
    contract = json.loads((SCRIPTS / "compatibility.json").read_text())
    path.write_text(json.dumps({**contract, **change}), encoding="utf-8")
    with pytest.raises(CompatibilityError):
        load_contract(path)


def test_unsupported_platform_blocks_before_discovery(doctor, monkeypatch):
    monkeypatch.setattr(doctor.sys, "platform", "unknown")
    report = doctor.diagnose()
    assert report["status"] == "unsupported_platform"
    assert report["candidates"] == []


def test_guard_reports_unavailable_sdk(doctor, monkeypatch):
    from common import version_guard

    def unavailable(name):
        raise ImportError("binding missing")

    monkeypatch.setattr(version_guard.importlib, "import_module", unavailable)
    with pytest.raises(version_guard.CompatibilityError, match="SDK is unavailable"):
        version_guard.require_sdk()


@pytest.mark.parametrize("contents", ["{bad json", "[]"])
def test_malformed_contract_fails_closed(doctor, tmp_path, contents):
    from common.version_guard import CompatibilityError, load_contract

    path = tmp_path / "contract.json"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(CompatibilityError):
        load_contract(path)


def test_missing_contract_fails_closed(doctor, tmp_path):
    from common.version_guard import CompatibilityError, load_contract

    with pytest.raises(CompatibilityError, match="Cannot read"):
        load_contract(tmp_path / "missing.json")


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_exported_sdk_doctor_blocks_missing_release_without_runtime(tmp_path, host):
    from adapters.claude_code_adapter import ClaudeCodeAdapter
    from adapters.codex_adapter import CodexAdapter
    from adapters.contracts import HostAdapterConfig

    adapter_type = ClaudeCodeAdapter if host == "claude" else CodexAdapter
    adapter = adapter_type(
        HostAdapterConfig(
            host_name="claude_code" if host == "claude" else host,
            workspace_root=Path(".").resolve(),
            runtime_mode="marketplace",
        )
    )
    result = adapter.export_plugin(tmp_path / "export", dry_run=False)
    scripts = result.plugin_dir / "skills/openstudio-sdk-model-editor/scripts"
    assert (
        json.loads((scripts / "compatibility.json").read_text())[
            "required_openstudio_version"
        ]
        == "3.11.0"
    )
    # Execute with stdlib only, in an unrelated CWD, outside the source checkout.
    completed = subprocess.run(
        [
            sys.executable,
            "-S",
            str(scripts / "doctor.py"),
            "--openstudio",
            str(tmp_path / "missing"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 2
    report = json.loads(completed.stdout)
    assert report["ok"] is False
    assert report["required_openstudio_version"] == "3.11.0"
    assert report["candidates"][0]["status"] == "missing"
