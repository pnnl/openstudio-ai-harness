"""District capacity edits retain graph, schedule, references and source bytes."""

import json
from pathlib import Path
import sys

import pytest
from test_vav_preflight import sdk, SCRIPTS

sys.path.insert(0, str(SCRIPTS))
from common import district_edit as district, model_transaction as tx, plant_create

OPERATION = "edit_district_capacity"


def fixture(o, folder, kind="DistrictHeatingWater", before="Autosize"):
    model = o.model.Model()
    role = "hot_water" if kind == "DistrictHeatingWater" else "chilled_water"
    planned = plant_create.plan(
        model,
        o,
        dict(
            output_model_path=str(folder / "unused.osm"),
            defaults_profile="prototype_plants_v1",
            **{role: dict(name="Plant", source=kind)},
        ),
    )
    plant_create.create(model, o, planned)
    obj = getattr(model, "get" + kind + "s")()[0]
    obj.setName("Selected District")
    if before != "Autosize":
        assert obj.setNominalCapacity(before)
    obj.additionalProperties().setFeature("review_note", "retain")
    source = folder / "before.osm"
    assert model.save(str(source), True)
    return source, model, obj


def config(folder, capacity=10000):
    return dict(
        output_model_path=str(folder / "edited.osm"),
        plant_loop=dict(name="Plant"),
        district_equipment=dict(name="Selected District"),
        settings=dict(nominal_capacity_w=capacity),
    )


def preflight(source, cfg):
    return tx.preflight(source, cfg, OPERATION, district.plan)


def apply(report, folder, creator=None):
    path = folder / "reviewed.json"
    path.write_text(json.dumps(report))
    return tx.apply(
        path,
        OPERATION,
        district.plan,
        creator or district.edit,
        district.validate_model,
    )


@pytest.mark.parametrize("kind", ["DistrictHeatingWater", "DistrictCooling"])
@pytest.mark.parametrize(
    "before,after", [("Autosize", 10000), (10000, 20000), (10000, "Autosize")]
)
def test_values_identity_graph_schedule_and_references(
    sdk, tmp_path, kind, before, after
):
    o = sdk[0]
    source, model, obj = fixture(o, tmp_path, kind, before)
    cost = o.model.LifeCycleCost.createLifeCycleCost(
        "Maintenance", obj, 100, "CostPerEach", "Maintenance", 1, 0
    ).get()
    actuator = o.model.EnergyManagementSystemActuator(
        obj,
        "Plant Component "
        + (
            "DistrictHeating:Water"
            if kind == "DistrictHeatingWater"
            else "DistrictCooling"
        ),
        "On/Off Supervisory",
    )
    refs = {
        str(x.handle()): str(x.idfObject())
        for x in (
            cost,
            actuator,
            obj.capacityFractionSchedule(),
            obj.additionalProperties(),
        )
    }
    model.save(str(source), True)
    original = source.read_bytes()
    report = preflight(source, config(tmp_path, after))
    assert report["ready"], report
    assert report == preflight(source, config(tmp_path, after))
    assert report["plan"]["impact"]["ems_actuator_count"] == 1
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and result["translation"]["ok"], result
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    current = district.equipment(
        saved, o, report["plan"]["resolved_objects"]["district_equipment"]
    )
    assert district.values(current) == dict(nominal_capacity_w=after)
    assert district.ports(current) == district.ports(obj)
    for handle, raw in refs.items():
        assert str(saved.getModelObject(o.toUUID(handle)).get().idfObject()) == raw
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    "value", [0, -1, True, "10000", "autosize", float("nan"), float("inf")]
)
def test_invalid_capacities(sdk, tmp_path, value):
    source, _, _ = fixture(sdk[0], tmp_path)
    with pytest.raises(ValueError, match="Invalid district capacity"):
        preflight(source, config(tmp_path, value))
    assert not (tmp_path / "edited.osm").exists()


@pytest.mark.parametrize("key", ["plant_loop", "district_equipment", "settings"])
def test_missing_choices_unready(sdk, tmp_path, key):
    source, _, _ = fixture(sdk[0], tmp_path)
    cfg = config(tmp_path)
    del cfg[key]
    report = preflight(source, cfg)
    assert not report["ready"] and key in report["plan"]["missing_inputs"]


