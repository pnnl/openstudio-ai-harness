"""Terminal controls retain equipment identity, service and every unselected field."""

import json
from pathlib import Path
import sys
import pytest
from test_vav_preflight import sdk, model_file, SCRIPTS
from test_supply_fan_performance import served_model

sys.path.insert(0, str(SCRIPTS))
from common import model_transaction as tx, terminal_edit as terminals

OPERATION = "edit_terminal"


def fixture(o, source, folder, system="VariableVolume", reheat=True):
    model, _ = served_model(o, source, folder, system)
    zone = model.getThermalZoneByName("Zone 1").get()
    old = zone.airLoopHVACTerminals()[0]
    if not reheat:
        loop = model.getAirLoopHVACs()[0]
        assert loop.removeBranchForZone(zone)
        old = o.model.AirTerminalSingleDuctVAVNoReheat(
            model, model.alwaysOnDiscreteSchedule()
        )
        assert loop.addBranchForZone(zone, old)
    else:
        old = old.to_AirTerminalSingleDuctVAVReheat().get()
    old.setName("Selected Terminal")
    old.additionalProperties().setFeature("review_note", "retain")
    model.save(str(source), True)
    return model, old


def config(folder, **settings):
    return dict(
        output_model_path=str(folder / "edited.osm"),
        air_loop={"name": "Existing Air Loop"},
        zone={"name": "Zone 1"},
        terminal={"name": "Selected Terminal"},
        settings=settings or dict(minimum_airflow_fraction=0.2),
    )


def preflight(source, cfg):
    return tx.preflight(source, cfg, OPERATION, terminals.plan)


def apply(report, folder, creator=None):
    path = folder / "plan.json"
    path.write_text(json.dumps(report))
    return tx.apply(
        path,
        OPERATION,
        terminals.plan,
        creator or terminals.edit,
        terminals.validate_model,
    )


@pytest.mark.parametrize("system", ["VariableVolume", "ConstantVolume"])
@pytest.mark.parametrize("reheat", [True, False])
def test_saved_values_identity_and_protected_state(
    sdk, model_file, tmp_path, system, reheat
):
    o = sdk[0]
    model, terminal = fixture(o, model_file, tmp_path, system, reheat)
    cost = o.model.LifeCycleCost.createLifeCycleCost(
        "Maintenance", terminal, 100, "CostPerEach", "Maintenance", 1, 0
    ).get()
    handle = str(terminal.handle())
    metadata = str(terminal.additionalProperties().handle())
    raw_cost = str(cost.idfObject())
    model.save(str(model_file), True)
    original = model_file.read_bytes()
    report = preflight(model_file, config(tmp_path))
    assert report["ready"], report
    assert report == preflight(model_file, config(tmp_path))
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and result["translation"]["ok"]
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    edited = terminals.typed(saved, o, report["plan"]["resolved_objects"]["terminal"])
    assert str(edited.handle()) == handle
    assert str(edited.additionalProperties().handle()) == metadata
    assert edited.constantMinimumAirFlowFraction().get() == pytest.approx(0.2)
    assert str(saved.getModelObject(cost.handle()).get().idfObject()) == raw_cost
    assert model_file.read_bytes() == original


@pytest.mark.parametrize(
    "settings,getter",
    [
        (dict(maximum_reheat_temperature_c=32), "maximumReheatAirTemperature"),
        (dict(damper_heating_action="Normal"), "damperHeatingAction"),
        (
            dict(
                maximum_reheat_flow_fraction=0.6,
                maximum_reheat_flow_per_area_m3_s_m2="Autosize",
            ),
            "maximumFlowFractionDuringReheat",
        ),
        (
            dict(maximum_reheat_flow_per_area_m3_s_m2="Autosize"),
            "maximumFlowPerZoneFloorAreaDuringReheat",
        ),
    ],
)
def test_water_reheat_settings_are_saved(sdk, model_file, tmp_path, settings, getter):
    fixture(sdk[0], model_file, tmp_path, "ConstantVolume")
    report = preflight(model_file, config(tmp_path, **settings))
    assert report["ready"], report
    result = apply(report, tmp_path)
    assert result["validation"]["ok"]
    saved = (
        sdk[0]
        .osversion.VersionTranslator()
        .loadModel(result["output_model_path"])
        .get()
    )
    terminal = saved.getAirTerminalSingleDuctVAVReheats()[0]
    expected = next(iter(settings.values()))
    if expected == "Autosize":
        assert terminal.isMaximumFlowPerZoneFloorAreaDuringReheatAutosized()
    else:
        assert terminals.optional(getattr(terminal, getter)()) == expected


