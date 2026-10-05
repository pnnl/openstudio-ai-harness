"""Behavioral regressions for the SDK script review, using real SDK where relevant."""

from __future__ import annotations
import copy
import errno
import json
from pathlib import Path
import subprocess
import sys
import pytest
from test_vav_preflight import sdk, model_file, config, catalog, modules, SCRIPTS
from test_vav_apply import apply_module, reviewed_plan


@pytest.mark.parametrize("field", ["supply_equipment", "supply_setpoint_managers"])
def test_empty_or_uncontrolled_plant_blocks_ready(
    modules, catalog, config, tmp_path, field
):
    catalog["plant_loops"][0][field] = []
    result = modules[1](config, catalog, tmp_path / "in.osm")
    assert not result["ready"] and any("plant_loop" in e for e in result["errors"])


@pytest.mark.parametrize(
    "temperature,value",
    [("zone_heating", 10), ("preheat", 20), ("precool", 5), ("zone_cooling", 5)],
)
def test_conflicting_air_temperatures_block_ready(
    modules, catalog, config, tmp_path, temperature, value
):
    config["design_temperatures_c"] = {temperature: value}
    result = modules[1](config, catalog, tmp_path / "in.osm")
    assert not result["ready"] and any(
        "design_temperatures" in e for e in result["errors"]
    )


def test_cold_hot_water_loop_blocks_reheat(modules, catalog, config, tmp_path):
    catalog["plant_loops"][0]["design_supply_temperature_c"] = 35
    result = modules[1](config, catalog, tmp_path / "in.osm")
    assert not result["ready"] and any(
        "hot-water return" in e for e in result["errors"]
    )


def test_nonexistent_drive_root_terminates(
    modules, catalog, config, tmp_path, monkeypatch
):
    import common.vav_plan as planning

    class Root:
        def exists(self):
            return False

        @property
        def parent(self):
            return self

    class Output:
        suffix = ".osm"
        parent = Root()

        def is_absolute(self):
            return True

        def is_symlink(self):
            return False

        def resolve(self):
            return self

        def exists(self):
            return False

        def __str__(self):
            return "Z:\\missing\\new.osm"

    monkeypatch.setattr(planning, "Path", lambda value: Output())
    result = planning.plan(config, catalog, tmp_path / "in.osm")
    assert not result["ready"] and any("drive/root" in e for e in result["errors"])


def test_plenum_owned_by_other_loop_blocks_preflight(sdk, model_file, config, tmp_path):
    o = sdk[0]
    model = o.osversion.VersionTranslator().loadModel(str(model_file)).get()
    plenum = o.model.ThermalZone(model)
    plenum.setName("Plenum")
    o.model.Space(model).setThermalZone(plenum)
    occupied = o.model.ThermalZone(model)
    o.model.Space(model).setThermalZone(occupied)
    loop = o.model.AirLoopHVAC(model)
    loop.multiAddBranchForZone(occupied)
    assert occupied.setReturnPlenum(plenum)
    assert model.save(str(model_file), True)
    config["return_plenum"] = {"name": "Plenum"}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    result = sdk[1].preflight(model_file, path)
    assert not result["ready"] and any("another loop" in e for e in result["errors"])
    assert not Path(config["output_model_path"]).exists()


def test_newer_model_has_actionable_error_before_mutation(sdk, model_file):
    content = model_file.read_text().replace("3.11.0;", "3.12.0;", 1)
    model_file.write_text(content)
    with pytest.raises(Exception, match="newer.*package"):
        sdk[1].preflight(model_file)
    assert model_file.read_text() == content


def test_controls_approve_build_validate_same_values(
    sdk, apply_module, model_file, config, tmp_path, monkeypatch
):
    from common.vav_plan import CONTROLS

    for key, value in {
        "fan_motor_in_airstream_fraction": 0.8,
        "fan_power_minimum_flow_fraction": 0.17,
        "fan_power_coefficients": [0.05, 0.10, -0.05, 0.88, 0.02],
        "night_cycle_runtime_seconds": 720,
        "electric_coil_efficiency": 0.91,
        "heating_water_controller_convergence": 0.2,
        "preheat_humidity_ratio": 0.007,
    }.items():
        monkeypatch.setitem(CONTROLS, key, value)
    path = reviewed_plan(sdk, model_file, config, tmp_path)
    planned = json.loads(path.read_text())["plan"]["controls"]
    result = apply_module.apply(path)
    assert result["validation"]["ok"]
    model = (
        sdk[0]
        .osversion.VersionTranslator()
        .loadModel(result["output_model_path"])
        .get()
    )
    fan = model.getFanVariableVolumes()[0]
    assert fan.fanPowerCoefficient5().get() == planned["fan_power_coefficients"][4]
    assert (
        fan.fanPowerMinimumFlowFraction() == planned["fan_power_minimum_flow_fraction"]
    )
    assert (
        model.getCoilHeatingElectrics()[0].efficiency()
        == planned["electric_coil_efficiency"]
    )
    assert (
        model.getAvailabilityManagerNightCycles()[0].cyclingRunTime()
        == planned["night_cycle_runtime_seconds"]
    )


