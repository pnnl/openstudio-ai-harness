"""Real historic OSMs, preparation gates, strict transactions and relocation."""

import json
from pathlib import Path
import re
import sys
import subprocess

import pytest
from test_vav_preflight import sdk

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/sdk_scripts"
FIXTURES = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))
from common import version_guard as guard
from common.diagnostics import failure_report, mismatch

TRANSACTION_ENTRYPOINTS = [
    "remove_hvac.py",
    "edit_supply_fan_performance.py",
    "edit_water_coil.py",
    "edit_ventilation.py",
    "edit_economizer.py",
    "plant_loops.py",
    "cav_system.py",
    "replace_supply_fan.py",
    "connect_water_coil.py",
    "replace_coil.py",
    "edit_pump_performance.py",
    "replace_pump.py",
    "manage_heat_recovery.py",
    "attach_outdoor_air.py",
]


def current_model(o, tmp_path, *, loop=False):
    model = o.model.Model()
    if loop:
        o.model.AirLoopHVAC(model)
    source = tmp_path / "current.osm"
    model.save(str(source), True)
    return source


@pytest.mark.parametrize(
    "name,version",
    [
        ("openstudio-1.13.4-example.osm", "1.13.4"),
        ("openstudio-legacy-multiloop.osm", "2.2.2"),
    ],
)
def test_genuine_older_input_gated_before_translation(sdk, monkeypatch, name, version):
    source = FIXTURES / name
    assert guard.model_version(source) == version

    def forbidden(*args):
        raise AssertionError("Older-model gate must precede VT and planners")

    monkeypatch.setattr(sdk[0].osversion, "VersionTranslator", forbidden)
    with pytest.raises(guard.PreparationRequired) as error:
        guard.load_model(sdk[0], source)
    report = failure_report(error.value)
    assert not report["ok"] and not report["ready"]
    assert report["status"] == "requires_preparation"
    assert report["source_version"] == version and report["target_version"] == "3.11.0"
    assert report["next_action"]["operation"] == "prepare_model"
    assert len(json.dumps(report)) < 2000


def test_current_default_guard_loads_twice_and_optional_single_load(
    sdk, tmp_path, monkeypatch
):
    o = sdk[0]
    source = current_model(o, tmp_path)
    real = o.osversion.VersionTranslator.loadModel
    calls = []

    def load(translator, *args):
        calls.append(args)
        return real(translator, *args)

    monkeypatch.setattr(o.osversion.VersionTranslator, "loadModel", load)
    guard.load_model(o, source)
    assert len(calls) == 2
    calls.clear()
    guard.load_model(o, source, check_stability=False)
    assert len(calls) == 1


def test_genuine_object_difference_between_loads_is_not_ignored(
    sdk, tmp_path, monkeypatch
):
    o = sdk[0]
    source = current_model(o, tmp_path)
    real = o.osversion.VersionTranslator.loadModel
    calls = []

    def load(translator, *args):
        result = real(translator, *args)
        calls.append(result)
        if len(calls) == 2:
            o.model.ThermalZone(result.get())
        return result

    monkeypatch.setattr(o.osversion.VersionTranslator, "loadModel", load)
    with pytest.raises(guard.PreparationRequired) as error:
        guard.load_model(o, source)
    details = error.value.details
    assert details["reason"] == "load_handle_instability"
    counts = details["handle_changes"]["added_by_type"]
    assert counts["OS_ThermalZone"] == 1
    assert sum(counts.values()) == details["handle_changes"]["added_count"]
    assert details["handle_changes"]["removed_count"] == 0


@pytest.mark.parametrize("loop_kind", ["AirLoopHVAC", "PlantLoop"])
def test_current_missing_assignment_list_has_bounded_error(sdk, tmp_path, loop_kind):
    o = sdk[0]
    model = o.model.Model()
    loop = getattr(o.model, loop_kind)(model)
    source = tmp_path / "current.osm"
    assert model.save(str(source), True)
    text = source.read_text()
    text, count = re.subn(
        r"(?ms)^OS:AvailabilityManagerAssignmentList\s*,.*?;", "", text
    )
    assert count == 1
    source.write_text(text)
    with pytest.raises(
        ValueError, match="AvailabilityManagerAssignmentList reference"
    ) as error:
        guard.load_model(o, source)
    report = failure_report(error.value)
    assert report["status"] == "invalid_model"
    assert report["invalid_reference_count"] == 1
    assert report["invalid_references"] == [
        {"handle": str(loop.handle()), "type": "OS_" + loop_kind}
    ]
    assert len(json.dumps(report)) < 1200


