"""Hot-water boiler performance edits preserve equipment and plant identities."""

import json
from pathlib import Path
import sys

import pytest
from test_vav_preflight import sdk, SCRIPTS

sys.path.insert(0, str(SCRIPTS))
from common import boiler_edit as boilers, plant_create, model_transaction as tx

OPERATION = "edit_boiler_performance"


def fixture(o, folder, fuel="NaturalGas", curve=False):
    model = o.model.Model()
    planned = plant_create.plan(
        model,
        o,
        dict(
            output_model_path=str(folder / "unused.osm"),
            defaults_profile="prototype_plants_v1",
            hot_water=dict(name="HW", source="NaturalGas"),
        ),
    )
    plant_create.create(model, o, planned)
    boiler = model.getBoilerHotWaters()[0]
    boiler.setName("Selected Boiler")
    assert boiler.setFuelType(fuel)
    boiler.setNominalThermalEfficiency(0.8)
    boiler.additionalProperties().setFeature("review_note", "retain")
    if curve:
        performance = o.model.CurveQuadratic(model)
        performance.setCoefficient1Constant(0.85)
        performance.setCoefficient2x(0.15)
        performance.setCoefficient3xPOW2(0)
        performance.setMinimumValueofx(0)
        performance.setMaximumValueofx(1.2)
        assert boiler.setNormalizedBoilerEfficiencyCurve(performance)
    source = folder / "before.osm"
    assert model.save(str(source), True)
    return source, model, boiler


def config(folder, **settings):
    return dict(
        output_model_path=str(folder / "edited.osm"),
        plant_loop={"name": "HW"},
        boiler={"name": "Selected Boiler"},
        settings=settings or dict(nominal_thermal_efficiency=0.9),
    )


def preflight(source, cfg):
    return tx.preflight(source, cfg, OPERATION, boilers.plan)


def apply(report, folder, creator=None):
    path = folder / "reviewed.json"
    path.write_text(json.dumps(report))
    return tx.apply(
        path, OPERATION, boilers.plan, creator or boilers.edit, boilers.validate_model
    )


@pytest.mark.parametrize("fuel", ["NaturalGas", "Electricity", "Propane"])
@pytest.mark.parametrize("curve", [False, True])
def test_saved_values_identity_references_and_curve(sdk, tmp_path, fuel, curve):
    o = sdk[0]
    source, model, boiler = fixture(o, tmp_path, fuel, curve)
    cost = o.model.LifeCycleCost.createLifeCycleCost(
        "Maintenance", boiler, 100, "CostPerEach", "Maintenance", 1, 0
    ).get()
    actuator = o.model.EnergyManagementSystemActuator(
        boiler, "Plant Component Boiler:HotWater", "On/Off Supervisory"
    )
    raw = {str(x.handle()): str(x.idfObject()) for x in [cost, actuator]}
    metadata = str(boiler.additionalProperties().handle())
    model.save(str(source), True)
    before = source.read_bytes()
    cfg = config(
        tmp_path,
        nominal_thermal_efficiency=0.9,
        on_cycle_parasitic_electric_load_w=100,
        off_cycle_parasitic_fuel_load_w=0 if fuel == "Electricity" else 15,
    )
    report = preflight(source, cfg)
    assert report["ready"], report
    assert report == preflight(source, cfg)
    assert (
        "Retained normalized efficiency curve" in " ".join(report["warnings"])
    ) == curve
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and result["translation"]["ok"], result
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    current = saved.getBoilerHotWater(boiler.handle()).get()
    assert boilers.values(current) == cfg["settings"]
    assert current.fuelType() == fuel
    assert str(current.additionalProperties().handle()) == metadata
    assert current.isNominalCapacityAutosized()
    assert (
        current.isDesignWaterFlowRateAutosized()
        == boiler.isDesignWaterFlowRateAutosized()
    )
    for handle, fields in raw.items():
        assert str(saved.getModelObject(o.toUUID(handle)).get().idfObject()) == fields
    assert source.read_bytes() == before


@pytest.mark.parametrize(
    "settings",
    [
        dict(nominal_thermal_efficiency=0),
        dict(nominal_thermal_efficiency=1.01),
        dict(nominal_thermal_efficiency=True),
        dict(nominal_thermal_efficiency=float("nan")),
        dict(on_cycle_parasitic_electric_load_w=-1),
        dict(off_cycle_parasitic_fuel_load_w=-1),
        dict(nominal_capacity_w=0),
        dict(fuel_type="Electricity"),
        dict(minimum_part_load_ratio=-0.2),
        dict(flow_mode="ConstantFlow"),
        dict(normalized_efficiency_curve={"name": "curve"}),
    ],
)
def test_invalid_and_out_of_scope_settings_reject(sdk, tmp_path, settings):
    source, _, _ = fixture(sdk[0], tmp_path)
    with pytest.raises(ValueError, match="Invalid boiler performance"):
        preflight(source, config(tmp_path, **settings))
    assert not (tmp_path / "edited.osm").exists()


@pytest.mark.parametrize("key", ["plant_loop", "boiler", "settings"])
def test_missing_choices_stay_unready(sdk, tmp_path, key):
    source, _, _ = fixture(sdk[0], tmp_path)
    cfg = config(tmp_path)
    del cfg[key]
    result = preflight(source, cfg)
    assert not result["ready"] and key in result["plan"]["missing_inputs"]
    assert result["plan"]["simulation_ready"] is False


@pytest.mark.parametrize("existing", [0, 15])
def test_electric_boiler_rejects_positive_requested_off_cycle_fuel(
    sdk, tmp_path, existing
):
    o = sdk[0]
    source, model, boiler = fixture(o, tmp_path, "Electricity")
    boiler.setOffCycleParasiticFuelLoad(existing)
    model.save(str(source), True)
    original = source.read_bytes()
    report = preflight(source, config(tmp_path, off_cycle_parasitic_fuel_load_w=20))
    assert not report["ready"] and not report["plan"]["simulation_ready"]
    assert "Electric boilers cannot apply positive" in " ".join(
        report["plan"]["errors"]
    )
    assert ("Existing nonzero" in " ".join(report["warnings"])) == bool(existing)
    assert (
        report["plan"]["impact"]["off_cycle_parasitic_fuel"]["effective_input_w"] == 0
    )
    assert source.read_bytes() == original
    assert not (tmp_path / "edited.osm").exists()


@pytest.mark.parametrize("clear", [False, True])
def test_electric_existing_ignored_value_is_flagged_not_silently_reset(
    sdk, tmp_path, clear
):
    o = sdk[0]
    source, model, boiler = fixture(o, tmp_path, "Electricity")
    boiler.setOffCycleParasiticFuelLoad(15)
    epw = Path(__file__).parent / "fixtures/USA_FL_Tampa.Intl.AP.722110_TMY3.epw"
    assert o.model.WeatherFile.setWeatherFile(
        model, o.EpwFile(str(epw.resolve()))
    ).is_initialized()
    model.save(str(source), True)
    cfg = config(tmp_path)
    if clear:
        cfg["settings"]["off_cycle_parasitic_fuel_load_w"] = 0
    report = preflight(source, cfg)
    assert report["ready"]
    assert report["plan"]["simulation_ready"] is True
    effect = report["plan"]["impact"]["off_cycle_parasitic_fuel"]
    assert effect["ignored_by_engine_before"] is True
    assert effect["ignored_by_engine_after"] is not clear
    assert "Existing nonzero" in " ".join(report["warnings"])
    result = apply(report, tmp_path)
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    assert saved.getBoilerHotWater(
        boiler.handle()
    ).get().offCycleParasiticFuelLoad() == (0 if clear else 15)
    assert result["simulation_ready"] is True