@pytest.mark.parametrize(
    "settings",
    [
        dict(minimum_airflow_fraction=-0.1),
        dict(minimum_airflow_fraction=1.1),
        dict(minimum_airflow_fraction=True),
        dict(minimum_airflow_fraction=float("nan")),
        dict(maximum_reheat_temperature_c=101),
        dict(maximum_reheat_temperature_c="30"),
        dict(maximum_reheat_flow_fraction="Autosize"),
        dict(maximum_reheat_flow_per_area_m3_s_m2=-0.1),
        dict(maximum_reheat_flow_per_area_m3_s_m2=0),
        dict(maximum_reheat_flow_per_area_m3_s_m2=0.003),
        dict(damper_heating_action="Dual Maximum"),
        dict(maximum_airflow_m3_s=1),
        dict(unknown=1),
    ],
)
def test_invalid_input_rejected(sdk, model_file, tmp_path, settings):
    fixture(sdk[0], model_file, tmp_path)
    with pytest.raises(ValueError, match="Invalid terminal"):
        preflight(model_file, config(tmp_path, **settings))


@pytest.mark.parametrize("method", ["FixedFlowRate", "Scheduled"])
def test_inactive_fraction_rejected_without_switching_method(
    sdk, model_file, tmp_path, method
):
    o = sdk[0]
    model, terminal = fixture(o, model_file, tmp_path)
    terminal.setZoneMinimumAirFlowInputMethod(method)
    if method == "Scheduled":
        terminal.setMinimumAirFlowFractionSchedule(model.alwaysOnDiscreteSchedule())
    else:
        terminal.setFixedMinimumAirFlowRate(0.1)
    model.save(str(model_file), True)
    report = preflight(model_file, config(tmp_path))
    assert not report["ready"]
    assert "existing Constant" in str(report["plan"]["errors"])
    # A discharge-temperature edit alone retains a valid Scheduled/FixedFlowRate method.
    report = preflight(model_file, config(tmp_path, maximum_reheat_temperature_c=30))
    assert report["ready"], report
    assert apply(report, tmp_path)["validation"]["ok"]


@pytest.mark.parametrize(
    "reheat,settings",
    [
        (False, dict(maximum_reheat_temperature_c=30)),
        (False, dict(damper_heating_action="Normal")),
        (True, dict(damper_heating_action="Reverse")),
        (True, dict(damper_heating_action="ReverseWithLimits")),
        (True, dict(maximum_reheat_flow_fraction=0.6)),
    ],
)
def test_inapplicable_controls_are_unready(sdk, model_file, tmp_path, reheat, settings):
    fixture(sdk[0], model_file, tmp_path, reheat=reheat)
    assert not preflight(model_file, config(tmp_path, **settings))["ready"]


def test_missing_noop_wrong_zone_and_duplicate_names(sdk, model_file, tmp_path):
    o = sdk[0]
    model, terminal = fixture(o, model_file, tmp_path)
    assert not preflight(model_file, dict(output_model_path=str(tmp_path / "out.osm")))[
        "ready"
    ]
    assert not preflight(model_file, config(tmp_path, minimum_airflow_fraction=0.3))[
        "ready"
    ]
    cfg = config(tmp_path)
    cfg["zone"] = {"name": "Missing"}
    assert not preflight(model_file, cfg)["ready"]
    duplicate = o.model.AirTerminalSingleDuctVAVNoReheat(
        model, model.alwaysOnDiscreteSchedule()
    )
    zone = o.model.ThermalZone(model)
    model.getAirLoopHVACs()[0].addBranchForZone(zone, duplicate)
    # Name collisions in different zones are harmless because selection is scoped.
    duplicate.setName(terminal.nameString())
    model.save(str(model_file), True)
    assert preflight(model_file, config(tmp_path))["ready"]