def test_mismatch_paths_categories_and_bounding():
    a = {
        "input_sha256": "a",
        "plan": {
            "fan": {"efficiency": 0.6},
            "handle": "{11111111-1111-1111-1111-111111111111}",
            "snapshot": {str(i): "SECRET-LEFT" for i in range(100)},
        },
    }
    b = {
        "input_sha256": "b",
        "plan": {
            "fan": {"efficiency": 0.7},
            "handle": "{22222222-2222-2222-2222-222222222222}",
            "snapshot": {str(i): "SECRET-RIGHT" for i in range(100)},
        },
    }
    error = mismatch(a, b)
    report = failure_report(error)
    diagnostic = report["diagnostic"]
    found = {(x["path"], x["category"]) for x in diagnostic["differences"]}
    assert ("/input_sha256", "stale_source") in found
    assert ("/plan/fan/efficiency", "changed_value") in found
    assert ("/plan/handle", "handle_churn") in found
    assert diagnostic["truncated"] and len(diagnostic["differences"]) == 12
    assert "SECRET" not in json.dumps(report)
    assert len(json.dumps(report)) < 3000


@pytest.mark.parametrize("script", TRANSACTION_ENTRYPOINTS + ["vav_preflight.py"])
@pytest.mark.parametrize("mode", ["inventory", "preflight"])
def test_every_entrypoint_older_model_gate(sdk, tmp_path, script, mode):
    report = tmp_path / "report.json"
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"output_model_path": str(tmp_path / "unused.osm")}))
    command = [
        sys.executable,
        str(SCRIPTS / script),
        "--input",
        str((FIXTURES / "openstudio-1.13.4-example.osm").resolve()),
        "--report",
        str(report),
    ]
    if mode == "preflight":
        command += ["--config", str(config)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 2, result.stdout + result.stderr
    data = json.loads(report.read_text())
    assert data["status"] == "requires_preparation" and not data["ready"]
    assert data["source_version"] == "1.13.4" and data["target_version"] == "3.11.0"
    assert "plan" not in data and "candidates" not in data
    assert len(result.stdout) < 2500
    assert not (tmp_path / "unused.osm").exists()


from common.model_preparation import prepare, fields
from common import model_transaction as tx
from common import hvac_remove as removal


@pytest.mark.parametrize(
    "name,remaining",
    [
        ("openstudio-1.13.4-example.osm", 0),
        ("openstudio-legacy-multiloop.osm", 9),
    ],
)
def test_old_prepare_inventory_preflight_apply_exact_and_partial(
    sdk, tmp_path, name, remaining
):
    o = sdk[0]
    source = FIXTURES / name
    original = source.read_bytes()
    prepared = tmp_path / "prepared.osm"
    report = prepare(source.resolve(), prepared)
    assert (
        report["status"] == "prepared" and report["validation"]["all_raw_fields_stable"]
    )
    assert report["source_version"] != "3.11.0" and report["target_version"] == "3.11.0"
    assert (
        report["object_changes"]["added_by_type"][
            "OS_AvailabilityManagerAssignmentList"
        ]
        == remaining + 1
    )
    assert report["lineage"]["source"]["sha256"] == report["input_sha256"]
    assert (
        report["state_patch"]["model_preparation"][report["output_sha256"]]
        == report["lineage"]
    )
    first, _ = guard.load_model(o, prepared)
    second, _ = guard.load_model(o, prepared)
    assert fields(first) == fields(second)
    roots = removal.inventory(first)["air_loops"]
    configuration = dict(
        output_model_path=str(tmp_path / "removed.osm"),
        air_loops=[{"handle": roots[0]["handle"]}],
    )
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(configuration))
    plans = []
    for index in range(2):
        path = tmp_path / f"plan{index}.json"
        run = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "remove_hvac.py"),
                "--input",
                str(prepared),
                "--config",
                str(cfg),
                "--report",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert run.returncode == 0, run.stdout + run.stderr
        plans.append(json.loads(path.read_text()))
    assert plans[0] == plans[1]
    result = tx.apply(
        tmp_path / "plan0.json",
        "remove_hvac",
        removal.plan,
        removal.remove,
        removal.validate_model,
    )
    assert result["validation"]["ok"] and result["translation"]["ok"]
    saved, _ = guard.load_model(o, Path(result["output_model_path"]))
    assert len(saved.getAirLoopHVACs()) == remaining
    assert len(saved.getAvailabilityManagerAssignmentLists()) == remaining
    if remaining:
        before_lists = {
            str(x.handle()) for x in first.getAvailabilityManagerAssignmentLists()
        }
        after_lists = {
            str(x.handle()) for x in saved.getAvailabilityManagerAssignmentLists()
        }
        assert after_lists < before_lists and len(before_lists - after_lists) == 1
    assert source.read_bytes() == original
    unused = tmp_path / "no-new-copy.osm"
    again = prepare(prepared, unused)
    assert again["status"] == "already_current"
    assert again["output_sha256"] == report["output_sha256"]
    assert not unused.exists() and not unused.with_suffix("").exists()


