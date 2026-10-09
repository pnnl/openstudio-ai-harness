"""Shared equipment reuse and independently validated CAV transactions."""

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import pytest
from test_vav_preflight import sdk, model_file, SCRIPTS
from vav_fixture import prepare_vav_fixture

sys.path.insert(0, str(SCRIPTS))
from common import cav_system as cav
from common import model_transaction as tx
from common.air_loop_validate import unwrap

OPERATION = "create_cav_system"


def config(tmp_path, cooling="DXTwoSpeed"):
    return dict(
        system_name="Test CAV",
        output_model_path=str(tmp_path / "cav.osm"),
        defaults_profile="prototype_cav_v1",
        outdoor_air_schedule={"builtin": "AlwaysOnDiscrete"},
        target_zones=[{"name": "Zone 1"}],
        central_heating={"type": "Water", "plant_loop": {"name": "HW"}},
        central_cooling=(
            {"type": "DXTwoSpeed", "dx_approved": True}
            if cooling == "DXTwoSpeed"
            else {"type": "Water", "plant_loop": {"name": "CHW"}}
        ),
        reheat={"type": "Water", "plant_loop": {"name": "HW"}},
    )


def preflight(source, cfg):
    return tx.preflight(source, cfg, OPERATION, cav.plan)


def apply(report, path):
    path.write_text(json.dumps(report))
    return tx.apply(path, OPERATION, cav.plan, cav.create, cav.validate_model)


@pytest.mark.parametrize("cooling", ["DXTwoSpeed", "Water"])
def test_saved_cav_connections_and_differences(sdk, model_file, tmp_path, cooling):
    from test_vav_preflight import prepare_existing_plant

    o = sdk[0]
    if cooling == "Water":
        model = o.model.Model.load(str(model_file)).get()
        loop = o.model.PlantLoop(model)
        loop.setName("CHW")
        loop.sizingPlant().setLoopType("Cooling")
        prepare_existing_plant(o, model, loop, False)
        model.save(str(model_file), True)
    cfg = config(tmp_path, cooling)
    cfg["fan"] = {"pressure_rise": 750, "pressure_units": "Pa"}
    before = model_file.read_bytes()
    report = preflight(model_file, cfg)
    assert report["ready"], report
    assert report == preflight(model_file, cfg)
    result = apply(report, tmp_path / "plan.json")
    assert result["validation"]["ok"] and result["translation"]["ok"], result
    assert model_file.read_bytes() == before
    model = o.model.Model.load(result["output_model_path"]).get()
    loop = model.getAirLoopHVACByName("Test CAV").get()
    assert len(model.getFanConstantVolumes()) == 1
    assert not model.getFanVariableVolumes()
    fan = model.getFanConstantVolumes()[0]
    assert fan.pressureRise() == 750
    assert loop.sizingSystem().centralHeatingMaximumSystemAirFlowRatio().get() == 1
    assert (
        loop.sizingSystem().centralHeatingDesignSupplyAirTemperature()
        == pytest.approx(16.6666666667)
    )
    terminal = model.getAirTerminalSingleDuctVAVReheats()[0]
    assert terminal.damperHeatingAction() == "ReverseWithLimits"
    assert unwrap(terminal.maximumReheatAirTemperature()) == 50
    assert unwrap(terminal.maximumFlowFractionDuringReheat()) == 0.5
    oa = model.getControllerOutdoorAirs()[0]
    assert oa.minimumFractionofOutdoorAirSchedule().is_initialized()
    assert not oa.minimumOutdoorAirSchedule().is_initialized()
    assert (
        loop.availabilityManagers()[0]
        .to_AvailabilityManagerNightCycle()
        .get()
        .cyclingRunTime()
        == 3600
    )
    with pytest.raises(ValueError):
        apply(report, tmp_path / "retry.json")


@pytest.mark.parametrize(
    "choice, all_oa", [(None, False), ({"builtin": "AlwaysOnDiscrete"}, True)]
)
def test_cav_explicit_outdoor_air_choice(sdk, model_file, tmp_path, choice, all_oa):
    cfg = config(tmp_path)
    cfg["outdoor_air_schedule"] = choice
    report = preflight(model_file, cfg)
    assert report["ready"], report
    planned = report["plan"]
    assert planned["controls"]["all_outdoor_air_cooling"] is all_oa
    assert planned["controls"]["all_outdoor_air_heating"] is all_oa
    row = next(
        r
        for r in planned["assumption_review"]["inputs"]
        if r["field"] == "outdoor_air_schedule"
    )
    assert ("100% outdoor air" in row["meaning"]) is all_oa
    result = apply(report, tmp_path / "plan.json")
    model = sdk[0].model.Model.load(result["output_model_path"]).get()
    sizing = model.getAirLoopHVACs()[0].sizingSystem()
    assert sizing.allOutdoorAirinHeating() is all_oa
    assert sizing.allOutdoorAirinCooling() is all_oa
    assert (
        model.getControllerOutdoorAirs()[0]
        .minimumFractionofOutdoorAirSchedule()
        .is_initialized()
        is all_oa
    )
    if all_oa:
        assert any("economizer" in w for w in planned["warnings"])