@pytest.mark.parametrize(
    "change",
    [
        "wrong_setter",
        "coil",
        "plant",
        "zone_sizing",
        "system_sizing",
        "maximum_flow",
        "schedule",
        "metadata",
        "extra_object",
        "terminal_oa_control",
        "graph",
    ],
)
def test_unrequested_mutations_do_not_publish(sdk, model_file, tmp_path, change):
    o = sdk[0]
    fixture(o, model_file, tmp_path, "ConstantVolume")
    report = preflight(model_file, config(tmp_path))

    def bad(model, native, planned):
        result = terminals.edit(model, native, planned)
        terminal = terminals.typed(
            model, native, planned["resolved_objects"]["terminal"]
        )
        if change == "wrong_setter":
            terminal.setConstantMinimumAirFlowFraction(0.9)
        elif change == "coil":
            terminal.reheatCoil().to_CoilHeatingWater().get().setRatedCapacity(100)
        elif change == "plant":
            model.getPlantLoops()[0].sizingPlant().setDesignLoopExitTemperature(60)
        elif change == "zone_sizing":
            model.getThermalZoneByName(
                "Zone 1"
            ).get().sizingZone().setHeatingMaximumAirFlowFraction(0.7)
        elif change == "system_sizing":
            model.getAirLoopHVACs()[
                0
            ].sizingSystem().setCentralCoolingDesignSupplyAirTemperature(16)
        elif change == "maximum_flow":
            terminal.setMaximumAirFlowRate(3)
        elif change == "schedule":
            terminal.setAvailabilitySchedule(model.alwaysOffDiscreteSchedule())
        elif change == "metadata":
            terminal.additionalProperties().setFeature("review_note", "changed")
        elif change == "terminal_oa_control":
            terminal.setControlForOutdoorAir(True)
        elif change == "graph":
            model.disconnect(terminal, terminal.inletPort())
        else:
            native.model.FanConstantVolume(model)
        return result

    with pytest.raises(ValueError, match="validation|connected"):
        apply(report, tmp_path, bad)
    assert not (tmp_path / "edited.osm").exists()
    assert not (tmp_path / "edited").exists()


def test_stale_and_tampered_plan_rejected(sdk, model_file, tmp_path):
    model, terminal = fixture(sdk[0], model_file, tmp_path)
    report = preflight(model_file, config(tmp_path))
    report["plan"]["after_values"]["minimum_airflow_fraction"] = 0.8
    with pytest.raises(ValueError, match="differs"):
        apply(report, tmp_path)
    report = preflight(model_file, config(tmp_path))
    terminal.setConstantMinimumAirFlowFraction(0.4)
    model.save(str(model_file), True)
    with pytest.raises(ValueError, match="Stale"):
        apply(report, tmp_path)


def test_schedule_ems_sizing_and_ventilation_warnings(sdk, model_file, tmp_path):
    o = sdk[0]
    model, terminal = fixture(o, model_file, tmp_path, "ConstantVolume")
    terminal.setMaximumAirFlowRate(0.1)
    terminal.setMinimumAirFlowTurndownSchedule(model.alwaysOnDiscreteSchedule())
    actuator = o.model.EnergyManagementSystemActuator(
        terminal, "AirTerminal:SingleDuct:VAV:Reheat", "Mass Flow Rate"
    )
    raw = str(actuator.idfObject())
    model.save(str(model_file), True)
    report = preflight(
        model_file,
        config(
            tmp_path,
            minimum_airflow_fraction=0.8,
            maximum_reheat_flow_fraction=0.5,
            maximum_reheat_flow_per_area_m3_s_m2="Autosize",
        ),
    )
    assert report["ready"]
    warnings = " ".join(report["warnings"])
    assert (
        "turndown" in warnings
        and "EMS" in warnings
        and "below terminal minimum" in warnings
    )
    result = apply(report, tmp_path)
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    assert str(saved.getModelObject(actuator.handle()).get().idfObject()) == raw


