"""Plant construction and selective HVAC replacement through reviewed bundles."""

import json
from pathlib import Path
import subprocess
import sys
import pytest
from test_vav_preflight import sdk

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/sdk_scripts"
sys.path.insert(0, str(SCRIPTS))
from common import model_transaction as tx
from common import plant_create as plants
from common import hvac_remove as removal


def source_model(o, tmp_path):
    source = tmp_path / "input.osm"
    o.model.Model().save(str(source), True)
    return source


def config(tmp_path, heating="NaturalGas", cooling="AirCooled", pumping="const_pri"):
    return dict(
        output_model_path=str(tmp_path / "plants.osm"),
        defaults_profile="prototype_plants_v1",
        hot_water=dict(name="New HW", source=heating),
        chilled_water=dict(name="New CHW", source=cooling, pumping=pumping),
    )


def execute(source, cfg, tmp_path, operation, planner, creator, validator):
    report = tx.preflight(source, cfg, operation, planner)
    planfile = tmp_path / "plan.json"
    planfile.write_text(json.dumps(report))
    return report, tx.apply(planfile, operation, planner, creator, validator)


@pytest.mark.parametrize(
    "heating", ["NaturalGas", "Electricity", "DistrictHeatingWater"]
)
@pytest.mark.parametrize("cooling", ["AirCooled", "WaterCooled", "DistrictCooling"])
def test_plant_saved_settings_and_connections(sdk, tmp_path, heating, cooling):
    o = sdk[0]
    src = source_model(o, tmp_path)
    original = src.read_bytes()
    report, result = execute(
        src,
        config(tmp_path, heating, cooling),
        tmp_path,
        "create_plant_loops",
        plants.plan,
        plants.create,
        plants.validate_model,
    )
    assert result["validation"]["ok"] and result["translation"]["ok"]
    assert src.read_bytes() == original
    model = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    assert len(model.getPlantLoops()) == (3 if cooling == "WaterCooled" else 2)
    cfg = dict(
        system_name="Hydronic VAV",
        output_model_path=str(tmp_path / "vav.osm"),
        target_zones=[{"name": "Zone"}],
        defaults_profile="prototype_vav_v1",
        central_heating={"type": "Water", "plant_loop": {"name": "New HW"}},
        central_cooling={"type": "Water", "plant_loop": {"name": "New CHW"}},
        reheat={"type": "Water", "plant_loop": {"name": "New HW"}},
    )
    # Demonstrate the new plants meet the existing VAV readiness contract.
    zone = o.model.ThermalZone(model)
    zone.setName("Zone")
    o.model.Space(model).setThermalZone(zone)
    thermostat = o.model.ThermostatSetpointDualSetpoint(model)
    for key, temp in [("Heating", 21), ("Cooling", 24)]:
        schedule = o.model.ScheduleConstant(model)
        schedule.setValue(temp)
        getattr(thermostat, "set" + key + "SetpointTemperatureSchedule")(schedule)
    zone.setThermostatSetpointDualSetpoint(thermostat)
    from common.vav_inventory import inventory
    from common.vav_plan import plan

    assert plan(cfg, inventory(model), Path(result["output_model_path"]))["ready"]


def test_primary_secondary_pumps_and_validation_failure(sdk, tmp_path):
    o = sdk[0]
    cfg = config(tmp_path, pumping="const_pri_var_sec")
    m = o.model.Model()
    p = plants.plan(m, o, cfg)
    r = plants.create(m, o, p)
    assert plants.validate_model(m, o, p, r)["ok"]
    pump = m.getPumpVariableSpeed(o.toUUID(r[1]["pumps"][1])).get()
    pump.setRatedPumpHead(1)
    assert not plants.validate_model(m, o, p, r)["ok"]


def test_plant_rejects_implicit_fuel_duplicates_and_bad_values(sdk, tmp_path):
    o = sdk[0]
    cfg = config(tmp_path)
    m = o.model.Model()
    for change in (
        {"defaults_profile": None},
        {"hot_water": {"name": "HW"}},
        {
            "hot_water": {
                "name": "HW",
                "source": "NaturalGas",
                "delta_temperature_k": False,
            }
        },
        {"chilled_water": {"name": "CHW", "source": "AirCooled", "num_chillers": 1.5}},
    ):
        with pytest.raises(ValueError):
            plants.plan(m, o, dict(cfg, **change))
    existing = o.model.PlantLoop(m)
    existing.setName("New HW")
    with pytest.raises(ValueError, match="name"):
        plants.plan(m, o, cfg)