@pytest.mark.parametrize("loop_type", ["Heating", "Cooling", "Condenser"])
def test_inventory_support_agrees_with_preflight_loop_type(sdk, tmp_path, loop_type):
    o = sdk[0]
    source, model, _ = fixture(o, tmp_path)
    model.getPlantLoops()[0].sizingPlant().setLoopType(loop_type)
    model.save(str(source), True)
    assert boilers.inventory(model)["plant_loops"][0]["boilers"][0]["supported"] == (
        loop_type == "Heating"
    )
    assert preflight(source, config(tmp_path))["ready"] == (loop_type == "Heating")


@pytest.mark.parametrize("weather", [False, True])
def test_explicit_readiness_includes_companion_blockers(sdk, tmp_path, weather):
    o = sdk[0]
    source, model, _ = fixture(o, tmp_path)
    if weather:
        epw = Path(__file__).parent / "fixtures/USA_FL_Tampa.Intl.AP.722110_TMY3.epw"
        assert o.model.WeatherFile.setWeatherFile(
            model, o.EpwFile(str(epw.resolve()))
        ).is_initialized()
        model.save(str(source), True)
    report = preflight(source, config(tmp_path))
    assert report["ready"]
    assert report["plan"]["simulation_ready"] is weather
    assert report["plan"]["companions"]["simulation_ready"] is weather


@pytest.mark.parametrize("operation_ready", [None, True, False])
def test_optional_readiness_rollup_preserves_legacy_report_shape(
    sdk, tmp_path, operation_ready
):
    from common import pump_edit

    source, _, _ = fixture(sdk[0], tmp_path)
    cfg = dict(
        output_model_path=str(tmp_path / "pump.osm"),
        plant_loop={"name": "HW"},
        pump={"name": "HW Pump 1"},
        settings=dict(head=50000, head_units="Pa"),
    )

    def planner(model, sdk, config):
        planned = pump_edit.plan(model, sdk, config)
        if operation_ready is not None:
            planned["simulation_ready"] = operation_ready
        return planned

    report = tx.preflight(source, cfg, "edit_pump_performance", planner)
    assert report["ready"]
    if operation_ready is None:
        assert "simulation_ready" not in report["plan"]
    else:
        assert report["plan"]["simulation_ready"] is operation_ready
    assert report["plan"]["companions"]["simulation_ready"] is False


@pytest.mark.parametrize(
    "case",
    [
        "noop",
        "empty",
        "unknown_loop",
        "unknown_boiler",
        "steam",
        "detached",
        "cooling_loop",
    ],
)
def test_unsupported_or_noop_requests_stay_unready(sdk, tmp_path, case):
    o = sdk[0]
    source, model, boiler = fixture(o, tmp_path)
    cfg = config(tmp_path)
    if case == "noop":
        cfg["settings"] = dict(nominal_thermal_efficiency=0.8)
    elif case == "empty":
        cfg["settings"] = {}
    elif case == "unknown_loop":
        cfg["plant_loop"] = {"name": "Absent"}
    elif case == "unknown_boiler":
        cfg["boiler"] = {"name": "Absent"}
    elif case == "steam":
        steam = o.model.BoilerSteam(model)
        steam.setName("Steam Boiler")
        model.getPlantLoops()[0].addSupplyBranchForComponent(steam)
        cfg["boiler"] = {"name": "Steam Boiler"}
    elif case == "detached":
        assert boiler.removeFromLoop()
    else:
        model.getPlantLoops()[0].sizingPlant().setLoopType("Cooling")
    model.save(str(source), True)
    report = preflight(source, cfg)
    assert not report["ready"], report
    assert report["plan"]["errors"] or report["plan"]["missing_inputs"]


@pytest.mark.parametrize("missing", ["pump", "setpoint"])
def test_rating_edit_does_not_require_plant_repair(sdk, tmp_path, missing):
    o = sdk[0]
    source, model, _ = fixture(o, tmp_path)
    if missing == "pump":
        model.getPumpVariableSpeeds()[0].remove()
    else:
        for manager in model.getPlantLoops()[0].supplyOutletNode().setpointManagers():
            manager.remove()
    model.save(str(source), True)
    report = preflight(source, config(tmp_path))
    assert report["ready"] and report["plan"]["simulation_ready"] is False
    assert "do not repair plant readiness" in " ".join(report["warnings"])
    assert apply(report, tmp_path)["validation"]["ok"]


def test_sdk_omitted_curve_is_reported_without_silent_control_repair(sdk, tmp_path):
    o = sdk[0]
    source, model, boiler = fixture(o, tmp_path, curve=True)
    boiler.resetEfficiencyCurveTemperatureEvaluationVariable()
    model.save(str(source), True)
    report = preflight(source, config(tmp_path))
    assert report["ready"]
    assert report["plan"]["impact"]["normalized_efficiency_curve"]
    assert report["plan"]["impact"]["normalized_efficiency_curve_translated"] is False
    assert report["plan"]["simulation_ready"] is False
    assert "not passed to EnergyPlus" in " ".join(report["warnings"])
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and not result["simulation_ready"]
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    current = saved.getBoilerHotWater(boiler.handle()).get()
    index = (
        current.iddObject()
        .getFieldIndex("Efficiency Curve Temperature Evaluation Variable")
        .get()
    )
    assert boilers.optional_string(current, index) == ""
    assert current.normalizedBoilerEfficiencyCurve().is_initialized()


def test_selected_boiler_only_preserves_fixed_sizing_and_dispatch(sdk, tmp_path):
    o = sdk[0]
    source, model, boiler = fixture(o, tmp_path)
    boiler.setNominalCapacity(50000)
    boiler.setDesignWaterFlowRate(0.002)
    other = o.model.BoilerHotWater(model)
    other.setName("Other Boiler")
    model.getPlantLoops()[0].addSupplyBranchForComponent(other)
    before = str(other.idfObject())
    model.save(str(source), True)
    report = preflight(source, config(tmp_path))
    assert report["ready"], report
    assert report["plan"]["impact"]["nominal_capacity_w"] == 50000
    assert "plant dispatch remain unchanged" in " ".join(report["warnings"])
    result = apply(report, tmp_path)
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    assert (
        saved.getBoilerHotWater(boiler.handle()).get().nominalCapacity().get() == 50000
    )
    assert str(saved.getBoilerHotWater(other.handle()).get().idfObject()) == before


@pytest.mark.parametrize(
    "mutation",
    [
        "efficiency",
        "fuel",
        "capacity",
        "flow",
        "part_load",
        "curve",
        "metadata",
        "pump",
        "sizing",
        "dispatch",
        "ports",
        "new_object",
    ],
)
def test_saved_mutations_never_publish(sdk, tmp_path, mutation):
    o = sdk[0]
    source, _, _ = fixture(o, tmp_path, curve=True)
    report = preflight(source, config(tmp_path))
    assert report["ready"], report

    def changed(model, sdk, planned):
        result = boilers.edit(model, sdk, planned)
        boiler = boilers.boiler_object(
            model, sdk, planned["resolved_objects"]["boiler"]
        )
        if mutation == "efficiency":
            boiler.setNominalThermalEfficiency(0.7)
        elif mutation == "fuel":
            boiler.setFuelType("Electricity")
        elif mutation == "capacity":
            boiler.setNominalCapacity(12345)
        elif mutation == "flow":
            boiler.setDesignWaterFlowRate(0.001)
        elif mutation == "part_load":
            boiler.setMinimumPartLoadRatio(0.2)
        elif mutation == "curve":
            boiler.normalizedBoilerEfficiencyCurve().get().to_CurveQuadratic().get().setCoefficient1Constant(
                0.5
            )
        elif mutation == "metadata":
            boiler.additionalProperties().setFeature("review_note", "changed")
        elif mutation == "pump":
            model.getPumpVariableSpeeds()[0].setRatedPumpHead(999)
        elif mutation == "sizing":
            model.getPlantLoops()[0].sizingPlant().setLoopDesignTemperatureDifference(
                15
            )
        elif mutation == "dispatch":
            model.getPlantLoops()[0].setLoadDistributionScheme("SequentialLoad")
        elif mutation == "ports":
            model.disconnect(boiler, boiler.inletPort())
        elif mutation == "new_object":
            o.model.BoilerHotWater(model)
        return result

    with pytest.raises(ValueError):
        apply(report, tmp_path, changed)
    assert not (tmp_path / "edited.osm").exists()