def test_definite_ventilation_shortfall_marks_simulation_unready(
    sdk, model_file, tmp_path
):
    o = sdk[0]
    model, terminal = fixture(o, model_file, tmp_path)
    terminal.setMaximumAirFlowRate(0.01)
    zone = model.getThermalZoneByName("Zone 1").get()
    space = zone.spaces()[0]
    oa = o.model.DesignSpecificationOutdoorAir(model)
    oa.setOutdoorAirFlowRate(0.2)
    space.setDesignSpecificationOutdoorAir(oa)
    model.save(str(model_file), True)
    report = preflight(model_file, config(tmp_path))
    assert report["ready"] and report["plan"]["simulation_ready"] is False
    assert report["plan"]["companions"]["simulation_ready"] is False
    assert "100% OA" in " ".join(report["warnings"])


def test_low_minimum_floor_is_not_a_maximum_ventilation_cap(sdk, model_file, tmp_path):
    o = sdk[0]
    model, terminal = fixture(o, model_file, tmp_path)
    terminal.setMaximumAirFlowRate(1)
    zone = model.getThermalZoneByName("Zone 1").get()
    oa = o.model.DesignSpecificationOutdoorAir(model)
    oa.setOutdoorAirFlowRate(0.2)
    zone.spaces()[0].setDesignSpecificationOutdoorAir(oa)
    terminal.setControlForOutdoorAir(True)
    model.save(str(model_file), True)
    report = preflight(model_file, config(tmp_path, minimum_airflow_fraction=0.1))
    assert report["ready"] and report["plan"].get("simulation_ready") is not False
    assert "actual airflow may be raised" in " ".join(report["warnings"])


@pytest.mark.parametrize("multiplier", [1, 10])
def test_zone_multiplier_uses_total_ventilation_demand(
    sdk, model_file, tmp_path, multiplier
):
    o = sdk[0]
    model, terminal = fixture(o, model_file, tmp_path)
    zone = model.getThermalZoneByName("Zone 1").get()
    zone.setMultiplier(multiplier)
    oa = o.model.DesignSpecificationOutdoorAir(model)
    oa.setOutdoorAirFlowRate(0.02)
    zone.spaces()[0].setDesignSpecificationOutdoorAir(oa)
    terminal.setMaximumAirFlowRate(0.05)
    model.save(str(model_file), True)
    report = preflight(model_file, config(tmp_path, minimum_airflow_fraction=0.5))
    assert report["ready"]
    assert report["plan"]["impact"]["nominal_zone_oa_m3_s"] == pytest.approx(
        0.02 * multiplier
    )
    assert report["plan"]["impact"]["maximum_airflow_m3_s"] == 0.05
    assert (report["plan"].get("simulation_ready") is False) == (multiplier == 10)
    assert ("100% OA" in " ".join(report["warnings"])) == (multiplier == 10)


def test_multiplied_real_floor_area_is_evidence_not_an_ignored_runtime_cap(
    sdk, model_file, tmp_path
):
    o = sdk[0]
    model, terminal = fixture(o, model_file, tmp_path, "ConstantVolume")
    zone = model.getThermalZoneByName("Zone 1").get()
    zone.setMultiplier(10)
    polygon = o.Point3dVector()
    for x, y in ((0, 0), (0, 10), (10, 10), (10, 0)):
        polygon.append(o.Point3d(x, y, 0))
    space = o.model.Space.fromFloorPrint(polygon, 3, model).get()
    space.setThermalZone(zone)
    terminal.setMaximumAirFlowRate(1)
    terminal.setMaximumFlowPerZoneFloorAreaDuringReheat(0.002)
    model.save(str(model_file), True)
    report = preflight(model_file, config(tmp_path, minimum_airflow_fraction=0.4))
    assert report["ready"]
    context = report["plan"]["context"]
    assert context["floor_area_per_copy_m2"] == pytest.approx(100)
    assert context["multiplied_floor_area_m2"] == pytest.approx(1000)
    effects = report["plan"]["impact"]["reheat_flow_limits"]
    for mode in ("before", "after"):
        assert effects[mode]["requested_per_area_flow_m3_s"] == pytest.approx(2)
        assert effects[mode]["mode"] == "user_limits_ignored_by_pinned_engine"
        assert effects[mode]["nominal_cap_m3_s"] is None
    assert "ignore the user reheat-flow limits" in " ".join(report["warnings"])