def removal_fixture(o, tmp_path):
    m = o.model.Model()
    zones = []
    for name in ("Office", "Other Office", "Stair"):
        z = o.model.ThermalZone(m)
        z.setName(name)
        space = o.model.Space(m)
        space.setThermalZone(z)
        zones.append(z)
    vrf = o.model.AirConditionerVariableRefrigerantFlow(m)
    vrf.setName("Office VRF")
    for z in zones[:2]:
        terminal = o.model.ZoneHVACTerminalUnitVariableRefrigerantFlow(m)
        terminal.addToThermalZone(z)
        vrf.addTerminal(terminal)
    oa = o.model.AirLoopHVAC(m)
    oa.setName("Office OA")
    fan = o.model.FanConstantVolume(m)
    fan.addToNode(oa.supplyInletNode())
    for z in zones[:2]:
        oa.addBranchForZone(
            z,
            o.model.AirTerminalSingleDuctConstantVolumeNoReheat(
                m, m.alwaysOnDiscreteSchedule()
            ),
        )
    stair = o.model.ZoneHVACUnitHeater(
        m,
        m.alwaysOnDiscreteSchedule(),
        o.model.FanConstantVolume(m),
        o.model.CoilHeatingElectric(m),
    )
    stair.setName("Stair Heater")
    stair.addToThermalZone(zones[2])
    existing = o.model.PlantLoop(m)
    existing.setName("Keep HW")
    src = tmp_path / "input.osm"
    m.save(str(src), True)
    return src


def test_selective_vrf_oa_removal_preserves_stair_plants_and_inputs(sdk, tmp_path):
    o = sdk[0]
    src = removal_fixture(o, tmp_path)
    original = src.read_bytes()
    cfg = dict(
        output_model_path=str(tmp_path / "removed.osm"),
        air_loops=[{"name": "Office OA"}],
        vrf_systems=[{"name": "Office VRF"}],
    )
    report, result = execute(
        src,
        cfg,
        tmp_path,
        "remove_hvac",
        removal.plan,
        removal.remove,
        removal.validate_model,
    )
    assert result["validation"]["ok"] and src.read_bytes() == original
    assert {z["name"] for z in report["plan"]["impact"]["affected_zones"]} == {
        "Office",
        "Other Office",
    }
    m = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    assert not m.getAirLoopHVACs() and not m.getAirConditionerVariableRefrigerantFlows()
    assert not m.getZoneHVACTerminalUnitVariableRefrigerantFlows()
    assert len(m.getPlantLoops()) == 1 and len(m.getZoneHVACUnitHeaters()) == 1
    assert not m.getThermalZoneByName("Office").get().equipment()


def test_zone_equipment_only_and_invalid_selectors(sdk, tmp_path):
    o = sdk[0]
    src = removal_fixture(o, tmp_path)
    m = o.osversion.VersionTranslator().loadModel(str(src)).get()
    cfg = dict(
        output_model_path=str(tmp_path / "removed.osm"),
        zone_equipment=[{"name": "Stair Heater"}],
    )
    p = removal.plan(m, o, cfg)
    r = removal.remove(m, o, p)
    assert removal.validate_model(m, o, p, r)["ok"]
    assert (
        len(m.getAirLoopHVACs()) == 1
        and len(m.getAirConditionerVariableRefrigerantFlows()) == 1
    )
    with pytest.raises(ValueError):
        removal.plan(m, o, dict(output_model_path=str(tmp_path / "x.osm")))
    with pytest.raises(ValueError):
        removal.plan(m, o, dict(cfg, plant_loops=[{"name": "Keep HW"}]))
    with pytest.raises(ValueError):
        removal.plan(m, o, dict(cfg, zone_equipment=[{"name": "missing"}]))


def test_stale_tampered_plan_and_existing_output(sdk, tmp_path):
    src = source_model(sdk[0], tmp_path)
    cfg = config(tmp_path)
    report = tx.preflight(src, cfg, "create_plant_loops", plants.plan)
    path = tmp_path / "plan.json"
    report["plan"]["parameters"]["plants"][0]["equipment"][
        "NominalThermalEfficiency"
    ] = 0.1
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="differs"):
        tx.apply(
            path,
            "create_plant_loops",
            plants.plan,
            plants.create,
            plants.validate_model,
        )
    report = tx.preflight(src, cfg, "create_plant_loops", plants.plan)
    path.write_text(json.dumps(report))
    src.write_bytes(src.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="Stale"):
        tx.apply(
            path,
            "create_plant_loops",
            plants.plan,
            plants.create,
            plants.validate_model,
        )
    Path(cfg["output_model_path"]).write_text("winner")
    with pytest.raises(ValueError, match="already exists"):
        tx.preflight(src, cfg, "create_plant_loops", plants.plan)
    assert Path(cfg["output_model_path"]).read_text() == "winner"