@pytest.mark.parametrize("mode", ["stale", "tampered"])
def test_exact_source_and_review_checks_remain(sdk, tmp_path, mode):
    source, _, _ = fixture(sdk[0], tmp_path)
    report = preflight(source, config(tmp_path))
    if mode == "stale":
        source.write_bytes(source.read_bytes() + b"\n! Stale source\n")
    else:
        report["plan"]["parameters"]["settings"]["nominal_thermal_efficiency"] = 0.7
    with pytest.raises(ValueError):
        apply(report, tmp_path)
    assert not (tmp_path / "edited.osm").exists()


@pytest.mark.parametrize("tamper", [False, True])
def test_csv_companions_relocate_or_reject_changed_resource(
    sdk, tmp_path, monkeypatch, tamper
):
    import shutil
    from common.companions import external_file_status

    o = sdk[0]
    source, model, _ = fixture(o, tmp_path)
    monkeypatch.chdir(tmp_path)
    csv = tmp_path / "loads.csv"
    csv.write_text("value\n" + "1000\n" * 8760)
    external = o.model.ExternalFile.getExternalFile(model, str(csv)).get()
    schedule = o.model.ScheduleFile(external)
    schedule.setRowstoSkipatTop(1)
    load = o.model.LoadProfilePlant(model)
    load.setLoadSchedule(schedule)
    model.getPlantLoops()[0].addDemandBranchForComponent(load)
    model.save(str(source), True)
    original = source.read_bytes()
    report = preflight(source, config(tmp_path))
    assert report["ready"], report
    bound = Path(
        next(
            x["source"]
            for x in report["plan"]["companions"]["resources"]
            if x["target"].endswith("loads.csv")
        )
    )
    if tamper:
        bound.write_text(bound.read_text() + "2000\n")
        with pytest.raises(ValueError):
            apply(report, tmp_path)
        assert not (tmp_path / "edited.osm").exists()
        return
    result = apply(report, tmp_path)
    moved = tmp_path / "moved"
    moved.mkdir()
    shutil.move(result["output_model_path"], moved / "edited.osm")
    shutil.move(result["companion_directory"], moved / "edited")
    for p in {csv, bound}:
        p.unlink()
    saved = o.osversion.VersionTranslator().loadModel(str(moved / "edited.osm")).get()
    assert result["requires_companion_workflow"]
    saved.workflowJSON().setOswPath(str(moved / "edited/workflow.osw"))
    assert external_file_status(saved)["ok"]
    assert source.read_bytes() == original


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("capacity", [False, True, "part_load"])
def test_native_relocated_exports(sdk, tmp_path, host, capacity):
    import shutil
    import subprocess
    from adapters.claude_code_adapter import ClaudeCodeAdapter
    from adapters.codex_adapter import CodexAdapter
    from adapters.contracts import HostAdapterConfig
    from plugin_fixture import copy_plugin_for_skill
    from test_supply_fan_performance import native_cli

    exe = str(native_cli())
    source, _, _ = fixture(sdk[0], tmp_path)
    original = source.read_bytes()
    adapter = (ClaudeCodeAdapter if host == "claude" else CodexAdapter)(
        HostAdapterConfig(
            host_name=host, workspace_root=Path.cwd(), runtime_mode="marketplace"
        )
    )
    exported = tmp_path / "export"
    adapter.export_plugin(exported, dry_run=False)
    skill = next(exported.rglob("openstudio-boiler-performance-editor/SKILL.md")).parent
    for relative in [
        "scripts/doctor.py",
        "scripts/sdk_probe.py",
        "scripts/prepare_model.py",
        "../../sdk/references/model_preparation.md",
        "../../sdk/references/boiler_performance.md",
        "../../sdk/references/boiler_performance.schema.json",
    ]:
        assert (skill / relative).is_file()
    skill = copy_plugin_for_skill(skill, tmp_path / "relocated")
    shutil.rmtree(exported)
    cfg = tmp_path / "request.json"
    cfg.write_text(
        json.dumps(
            config(
                tmp_path,
                **(
                    dict(minimum_part_load_ratio=0.2, optimum_part_load_ratio=0.8)
                    if capacity == "part_load"
                    else {"nominal_capacity_w": 20000} if capacity else {}
                ),
            )
        )
    )
    plan = tmp_path / "reviewed.json"
    repeated = tmp_path / "repeated.json"
    script = skill / "scripts/edit_boiler_performance.py"
    for args in [
        ["--input", str(source), "--report", str(tmp_path / "inventory.json")],
        ["--input", str(source), "--config", str(cfg), "--report", str(plan)],
        ["--input", str(source), "--config", str(cfg), "--report", str(repeated)],
        ["--plan", str(plan), "--report", str(tmp_path / "applied.json")],
    ]:
        run = subprocess.run(
            [exe, "execute_python_script", str(script), *args],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(plan.read_text()) == json.loads(repeated.read_text())
    result = json.loads((tmp_path / "applied.json").read_text())
    assert result["validation"]["ok"] and result["translation"]["ok"]
    assert source.read_bytes() == original


def native_run(o, source, folder, boiler_handle, extra_variables=(), meters=()):
    import sqlite3
    import subprocess
    from test_supply_fan_performance import native_cli

    folder.mkdir()
    model = o.osversion.VersionTranslator().loadModel(str(source)).get()
    boiler = model.getBoilerHotWater(o.toUUID(boiler_handle)).get()
    variables = [
        "Boiler Heating Energy",
        f"Boiler {boiler.fuelType()} Energy",
        "Boiler Part Load Ratio",
        "Boiler Outlet Temperature",
        "Boiler Mass Flow Rate",
    ] + list(extra_variables)
    for variable in variables:
        output = o.model.OutputVariable(variable, model)
        output.setKeyValue(boiler.nameString())
        output.setReportingFrequency("Hourly")
    for name in meters:
        meter = o.model.OutputMeter(model)
        meter.setName(name)
        meter.setReportingFrequency("Hourly")
    weather = Path(str(model.getWeatherFile().path().get()))
    if not weather.is_absolute():
        weather = source.parent / weather
    assert o.model.WeatherFile.setWeatherFile(
        model, o.EpwFile(str(weather.resolve()))
    ).is_initialized()
    instrumented = folder / "instrumented.osm"
    model.save(str(instrumented), True)
    workflow = folder / "workflow.osw"
    workflow.write_text(json.dumps(dict(seed_file=str(instrumented), steps=[])))
    run = subprocess.run(
        [str(native_cli()), "run", "-w", str(workflow)],
        cwd=folder,
        capture_output=True,
        text=True,
        timeout=120,
    )
    (folder / "cli.log").write_text(run.stdout + run.stderr)
    assert run.returncode == 0, run.stdout + run.stderr
    err = (folder / "run/eplusout.err").read_text()
    assert (
        "EnergyPlus Completed Successfully" in err
        and "** Severe **" not in err
        and "**  Fatal  **" not in err
    ), err
    with sqlite3.connect(folder / "run/eplusout.sql") as sql:
        data = {}
        for variable in variables:
            rows = sql.execute(
                "SELECT t.EnvironmentPeriodIndex,t.SimulationDays,t.Hour,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE d.Name=? AND lower(d.KeyValue)=lower(?) AND t.WarmupFlag=0 ORDER BY t.TimeIndex",
                (variable, boiler.nameString()),
            ).fetchall()
            assert rows, (variable, boiler.nameString())
            data[variable] = rows
        sizes = sql.execute(
            "SELECT Description,Value FROM ComponentSizes WHERE lower(CompName)=lower(?)",
            (boiler.nameString(),),
        ).fetchall()
        meter_energy = {}
        for name in meters:
            rows = sql.execute(
                "SELECT r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) WHERE lower(d.Name)=lower(?) AND d.IsMeter=1",
                (name,),
            ).fetchall()
            assert rows, name
            meter_energy[name] = sum(x[0] for x in rows)
        environments = dict(
            sql.execute(
                "SELECT EnvironmentPeriodIndex,EnvironmentName FROM EnvironmentPeriods"
            ).fetchall()
        )
    observed = dict(
        hours=len(data[variables[0]]),
        heating_j=sum(x[3] for x in data[variables[0]]),
        fuel_j=sum(x[3] for x in data[variables[1]]),
        plr_range=[
            min(x[3] for x in data[variables[2]]),
            max(x[3] for x in data[variables[2]]),
        ],
        outlet_range_c=[
            min(x[3] for x in data[variables[3]]),
            max(x[3] for x in data[variables[3]]),
        ],
        sizes=sizes,
        warnings=err,
        meter_energy_j=meter_energy,
        environments=environments,
    )
    (folder / "hourly.json").write_text(json.dumps(data, indent=2))
    (folder / "observed.json").write_text(json.dumps(observed, indent=2))
    return observed


@pytest.mark.parametrize("curve", [False, True])
def test_native_efficiency_edit_changes_fuel_not_heat_or_sizing(sdk, tmp_path, curve):
    import hashlib
    from vav_fixture import prepare_vav_fixture
    from test_supply_fan_performance import native_cli
    from common import cav_system

    native_cli()
    o = sdk[0]
    unserved, cfg, original_fixture, original_bytes = prepare_vav_fixture(
        o, tmp_path, True
    )
    model = o.osversion.VersionTranslator().loadModel(str(unserved)).get()
    cfg.update(defaults_profile="prototype_cav_v1", outdoor_air_schedule=None)
    cav = cav_system.plan(model, o, cfg)
    assert cav["ready"], cav
    cav_system.create(model, o, cav)
    plant = model.getPlantLoopByName("Fixture HW").get()
    model.getDistrictHeatingWaters()[0].remove()
    boiler = o.model.BoilerHotWater(model)
    boiler.setName("Native Boiler")
    boiler.setNominalThermalEfficiency(0.8)
    boiler.autosizeNominalCapacity()
    boiler.autosizeDesignWaterFlowRate()
    boiler.setBoilerFlowMode("LeavingSetpointModulated")
    assert boiler.setEfficiencyCurveTemperatureEvaluationVariable("LeavingBoiler")
    boiler.setMaximumPartLoadRatio(1.2)
    boiler.setSizingFactor(
        2.0
    )  # Exercise part-load curve behavior, not just its value at PLR=1.
    if curve:
        performance = o.model.CurveQuadratic(model)
        performance.setCoefficient1Constant(0.85)
        performance.setCoefficient2x(0.15)
        performance.setCoefficient3xPOW2(0)
        performance.setMinimumValueofx(0)
        performance.setMaximumValueofx(1.2)
        assert boiler.setNormalizedBoilerEfficiencyCurve(performance)
    assert plant.addSupplyBranchForComponent(boiler)
    source = tmp_path / "before.osm"
    assert model.save(str(source), True)
    original = source.read_bytes()
    request = config(tmp_path)
    request.update(plant_loop={"name": "Fixture HW"}, boiler={"name": "Native Boiler"})
    report = preflight(source, request)
    assert report["ready"], report
    result = apply(report, tmp_path)
    before = native_run(o, source, tmp_path / "before_run", str(boiler.handle()))
    after = native_run(
        o,
        Path(result["output_model_path"]),
        tmp_path / "after_run",
        str(boiler.handle()),
    )
    assert before["hours"] == after["hours"] == 72
    assert before["heating_j"] > 1e8
    assert 0 < before["plr_range"][1] < 1
    if curve:
        assert before["heating_j"] / before["fuel_j"] < 0.8
    assert after["heating_j"] == pytest.approx(before["heating_j"], rel=1e-6)
    assert after["fuel_j"] / before["fuel_j"] == pytest.approx(0.8 / 0.9, rel=1e-5)
    assert after["sizes"] == before["sizes"]
    assert (
        source.read_bytes() == original
        and original_fixture.read_bytes() == original_bytes
    )
    (tmp_path / "native_evidence.json").write_text(
        json.dumps(
            dict(
                curve=curve,
                before=before,
                after=after,
                source_sha256=hashlib.sha256(original).hexdigest(),
                source_unchanged=True,
                validation=result["validation"],
                translation=result["translation"],
            ),
            indent=2,
        )
    )


def parasitic_fixture(o, folder, fuel):
    source, model, boiler = fixture(o, folder, fuel)
    boiler.setNominalCapacity(10000)
    boiler.setDesignWaterFlowRate(0.001)
    boiler.setMaximumPartLoadRatio(1)
    loop = model.getPlantLoops()[0]
    loop.setMaximumLoopFlowRate(0.001)
    loop.setPlantLoopVolume(0.1)
    pump = model.getPumpVariableSpeeds()[0]
    pump.setRatedFlowRate(0.001)
    pump.setRatedPowerConsumption(100)
    pump.setRatedPumpHead(50000)
    loads = o.model.ScheduleRuleset(model)
    loads.defaultDaySchedule().addValue(o.Time(0, 24, 0, 0), 0)
    winter = o.model.ScheduleDay(model)
    for hour, watts in [(6, 0), (12, 3000), (18, 6000), (24, 0)]:
        winter.addValue(o.Time(0, hour, 0, 0), watts)
    loads.setWinterDesignDaySchedule(winter)
    flows = o.model.ScheduleRuleset(model)
    flows.defaultDaySchedule().addValue(o.Time(0, 24, 0, 0), 0)
    winter_flow = o.model.ScheduleDay(model)
    for hour, fraction in [(6, 0), (18, 1), (24, 0)]:
        winter_flow.addValue(o.Time(0, hour, 0, 0), fraction)
    flows.setWinterDesignDaySchedule(winter_flow)
    load = o.model.LoadProfilePlant(model)
    load.setLoadSchedule(loads)
    load.setPeakFlowRate(0.001)
    load.setFlowRateFractionSchedule(flows)
    loop.addDemandBranchForComponent(load)
    for name, kind, month, day, dry, wet in [
        ("A Summer Before", "SummerDesignDay", 7, 20, 35, 23),
        ("B Winter Firing", "WinterDesignDay", 1, 21, 10, 0),
        ("C Summer After", "SummerDesignDay", 7, 22, 35, 23),
    ]:
        design = o.model.DesignDay(model)
        design.setName(name)
        design.setDayType(kind)
        design.setMonth(month)
        design.setDayOfMonth(day)
        design.setMaximumDryBulbTemperature(dry)
        design.setBarometricPressure(101325)
        design.setDailyDryBulbTemperatureRange(0)
        design.setHumidityConditionType("Wetbulb")
        design.setWetBulbOrDewPointAtMaximumDryBulb(wet)
        design.setSolarModelIndicator("ASHRAEClearSky")
        design.setSkyClearness(1)
    control = model.getSimulationControl()
    control.setDoZoneSizingCalculation(False)
    control.setDoSystemSizingCalculation(False)
    control.setDoPlantSizingCalculation(False)
    control.setRunSimulationforSizingPeriods(True)
    control.setRunSimulationforWeatherFileRunPeriods(False)
    epw = Path(__file__).parent / "fixtures/USA_FL_Tampa.Intl.AP.722110_TMY3.epw"
    assert o.model.WeatherFile.setWeatherFile(
        model, o.EpwFile(str(epw.resolve()))
    ).is_initialized()
    assert model.save(str(source), True)
    return source, model, boiler


@pytest.mark.parametrize("fuel", ["NaturalGas", "Electricity"])
def test_native_parasitic_inputs_and_idle_carryover(sdk, tmp_path, fuel):
    from test_supply_fan_performance import native_cli

    native_cli()
    o = sdk[0]
    source, model, boiler = parasitic_fixture(o, tmp_path, fuel)
    extra = [
        "Boiler Heating Rate",
        "Boiler Ancillary Electricity Rate",
        "Boiler Ancillary Electricity Energy",
    ]
    meters = ["Boiler Parasitic:Heating:Electricity"]
    if fuel == "NaturalGas":
        extra += [
            "Boiler Ancillary NaturalGas Rate",
            "Boiler Ancillary NaturalGas Energy",
        ]
        meters.append("Boiler Parasitic:Heating:NaturalGas")
        original = source.read_bytes()
        report = preflight(
            source,
            config(
                tmp_path,
                on_cycle_parasitic_electric_load_w=100,
                off_cycle_parasitic_fuel_load_w=15,
            ),
        )
        assert report["ready"] and report["plan"]["simulation_ready"], report
        assert "retains the last rate while idle" in " ".join(report["warnings"])
        result = apply(report, tmp_path)
        before = native_run(
            o, source, tmp_path / "before_run", str(boiler.handle()), extra, meters
        )
        after = native_run(
            o,
            Path(result["output_model_path"]),
            tmp_path / "after_run",
            str(boiler.handle()),
            extra,
            meters,
        )
        assert source.read_bytes() == original
    else:
        # Deliberate invalid source probe: inspect engine handling independently
        # of the planner, which correctly rejects creating this combination.
        boiler.setOnCycleParasiticElectricLoad(100)
        boiler.setOffCycleParasiticFuelLoad(15)
        model.save(str(source), True)
        original = source.read_bytes()
        before = native_run(
            o, source, tmp_path / "ignored_run", str(boiler.handle()), extra, meters
        )
        assert "It will be ignored" in before["warnings"]
        report = preflight(source, config(tmp_path, off_cycle_parasitic_fuel_load_w=0))
        assert report["ready"] and report["plan"]["simulation_ready"]
        result = apply(report, tmp_path)
        after = native_run(
            o,
            Path(result["output_model_path"]),
            tmp_path / "after_run",
            str(boiler.handle()),
            extra,
            meters,
        )
        assert "It will be ignored" not in after["warnings"]
        assert after["fuel_j"] == pytest.approx(before["fuel_j"], rel=1e-9)
        assert after["meter_energy_j"] == pytest.approx(
            before["meter_energy_j"], rel=1e-9
        )
        assert source.read_bytes() == original
    assert before["hours"] == after["hours"] == 72
    assert "Plant loop exceeding upper temperature limit" not in after["warnings"]
    assert after["heating_j"] == pytest.approx(before["heating_j"], rel=1e-9)
    rows = json.loads((tmp_path / "after_run/hourly.json").read_text())
    series = {
        name: {tuple(row[:3]): row[3] for row in values}
        for name, values in rows.items()
    }
    plrs = series["Boiler Part Load Ratio"]
    electric = series["Boiler Ancillary Electricity Rate"]
    for key, plr in plrs.items():
        assert electric[key] == pytest.approx(100 * plr, abs=1e-7)
    assert after["meter_energy_j"][meters[0]] == pytest.approx(
        sum(series["Boiler Ancillary Electricity Energy"].values())
    )
    idle_rate = None
    if fuel == "NaturalGas":
        gas = series["Boiler Ancillary NaturalGas Rate"]
        environments = {int(k): v.upper() for k, v in after["environments"].items()}
        before_keys = [k for k in gas if "A SUMMER BEFORE" in environments[k[0]]]
        firing = [
            k
            for k in gas
            if "B WINTER FIRING" in environments[k[0]]
            and k[2] in [8, 9, 10, 14, 15, 16]
        ]
        idle = [
            k for k in gas if "B WINTER FIRING" in environments[k[0]] and k[2] >= 20
        ]
        summer_after = [k for k in gas if "C SUMMER AFTER" in environments[k[0]]]
        assert len(before_keys) == len(summer_after) == 24 and firing and idle
        assert all(gas[k] == 0 for k in before_keys)
        for key in firing:
            assert 0 < plrs[key] < 1
            assert gas[key] == pytest.approx(15 * (1 - plrs[key]), abs=1e-7)
        idle_rate = gas[idle[0]]
        assert 0 < idle_rate < 15
        for key in idle + summer_after:
            assert plrs[key] == 0
            assert gas[key] == pytest.approx(idle_rate, abs=1e-7)
        assert after["meter_energy_j"][meters[1]] == pytest.approx(
            sum(series["Boiler Ancillary NaturalGas Energy"].values())
        )
    (tmp_path / "parasitic_evidence.json").write_text(
        json.dumps(
            dict(
                fuel=fuel,
                before=before,
                after=after,
                carried_idle_rate_w=idle_rate,
                validation=result["validation"],
                translation=result["translation"],
            ),
            indent=2,
        )
    )


@pytest.mark.parametrize("fuel", ["NaturalGas", "Electricity", "Propane"])
@pytest.mark.parametrize(
    "before,after", [("Autosize", 20000), (10000, 20000), (10000, "Autosize")]
)
def test_explicit_capacity_preserves_identity_other_fields_and_references(
    sdk, tmp_path, fuel, before, after
):
    o = sdk[0]
    source, model, boiler = fixture(o, tmp_path, fuel, curve=True)
    if before != "Autosize":
        boiler.setNominalCapacity(before)
    cost = o.model.LifeCycleCost.createLifeCycleCost(
        "Maintenance", boiler, 100, "CostPerEach", "Maintenance", 1, 0
    ).get()
    actuator = o.model.EnergyManagementSystemActuator(
        boiler, "Plant Component Boiler:HotWater", "On/Off Supervisory"
    )
    protected = {
        str(x.handle()): str(x.idfObject())
        for x in (
            cost,
            actuator,
            boiler.additionalProperties(),
            boiler.normalizedBoilerEfficiencyCurve().get(),
        )
    }
    before_ratings = boilers.values(boiler)
    model.save(str(source), True)
    original = source.read_bytes()
    cfg = config(tmp_path, nominal_capacity_w=after)
    report = preflight(source, cfg)
    assert report["ready"], report
    assert report == preflight(source, cfg)
    assert report["plan"]["before_values"]["nominal_capacity_w"] == before
    assert report["plan"]["impact"]["nominal_capacity_w"] == before
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and result["translation"]["ok"]
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    current = saved.getBoilerHotWater(boiler.handle()).get()
    assert boilers.sized(current, "NominalCapacity") == after
    assert boilers.values(current) == before_ratings
    assert (
        current.isDesignWaterFlowRateAutosized()
        == boiler.isDesignWaterFlowRateAutosized()
    )
    for handle, raw in protected.items():
        assert str(saved.getModelObject(o.toUUID(handle)).get().idfObject()) == raw
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    "capacity", [0, -1, True, "20000", "autosize", float("nan"), float("inf")]
)
def test_invalid_capacity_rejects(sdk, tmp_path, capacity):
    source, _, _ = fixture(sdk[0], tmp_path)
    with pytest.raises(ValueError, match="Invalid boiler performance"):
        preflight(source, config(tmp_path, nominal_capacity_w=capacity))
    assert not (tmp_path / "edited.osm").exists()