def test_fraction_edit_requires_explicit_per_area_reset(sdk, model_file, tmp_path):
    o = sdk[0]
    model, terminal = fixture(o, model_file, tmp_path, "ConstantVolume")
    original = model_file.read_bytes()
    cfg = config(tmp_path, maximum_reheat_flow_fraction=0.2)
    report = preflight(model_file, cfg)
    assert not report["ready"]
    assert '"Autosize"' in " ".join(report["plan"]["errors"])
    assert (
        report["plan"]["impact"]["reheat_flow_limits"]["after"]["mode"]
        == "user_limits_ignored_by_pinned_engine"
    )
    with pytest.raises(ValueError, match="ready"):
        apply(report, tmp_path)
    assert not (tmp_path / "edited.osm").exists()
    cfg["settings"]["maximum_reheat_flow_per_area_m3_s_m2"] = "Autosize"
    report = preflight(model_file, cfg)
    assert report["ready"], report
    assert report == preflight(model_file, cfg)
    assert (
        report["plan"]["impact"]["reheat_flow_limits"]["after"]["mode"]
        == "fraction_only"
    )
    result = apply(report, tmp_path)
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    selected = saved.getAirTerminalSingleDuctVAVReheat(terminal.handle()).get()
    assert selected.isMaximumFlowPerZoneFloorAreaDuringReheatAutosized()
    assert selected.maximumFlowFractionDuringReheat().get() == pytest.approx(0.2)
    assert model_file.read_bytes() == original


@pytest.mark.parametrize("tamper", [False, True])
def test_csv_companion_move_and_resource_hash(
    sdk, model_file, tmp_path, monkeypatch, tamper
):
    import shutil
    from common.companions import external_file_status

    o = sdk[0]
    model, _ = fixture(o, model_file, tmp_path)
    monkeypatch.chdir(tmp_path)
    csv = tmp_path / "loads.csv"
    csv.write_text("value\n" + "0.5\n" * 8760)
    external = o.model.ExternalFile.getExternalFile(model, str(csv)).get()
    schedule = o.model.ScheduleFile(external)
    schedule.setRowstoSkipatTop(1)
    light = o.model.Lights(o.model.LightsDefinition(model))
    light.setSpace(model.getThermalZoneByName("Zone 1").get().spaces()[0])
    light.setSchedule(schedule)
    model.save(str(model_file), True)
    report = preflight(model_file, config(tmp_path))
    assert report["ready"], report
    bound = Path(
        next(
            x["source"]
            for x in report["plan"]["companions"]["resources"]
            if x["target"].endswith("loads.csv")
        )
    )
    if tamper:
        bound.write_text(bound.read_text() + "0.1\n")
        with pytest.raises(ValueError):
            apply(report, tmp_path)
        assert not (tmp_path / "edited.osm").exists()
        return
    original = model_file.read_bytes()
    result = apply(report, tmp_path)
    moved = tmp_path / "moved"
    moved.mkdir()
    shutil.move(result["output_model_path"], moved / "edited.osm")
    shutil.move(result["companion_directory"], moved / "edited")
    for path in {csv, bound}:
        path.unlink()
    saved = o.osversion.VersionTranslator().loadModel(str(moved / "edited.osm")).get()
    assert result["requires_companion_workflow"]
    saved.workflowJSON().setOswPath(str(moved / "edited/workflow.osw"))
    assert external_file_status(saved)["ok"]
    assert saved.getScheduleFiles()
    assert model_file.read_bytes() == original