def test_translation_errors_block_publication(
    sdk, apply_module, model_file, config, tmp_path, monkeypatch
):
    path = reviewed_plan(sdk, model_file, config, tmp_path)

    class Error:
        def logMessage(self):
            return "repro translation failure"

    class Workspace:
        def objects(self):
            return []

    class Translator:
        def translateModel(self, model):
            return Workspace()

        def errors(self):
            return [Error()]

        def warnings(self):
            return []

    monkeypatch.setattr(sdk[0].energyplus, "ForwardTranslator", Translator)
    with pytest.raises(RuntimeError, match="EnergyPlus translation failed"):
        apply_module.apply(path)
    assert not Path(config["output_model_path"]).exists()
    assert not Path(config["output_model_path"]).with_name("out_files").exists()


def test_history_patch_preserves_and_deduplicates():
    from blackboard.operations import apply_state_patch

    before = {"completed_steps": ["inspection"], "assumptions": ["earlier"]}
    patch = {"completed_steps": ["vav_creation"], "assumptions": ["new"]}
    merged = apply_state_patch(before, patch)
    assert merged["completed_steps"] == ["inspection", "vav_creation"]
    assert merged["assumptions"] == ["earlier", "new"]
    assert apply_state_patch(merged, patch)["assumptions"] == merged["assumptions"]
    assert before == {"completed_steps": ["inspection"], "assumptions": ["earlier"]}


def test_package_pin_matches_contract_and_lock():
    required = json.loads((SCRIPTS / "compatibility.json").read_text())[
        "required_openstudio_version"
    ]
    assert f'"openstudio=={required}"' in Path("pyproject.toml").read_text()
    assert (
        f'{{ name = "openstudio", specifier = "=={required}" }}'
        in Path("uv.lock").read_text()
    )


def test_copy_fallback_preserves_existing_output_and_reports_method(
    tmp_path, monkeypatch
):
    sys.path.insert(0, str(SCRIPTS))
    from common import files

    source = tmp_path / "staged"
    source.write_bytes(b"validated")

    def unavailable(*args):
        raise OSError(errno.EOPNOTSUPP, "hard links unavailable")

    monkeypatch.setattr(files.os, "link", unavailable)
    out = tmp_path / "output"
    assert (
        files.publish(source, out) == "exclusive_copy"
        and out.read_bytes() == b"validated"
    )
    with pytest.raises(FileExistsError):
        files.publish(source, out)
    assert out.read_bytes() == b"validated"


def test_failed_fallback_cleans_only_owned_partial(tmp_path, monkeypatch):
    from common import files

    source = tmp_path / "staged"
    source.write_bytes(b"validated")

    def unavailable(*args):
        raise OSError(errno.EOPNOTSUPP, "hard links unavailable")

    def fail(source, destination):
        destination.write(b"partial")
        raise OSError("copy failed")

    monkeypatch.setattr(files.os, "link", unavailable)
    monkeypatch.setattr(files.shutil, "copyfileobj", fail)
    out = tmp_path / "output"
    with pytest.raises(OSError, match="copy failed"):
        files.publish(source, out)
    assert not out.exists()


def test_large_inventory_summary_is_bounded_and_filterable():
    from report import summarize

    result = {
        "mode": "inspect_only",
        "ok": True,
        "ready": False,
        "candidates": {
            "schedules": [
                {"name": f"Operation {i}", "handle": str(i)} for i in range(10000)
            ]
        },
    }
    short = summarize(result, Path("/tmp/report.json"))
    assert (
        len(short["candidates"]["schedules"]) == 8
        and short["candidate_counts"]["schedules"] == 10000
    )
    assert short["candidates_truncated"] and len(json.dumps(short)) < 2000
    filtered = summarize(result, Path("/tmp/report.json"), "Operation 9999")
    assert filtered["candidates"]["schedules"] == [
        {"name": "Operation 9999", "handle": "9999"}
    ]