def test_cav_profile_cannot_choose_outdoor_air_for_user(sdk, model_file, tmp_path):
    cfg = config(tmp_path)
    del cfg["outdoor_air_schedule"]
    report = preflight(model_file, cfg)
    assert not report["ready"]
    assert any("outdoor_air_schedule" in x for x in report["plan"]["missing_inputs"])
    row = next(
        r
        for r in report["plan"]["assumption_review"]["inputs"]
        if r["field"] == "outdoor_air_schedule"
    )
    assert row["source"] == "requires_user_choice"
    with pytest.raises(ValueError, match="ready"):
        apply(report, tmp_path / "plan.json")


@pytest.mark.parametrize("fraction", [1.0, 0.4, 0.0])
def test_cav_named_fraction_schedule_sizing(sdk, model_file, tmp_path, fraction):
    model = sdk[0].model.Model.load(str(model_file)).get()
    schedule = sdk[0].model.ScheduleConstant(model)
    schedule.setName("OA Fraction")
    schedule.setValue(fraction)
    limits = sdk[0].model.ScheduleTypeLimits(model)
    limits.setUnitType("Dimensionless")
    limits.setLowerLimitValue(0)
    limits.setUpperLimitValue(1)
    schedule.setScheduleTypeLimits(limits)
    model.save(str(model_file), True)
    cfg = config(tmp_path)
    cfg["outdoor_air_schedule"] = {"name": "OA Fraction"}
    report = preflight(model_file, cfg)
    assert report["ready"], report
    assert report["plan"]["controls"]["all_outdoor_air_heating"] is (fraction > 0)
    assert report["plan"]["outdoor_air_policy"]["constant_minimum_fraction"] == fraction