@pytest.mark.parametrize("before", [20000, "Autosize"])
def test_capacity_noop_rejects(sdk, tmp_path, before):
    source, model, boiler = fixture(sdk[0], tmp_path)
    if before != "Autosize":
        boiler.setNominalCapacity(before)
    model.save(str(source), True)
    assert not preflight(source, config(tmp_path, nominal_capacity_w=before))["ready"]


@pytest.mark.parametrize(
    "mutation", ["capacity", "efficiency", "flow", "part_load", "curve", "metadata"]
)
def test_capacity_patch_does_not_allow_unrequested_side_effects(
    sdk, tmp_path, mutation
):
    o = sdk[0]
    source, _, _ = fixture(o, tmp_path, curve=True)
    report = preflight(source, config(tmp_path, nominal_capacity_w=20000))

    def changed(model, sdk, planned):
        result = boilers.edit(model, sdk, planned)
        boiler = boilers.boiler_object(
            model, sdk, planned["resolved_objects"]["boiler"]
        )
        if mutation == "capacity":
            boiler.setNominalCapacity(12345)
        elif mutation == "efficiency":
            boiler.setNominalThermalEfficiency(0.7)
        elif mutation == "flow":
            boiler.setDesignWaterFlowRate(0.002)
        elif mutation == "part_load":
            boiler.setMinimumPartLoadRatio(0.2)
        elif mutation == "curve":
            boiler.normalizedBoilerEfficiencyCurve().get().to_CurveQuadratic().get().setCoefficient1Constant(
                0.5
            )
        else:
            boiler.additionalProperties().setFeature("mutation", True)
        return result

    with pytest.raises(ValueError):
        apply(report, tmp_path, changed)
    assert not (tmp_path / "edited.osm").exists()