def test_preparation_detects_same_handle_value_change_on_saved_reload(
    sdk, tmp_path, monkeypatch
):
    o = sdk[0]
    real = o.osversion.VersionTranslator.loadModel

    def load(translator, *args):
        result = real(translator, *args)
        if Path(str(args[0])).name == "prepared.osm":
            result.get().getBuilding().setName("Unexpected genuine change")
        return result

    monkeypatch.setattr(o.osversion.VersionTranslator, "loadModel", load)
    output = tmp_path / "output.osm"
    with pytest.raises(ValueError, match="raw object fields") as error:
        prepare((FIXTURES / "openstudio-1.13.4-example.osm").resolve(), output)
    assert error.value.details["status"] == "plan_mismatch"
    assert not output.exists() and not output.with_suffix("").exists()


@pytest.mark.parametrize("tampering", ["plan", "source"])
def test_prepared_tampered_and_stale_plans_reject(sdk, tmp_path, tampering):
    source = tmp_path / "prepared.osm"
    prepare((FIXTURES / "openstudio-1.13.4-example.osm").resolve(), source)
    model, _ = guard.load_model(sdk[0], source)
    cfg = dict(
        output_model_path=str(tmp_path / "removed.osm"),
        air_loops=[{"handle": str(model.getAirLoopHVACs()[0].handle())}],
    )
    reviewed = tx.preflight(source, cfg, "remove_hvac", removal.plan)
    if tampering == "plan":
        reviewed["plan"]["impact"]["removed_object_count"] += 1
    else:
        source.write_bytes(source.read_bytes() + b"\n! stale input\n")
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(reviewed))
    with pytest.raises(ValueError) as error:
        tx.apply(
            path, "remove_hvac", removal.plan, removal.remove, removal.validate_model
        )
    diagnostic = error.value.details["diagnostic"]
    assert diagnostic["differences"]
    assert diagnostic["differences"][0]["category"] == (
        "stale_source" if tampering == "source" else "changed_value"
    )
    assert not Path(cfg["output_model_path"]).exists()