def native_run(o, source, folder, terminal_handle):
    import sqlite3
    import subprocess
    from test_supply_fan_performance import native_cli

    folder.mkdir()
    model = o.osversion.VersionTranslator().loadModel(str(source)).get()
    terminal = model.getAirTerminalSingleDuctVAVReheat(o.toUUID(terminal_handle)).get()
    node = terminal.outletModelObject().get()
    variables = {
        "Zone Air Terminal Minimum Air Flow Fraction": terminal.nameString(),
        "Zone Air Terminal VAV Damper Position": terminal.nameString(),
        "System Node Temperature": node.nameString(),
        "System Node Standard Density Volume Flow Rate": node.nameString(),
        "Heating Coil Heating Energy": terminal.reheatCoil().nameString(),
    }
    for variable, key in variables.items():
        output = o.model.OutputVariable(variable, model)
        output.setKeyValue(key)
        output.setReportingFrequency("Hourly")
    weather = Path(str(model.getWeatherFile().path().get()))
    if not weather.is_absolute():
        weather = source.parent / weather
    assert o.model.WeatherFile.setWeatherFile(
        model, o.EpwFile(str(weather.resolve()))
    ).is_initialized()
    instrumented = folder / "instrumented.osm"
    model.save(str(instrumented), True)
    workflow = folder / "workflow.osw"
    workflow.write_text(json.dumps({"seed_file": str(instrumented), "steps": []}))
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
        result = {}
        for variable, key in variables.items():
            rows = sql.execute(
                "SELECT t.EnvironmentPeriodIndex,t.SimulationDays,t.Hour,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE d.Name=? AND lower(d.KeyValue)=lower(?) AND t.WarmupFlag=0",
                (variable, key),
            ).fetchall()
            assert rows, (variable, key)
            result[variable] = {tuple(row[:3]): row[3] for row in rows}
        sizes = sql.execute(
            "SELECT CompType,Description,Value FROM ComponentSizes WHERE lower(CompName)=lower(?)",
            (terminal.nameString(),),
        ).fetchall()
    heating = result["Heating Coil Heating Energy"]
    active = [key for key, value in heating.items() if value > 1]
    assert active, heating
    return dict(
        hours=len(heating),
        heating_hours=len(active),
        minimum_fraction_range=[
            min(
                result["Zone Air Terminal Minimum Air Flow Fraction"][k] for k in active
            ),
            max(
                result["Zone Air Terminal Minimum Air Flow Fraction"][k] for k in active
            ),
        ],
        damper_range=[
            min(result["Zone Air Terminal VAV Damper Position"][k] for k in active),
            max(result["Zone Air Terminal VAV Damper Position"][k] for k in active),
        ],
        discharge_temperature_range_c=[
            min(result["System Node Temperature"][k] for k in active),
            max(result["System Node Temperature"][k] for k in active),
        ],
        supply_flow_range_m3_s=[
            min(
                result["System Node Standard Density Volume Flow Rate"][k]
                for k in active
            ),
            max(
                result["System Node Standard Density Volume Flow Rate"][k]
                for k in active
            ),
        ],
        heating_energy_j=sum(heating.values()),
        terminal_sizes=sizes,
    )