def test_capacity_and_efficiency_may_be_explicitly_combined(sdk, tmp_path):
    source, _, _ = fixture(sdk[0], tmp_path)
    report = preflight(
        source,
        config(tmp_path, nominal_capacity_w=20000, nominal_thermal_efficiency=0.9),
    )
    assert report["ready"], report
    assert report["plan"]["after_values"]["nominal_thermal_efficiency"] == 0.9
    assert apply(report, tmp_path)["validation"]["ok"]


@pytest.mark.parametrize("problem", ["missing", "mismatch"])
def test_capacity_translation_inconsistency_is_normal_plan_error(
    sdk, tmp_path, monkeypatch, problem
):
    source, _, _ = fixture(sdk[0], tmp_path)
    original = boilers.translated_state

    def changed(*args):
        if problem == "missing":
            raise ValueError("Translated boiler performance field is not numeric")
        result = original(*args)
        result["settings"]["nominal_capacity_w"] = 1234
        return result

    monkeypatch.setattr(boilers, "translated_state", changed)
    report = preflight(source, config(tmp_path, nominal_capacity_w=20000))
    assert not report["ready"] and report["plan"]["errors"]


@pytest.mark.parametrize("curve", [False, True])
def test_native_capacity_changes_plr_parasitics_and_curve_use(sdk, tmp_path, curve):
    from test_supply_fan_performance import native_cli

    native_cli()
    o = sdk[0]
    source, model, boiler = parasitic_fixture(o, tmp_path, "NaturalGas")
    boiler.setOnCycleParasiticElectricLoad(100)
    boiler.setOffCycleParasiticFuelLoad(15)
    if curve:
        c = o.model.CurveQuadratic(model)
        c.setCoefficient1Constant(0.85)
        c.setCoefficient2x(0.15)
        c.setCoefficient3xPOW2(0)
        c.setMinimumValueofx(0)
        c.setMaximumValueofx(1.2)
        boiler.setNormalizedBoilerEfficiencyCurve(c)
        boiler.setEfficiencyCurveTemperatureEvaluationVariable("LeavingBoiler")
    model.save(str(source), True)
    original = source.read_bytes()
    report = preflight(source, config(tmp_path, nominal_capacity_w=20000))
    assert report["ready"] and report["plan"]["simulation_ready"], report
    result = apply(report, tmp_path)
    extra = [
        "Boiler Ancillary Electricity Energy",
        "Boiler Ancillary NaturalGas Energy",
        "Boiler Heating Rate",
    ]
    before = native_run(o, source, tmp_path / "before_run", str(boiler.handle()), extra)
    after = native_run(
        o,
        Path(result["output_model_path"]),
        tmp_path / "after_run",
        str(boiler.handle()),
        extra,
    )
    assert before["hours"] == after["hours"] == 72
    assert after["heating_j"] == pytest.approx(before["heating_j"], rel=1e-6)
    assert after["plr_range"][1] == pytest.approx(before["plr_range"][1] / 2, rel=1e-6)
    if curve:
        assert after["fuel_j"] > before["fuel_j"]
    else:
        assert after["fuel_j"] == pytest.approx(before["fuel_j"], rel=1e-6)
    totals = []
    for name in ("before_run", "after_run"):
        rows = json.loads((tmp_path / name / "hourly.json").read_text())
        totals.append({key: sum(row[3] for row in rows[key]) for key in extra[:2]})
    assert totals[1][extra[0]] == pytest.approx(totals[0][extra[0]] / 2, rel=1e-6)
    assert totals[1][extra[1]] > totals[0][extra[1]]
    assert source.read_bytes() == original
    (tmp_path / "capacity_native.json").write_text(
        json.dumps(
            dict(
                curve=curve,
                before=before,
                after=after,
                ancillary_before=totals[0],
                ancillary_after=totals[1],
                validation=result["validation"],
                translation=result["translation"],
                source_unchanged=True,
            ),
            indent=2,
        )
    )