def test_preparation_companions_resolve_from_original_and_move(
    sdk, tmp_path, monkeypatch
):
    import shutil
    from test_sdk_followup_regressions import measure, EPW
    from common.companions import external_file_status

    monkeypatch.chdir(tmp_path)
    o = sdk[0]
    original_dir = tmp_path / "original"
    original_dir.mkdir()
    source = current_model(o, original_dir)
    root = source.with_suffix("")
    (root / "files").mkdir(parents=True)
    shutil.copy(EPW, root / "files/weather.epw")
    csv = root / "files/schedule.csv"
    csv.write_text("value\n" + "0.5\n" * 8760)
    measure(o, root / "measures/example")
    (root / "workflow.osw").write_text(
        json.dumps(
            dict(weather_file="weather.epw", steps=[dict(measure_dir_name="example")])
        )
    )
    model, _ = guard.load_model(o, source)
    o.model.WeatherFile.setWeatherFile(
        model, o.EpwFile(str(root / "files/weather.epw"))
    )
    o.model.ScheduleFile(o.model.ExternalFile.getExternalFile(model, str(csv)).get())
    model.save(str(source), True)
    original = source.read_bytes()
    csv_bytes = csv.read_bytes()
    real = o.osversion.VersionTranslator.loadModel
    calls = 0

    def load(translator, *args):
        nonlocal calls
        result = real(translator, *args)
        calls += 1
        if calls == 2:
            o.model.ThermalZone(result.get())
        return result

    monkeypatch.setattr(o.osversion.VersionTranslator, "loadModel", load)
    out = tmp_path / "output/prepared.osm"
    report = prepare(source, out)
    assert report["status"] == "prepared" and report["source_version"] == "3.11.0"
    assert report["requires_companion_workflow"] and report["companion_readiness"]
    assert source.read_bytes() == original
    moved = tmp_path / "moved"
    moved.mkdir()
    shutil.move(str(out), moved / out.name)
    shutil.move(str(out.with_suffix("")), moved / out.stem)
    shutil.rmtree(original_dir)
    monkeypatch.chdir(moved)
    saved, _ = guard.load_model(o, moved / out.name)
    saved.workflowJSON().setOswPath(str(moved / out.stem / "workflow.osw"))
    assert external_file_status(saved)["ok"]
    assert Path(str(saved.getExternalFiles()[0].filePath())).read_bytes() == csv_bytes
    weather = Path(str(saved.getWeatherFile().path().get()))
    assert not weather.is_absolute() and weather.is_file()
    wf = o.WorkflowJSON(str(moved / out.stem / "workflow.osw"))
    assert wf.findMeasure("example").is_initialized()
    assert wf.findFile(wf.weatherFile().get()).is_initialized()


def test_native_preparation_skips_before_optional_schema_import(
    sdk, tmp_path, monkeypatch
):
    import builtins

    monkeypatch.setenv("OPENSTUDIO_SKILL_TEST_EXE", str(tmp_path / "no-cli"))
    real_import = builtins.__import__

    def without_jsonschema(name, *args, **kwargs):
        if name == "jsonschema":
            raise ModuleNotFoundError("Simulated sandbox without jsonschema")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_jsonschema)
    with pytest.raises(pytest.skip.Exception, match="Native 3.11.0 CLI unavailable"):
        test_native_cli_preparation_report_and_removal(sdk, tmp_path)