def test_native_pinned_reheat_limit_sizing_matrix(sdk, tmp_path):
    """Pin the 25.2 sizing overwrite; translated user fields alone are insufficient."""
    import csv
    from vav_fixture import prepare_vav_fixture
    from common import cav_system
    from test_supply_fan_performance import native_cli

    native_cli()
    o = sdk[0]
    source, cfg, _, _ = prepare_vav_fixture(o, tmp_path, True)
    model = o.osversion.VersionTranslator().loadModel(str(source)).get()
    cfg.update(defaults_profile="prototype_cav_v1", outdoor_air_schedule=None)
    cav_system.create(model, o, cav_system.plan(model, o, cfg))
    zone = model.getThermalZoneByName("Perimeter_ZN_1 ZN").get()
    terminal = zone.airLoopHVACTerminals()[0].to_AirTerminalSingleDuctVAVReheat().get()
    terminal.setMaximumReheatAirTemperature(24)  # Force the heating-flow limit to bind.
    terminal.setDamperHeatingAction("ReverseWithLimits")
    terminal.setConstantMinimumAirFlowFraction(0.3)
    handle = str(terminal.handle())
    model.save(str(source), True)
    original = source.read_bytes()
    results = {}
    for area in (0, "Autosize"):
        for fraction in (0.5, 0.2):
            name = f"area_{area}_fraction_{fraction}"
            seed = tmp_path / (name + ".osm")
            if area == "Autosize":
                request = dict(
                    output_model_path=str(seed),
                    air_loop={"name": cfg["system_name"]},
                    zone={"handle": str(zone.handle())},
                    terminal={"handle": handle},
                    settings=dict(
                        maximum_reheat_flow_fraction=fraction,
                        maximum_reheat_flow_per_area_m3_s_m2="Autosize",
                    ),
                )
                reviewed = preflight(source, request)
                assert reviewed["ready"], reviewed
                applied = apply(reviewed, tmp_path)
                (tmp_path / (name + "_plan.json")).write_text(
                    json.dumps(reviewed, indent=2)
                )
                (tmp_path / (name + "_apply.json")).write_text(
                    json.dumps(applied, indent=2)
                )
            else:
                # Deliberately construct the existing recipe's ignored input form.
                current = o.osversion.VersionTranslator().loadModel(str(source)).get()
                selected = current.getAirTerminalSingleDuctVAVReheat(
                    o.toUUID(handle)
                ).get()
                selected.setMaximumFlowPerZoneFloorAreaDuringReheat(area)
                selected.setMaximumFlowFractionDuringReheat(fraction)
                current.save(str(seed), True)
            observed = native_run(o, seed, tmp_path / (name + "_run"), handle)
            with (tmp_path / (name + "_run") / "run/eplusout.eio").open() as stream:
                sizing = [
                    row
                    for row in csv.reader(stream)
                    if len(row) >= 5
                    and row[0].strip() == "Component Sizing Information"
                    and row[2].strip().casefold() == terminal.nameString().casefold()
                    and "Maximum Flow Fraction during Reheat" in row[3]
                ]
            assert sizing, name
            design = [
                float(row[4])
                for row in sizing
                if row[3].strip().startswith("Design Size")
            ]
            user = [
                float(row[4])
                for row in sizing
                if row[3].strip().startswith("User-Specified")
            ]
            assert design == pytest.approx([0.3])
            assert user == pytest.approx([fraction])
            observed["eio_reheat_fraction_rows"] = [
                [x.strip() for x in row] for row in sizing
            ]
            results[name] = observed
    same_high = results["area_0_fraction_0.5"]
    same_low = results["area_0_fraction_0.2"]
    effective_high = results["area_Autosize_fraction_0.5"]
    effective_low = results["area_Autosize_fraction_0.2"]
    (tmp_path / "reheat_limit_matrix.json").write_text(json.dumps(results, indent=2))
    assert same_high["damper_range"] == pytest.approx(
        same_low["damper_range"], abs=1e-5
    )
    assert same_high["supply_flow_range_m3_s"] == pytest.approx(
        same_low["supply_flow_range_m3_s"], abs=1e-5
    )
    assert effective_high["damper_range"][1] > effective_low["damper_range"][1] + 0.1
    assert effective_low["damper_range"][1] == pytest.approx(
        0.3, abs=1e-5
    )  # Minimum bounds the requested 0.2.
    assert source.read_bytes() == original