def test_native_capacity_autosize_retains_flow_and_sizing_factor(sdk, tmp_path):
    import sqlite3
    from test_supply_fan_performance import native_cli

    native_cli()
    o = sdk[0]
    source, model, boiler = parasitic_fixture(o, tmp_path, "NaturalGas")
    boiler.setNominalCapacity(1e6)
    boiler.setSizingFactor(1.5)
    model.getSimulationControl().setDoPlantSizingCalculation(True)
    model.save(str(source), True)
    report = preflight(source, config(tmp_path, nominal_capacity_w="Autosize"))
    assert report["ready"] and report["plan"]["simulation_ready"], report
    result = apply(report, tmp_path)
    before = native_run(o, source, tmp_path / "before_run", str(boiler.handle()))
    after = native_run(
        o,
        Path(result["output_model_path"]),
        tmp_path / "after_run",
        str(boiler.handle()),
    )
    sizes = dict(after["sizes"])
    assert sizes["Design Size Nominal Capacity"] == pytest.approx(
        dict(before["sizes"])["Design Size Nominal Capacity"]
    )
    with sqlite3.connect(tmp_path / "after_run/run/eplusout.sql") as sql:
        plant_capacity = sql.execute(
            "SELECT Value FROM ComponentSizes WHERE CompType='PlantLoop' AND Description='Design Capacity'"
        ).fetchone()[0]
    assert sizes["Design Size Nominal Capacity"] == pytest.approx(68578.2, rel=1e-9)
    # Boiler fluid properties use HWInitConvTemp; the plant report uses a
    # different property evaluation, so verify the retained factor independently.
    reference = tmp_path / "reference-factor-one.osm"
    boiler.autosizeNominalCapacity()
    boiler.setSizingFactor(1)
    model.save(str(reference), True)
    factor_one = native_run(
        o, reference, tmp_path / "factor_one_run", str(boiler.handle())
    )
    assert sizes["Design Size Nominal Capacity"] == pytest.approx(
        dict(factor_one["sizes"])["Design Size Nominal Capacity"] * 1.5, rel=1e-9
    )
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    current = saved.getBoilerHotWater(boiler.handle()).get()
    assert current.isNominalCapacityAutosized()
    assert current.designWaterFlowRate().get() == 0.001
    assert current.sizingFactor() == 1.5
    assert after["heating_j"] == pytest.approx(before["heating_j"], rel=1e-6)
    (tmp_path / "capacity_native.json").write_text(
        json.dumps(
            dict(
                before=before,
                after=after,
                plant_design_capacity_w=plant_capacity,
                factor_one_reference=factor_one,
                sizing_factor=1.5,
                validation=result["validation"],
                translation=result["translation"],
            ),
            indent=2,
        )
    )