def test_native_cli_preparation_report_and_removal(sdk, tmp_path):
    import os

    cli = Path(
        os.environ.get(
            "OPENSTUDIO_SKILL_TEST_EXE",
            "/Applications/OpenStudio-3.11.0/bin/openstudio",
        )
    )
    if not cli.is_file():
        pytest.skip("Native 3.11.0 CLI unavailable")
    import jsonschema

    output = tmp_path / "native-prepared.osm"
    report_path = tmp_path / "preparation.json"
    run = subprocess.run(
        [
            str(cli),
            "execute_python_script",
            str(SCRIPTS / "prepare_model.py"),
            "--input",
            str((FIXTURES / "openstudio-legacy-multiloop.osm").resolve()),
            "--output",
            str(output),
            "--report",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    report = json.loads(report_path.read_text())
    jsonschema.validate(
        report,
        json.loads((SCRIPTS / "schemas/preparation_report.schema.json").read_text()),
    )
    assert report["validation"]["all_raw_fields_stable"]
    model, _ = guard.load_model(sdk[0], output)
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            dict(
                output_model_path=str(tmp_path / "removed.osm"),
                air_loops=[{"handle": str(model.getAirLoopHVACs()[0].handle())}],
            )
        )
    )
    plan = tmp_path / "plan.json"
    for args in [
        ["--input", str(output), "--config", str(config), "--report", str(plan)],
        ["--plan", str(plan), "--report", str(tmp_path / "apply.json")],
    ]:
        run = subprocess.run(
            [str(cli), "execute_python_script", str(SCRIPTS / "remove_hvac.py"), *args],
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads((tmp_path / "apply.json").read_text())["translation"]["ok"]


@pytest.mark.parametrize(
    "entrypoint",
    [
        "remove_hvac.py",
        "edit_supply_fan_performance.py",
        "edit_water_coil.py",
        "edit_ventilation.py",
        "vav_preflight.py",
    ],
)
def test_current_missing_list_entrypoints_write_bounded_failure(
    sdk, tmp_path, entrypoint
):
    source = current_model(sdk[0], tmp_path, loop=True)
    source.write_text(
        re.sub(
            r"(?ms)^OS:AvailabilityManagerAssignmentList\s*,.*?;",
            "",
            source.read_text(),
        )
    )
    report = tmp_path / "failure.json"
    run = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / entrypoint),
            "--input",
            str(source),
            "--report",
            str(report),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 2, run.stdout + run.stderr
    failure = json.loads(report.read_text())
    assert failure["status"] == "invalid_model" and not failure["ready"]
    assert "AvailabilityManagerAssignmentList" in failure["error"]
    assert len(report.read_bytes()) < 2000


def test_genuine_old_fixture_exhibits_native_handle_churn(sdk):
    source = FIXTURES / "openstudio-legacy-multiloop.osm"
    first, _ = guard.load_model(
        sdk[0], source, allow_preparation=True, check_stability=False
    )
    second, _ = guard.load_model(
        sdk[0], source, allow_preparation=True, check_stability=False
    )
    a, b = guard.object_types(first), guard.object_types(second)
    assert a.keys() != b.keys()
    from common.diagnostics import handle_changes

    counts = handle_changes(a, b)
    assert counts["added_by_type"]["OS_AvailabilityManagerAssignmentList"] == 10
    assert counts["removed_by_type"]["OS_AvailabilityManagerAssignmentList"] == 10


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_preparation_available_in_every_relocated_owning_bundle(sdk, tmp_path, host):
    import shutil
    import yaml
    from adapters.claude_code_adapter import ClaudeCodeAdapter
    from adapters.codex_adapter import CodexAdapter
    from adapters.contracts import HostAdapterConfig
    from harness.asset_manifest import MANIFEST_PATH

    adapter = (ClaudeCodeAdapter if host == "claude" else CodexAdapter)(
        HostAdapterConfig(
            host_name="claude_code" if host == "claude" else host,
            workspace_root=SCRIPTS.parents[1],
            runtime_mode="marketplace",
        )
    )
    result = adapter.export_plugin(tmp_path / "export", dry_run=False)
    moved = tmp_path / "moved-plugin"
    shutil.move(str(result.plugin_dir), moved)
    manifest = yaml.safe_load(MANIFEST_PATH.read_text())
    owners = next(
        x["owners"]
        for x in manifest["resources"]
        if x["source"].endswith("/version_guard.py")
    )
    assert len(owners) == 16
    for owner in owners:
        skill = moved / "skills" / owner["skill"]
        script = skill / "scripts/prepare_model.py"
        assert script.is_file()
        assert (skill / "references/preparation_report.schema.json").is_file()
        assert "requires_preparation" in (skill / "SKILL.md").read_text()
        run = subprocess.run(
            [sys.executable, "-I", "-S", str(script), "--help"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert run.returncode == 0, run.stderr
    script = moved / "skills/openstudio-hvac-remover/scripts/prepare_model.py"
    output = tmp_path / "prepared.osm"
    report = tmp_path / "preparation.json"
    run = subprocess.run(
        [
            sys.executable,
            "-I",
            str(script),
            "--input",
            str((FIXTURES / "openstudio-1.13.4-example.osm").resolve()),
            "--output",
            str(output),
            "--report",
            str(report),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(report.read_text())["status"] == "prepared"