@pytest.mark.parametrize(
    "cooling,pumping",
    [
        ("AirCooled", "const_pri"),
        ("WaterCooled", "const_pri_var_sec"),
        ("DistrictCooling", "const_pri"),
    ],
)
def test_native_new_plants_then_vav_sizing(sdk, tmp_path, cooling, pumping):
    import os
    from vav_fixture import prepare_vav_fixture
    from common.vav_create import create as create_vav
    from common.vav_inventory import inventory
    from common.vav_plan import plan as plan_vav

    exe = Path(
        os.environ.get(
            "OPENSTUDIO_SKILL_TEST_EXE",
            "/Applications/OpenStudio-3.11.0/bin/openstudio",
        )
    )
    if not exe.is_file():
        pytest.skip("Native CLI required")
    o = sdk[0]
    src, vav_cfg, _, _ = prepare_vav_fixture(o, tmp_path, False)
    cfg = config(tmp_path, cooling=cooling, pumping=pumping)
    _, result = execute(
        src,
        cfg,
        tmp_path,
        "create_plant_loops",
        plants.plan,
        plants.create,
        plants.validate_model,
    )
    model = o.model.Model.load(result["output_model_path"]).get()
    for role, name in [
        ("central_heating", "New HW"),
        ("central_cooling", "New CHW"),
        ("reheat", "New HW"),
    ]:
        vav_cfg[role] = {"type": "Water", "plant_loop": {"name": name}}
    vav_cfg["output_model_path"] = str(tmp_path / "vav.osm")
    planned = plan_vav(vav_cfg, inventory(model), Path(result["output_model_path"]))
    assert planned["ready"], planned["errors"]
    create_vav(model, o, planned)
    # Save beside the plant companion resources with its workflow retained.
    model.save(result["output_model_path"], True)
    workflow = Path(result["companion_directory"]) / "workflow.osw"
    completed = subprocess.run(
        [str(exe), "run", "-w", str(workflow)],
        cwd=workflow.parent,
        capture_output=True,
        text=True,
        timeout=120,
    )
    (tmp_path / "cli.log").write_text(completed.stdout + completed.stderr)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    errors = (workflow.parent / "run/eplusout.err").read_text()
    assert "** Severe **" not in errors and "**  Fatal  **" not in errors, errors
    assert "EnergyPlus Completed Successfully" in errors
    import sqlite3

    with sqlite3.connect(workflow.parent / "run/eplusout.sql") as connection:
        sizing = connection.execute(
            "SELECT CompType, Description, Value FROM ComponentSizes"
        ).fetchall()

    def sized(kind, description):
        values = [v for t, d, v in sizing if t == kind and d == description]
        assert len(values) == 1 and values[0] > 0, sizing

    sized("Boiler:HotWater", "Design Size Nominal Capacity")
    sized("Fan:VariableVolume", "Design Size Maximum Flow Rate")
    if cooling == "DistrictCooling":
        sized("DistrictCooling", "Design Size Nominal Capacity")
    else:
        sized("Chiller:Electric:EIR", "Design Size Reference Capacity")
    if cooling == "WaterCooled":
        sized("CoolingTower:VariableSpeed", "Nominal Capacity")


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_new_skill_exports_run_relocated_without_runtime(sdk, tmp_path, host):
    import shutil
    from adapters.claude_code_adapter import ClaudeCodeAdapter
    from adapters.codex_adapter import CodexAdapter
    from adapters.contracts import HostAdapterConfig

    exe = Path("/Applications/OpenStudio-3.11.0/bin/openstudio")
    if not exe.is_file():
        pytest.skip("Native CLI required")
    root = Path(__file__).resolve().parents[1]
    cfg = HostAdapterConfig(
        host_name=host, workspace_root=root, runtime_mode="marketplace"
    )
    adapter = ClaudeCodeAdapter(cfg) if host == "claude" else CodexAdapter(cfg)
    exported = tmp_path / "export"
    adapter.export_plugin(exported, dry_run=False)
    for skill, script in [
        ("openstudio-plant-loop-creator", "plant_loops.py"),
        ("openstudio-hvac-remover", "remove_hvac.py"),
    ]:
        original = next(exported.rglob(skill + "/SKILL.md")).parent
        bundle = tmp_path / skill
        shutil.copytree(original, bundle)
    shutil.rmtree(exported)
    src = removal_fixture(sdk[0], tmp_path)
    for skill, script, params in [
        ("openstudio-plant-loop-creator", "plant_loops.py", config(tmp_path)),
        (
            "openstudio-hvac-remover",
            "remove_hvac.py",
            {
                "output_model_path": str(tmp_path / "removed.osm"),
                "air_loops": [{"name": "Office OA"}],
                "vrf_systems": [{"name": "Office VRF"}],
            },
        ),
    ]:
        bundle = tmp_path / skill
        cfgfile = tmp_path / (skill + ".json")
        cfgfile.write_text(json.dumps(params))
        doctor = subprocess.run(
            [
                sys.executable,
                "-S",
                str(bundle / "scripts/doctor.py"),
                "--openstudio",
                str(exe),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert doctor.returncode == 0, doctor.stdout + doctor.stderr
        report = tmp_path / (skill + "-plan.json")
        applied = tmp_path / (skill + "-apply.json")
        for arguments in (
            ["--input", str(src), "--config", str(cfgfile), "--report", str(report)],
            ["--plan", str(report), "--report", str(applied)],
        ):
            completed = subprocess.run(
                [
                    str(exe),
                    "execute_python_script",
                    str(bundle / "scripts" / script),
                    *arguments,
                ],
                cwd=tmp_path,
                capture_output=True,
                text=True,
                timeout=120,
            )
            assert completed.returncode == 0, completed.stdout + completed.stderr
        result = json.loads(applied.read_text())
        assert result["validation"]["ok"] and result["translation"]["ok"]


def test_failed_translation_and_changed_source_publish_nothing(
    sdk, tmp_path, monkeypatch
):
    o = sdk[0]
    src = source_model(o, tmp_path)
    cfg = config(tmp_path)
    report = tx.preflight(src, cfg, "create_plant_loops", plants.plan)
    file = tmp_path / "plan.json"
    file.write_text(json.dumps(report))
    original = plants.create

    def changed_source(model, sdk, planned):
        result = original(model, sdk, planned)
        src.write_bytes(src.read_bytes() + b"\n")
        return result

    with pytest.raises(ValueError, match="Input changed"):
        tx.apply(
            file,
            "create_plant_loops",
            plants.plan,
            changed_source,
            plants.validate_model,
        )
    assert (
        not Path(cfg["output_model_path"]).exists()
        and not Path(cfg["output_model_path"]).with_suffix("").exists()
    )
    report = tx.preflight(src, cfg, "create_plant_loops", plants.plan)
    file.write_text(json.dumps(report))

    class Error:
        def logMessage(self):
            return "forced translation error"

    class Translator:
        def translateModel(self, model):
            pass

        def errors(self):
            return [Error()]

        def warnings(self):
            return []

    monkeypatch.setattr(o.energyplus, "ForwardTranslator", Translator)
    with pytest.raises(ValueError, match="EnergyPlus translation failed"):
        tx.apply(
            file,
            "create_plant_loops",
            plants.plan,
            plants.create,
            plants.validate_model,
        )
    assert (
        not Path(cfg["output_model_path"]).exists()
        and not Path(cfg["output_model_path"]).with_suffix("").exists()
    )


def test_sdk_guard_runs_before_user_file_reads(tmp_path, monkeypatch):
    from common.version_guard import CompatibilityError

    def incompatible():
        raise CompatibilityError("wrong SDK")

    monkeypatch.setattr(tx, "require_sdk", incompatible)
    with pytest.raises(CompatibilityError, match="wrong SDK"):
        tx.apply(
            tmp_path / "nonexistent.json",
            "create_plant_loops",
            plants.plan,
            plants.create,
            plants.validate_model,
        )


def test_removal_validator_rejects_unselected_equipment_changes(sdk, tmp_path):
    o = sdk[0]
    src = removal_fixture(o, tmp_path)
    m = o.osversion.VersionTranslator().loadModel(str(src)).get()
    p = removal.plan(
        m,
        o,
        dict(
            output_model_path=str(tmp_path / "removed.osm"),
            air_loops=[{"name": "Office OA"}],
            vrf_systems=[{"name": "Office VRF"}],
        ),
    )
    r = removal.remove(m, o, p)
    m.getZoneHVACUnitHeaters()[0].remove()
    assert not removal.validate_model(m, o, p, r)["ok"]