@pytest.mark.parametrize("mode", ["stale", "tampered"])
def test_exact_review_and_source_checks(sdk, tmp_path, mode):
    source, _, _ = fixture(sdk[0], tmp_path)
    report = preflight(source, config(tmp_path))
    if mode == "stale":
        source.write_bytes(source.read_bytes() + b"\n! changed\n")
    else:
        report["plan"]["after_values"]["nominal_capacity_w"] = 20000
    with pytest.raises(ValueError):
        apply(report, tmp_path)
    assert not (tmp_path / "edited.osm").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "capacity",
        "schedule",
        "metadata",
        "pump",
        "sizing",
        "dispatch",
        "ports",
        "object",
    ],
)
def test_unrequested_mutations_not_published(sdk, tmp_path, mutation):
    o = sdk[0]
    source, _, _ = fixture(o, tmp_path)
    report = preflight(source, config(tmp_path))

    def altered(model, sdk, planned):
        result = district.edit(model, sdk, planned)
        obj = district.equipment(
            model, sdk, planned["resolved_objects"]["district_equipment"]
        )
        loop = obj.plantLoop().get()
        if mutation == "capacity":
            obj.setNominalCapacity(20000)
        elif mutation == "schedule":
            obj.capacityFractionSchedule().to_ScheduleConstant().get().setValue(0.5)
        elif mutation == "metadata":
            obj.additionalProperties().setFeature("changed", True)
        elif mutation == "pump":
            model.getPumpVariableSpeeds()[0].setRatedPumpHead(1)
        elif mutation == "sizing":
            loop.sizingPlant().setLoopDesignTemperatureDifference(1)
        elif mutation == "dispatch":
            loop.setLoadDistributionScheme("SequentialLoad")
        elif mutation == "ports":
            obj.removeFromLoop()
        else:
            o.model.ScheduleConstant(model)
        return result

    with pytest.raises(ValueError):
        apply(report, tmp_path, altered)
    assert not (tmp_path / "edited.osm").exists()


@pytest.mark.parametrize("fraction", [0, 0.5, 1.5])
def test_retained_schedule_multiplier_visible(sdk, tmp_path, fraction):
    source, model, obj = fixture(sdk[0], tmp_path)
    obj.capacityFractionSchedule().to_ScheduleConstant().get().setValue(fraction)
    model.save(str(source), True)
    report = preflight(source, config(tmp_path))
    assert report["ready"], report
    assert report["plan"]["impact"]["effective_constant_limit_w"] == 10000 * fraction
    assert "not electric watts, COP or efficiency" in " ".join(report["warnings"])


def test_noop_out_of_scope_and_unsupported_steam(sdk, tmp_path):
    o = sdk[0]
    source, model, obj = fixture(o, tmp_path, before=10000)
    assert not preflight(source, config(tmp_path))["ready"]
    cfg = config(tmp_path, 20000)
    cfg["settings"]["cop"] = 5
    with pytest.raises(ValueError):
        preflight(source, cfg)
    loop = obj.plantLoop().get()
    obj.remove()
    steam = o.model.DistrictHeatingSteam(model)
    steam.setName("Selected District")
    loop.addSupplyBranchForComponent(steam)
    model.save(str(source), True)
    report = preflight(source, config(tmp_path))
    assert not report["ready"] and "steam" in " ".join(report["plan"]["errors"])
    assert not district.inventory(model)["plant_loops"][0]["equipment"][0]["supported"]


@pytest.mark.parametrize("missing", ["pump", "setpoint", "weather"])
def test_rating_edit_allowed_with_simulation_blocker(sdk, tmp_path, missing):
    o = sdk[0]
    source, model, _ = fixture(o, tmp_path)
    if missing == "pump":
        model.getPumpVariableSpeeds()[0].remove()
    elif missing == "setpoint":
        model.getSetpointManagerScheduleds()[0].remove()
    model.save(str(source), True)
    report = preflight(source, config(tmp_path))
    assert report["ready"] and not report["plan"]["simulation_ready"]
    assert apply(report, tmp_path)["validation"]["ok"]