def test_native_capacity_limit_includes_retained_maximum_plr(sdk, tmp_path):
    from test_supply_fan_performance import native_cli

    native_cli()
    o = sdk[0]
    source, model, boiler = parasitic_fixture(o, tmp_path, "NaturalGas")
    boiler.setMaximumPartLoadRatio(1.2)
    model.save(str(source), True)
    report = preflight(source, config(tmp_path, nominal_capacity_w=4000))
    assert report["ready"] and report["plan"]["simulation_ready"], report
    assert (
        report["plan"]["impact"]["capacity_edit"]["dispatch_load_limits_w"]["maximum"]
        == 4800
    )
    result = apply(report, tmp_path)
    extra = ["Boiler Heating Rate"]
    before = native_run(o, source, tmp_path / "before_run", str(boiler.handle()), extra)
    after = native_run(
        o,
        Path(result["output_model_path"]),
        tmp_path / "after_run",
        str(boiler.handle()),
        extra,
    )
    rows = json.loads((tmp_path / "after_run/hourly.json").read_text())
    assert max(x[3] for x in rows[extra[0]]) == pytest.approx(4800, rel=1e-6)
    assert after["heating_j"] < before["heating_j"]
    (tmp_path / "capacity_native.json").write_text(
        json.dumps(
            dict(
                before=before,
                after=after,
                retained_maximum_plr=1.2,
                maximum_heating_w=4800,
                validation=result["validation"],
                translation=result["translation"],
            ),
            indent=2,
        )
    )


def test_native_capacity_edit_redistributes_to_retained_backup(sdk, tmp_path):
    import sqlite3
    from test_supply_fan_performance import native_cli

    native_cli()
    o = sdk[0]
    source, model, boiler = parasitic_fixture(o, tmp_path, "NaturalGas")
    loop = boiler.plantLoop().get()
    backup = o.model.BoilerHotWater(model)
    backup.setName("Retained Backup")
    backup.setNominalCapacity(10000)
    backup.setNominalThermalEfficiency(0.8)
    backup.setDesignWaterFlowRate(0.001)
    backup.setBoilerFlowMode("LeavingSetpointModulated")
    backup.setMinimumPartLoadRatio(0)
    backup.setMaximumPartLoadRatio(1)
    assert loop.addSupplyBranchForComponent(backup)
    operation = o.model.PlantEquipmentOperationHeatingLoad(model)
    assert operation.addEquipment(boiler) and operation.addEquipment(backup)
    assert loop.setPlantEquipmentOperationHeatingLoad(operation)
    assert loop.setLoadDistributionScheme("SequentialLoad")
    for variable in ["Boiler Heating Energy", "Boiler Heating Rate"]:
        output = o.model.OutputVariable(variable, model)
        output.setKeyValue(backup.nameString())
        output.setReportingFrequency("Hourly")
    model.save(str(source), True)
    original = source.read_bytes()
    report = preflight(source, config(tmp_path, nominal_capacity_w=2000))
    assert report["ready"] and report["plan"]["simulation_ready"], report
    result = apply(report, tmp_path)
    before = native_run(
        o,
        source,
        tmp_path / "before_run",
        str(boiler.handle()),
        ["Boiler Heating Rate"],
    )
    after = native_run(
        o,
        Path(result["output_model_path"]),
        tmp_path / "after_run",
        str(boiler.handle()),
        ["Boiler Heating Rate"],
    )
    secondary = []
    for folder in ("before_run", "after_run"):
        with sqlite3.connect(tmp_path / folder / "run/eplusout.sql") as sql:
            rows = sql.execute(
                "SELECT r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE d.Name='Boiler Heating Energy' AND lower(d.KeyValue)=lower(?) AND t.WarmupFlag=0",
                (backup.nameString(),),
            ).fetchall()
            assert rows
            secondary.append(sum(x[0] for x in rows))
    assert secondary[0] == 0 and secondary[1] > 1e7
    assert after["heating_j"] < before["heating_j"]
    assert after["heating_j"] + secondary[1] == pytest.approx(
        before["heating_j"], rel=0.001
    )
    after_hourly = json.loads((tmp_path / "after_run/hourly.json").read_text())
    assert max(x[3] for x in after_hourly["Boiler Heating Rate"]) == pytest.approx(2000)
    assert source.read_bytes() == original
    (tmp_path / "capacity_native.json").write_text(
        json.dumps(
            dict(
                before=before,
                after=after,
                backup_energy_j=secondary,
                validation=result["validation"],
                translation=result["translation"],
                source_unchanged=True,
            ),
            indent=2,
        )
    )


def test_capacity_review_exposes_retained_minimum_and_maximum_output(sdk, tmp_path):
    source, model, boiler = fixture(sdk[0], tmp_path)
    boiler.setNominalCapacity(10000)
    boiler.setMinimumPartLoadRatio(0.25)
    boiler.setMaximumPartLoadRatio(1.2)
    boiler.setOptimumPartLoadRatio(0.8)
    model.save(str(source), True)
    report = preflight(source, config(tmp_path, nominal_capacity_w=20000))
    assert report["ready"], report
    assert report["plan"]["impact"]["capacity_edit"]["dispatch_load_limits_w"] == dict(
        minimum=5000, maximum=24000, optimal=16000
    )
    assert "Increasing capacity raises that floor" in " ".join(report["warnings"])
    assert apply(report, tmp_path)["validation"]["ok"]


@pytest.mark.parametrize(
    "settings",
    [
        {"minimum_part_load_ratio": 0.2},
        {"maximum_part_load_ratio": 0.7, "optimum_part_load_ratio": 0.6},
        {"optimum_part_load_ratio": 0.8},
        {
            "minimum_part_load_ratio": 0.3,
            "optimum_part_load_ratio": 0.5,
            "maximum_part_load_ratio": 0.8,
            "nominal_capacity_w": 20000,
        },
        {"maximum_part_load_ratio": 1.5},
    ],
)
def test_part_load_edits_preserve_unrequested_state(sdk, tmp_path, settings):
    o = sdk[0]
    source, model, boiler = fixture(o, tmp_path)
    original = source.read_bytes()
    report = preflight(source, config(tmp_path, **settings))
    assert report["ready"], report
    assert report == preflight(source, config(tmp_path, **settings))
    impact = report["plan"]["impact"]["part_load_edit"]
    capacity = settings.get("nominal_capacity_w", "Autosize")
    assert impact["dispatch_load_limits_after_w"] == boilers.dispatch_limits(
        capacity, boilers.part_load_values(boiler, settings)
    )
    if "capacity_edit" in report["plan"]["impact"]:
        assert (
            report["plan"]["impact"]["capacity_edit"]["dispatch_load_limits_w"]
            == impact["dispatch_load_limits_after_w"]
        )
    assert ("Effective maximum PLR exceeds 1" in " ".join(report["warnings"])) is (
        settings.get("maximum_part_load_ratio", boiler.maximumPartLoadRatio()) > 1
    )
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and result["translation"]["ok"]
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    current = saved.getBoilerHotWater(boiler.handle()).get()
    assert boilers.signature(current, settings) == boilers.signature(boiler, settings)
    for key, value in settings.items():
        assert (
            boilers.values(current, "nominal_capacity_w" in settings, settings)[key]
            == value
        )
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    "settings",
    [
        {"minimum_part_load_ratio": -0.1},
        {"maximum_part_load_ratio": 0},
        {"optimum_part_load_ratio": True},
        {"minimum_part_load_ratio": "Autosize"},
        {"maximum_part_load_ratio": float("inf")},
        {"optimum_part_load_ratio": float("nan")},
    ],
)
def test_invalid_part_load_inputs_reject(sdk, tmp_path, settings):
    source, _, _ = fixture(sdk[0], tmp_path)
    with pytest.raises(ValueError, match="Invalid boiler performance"):
        preflight(source, config(tmp_path, **settings))
    assert not (tmp_path / "edited.osm").exists()


