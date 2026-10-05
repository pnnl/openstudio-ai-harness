from __future__ import annotations
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import os
import pytest
from test_vav_preflight import sdk, model_file, config, SCRIPTS, prepare_existing_plant


@pytest.fixture
def apply_module(sdk):
    spec = importlib.util.spec_from_file_location(
        "vav_apply_script", SCRIPTS / "vav_apply.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reviewed_plan(sdk, model_file, config, tmp_path):
    configuration = tmp_path / "config.json"
    configuration.write_text(json.dumps(config))
    report = sdk[1].preflight(model_file, configuration)
    assert report["ready"], report
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(report))
    return path


@pytest.mark.parametrize("heating", ["Water", "NaturalGas", "Electricity", "None"])
@pytest.mark.parametrize("cooling", ["Water", "DXTwoSpeed"])
@pytest.mark.parametrize("reheat", ["Water", "NaturalGas", "Electricity", "None"])
def test_supported_branches_validate_after_save(
    sdk, apply_module, model_file, config, tmp_path, heating, cooling, reheat
):
    o = sdk[0]
    model = o.osversion.VersionTranslator().loadModel(str(model_file)).get()
    hw = model.getPlantLoopByName("HW").get()
    hw.sizingPlant().setDesignLoopExitTemperature(82.222222)
    hw.sizingPlant().setLoopDesignTemperatureDifference(11.111111)
    chw = o.model.PlantLoop(model)
    chw.setName("CHW")
    chw.sizingPlant().setLoopType("Cooling")
    prepare_existing_plant(o, model, chw, False)
    model.save(str(model_file), True)
    for role, kind in (
        ("central_heating", heating),
        ("central_cooling", cooling),
        ("reheat", reheat),
    ):
        config[role] = {"type": kind}
        if kind == "Water":
            config[role]["plant_loop"] = {
                "name": "CHW" if role == "central_cooling" else "HW"
            }
        if kind == "DXTwoSpeed":
            config[role]["dx_approved"] = True
    before = model_file.read_bytes()
    plan_file = reviewed_plan(sdk, model_file, config, tmp_path)
    report = apply_module.apply(plan_file)
    assert report["ok"] and report["validation"]["ok"], report
    assert report["validation"]["checks"] >= 65
    assert report["created_object_count"] > len(report["changes"])
    assert all(x["type"] != "OS_Node" for x in report["changes"])
    output = Path(report["output_model_path"])
    assert report["output_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert model_file.read_bytes() == before
    assert not list(output.parent.glob(".vav-stage-*"))
    original_output = output.read_bytes()
    with pytest.raises(ValueError, match="no longer ready"):
        apply_module.apply(plan_file)
    assert output.read_bytes() == original_output


@pytest.mark.parametrize(
    "change",
    [
        "stale",
        "controls",
        "handles",
        "parameters",
        "version",
        "not_ready",
        "output",
        "invalid_config",
    ],
)
def test_reject_invalid_or_stale_plan_before_output(
    sdk, apply_module, model_file, config, tmp_path, change
):
    plan_file = reviewed_plan(sdk, model_file, config, tmp_path)
    report = json.loads(plan_file.read_text())
    if change == "stale":
        model_file.write_bytes(model_file.read_bytes() + b"\n")
    elif change == "controls":
        report["plan"]["controls"]["night_cycle_runtime_seconds"] = 1
    elif change == "handles":
        report["plan"]["resolved_objects"]["target_zones"][0]["handle"] = "bad"
    elif change == "parameters":
        report["plan"]["parameters"]["fan"]["pressure_rise_pa"] = 1
    elif change == "version":
        report["plan_version"] = 1
    elif change == "not_ready":
        report["ready"] = False
    elif change == "output":
        report["output_model_path"] = str(tmp_path / "wrong.osm")
    elif change == "invalid_config":
        report["configuration"]["typo"] = True
    plan_file.write_text(json.dumps(report))
    with pytest.raises(ValueError):
        apply_module.apply(plan_file)
    assert not Path(config["output_model_path"]).exists()


def test_setter_failure_blocks_output(
    sdk, apply_module, model_file, config, tmp_path, monkeypatch
):
    plan_file = reviewed_plan(sdk, model_file, config, tmp_path)
    monkeypatch.setattr(
        sdk[0].model.FanVariableVolume, "setPressureRise", lambda *args: False
    )
    with pytest.raises(RuntimeError, match="SDK rejected"):
        apply_module.apply(plan_file)
    assert not Path(config["output_model_path"]).exists()


def test_independent_validator_catches_accepted_but_wrong_setter(
    sdk, apply_module, model_file, config, tmp_path, monkeypatch
):
    plan_file = reviewed_plan(sdk, model_file, config, tmp_path)
    monkeypatch.setattr(
        sdk[0].model.FanVariableVolume, "setPressureRise", lambda *args: True
    )
    with pytest.raises(RuntimeError, match="fan.pressureRise"):
        apply_module.apply(plan_file)
    assert not Path(config["output_model_path"]).exists()
    assert not list(tmp_path.glob(".vav-stage-*"))


def test_publish_race_cannot_overwrite_existing_file(
    sdk, apply_module, model_file, config, tmp_path, monkeypatch
):
    plan_file = reviewed_plan(sdk, model_file, config, tmp_path)
    real_link = apply_module.os.link

    def racing_link(source, target):
        Path(target).write_bytes(b"another writer")
        return real_link(source, target)

    monkeypatch.setattr(apply_module.os, "link", racing_link)
    with pytest.raises(FileExistsError):
        apply_module.apply(plan_file)
    assert Path(config["output_model_path"]).read_bytes() == b"another writer"
    assert not list(tmp_path.glob(".vav-stage-*"))


def test_wrong_sdk_blocks_before_plan_read(sdk, apply_module, tmp_path, monkeypatch):
    monkeypatch.setattr(sdk[0], "openStudioVersion", lambda: "3.10.0")
    with pytest.raises(RuntimeError, match="executing SDK"):
        apply_module.apply(tmp_path / "absent.json")


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_native_export_apply(sdk, model_file, config, tmp_path, host):
    from adapters.claude_code_adapter import ClaudeCodeAdapter
    from adapters.codex_adapter import CodexAdapter
    from adapters.contracts import HostAdapterConfig

    exe = Path(
        os.environ.get(
            "OPENSTUDIO_SKILL_TEST_EXE",
            "/Applications/OpenStudio-3.11.0/bin/openstudio",
        )
    )
    if not exe.is_file():
        pytest.skip("Native CLI unavailable")
    adapter = ClaudeCodeAdapter if host == "claude" else CodexAdapter
    exported = adapter(
        HostAdapterConfig(
            host_name="claude_code" if host == "claude" else host,
            workspace_root=Path.cwd(),
            runtime_mode="marketplace",
        )
    ).export_plugin(tmp_path / "export", dry_run=False)
    skill = exported.plugin_dir / "skills/openstudio-vav-reheat-system-creator"
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config))
    command = [str(exe), "execute_python_script"]
    preflight = subprocess.run(
        command
        + [
            str(skill / "scripts/vav_preflight.py"),
            "--input",
            str(model_file),
            "--config",
            str(config_file),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert preflight.returncode == 0, preflight.stdout + preflight.stderr
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(preflight.stdout.splitlines()[-1])
    completed = subprocess.run(
        command + [str(skill / "scripts/vav_apply.py"), "--plan", str(plan_file)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(completed.stdout.splitlines()[-1])
    assert report["validation"]["ok"]


def test_multiple_zones_schedules_and_return_plenum(
    sdk, apply_module, model_file, config, tmp_path
):
    o = sdk[0]
    model = o.osversion.VersionTranslator().loadModel(str(model_file)).get()
    zone2 = o.model.ThermalZone(model)
    zone2.setName("Zone 2")
    o.model.Space(model).setThermalZone(zone2)
    zone2.setThermostatSetpointDualSetpoint(
        model.getThermalZoneByName("Zone 1")
        .get()
        .thermostatSetpointDualSetpoint()
        .get()
    )
    plenum_zone = o.model.ThermalZone(model)
    plenum_zone.setName("Return Plenum")
    o.model.Space(model).setThermalZone(plenum_zone)
    assert not plenum_zone.isPlenum() and plenum_zone.canBePlenum()
    operation = o.model.ScheduleConstant(model)
    operation.setName("Operation")
    operation.setValue(0.75)
    limits = o.model.ScheduleTypeLimits(model)
    limits.setUnitType("Dimensionless")
    limits.setLowerLimitValue(0.0)
    limits.setUpperLimitValue(1.0)
    operation.setScheduleTypeLimits(limits)
    assert model.save(str(model_file), True)
    config.update(
        target_zones=[{"name": "Zone 1"}, {"name": "Zone 2"}],
        return_plenum={"name": "Return Plenum"},
        availability_schedule={"name": "Operation"},
        outdoor_air_schedule={"name": "Operation"},
        sizing_option="NonCoincident",
        economizer="DifferentialDryBulb",
        minimum_terminal_airflow_fraction=0.2,
    )
    report = apply_module.apply(reviewed_plan(sdk, model_file, config, tmp_path))
    assert report["validation"]["ok"] and report["counts"]["terminals"] == 2


def test_no_reheat_preserves_existing_zone_heating_sizing(
    sdk, apply_module, model_file, config, tmp_path
):
    o = sdk[0]
    model = o.osversion.VersionTranslator().loadModel(str(model_file)).get()
    zs = model.getThermalZoneByName("Zone 1").get().sizingZone()
    assert zs.setHeatingDesignAirFlowMethod("Flow/Zone")
    assert zs.setZoneHeatingDesignSupplyAirTemperature(35.0)
    assert model.save(str(model_file), True)
    config["reheat"] = {"type": "None"}
    report = apply_module.apply(reviewed_plan(sdk, model_file, config, tmp_path))
    saved = o.osversion.VersionTranslator().loadModel(report["output_model_path"]).get()
    zs = saved.getThermalZoneByName("Zone 1").get().sizingZone()
    assert zs.heatingDesignAirFlowMethod() == "Flow/Zone"
    assert zs.zoneHeatingDesignSupplyAirTemperature() == 35.0


def test_input_change_during_creation_blocks_publication(
    sdk, apply_module, model_file, config, tmp_path, monkeypatch
):
    plan_file = reviewed_plan(sdk, model_file, config, tmp_path)
    original_create = apply_module.create

    def changing_create(*args):
        result = original_create(*args)
        model_file.write_bytes(model_file.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(apply_module, "create", changing_create)
    with pytest.raises(ValueError, match="changed during creation"):
        apply_module.apply(plan_file)
    assert not Path(config["output_model_path"]).exists()
    assert not list(tmp_path.glob(".vav-stage-*"))


def test_saved_topology_disconnect_blocks_publication(
    sdk, apply_module, model_file, config, tmp_path, monkeypatch
):
    plan_file = reviewed_plan(sdk, model_file, config, tmp_path)
    original_create = apply_module.create

    def disconnecting_create(model, os_sdk, planned):
        result = original_create(model, os_sdk, planned)
        loop = model.getAirLoopHVAC(os_sdk.toUUID(result)).get()
        zone = model.getThermalZoneByName("Zone 1").get()
        assert loop.removeBranchForZone(zone)
        return result

    monkeypatch.setattr(apply_module, "create", disconnecting_create)
    with pytest.raises(RuntimeError, match="served zones"):
        apply_module.apply(plan_file)
    assert not Path(config["output_model_path"]).exists()


def test_release_build_metadata_is_accepted(
    sdk, apply_module, model_file, config, tmp_path
):
    plan_file = reviewed_plan(sdk, model_file, config, tmp_path)
    report = json.loads(plan_file.read_text())
    report["openstudio_version"] = "3.11.0+241b8abb4d"
    plan_file.write_text(json.dumps(report))
    assert apply_module.apply(plan_file)["ok"]