def test_direct_reports_do_not_depend_on_stdout_order(
    sdk, model_file, config, tmp_path
):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps(config))
    report = tmp_path / "ready.json"
    code = "import sys; sys.path.insert(0,sys.argv[1]); import vav_preflight; sys.argv=['vav_preflight','--input',sys.argv[2],'--config',sys.argv[3],'--report',sys.argv[4]]; exit_code=vav_preflight.main(); print('later SDK output'); raise SystemExit(exit_code)"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(SCRIPTS),
            str(model_file),
            str(cfg),
            str(report),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        result.stdout.endswith("later SDK output\n")
        and json.loads(report.read_text())["ready"]
    )


def test_contract_bump_metadata_has_no_fixed_sdk_release(
    sdk, apply_module, model_file, config, tmp_path, monkeypatch
):
    # Exercise contract plumbing with the installed binding; this does not certify a future SDK.
    import common.version_guard as guard

    contract = guard.load_contract()
    contract["required_openstudio_version"] = "3.12.0"
    monkeypatch.setattr(guard, "load_contract", lambda: contract)
    monkeypatch.setattr(apply_module, "load_contract", lambda: contract)
    monkeypatch.setattr(sdk[0], "openStudioVersion", lambda: "3.12.0+test")
    path = reviewed_plan(sdk, model_file, config, tmp_path)
    report = apply_module.apply(path)
    assert report["openstudio_version"] == "3.12.0+test" and report["validation"]["ok"]


def test_companion_measures_follow_output_and_source_change_blocks(
    sdk, apply_module, model_file, config, tmp_path
):
    companion = model_file.with_name(model_file.stem + "_files")
    measure = companion / "measures/example/measure.rb"
    measure.parent.mkdir(parents=True)
    measure.write_text("# reviewed measure resource\n")
    (companion / "workflow.osw").write_text(
        json.dumps(
            {"seed_file": "../in.osm", "measure_paths": ["measures"], "steps": []}
        )
    )
    path = reviewed_plan(sdk, model_file, config, tmp_path)
    measure.write_text("# changed after review\n")
    with pytest.raises(ValueError, match="differs"):
        apply_module.apply(path)
    assert not Path(config["output_model_path"]).exists()
    path.unlink()
    report = apply_module.apply(reviewed_plan(sdk, model_file, config, tmp_path))
    directory = Path(report["companion_directory"])
    assert (
        directory / "measures/0/example/measure.rb"
    ).read_text() == measure.read_text()
    workflow = json.loads((directory / "workflow.osw").read_text())
    assert workflow["seed_file"] == "../out.osm" and workflow["measure_paths"] == [
        "measures/0"
    ]


def test_missing_companion_weather_blocks_before_output(
    sdk, model_file, config, tmp_path
):
    companion = model_file.with_name(model_file.stem + "_files")
    companion.mkdir()
    (companion / "workflow.osw").write_text(
        json.dumps({"weather_file": "missing.epw", "steps": []})
    )
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config))
    report = sdk[1].preflight(model_file, cfg)
    assert not report["ready"] and any(
        "Missing companion" in x for x in report["errors"]
    )
    assert not Path(config["output_model_path"]).exists()


def test_existing_report_blocks_apply_before_model_write(
    sdk, model_file, config, tmp_path
):
    plan = reviewed_plan(sdk, model_file, config, tmp_path)
    report = tmp_path / "already.json"
    report.write_text("previous report")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "vav_apply.py"),
            "--plan",
            str(plan),
            "--report",
            str(report),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2 and report.read_text() == "previous report"
    assert not Path(config["output_model_path"]).exists()


def test_external_schedule_file_is_relocated(
    sdk, apply_module, model_file, config, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    o = sdk[0]
    model = o.osversion.VersionTranslator().loadModel(str(model_file)).get()
    csv = tmp_path / "schedule.csv"
    csv.write_text("value\n" + "0.5\n" * 8760)
    external = o.model.ExternalFile.getExternalFile(model, str(csv)).get()
    o.model.ScheduleFile(external)
    assert model.save(str(model_file), True)
    report = apply_module.apply(reviewed_plan(sdk, model_file, config, tmp_path))
    saved = o.osversion.VersionTranslator().loadModel(report["output_model_path"]).get()
    relocated = Path(str(saved.getExternalFiles()[0].filePath()))
    assert relocated.is_file() and relocated.read_bytes() == csv.read_bytes()
    assert relocated.is_relative_to(Path(report["companion_directory"]))