@pytest.mark.parametrize(
    "settings",
    [
        {"minimum_part_load_ratio": 1.1},
        {"maximum_part_load_ratio": 0.5},
        {"minimum_part_load_ratio": 0.8, "optimum_part_load_ratio": 0.7},
        {"optimum_part_load_ratio": 1.3},
    ],
)
def test_cross_field_part_load_choices_stay_unready(sdk, tmp_path, settings):
    source, _, _ = fixture(sdk[0], tmp_path)
    report = preflight(source, config(tmp_path, **settings))
    assert not report["ready"] and "minimum <= optimum <= maximum" in " ".join(
        report["plan"]["errors"]
    )
    assert not (tmp_path / "edited.osm").exists()


@pytest.mark.parametrize("mutation", ["capacity", "other_plr", "curve", "requested"])
def test_part_load_mutations_do_not_publish(sdk, tmp_path, mutation):
    source, _, _ = fixture(sdk[0], tmp_path, curve=True)
    report = preflight(source, config(tmp_path, minimum_part_load_ratio=0.2))

    def altered(model, o, planned):
        result = boilers.edit(model, o, planned)
        b = boilers.boiler_object(model, o, planned["resolved_objects"]["boiler"])
        if mutation == "capacity":
            b.setNominalCapacity(10000)
        elif mutation == "other_plr":
            b.setOptimumPartLoadRatio(0.8)
        elif mutation == "requested":
            b.setMinimumPartLoadRatio(0.3)
        else:
            b.normalizedBoilerEfficiencyCurve().get().setName("Changed Curve")
        return result

    with pytest.raises(ValueError):
        apply(report, tmp_path, altered)
    assert not (tmp_path / "edited.osm").exists()


@pytest.mark.parametrize("mode", ["stale", "tampered"])
def test_part_load_exact_plan_source_checks(sdk, tmp_path, mode):
    source, _, _ = fixture(sdk[0], tmp_path)
    report = preflight(source, config(tmp_path, minimum_part_load_ratio=0.2))
    if mode == "stale":
        source.write_bytes(source.read_bytes() + b"\\n! changed\\n")
    else:
        report["plan"]["parameters"]["settings"]["minimum_part_load_ratio"] = 0.3
    with pytest.raises(ValueError):
        apply(report, tmp_path)
    assert not (tmp_path / "edited.osm").exists()


@pytest.mark.parametrize("mode", ["minimum", "maximum", "optimum"])
def test_native_part_load_operation(sdk, tmp_path, mode):
    from test_supply_fan_performance import native_cli

    native_cli()
    o = sdk[0]
    source, model, boiler = parasitic_fixture(o, tmp_path, "NaturalGas")
    boiler.setOnCycleParasiticElectricLoad(100)
    boiler.setOffCycleParasiticFuelLoad(15)
    settings = {
        "minimum": dict(minimum_part_load_ratio=0.5),
        "maximum": dict(maximum_part_load_ratio=0.4, optimum_part_load_ratio=0.4),
        "optimum": dict(optimum_part_load_ratio=0.6),
    }[mode]
    if mode == "minimum":
        loop = boiler.plantLoop().get()
        supply = (
            loop.supplyOutletNode()
            .setpointManagers()[0]
            .to_SetpointManagerScheduled()
            .get()
            .schedule()
            .to_ScheduleConstant()
            .get()
            .value()
        )
        reservoir = o.model.PlantComponentTemperatureSource(model)
        reservoir.setTemperatureSpecificationType("Constant")
        # Keep the return below the target by ~3kW at fixed 0.001m3/s, isolating the floor without high-limit cycling.
        reservoir.setSourceTemperature(supply - 3000 / (1000 * 4180 * 0.001))
        reservoir.setDesignVolumeFlowRate(0.001)
        assert reservoir.addToNode(loop.demandOutletNode())
    if mode == "optimum":
        boiler.plantLoop().get().setLoadDistributionScheme("SequentialLoad")
    assert model.save(str(source), True)
    original = source.read_bytes()
    report = preflight(source, config(tmp_path, **settings))
    assert report["ready"] and report["plan"]["simulation_ready"], report
    result = apply(report, tmp_path)
    extra = [
        "Boiler Heating Rate",
        "Boiler Ancillary Electricity Energy",
        "Boiler Ancillary NaturalGas Energy",
    ]
    before = native_run(o, source, tmp_path / "before_run", str(boiler.handle()), extra)
    after = native_run(
        o,
        Path(result["output_model_path"]),
        tmp_path / "after_run",
        str(boiler.handle()),
        extra,
    )
    assert before["hours"] == after["hours"] == 72
    old = json.loads((tmp_path / "before_run/hourly.json").read_text())
    new = json.loads((tmp_path / "after_run/hourly.json").read_text())
    active = [row[3] for row in new[extra[0]] if row[3] > 1]
    if mode == "minimum":
        assert min(active) == pytest.approx(5000, rel=1e-4)
        assert after["heating_j"] > before["heating_j"]
    elif mode == "maximum":
        assert max(active) == pytest.approx(4000, rel=1e-4)
        assert after["heating_j"] < before["heating_j"]
    else:
        assert after["heating_j"] == pytest.approx(before["heating_j"], rel=1e-6)
        assert after["fuel_j"] == pytest.approx(before["fuel_j"], rel=1e-6)
    assert source.read_bytes() == original
    (tmp_path / "part_load_native.json").write_text(
        json.dumps(
            dict(
                mode=mode,
                settings=settings,
                before=before,
                after=after,
                ancillary_before_j={
                    name: sum(r[3] for r in old[name]) for name in extra[1:]
                },
                ancillary_after_j={
                    name: sum(r[3] for r in new[name]) for name in extra[1:]
                },
                validation=result["validation"],
                translation=result["translation"],
                source_unchanged=True,
            ),
            indent=2,
        )
    )


@pytest.mark.parametrize("field", list(boilers.PLR_FIELDS))
def test_part_load_noops_reject(sdk, tmp_path, field):
    source, _, boiler = fixture(sdk[0], tmp_path)
    value = boilers.part_load_values(boiler, {})[field]
    report = preflight(source, config(tmp_path, **{field: value}))
    assert not report["ready"] and "must change" in " ".join(report["plan"]["errors"])


@pytest.mark.parametrize("field", list(boilers.PLR_FIELDS))
@pytest.mark.parametrize("problem", ["mismatch", "malformed"])
def test_part_load_translation_errors_do_not_capture_failure(
    sdk, tmp_path, monkeypatch, field, problem
):
    source, _, _ = fixture(sdk[0], tmp_path)
    original = source.read_bytes()
    translate = boilers.translated_workspace

    def altered(model, o, label):
        workspace = translate(model, o, label)
        obj = workspace.getObjectsByType(o.IddObjectType("Boiler_HotWater"))[0]
        index = obj.iddObject().getFieldIndex(boilers.PLR_FIELDS[field][1]).get()
        assert (
            obj.setString(index, "not-a-number")
            if problem == "malformed"
            else obj.setDouble(index, 0.123)
        )
        return workspace

    monkeypatch.setattr(boilers, "translated_workspace", altered)
    captured = []
    monkeypatch.setattr(
        tx, "capture_exception", lambda *args, **kwargs: captured.append(args) or {}
    )
    settings = dict(
        minimum_part_load_ratio=0.2,
        optimum_part_load_ratio=0.8,
        maximum_part_load_ratio=1,
    )
    cfg = tmp_path / "request.json"
    cfg.write_text(json.dumps(config(tmp_path, **settings)))
    report_path = tmp_path / "blocked.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "edit_boiler_performance.py",
            "--input",
            str(source),
            "--config",
            str(cfg),
            "--report",
            str(report_path),
        ],
    )
    assert (
        tx.cli(
            OPERATION,
            boilers.plan,
            boilers.edit,
            boilers.validate_model,
            boilers.inventory,
        )
        == 2
    )
    report = json.loads(report_path.read_text())
    assert not report["ready"] and report["plan"]["errors"] and not captured
    assert source.read_bytes() == original and not (tmp_path / "edited.osm").exists()