def test_cav_variable_oa_schedule_exposes_conservative_sizing(
    sdk, model_file, tmp_path
):
    native = sdk[0]
    model = native.model.Model.load(str(model_file)).get()
    schedule = native.model.ScheduleRuleset(model)
    schedule.setName("Variable OA")
    schedule.defaultDaySchedule().addValue(native.Time(0, 12, 0, 0), 0.4)
    schedule.defaultDaySchedule().addValue(native.Time(0, 24, 0, 0), 0.8)
    limits = native.model.ScheduleTypeLimits(model)
    limits.setUnitType("Dimensionless")
    limits.setLowerLimitValue(0)
    limits.setUpperLimitValue(1)
    schedule.setScheduleTypeLimits(limits)
    model.save(str(model_file), True)
    cfg = config(tmp_path)
    cfg["outdoor_air_schedule"] = {"name": "Variable OA"}
    report = preflight(model_file, cfg)
    assert report["ready"], report
    assert report["plan"]["controls"]["all_outdoor_air_cooling"]
    assert report["plan"]["controls"]["all_outdoor_air_heating"]
    assert "conservatively" in report["plan"]["outdoor_air_policy"]["meaning"]
    assert any("conservatively" in w for w in report["plan"]["warnings"])
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(cfg))
    run = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "cav_system.py"),
            "--input",
            str(model_file),
            "--config",
            str(cfg_path),
            "--report",
            str(tmp_path / "cli-report.json"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    compact = next(
        json.loads(line) for line in run.stdout.splitlines() if line.startswith("{")
    )
    assert compact["outdoor_air_policy"] == report["plan"]["outdoor_air_policy"]


def test_cav_rejects_another_system_recipe(sdk, model_file, tmp_path):
    model = sdk[0].model.Model.load(str(model_file)).get()
    planned = cav.plan(model, sdk[0], config(tmp_path))
    planned["system_kind"] = "vav_reheat"
    with pytest.raises(ValueError, match="recipe"):
        cav.create(model, sdk[0], planned)
    assert not model.getAirLoopHVACs()


def test_cav_review_does_not_approve_defaults(sdk, model_file, tmp_path):
    cfg = config(tmp_path)
    del cfg["defaults_profile"]
    report = preflight(model_file, cfg)
    assert not report["ok"] and not report["ready"]
    assert report["plan"]["assumption_review"]["status"] == "needs_review"
    assert report["plan"]["controls"] == {}
    with pytest.raises(ValueError, match="ready"):
        apply(report, tmp_path / "plan.json")
    assert not Path(cfg["output_model_path"]).exists()


@pytest.mark.parametrize(
    "change", ["gas", "plenum", "ratio", "unapproved_dx", "empty_plant", "unknown"]
)
def test_cav_rejects_unsupported_or_incomplete_inputs(
    sdk, model_file, tmp_path, change
):
    cfg = config(tmp_path)
    if change == "gas":
        cfg["reheat"] = {"type": "NaturalGas"}
    elif change == "plenum":
        cfg["return_plenum"] = {"name": "Zone 1"}
    elif change == "ratio":
        cfg["minimum_system_airflow_ratio"] = 0.3
    elif change == "unapproved_dx":
        del cfg["central_cooling"]["dx_approved"]
    elif change == "empty_plant":
        cfg["central_heating"]["plant_loop"] = {"name": "missing"}
    else:
        cfg["unknown"] = 1
    if change in ("unapproved_dx", "empty_plant"):
        assert not preflight(model_file, cfg)["ready"]
    else:
        with pytest.raises(ValueError, match="Invalid CAV"):
            preflight(model_file, cfg)
    assert not Path(cfg["output_model_path"]).exists()


@pytest.mark.parametrize("change", ["stale", "controls", "operation"])
def test_cav_rejects_stale_or_tampered_plan(sdk, model_file, tmp_path, change):
    report = preflight(model_file, config(tmp_path))
    if change == "stale":
        model_file.write_bytes(model_file.read_bytes() + b"\n")
    elif change == "controls":
        report["plan"]["controls"]["damper_heating_action"] = "Normal"
    else:
        report["operation"] = "create_plant_loops"
    with pytest.raises(ValueError):
        apply(report, tmp_path / "plan.json")
    assert not (tmp_path / "cav.osm").exists()


def test_cav_wrong_accepted_setter_prevents_publication(
    sdk, model_file, tmp_path, monkeypatch
):
    report = preflight(model_file, config(tmp_path))
    monkeypatch.setattr(
        sdk[0].model.FanConstantVolume, "setPressureRise", lambda *args: True
    )
    with pytest.raises(ValueError, match="fan.pressureRise"):
        apply(report, tmp_path / "plan.json")
    assert not (tmp_path / "cav.osm").exists()
    assert not (tmp_path / "cav").exists()


@pytest.mark.parametrize("extra_fan", ["FanVariableVolume", "FanOnOff"])
def test_cav_rejects_extra_fan_before_publication(
    sdk, model_file, tmp_path, monkeypatch, extra_fan
):
    report = preflight(model_file, config(tmp_path))
    create = cav.create

    def wrong_create(model, native, planned):
        result = create(model, native, planned)
        getattr(native.model, extra_fan)(model)
        return result

    monkeypatch.setattr(cav, "create", wrong_create)
    with pytest.raises(ValueError, match="count delta.fan_"):
        apply(report, tmp_path / "plan.json")
    assert not (tmp_path / "cav.osm").exists()
    assert not (tmp_path / "cav").exists()


def test_cav_preserves_existing_other_fan_class(sdk, model_file, tmp_path):
    model = sdk[0].model.Model.load(str(model_file)).get()
    fan = sdk[0].model.FanVariableVolume(model)
    fan.setName("Existing Fan")
    model.save(str(model_file), True)
    result = apply(preflight(model_file, config(tmp_path)), tmp_path / "plan.json")
    assert result["validation"]["ok"]
    assert result["validation"]["counts"]["fan_VariableVolume"] == 1


def test_cav_validator_detects_wrong_schedule_field(sdk, model_file, tmp_path):
    model = sdk[0].model.Model.load(str(model_file)).get()
    planned = cav.plan(model, sdk[0], config(tmp_path))
    result = cav.create(model, sdk[0], planned)
    assert cav.validate_model(model, sdk[0], planned, result)["ok"]
    model.getControllerOutdoorAirs()[0].resetMinimumFractionofOutdoorAirSchedule()
    with pytest.raises(ValueError, match="optional"):
        cav.validate_model(model, sdk[0], planned, result)


@pytest.mark.parametrize("cooling", ["Water", "DXTwoSpeed"])
def test_native_cav_sizing(sdk, tmp_path, cooling):
    exe = Path(
        os.environ.get(
            "OPENSTUDIO_SKILL_TEST_EXE",
            "/Applications/OpenStudio-3.11.0/bin/openstudio",
        )
    )
    if not exe.is_file():
        pytest.skip("Native CLI required")
    source, base, _, _ = prepare_vav_fixture(sdk[0], tmp_path, True)
    cfg = dict(
        base,
        system_name="Sizing CAV",
        defaults_profile="prototype_cav_v1",
        output_model_path=str(tmp_path / "cav.osm"),
        outdoor_air_schedule={"builtin": "AlwaysOnDiscrete"},
    )
    if cooling == "DXTwoSpeed":
        cfg["central_cooling"] = {"type": cooling, "dx_approved": True}
    result = apply(preflight(source, cfg), tmp_path / "plan.json")
    workflow = Path(result["companion_directory"]) / "workflow.osw"
    run = subprocess.run(
        [str(exe), "run", "-w", str(workflow)],
        cwd=workflow.parent,
        capture_output=True,
        text=True,
        timeout=120,
    )
    (tmp_path / "cli.log").write_text(run.stdout + run.stderr)
    assert run.returncode == 0, run.stdout + run.stderr
    errors = (workflow.parent / "run/eplusout.err").read_text()
    assert "** Severe **" not in errors and "**  Fatal  **" not in errors, errors
    assert "EnergyPlus Completed Successfully" in errors
    with sqlite3.connect(workflow.parent / "run/eplusout.sql") as sql:
        rows = sql.execute(
            "SELECT CompType, Description, Value FROM ComponentSizes"
        ).fetchall()
        central = sql.execute(
            "SELECT Value FROM ComponentSizes WHERE CompType = 'Coil:Heating:Water' "
            "AND CompName = 'SIZING CAV MAIN HEATING COIL' "
            "AND Description = 'Design Size Rated Capacity'"
        ).fetchall()
        assert len(central) == 1 and central[0][0] > 0, central
    for kind, description in (("Fan:ConstantVolume", "Design Size Maximum Flow Rate"),):
        values = [v for k, d, v in rows if k == kind and d == description]
        assert values and all(v > 0 for v in values), rows
    reheat = [
        v
        for k, d, v in rows
        if k == "Coil:Heating:Water" and d == "Design Size Rated Capacity"
    ]
    assert len(reheat) == 6 and all(v > 0 for v in reheat), rows
    cooling_kind, cooling_description = (
        ("Coil:Cooling:Water", "Design Size Design Coil Load")
        if cooling == "Water"
        else (
            "Coil:Cooling:DX:TwoSpeed",
            "Design Size High Speed Gross Rated Total Cooling Capacity",
        )
    )
    capacities = [
        v for k, d, v in rows if k == cooling_kind and d == cooling_description
    ]
    assert len(capacities) == 1 and capacities[0] > 0, rows


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_cav_bundle_native_after_relocation(sdk, model_file, tmp_path, host):
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
        pytest.skip("Native CLI required")
    setup = HostAdapterConfig(
        host_name=host, workspace_root=Path.cwd(), runtime_mode="marketplace"
    )
    adapter = ClaudeCodeAdapter(setup) if host == "claude" else CodexAdapter(setup)
    export = tmp_path / "export"
    adapter.export_plugin(export, dry_run=False)
    skill = next(export.rglob("openstudio-cav-system-creator/SKILL.md")).parent
    moved = tmp_path / "relocated"
    shutil.copytree(skill, moved)
    shutil.rmtree(export)
    doctor = subprocess.run(
        [
            sys.executable,
            "-S",
            str(moved / "scripts/doctor.py"),
            "--openstudio",
            str(exe),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert doctor.returncode == 0, doctor.stdout + doctor.stderr
    verified = json.loads(doctor.stdout)["openstudio_executable"]
    cfg = config(tmp_path)
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(cfg))
    command = [verified, "execute_python_script", str(moved / "scripts/cav_system.py")]
    plan_path = tmp_path / "plan.json"
    inspected = subprocess.run(
        command
        + [
            "--input",
            str(model_file),
            "--config",
            str(cfg_path),
            "--report",
            str(plan_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert inspected.returncode == 0, inspected.stdout + inspected.stderr
    applied_path = tmp_path / "applied.json"
    applied = subprocess.run(
        command + ["--plan", str(plan_path), "--report", str(applied_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert applied.returncode == 0, applied.stdout + applied.stderr
    report = json.loads(applied_path.read_text())
    assert report["validation"]["ok"] and report["translation"]["ok"]
