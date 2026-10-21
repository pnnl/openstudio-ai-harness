from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import pytest

SCRIPT = Path("skills/sdk_scripts/report.py").resolve()


@pytest.fixture
def module():
    spec = importlib.util.spec_from_file_location("sdk_report_script", SCRIPT)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def ready():
    return {
        "ok": True,
        "ready": True,
        "mode": "inspect_only",
        "assumptions": ["approved"] * 50,
        "plan": {
            "parameters": {"system_name": "VAV"},
            "resolved_objects": {"target_zones": [{"name": "Zone", "handle": "zone"}]},
        },
        "candidates": {"schedules": [{"name": "unused"}]},
        "warnings": ["generic profile"],
    }


def test_preserves_full_report_and_reduces_stdout_context(module, ready, tmp_path):
    raw = json.dumps(ready)
    log = tmp_path / "sdk.log"
    log.write_text("SDK warning\n" + raw + "\n")
    output = tmp_path / "plan.json"
    summary = module.persist(log, output)
    assert output.read_text() == raw + "\n"
    assert summary["parameters"]["system_name"] == "VAV"
    assert summary["resolved_objects"]["target_zones"][0]["handle"] == "zone"
    assert (
        summary["assumption_count"] == 50 and summary["warnings"] == ready["warnings"]
    )
    assert "assumptions" not in summary and "candidates" not in summary
    assert len(json.dumps(summary)) < len(raw)
    assert not list(tmp_path.glob(".sdk-report-*"))


@pytest.mark.parametrize(
    "last",
    [
        "",
        "not JSON",
        '{"ok":true,"ok":false,"mode":"inspect_only"}',
        '{"ok":true,"mode":"inspect_only","ready":NaN}',
        '{"ok":true,"mode":"inspect_only","ready":true,"n":1e309}',
        '{"ok":"yes","mode":"inspect_only"}',
        '{"ok":true,"mode":"edit_model"}',
        '{"ok":true,"mode":"edit_model","validation":{"ok":false}}',
        '{"ok":true,"mode":"inspect_only"}',
    ],
)
def test_malformed_log_never_publishes_report(module, tmp_path, last):
    log = tmp_path / "sdk.log"
    log.write_text(last)
    output = tmp_path / "report.json"
    with pytest.raises(ValueError):
        module.persist(log, output)
    assert not output.exists()


def test_does_not_search_past_invalid_final_line(module, ready, tmp_path):
    log = tmp_path / "sdk.log"
    log.write_text(json.dumps(ready) + "\ntrailing failure\n")
    with pytest.raises(ValueError):
        module.persist(log, tmp_path / "report.json")


def test_inventory_preserves_choices_without_nested_space_inventory(module, tmp_path):
    log = tmp_path / "sdk.log"
    report = {
        "ok": True,
        "ready": False,
        "mode": "inspect_only",
        "candidates": {
            "zones": [
                {
                    "name": "Zone",
                    "handle": "zone",
                    "spaces": [{"name": "Space"}],
                    "is_plenum": False,
                    "has_thermostat": True,
                    "air_loops": [],
                    "equipment": [],
                }
            ],
            "plant_loops": [{"name": "HW"}],
            "schedules": [{"name": "On"}],
        },
    }
    log.write_text(json.dumps(report))
    result = module.persist(log, tmp_path / "report.json")
    assert result["candidates"]["zones"][0]["space_count"] == 1
    assert result["candidates"]["plant_loops"] == report["candidates"]["plant_loops"]


@pytest.mark.parametrize("existing", ["file", "symlink"])
def test_existing_report_preserved(module, ready, tmp_path, existing):
    log = tmp_path / "sdk.log"
    log.write_text(json.dumps(ready))
    output = tmp_path / "report.json"
    if existing == "file":
        output.write_text("existing")
    else:
        output.symlink_to(tmp_path / "missing.json")
    with pytest.raises(ValueError, match="already exists"):
        module.persist(log, output)
    if existing == "file":
        assert output.read_text() == "existing"
    else:
        assert output.is_symlink()


def test_publish_race_preserves_other_writer(module, ready, tmp_path, monkeypatch):
    log = tmp_path / "sdk.log"
    log.write_text(json.dumps(ready))
    output = tmp_path / "report.json"
    link = module.os.link

    def competing(source, target):
        Path(target).write_text("other writer")
        return link(source, target)

    monkeypatch.setattr(module.os, "link", competing)
    with pytest.raises(FileExistsError):
        module.persist(log, output)
    assert output.read_text() == "other writer"
    assert not list(tmp_path.glob(".sdk-report-*"))


def test_failure_report_is_saved_and_cli_returns_two_without_sdk(tmp_path):
    log = tmp_path / "sdk.log"
    log.write_text(
        json.dumps({"ok": False, "mode": "edit_model", "error": "stale input"})
    )
    output = tmp_path / "failure.json"
    result = subprocess.run(
        [sys.executable, "-S", str(SCRIPT), "--log", str(log), "--report", str(output)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout)["error"] == "stale input"
    assert json.loads(output.read_text())["ok"] is False