@pytest.mark.parametrize("system", ["VAV", "CAV"])
def test_native_airflow_and_reheat_control_before_after(sdk, tmp_path, system):
    from vav_fixture import prepare_vav_fixture
    from common import cav_system
    from common.hvac_inventory import inventory as hvac_inventory
    from common.vav_plan import plan as vav_plan
    from common.vav_create import create as create_vav
    from test_supply_fan_performance import native_cli

    native_cli()  # Skip before making fixtures when the native CLI is unavailable.
    o = sdk[0]
    source, cfg, _, _ = prepare_vav_fixture(o, tmp_path, system == "CAV")
    model = o.osversion.VersionTranslator().loadModel(str(source)).get()
    if system == "CAV":
        cfg.update(defaults_profile="prototype_cav_v1", outdoor_air_schedule=None)
        cav_system.create(model, o, cav_system.plan(model, o, cfg))
    else:
        create_vav(model, o, vav_plan(cfg, hvac_inventory(model), None))
    zone = model.getThermalZoneByName("Perimeter_ZN_1 ZN").get()
    terminal = zone.airLoopHVACTerminals()[0].to_AirTerminalSingleDuctVAVReheat().get()
    terminal.setDamperHeatingAction("Normal")
    terminal.setConstantMinimumAirFlowFraction(0.3)
    terminal.setMaximumReheatAirTemperature(40)
    name, handle = terminal.nameString(), str(terminal.handle())
    model.save(str(source), True)
    original = source.read_bytes()
    request = dict(
        output_model_path=str(tmp_path / "edited.osm"),
        air_loop={"name": cfg["system_name"]},
        zone={"name": zone.nameString()},
        terminal={"name": name},
        settings=dict(minimum_airflow_fraction=0.6, maximum_reheat_temperature_c=30),
    )
    report = preflight(source, request)
    assert report["ready"], report
    result = apply(report, tmp_path)
    (tmp_path / "edited-plan.json").write_text(json.dumps(report, indent=2))
    (tmp_path / "edited-apply.json").write_text(json.dumps(result, indent=2))
    temperature_request = dict(
        request,
        output_model_path=str(tmp_path / "temperature_only.osm"),
        settings=dict(maximum_reheat_temperature_c=30),
    )
    temperature_result = apply(preflight(source, temperature_request), tmp_path)
    (tmp_path / "temperature-apply.json").write_text(
        json.dumps(temperature_result, indent=2)
    )
    before = native_run(o, source, tmp_path / "before", handle)
    temperature_only = native_run(
        o,
        Path(temperature_result["output_model_path"]),
        tmp_path / "temperature_only_run",
        handle,
    )
    after = native_run(o, Path(result["output_model_path"]), tmp_path / "after", handle)
    assert before["minimum_fraction_range"] == pytest.approx([0.3, 0.3])
    assert after["minimum_fraction_range"] == pytest.approx([0.6, 0.6])
    assert after["damper_range"][0] >= 0.6 - 1e-5
    assert after["discharge_temperature_range_c"][1] <= 30.1
    assert before["discharge_temperature_range_c"][1] > 32
    assert temperature_only["minimum_fraction_range"] == pytest.approx([0.3, 0.3])
    assert temperature_only["discharge_temperature_range_c"][1] == pytest.approx(
        30, abs=0.1
    )
    assert before["supply_flow_range_m3_s"] != after["supply_flow_range_m3_s"]
    assert source.read_bytes() == original
    evidence = dict(
        system=system,
        openstudio_version=o.openStudioVersion(),
        terminal_handle=handle,
        input_sha256=result["input_sha256"],
        output_sha256=result["output_sha256"],
        before=before,
        temperature_only=temperature_only,
        after=after,
        source_unchanged=True,
    )
    (tmp_path / "native_evidence.json").write_text(json.dumps(evidence, indent=2))


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_native_exported_editor_after_complete_relocation(
    sdk, model_file, tmp_path, host
):
    import shutil
    import subprocess
    from adapters.claude_code_adapter import ClaudeCodeAdapter
    from adapters.codex_adapter import CodexAdapter
    from adapters.contracts import HostAdapterConfig
    from plugin_fixture import copy_plugin_for_skill
    from test_supply_fan_performance import native_cli

    exe = str(native_cli())
    fixture(sdk[0], model_file, tmp_path)
    setup = HostAdapterConfig(
        host_name=host, workspace_root=Path.cwd(), runtime_mode="marketplace"
    )
    adapter = ClaudeCodeAdapter(setup) if host == "claude" else CodexAdapter(setup)
    exported = tmp_path / "export"
    adapter.export_plugin(exported, dry_run=False)
    skill = next(exported.rglob("openstudio-terminal-editor/SKILL.md")).parent
    for relative in (
        "scripts/doctor.py",
        "scripts/sdk_probe.py",
        "scripts/prepare_model.py",
        "../../sdk/references/model_preparation.md",
        "../../sdk/references/terminal_edit.md",
        "../../sdk/references/terminal_edit.schema.json",
    ):
        assert (skill / relative).is_file(), relative
    skill = copy_plugin_for_skill(skill, tmp_path / "relocated")
    shutil.rmtree(exported)
    cfg = tmp_path / "request.json"
    cfg.write_text(json.dumps(config(tmp_path)))
    script = skill / "scripts/edit_terminal.py"
    reviewed = tmp_path / "reviewed.json"
    for args in (
        ["--input", str(model_file), "--report", str(tmp_path / "inventory.json")],
        ["--input", str(model_file), "--config", str(cfg), "--report", str(reviewed)],
        ["--plan", str(reviewed), "--report", str(tmp_path / "applied.json")],
    ):
        run = subprocess.run(
            [exe, "execute_python_script", str(script), *args],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert run.returncode == 0, run.stdout + run.stderr
    result = json.loads((tmp_path / "applied.json").read_text())
    assert result["validation"]["ok"] and result["translation"]["ok"]
    assert json.loads((tmp_path / "inventory.json").read_text())["candidates"][
        "terminals"
    ]
    assert "openstudio-terminal-editor" in (skill / "SKILL.md").read_text()