@pytest.mark.parametrize("problem", ["missing", "mismatch"])
def test_source_translation_problems_are_normal_plan_errors(
    sdk, tmp_path, monkeypatch, problem
):
    source, _, _ = fixture(sdk[0], tmp_path)
    original = district.translated_state

    def changed(*args):
        if problem == "missing":
            raise ValueError("Cannot identify one translated district source")
        result = original(*args)
        result["settings"]["nominal_capacity_w"] = 77
        return result

    monkeypatch.setattr(district, "translated_state", changed)
    report = preflight(source, config(tmp_path))
    assert not report["ready"] and report["plan"]["errors"]


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_native_relocated_exports(sdk, tmp_path, host):
    import shutil
    import subprocess
    from adapters.claude_code_adapter import ClaudeCodeAdapter
    from adapters.codex_adapter import CodexAdapter
    from adapters.contracts import HostAdapterConfig
    from plugin_fixture import copy_plugin_for_skill
    from test_supply_fan_performance import native_cli

    exe = str(native_cli())
    source, _, _ = fixture(sdk[0], tmp_path)
    adapter = (ClaudeCodeAdapter if host == "claude" else CodexAdapter)(
        HostAdapterConfig(
            host_name=host, workspace_root=Path.cwd(), runtime_mode="marketplace"
        )
    )
    exported = tmp_path / "export"
    adapter.export_plugin(exported, dry_run=False)
    skill = next(exported.rglob("openstudio-district-capacity-editor/SKILL.md")).parent
    for relative in [
        "scripts/doctor.py",
        "scripts/sdk_probe.py",
        "scripts/prepare_model.py",
        "../../sdk/references/model_preparation.md",
        "../../sdk/references/district_capacity.schema.json",
    ]:
        assert (skill / relative).is_file()
    skill = copy_plugin_for_skill(skill, tmp_path / "relocated")
    shutil.rmtree(exported)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config(tmp_path)))
    reviewed = tmp_path / "plan.json"
    repeat = tmp_path / "repeat.json"
    for args in [
        ["--input", str(source), "--report", str(tmp_path / "inventory.json")],
        ["--input", str(source), "--config", str(cfg), "--report", str(reviewed)],
        ["--input", str(source), "--config", str(cfg), "--report", str(repeat)],
        ["--plan", str(reviewed), "--report", str(tmp_path / "apply.json")],
    ]:
        run = subprocess.run(
            [
                exe,
                "execute_python_script",
                str(skill / "scripts/edit_district_capacity.py"),
                *args,
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(reviewed.read_text()) == json.loads(repeat.read_text())
    assert json.loads((tmp_path / "apply.json").read_text())["validation"]["ok"]


def native_run(o, source, folder, handle, additional_handles=()):
    import sqlite3
    import subprocess
    from test_supply_fan_performance import native_cli

    folder.mkdir()
    model = o.osversion.VersionTranslator().loadModel(str(source)).get()
    obj = model.getModelObject(o.toUUID(handle)).get()
    heating = obj.to_DistrictHeatingWater().is_initialized()
    prefix = "District Heating Water " if heating else "District Cooling Water "
    variables = [
        prefix + x
        for x in [
            "Rate",
            "Energy",
            "Inlet Temperature",
            "Outlet Temperature",
            "Mass Flow Rate",
        ]
    ]
    sources = [obj] + [
        model.getModelObject(o.toUUID(h)).get() for h in additional_handles
    ]
    for item in sources:
        for name in variables:
            output = o.model.OutputVariable(name, model)
            output.setKeyValue(item.nameString())
            output.setReportingFrequency("Hourly")
    owner = district.equipment(model, o, dict(handle=handle)).plantLoop().get()
    plant_variables = [
        "Plant Supply Side Heating Demand Rate",
        "Plant Supply Side Cooling Demand Rate",
        "Plant Supply Side Not Distributed Demand Rate",
        "Plant Supply Side Unmet Demand Rate",
    ]
    pumps = [
        x
        for x in owner.supplyComponents()
        if x.iddObjectType().valueName().startswith("OS_Pump_")
    ]
    pump_variables = ["Pump Electricity Energy", "Pump Mass Flow Rate"]
    for item, names in [(owner, plant_variables)] + [
        (pump, pump_variables) for pump in pumps
    ]:
        for name in names:
            output = o.model.OutputVariable(name, model)
            output.setKeyValue(item.nameString())
            output.setReportingFrequency("Hourly")
    weather = Path(str(model.getWeatherFile().path().get()))
    if not weather.is_absolute():
        weather = source.parent / weather
    assert o.model.WeatherFile.setWeatherFile(
        model, o.EpwFile(str(weather.resolve()))
    ).is_initialized()
    model.save(str(folder / "instrumented.osm"), True)
    workflow = folder / "workflow.osw"
    workflow.write_text(
        json.dumps(dict(seed_file=str(folder / "instrumented.osm"), steps=[]))
    )
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

        def query(name, key):
            rows = sql.execute(
                "SELECT r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE d.Name=? AND lower(d.KeyValue)=lower(?) AND t.WarmupFlag=0 ORDER BY t.TimeIndex",
                (name, key),
            ).fetchall()
            assert rows, (name, key)
            return [x[0] for x in rows]

        source_hourly = {
            str(item.handle()): {
                name: query(name, item.nameString()) for name in variables
            }
            for item in sources
        }
        hourly = source_hourly[handle]
        plant_hourly = {
            name: query(name, owner.nameString()) for name in plant_variables
        }
        pump_hourly = {
            str(pump.handle()): {
                name: query(name, pump.nameString()) for name in pump_variables
            }
            for pump in pumps
        }
        sizes = sql.execute(
            "SELECT Description,Value FROM ComponentSizes WHERE lower(CompName)=lower(?)",
            (obj.nameString(),),
        ).fetchall()
        owner = district.equipment(model, o, dict(handle=handle)).plantLoop().get()
        plant_design = sql.execute(
            "SELECT Value FROM ComponentSizes WHERE lower(CompName)=lower(?) AND Description='Design Capacity'",
            (owner.nameString(),),
        ).fetchone()
        meter = (
            "DistrictHeatingWater:Facility" if heating else "DistrictCooling:Facility"
        )
        energy = sum(
            x[0]
            for x in sql.execute(
                "SELECT r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) WHERE lower(d.Name)=lower(?) AND d.IsMeter=1",
                (meter,),
            ).fetchall()
        )
    assert all(hourly.values())
    observed = dict(
        hours=len(hourly[variables[0]]),
        peak_w=max(hourly[variables[0]]),
        energy_j=sum(hourly[variables[1]]),
        meter_j=energy,
        sizes=sizes,
        warnings=err,
        plant_design_capacity_w=plant_design[0] if plant_design else None,
    )
    observed["other_sources"] = {
        key: dict(
            peak_w=max(data[prefix + "Rate"]),
            energy_j=sum(data[prefix + "Energy"]),
            hourly=data,
        )
        for key, data in source_hourly.items()
        if key != handle
    }
    observed["plant_hourly"] = plant_hourly
    observed["pump_hourly"] = pump_hourly
    delivered = observed["energy_j"] + sum(
        x["energy_j"] for x in observed["other_sources"].values()
    )
    assert observed["meter_j"] == pytest.approx(delivered, rel=1e-8)
    (folder / "hourly.json").write_text(json.dumps(hourly, indent=2))
    (folder / "observed.json").write_text(json.dumps(observed, indent=2))
    return observed


def load_fixture(o, folder, kind, reservoir_enabled=True):
    source, model, obj = fixture(o, folder, kind, 10000)
    cooling = kind == "DistrictCooling"
    capacity_fraction = o.model.ScheduleConstant(model)
    capacity_fraction.setName("District Capacity Fraction")
    capacity_fraction.setValue(0.5)
    assert obj.setCapacityFractionSchedule(capacity_fraction)
    loop = obj.plantLoop().get()
    loop.setMaximumLoopFlowRate(0.001)
    loop.setPlantLoopVolume(0.1)
    pump = (
        model.getPumpVariableSpeeds()[0]
        if model.getPumpVariableSpeeds()
        else model.getPumpConstantSpeeds()[0]
    )
    pump.setRatedFlowRate(0.001)
    pump.setRatedPowerConsumption(100)
    pump.setRatedPumpHead(50000)
    loads = o.model.ScheduleRuleset(model)
    sign = -1 if cooling else 1
    loads.defaultDaySchedule().addValue(o.Time(0, 6, 0, 0), 0)
    loads.defaultDaySchedule().addValue(o.Time(0, 12, 0, 0), 3000 * sign)
    loads.defaultDaySchedule().addValue(o.Time(0, 18, 0, 0), 6000 * sign)
    loads.defaultDaySchedule().addValue(o.Time(0, 24, 0, 0), 0)
    flows = o.model.ScheduleConstant(model)
    flows.setValue(1)
    load = o.model.LoadProfilePlant(model)
    load.setLoadSchedule(loads)
    load.setPeakFlowRate(0.001)
    load.setFlowRateFractionSchedule(flows)
    assert loop.addDemandBranchForComponent(load)
    # Test reservoir holds the return temperature away from loop protection bounds;
    # otherwise EnergyPlus temperature clamping can override the capacity limit.
    if reservoir_enabled:
        reservoir = o.model.PlantComponentTemperatureSource(model)
        reservoir.setTemperatureSpecificationType("Constant")
        reservoir.setSourceTemperature(12 if cooling else 60)
        reservoir.setDesignVolumeFlowRate(0.001)
        assert reservoir.addToNode(loop.demandOutletNode())
    design = o.model.DesignDay(model)
    design.setName("District Design Day")
    design.setDayType("SummerDesignDay" if cooling else "WinterDesignDay")
    design.setMonth(7 if cooling else 1)
    design.setDayOfMonth(21)
    design.setMaximumDryBulbTemperature(30 if cooling else 10)
    design.setBarometricPressure(101325)
    design.setDailyDryBulbTemperatureRange(0)
    design.setHumidityConditionType("Wetbulb")
    design.setWetBulbOrDewPointAtMaximumDryBulb(20 if cooling else 0)
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
    model.save(str(source), True)
    return source, model, obj


@pytest.mark.parametrize("kind", ["DistrictHeatingWater", "DistrictCooling"])
def test_native_capacity_schedule_limits_and_meter(sdk, tmp_path, kind):
    from test_supply_fan_performance import native_cli

    native_cli()
    o = sdk[0]
    source, _, obj = load_fixture(o, tmp_path, kind)
    original = source.read_bytes()
    report = preflight(source, config(tmp_path, 2000))
    assert report["ready"] and report["plan"]["simulation_ready"], report
    result = apply(report, tmp_path)
    before = native_run(o, source, tmp_path / "before_run", str(obj.handle()))
    after = native_run(
        o, Path(result["output_model_path"]), tmp_path / "after_run", str(obj.handle())
    )
    assert before["hours"] == after["hours"] == 24
    assert before["peak_w"] == pytest.approx(5000, rel=1e-6)
    assert after["peak_w"] == pytest.approx(1000, rel=1e-6)
    assert after["energy_j"] < before["energy_j"]
    assert source.read_bytes() == original
    (tmp_path / "native_evidence.json").write_text(
        json.dumps(
            dict(
                before=before,
                after=after,
                source_unchanged=True,
                validation=result["validation"],
                translation=result["translation"],
            ),
            indent=2,
        )
    )


@pytest.mark.parametrize("kind", ["DistrictHeatingWater", "DistrictCooling"])
def test_native_explicit_autosize_design_day(sdk, tmp_path, kind):
    from test_supply_fan_performance import native_cli
    from vav_fixture import prepare_vav_fixture
    from common import cav_system

    native_cli()
    o = sdk[0]
    unserved, cfg, seed, seed_bytes = prepare_vav_fixture(o, tmp_path, True)
    model = o.osversion.VersionTranslator().loadModel(str(unserved)).get()
    cfg.update(defaults_profile="prototype_cav_v1", outdoor_air_schedule=None)
    cav = cav_system.plan(model, o, cfg)
    assert cav["ready"], cav
    cav_system.create(model, o, cav)
    obj = getattr(model, "get" + kind + "s")()[0]
    obj.setName("Selected District")
    obj.setNominalCapacity(1e6)
    obj.plantLoop().get().setName("Plant")
    source = tmp_path / "before.osm"
    model.save(str(source), True)
    original = source.read_bytes()
    report = preflight(source, config(tmp_path, "Autosize"))
    assert report["ready"] and report["plan"]["simulation_ready"], report
    result = apply(report, tmp_path)
    before = native_run(o, source, tmp_path / "before_run", str(obj.handle()))
    after = native_run(
        o, Path(result["output_model_path"]), tmp_path / "after_run", str(obj.handle())
    )
    assert before["hours"] == after["hours"] == 72
    assert after["energy_j"] > 1e7
    # Coupled heating/cooling operation need not preserve or monotonically reduce
    # purchased energy. Verify native sizing against the independently sized loop.
    assert before["plant_design_capacity_w"] == pytest.approx(
        after["plant_design_capacity_w"], rel=1e-9
    )
    sizes = dict(after["sizes"])
    assert 0 < sizes["Design Size Nominal Capacity"] < 1e6
    assert sizes["Design Size Nominal Capacity"] == pytest.approx(
        after["plant_design_capacity_w"], rel=1e-9
    )
    assert source.read_bytes() == original and seed.read_bytes() == seed_bytes
    (tmp_path / "native_evidence.json").write_text(
        json.dumps(
            dict(
                before=before,
                after=after,
                source_unchanged=True,
                validation=result["validation"],
                translation=result["translation"],
            ),
            indent=2,
        )
    )


@pytest.mark.parametrize("fraction", [0.5, 0])
def test_native_temperature_protection_can_override_capacity(sdk, tmp_path, fraction):
    from test_supply_fan_performance import native_cli

    native_cli()
    o = sdk[0]
    source, _, obj = load_fixture(
        o, tmp_path, "DistrictHeatingWater", reservoir_enabled=False
    )
    obj.capacityFractionSchedule().to_ScheduleConstant().get().setValue(fraction)
    model = obj.model()
    assert model.save(str(source), True)
    report = preflight(source, config(tmp_path, 2000))
    assert "zero schedule is not a guaranteed off switch" in " ".join(
        report["warnings"]
    )
    assert "can override" in " ".join(report["warnings"])
    result = apply(report, tmp_path)
    observed = native_run(
        o, Path(result["output_model_path"]), tmp_path / "after_run", str(obj.handle())
    )
    assert observed["peak_w"] > 1000
    hourly = json.loads((tmp_path / "after_run/hourly.json").read_text())
    assert min(hourly["District Heating Water Outlet Temperature"]) == pytest.approx(
        10, abs=1e-7
    )


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
    model.getPlantLoopByName("Plant").get().addDemandBranchForComponent(load)
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


@pytest.mark.parametrize("role", ["Heating", "Cooling", "Condenser"])
def test_inventory_and_planner_agree_on_loop_roles(sdk, tmp_path, role):
    source, model, obj = fixture(sdk[0], tmp_path)
    obj.plantLoop().get().sizingPlant().setLoopType(role)
    model.save(str(source), True)
    inv = district.inventory(model)
    assert inv["plant_loops"][0]["equipment"][0]["supported"]
    report = preflight(source, config(tmp_path))
    assert report["ready"], report
    assert report["plan"]["impact"]["loop_type"] == role
    assert ("different sizing role" in " ".join(report["warnings"])) == (
        role != "Heating"
    )


@pytest.mark.parametrize("kind", ["DistrictHeatingWater", "DistrictCooling"])
@pytest.mark.parametrize("scheme", ["SequentialLoad", "UniformPLR"])
def test_native_two_sources_dispatch_share_and_unreallocated_shortfall(
    sdk, tmp_path, kind, scheme
):
    from test_supply_fan_performance import native_cli

    native_cli()
    o = sdk[0]
    source, model, obj = load_fixture(o, tmp_path, kind)
    loop = obj.plantLoop().get()
    cooling = kind == "DistrictCooling"
    backup = getattr(o.model, kind)(model)
    backup.setName("Backup District")
    backup.setNominalCapacity(20000)
    fraction = o.model.ScheduleConstant(model)
    fraction.setValue(1)
    backup.setCapacityFractionSchedule(fraction)
    assert loop.addSupplyBranchForComponent(backup)
    reservoir = model.getPlantComponentTemperatureSources()[0]
    target = loop.sizingPlant().designLoopExitTemperature()
    reservoir.setSourceTemperature(target + (5.5 if cooling else -5.5))
    operation = (
        o.model.PlantEquipmentOperationCoolingLoad
        if cooling
        else o.model.PlantEquipmentOperationHeatingLoad
    )(model)
    assert operation.addEquipment(obj) and operation.addEquipment(backup)
    assert getattr(
        loop,
        "setPlantEquipmentOperation" + ("CoolingLoad" if cooling else "HeatingLoad"),
    )(operation)
    assert loop.setLoadDistributionScheme(scheme)
    assert model.save(str(source), True)
    original = source.read_bytes()
    report = preflight(source, config(tmp_path, 4000))
    assert report["ready"] and report["plan"]["simulation_ready"], report
    assert report["plan"]["impact"]["load_distribution_scheme"] == scheme
    assert not report["plan"]["impact"][
        "dispatch_design_capacity_includes_schedule_fraction"
    ]
    assert "redistribute load between sources" in " ".join(report["warnings"])
    result = apply(report, tmp_path)
    before = native_run(
        o, source, tmp_path / "before_run", str(obj.handle()), [str(backup.handle())]
    )
    after = native_run(
        o,
        Path(result["output_model_path"]),
        tmp_path / "after_run",
        str(obj.handle()),
        [str(backup.handle())],
    )
    for observed, nominal in ((before, 10000), (after, 4000)):
        spare = observed["other_sources"][str(backup.handle())]
        demands = observed["plant_hourly"][
            "Plant Supply Side "
            + ("Cooling" if cooling else "Heating")
            + " Demand Rate"
        ]
        expected_backup = [
            d - nominal if scheme == "SequentialLoad" else d * 20000 / (nominal + 20000)
            for d in demands
        ]
        assert spare["hourly"][
            ("District Cooling Water " if cooling else "District Heating Water ")
            + "Rate"
        ] == pytest.approx(expected_backup, rel=1e-9)
        assert observed["peak_w"] == pytest.approx(nominal * 0.5, rel=1e-9)
        assert 0 < spare["peak_w"] < 20000
        assert (
            max(
                abs(x)
                for x in observed["plant_hourly"]["Plant Supply Side Unmet Demand Rate"]
            )
            > 100
        )
        assert (
            max(
                abs(x)
                for x in observed["plant_hourly"][
                    "Plant Supply Side Not Distributed Demand Rate"
                ]
            )
            < 1
        )
    before_unmet = max(
        abs(x) for x in before["plant_hourly"]["Plant Supply Side Unmet Demand Rate"]
    )
    assert (
        20000 - before["other_sources"][str(backup.handle())]["peak_w"] > before_unmet
    )
    assert after["peak_w"] == pytest.approx(2000, rel=1e-6)
    assert (
        after["other_sources"][str(backup.handle())]["energy_j"]
        > before["other_sources"][str(backup.handle())]["energy_j"]
    )
    # The district model still requests full design flow. Actual mass flow/pump
    # energy can differ slightly through the loop's temperature/density response;
    # neither should scale with the 60% nominal-capacity reduction in this case.
    for handle, data in before["pump_hourly"].items():
        for variable, values in data.items():
            assert after["pump_hourly"][handle][variable] == pytest.approx(
                values, rel=0.01
            )
    assert source.read_bytes() == original
    (tmp_path / "native_evidence.json").write_text(
        json.dumps(
            dict(
                before=before,
                after=after,
                scheme=scheme,
                source_unchanged=True,
                validation=result["validation"],
                translation=result["translation"],
            ),
            indent=2,
        )
    )


@pytest.mark.parametrize("backup_kind", ["DistrictHeatingWater", "BoilerHotWater"])
def test_dispatch_warning_includes_mixed_source_plants(sdk, tmp_path, backup_kind):
    o = sdk[0]
    source, model, obj = fixture(o, tmp_path)
    backup = getattr(o.model, backup_kind)(model)
    obj.plantLoop().get().addSupplyBranchForComponent(backup)
    obj.capacityFractionSchedule().to_ScheduleConstant().get().setValue(0.5)
    model.save(str(source), True)
    report = preflight(source, config(tmp_path))
    assert report["ready"], report
    text = " ".join(report["warnings"])
    assert "maximum/optimal load without the capacity-fraction schedule" in text
    assert "shortfall may remain unmet instead of being reassigned" in text
    assert "full design water flow before capacity limiting" in text
