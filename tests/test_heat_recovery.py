"""Direct OA recovery contracts, graph preservation and saved native behavior."""

import json
import sys
import pytest
from test_vav_preflight import sdk, model_file, SCRIPTS
from test_ventilation import fixture

sys.path.insert(0, str(SCRIPTS))
from common import heat_recovery as hr, model_transaction as tx


def config(tmp_path, control=True):
    settings = dict(
        nominal_power_w=100,
        nominal_flow_m3_s="Autosize",
        heat_exchanger_type="Rotary",
        frost_control="ExhaustOnly",
        frost_threshold_c=-23.3,
        initial_defrost_fraction=0.167,
        defrost_fraction_increase_per_k=1.44,
        supply_outlet_temperature_control=control,
        economizer_lockout=True,
        availability_schedule={"name": "Always On Discrete"},
        sensible_heating_100=0.7,
        latent_heating_100=0.6,
        sensible_cooling_100=0.75,
        latent_cooling_100=0.6,
    )
    result = dict(
        output_model_path=str(tmp_path / "recovery.osm"),
        mode="attach",
        air_loop={"name": "Existing Air Loop"},
        name="Recovery",
        settings=settings,
        part_load_effectiveness=dict(
            sensible_heating=0.8,
            latent_heating=0.7,
            sensible_cooling=0.8,
            latent_cooling=0.65,
        ),
        part_load_policy="Linear75To100ConstantOutside",
        bypass_control="BypassWhenOAFlowGreaterThanMinimum",
        pretreat_limits=dict(
            minimum_temperature_c=-99,
            maximum_temperature_c=99,
            minimum_humidity_ratio=0.00001,
            maximum_humidity_ratio=1,
        ),
    )

    if not control:
        result.pop("pretreat_limits")
    return result


def preflight(source, cfg):
    return tx.preflight(source, cfg, "manage_heat_recovery", hr.plan)


def apply(report, tmp_path, creator=None):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(report))
    return tx.apply(
        path, "manage_heat_recovery", hr.plan, creator or hr.execute, hr.validate_model
    )


@pytest.mark.parametrize("kind", ["VariableVolume", "ConstantVolume"])
@pytest.mark.parametrize("control", [True, False])
def test_attach_saved_graph_and_explicit_choices(
    sdk, model_file, tmp_path, kind, control
):
    o = sdk[0]
    m, c = fixture(o, model_file, tmp_path, kind)
    original = model_file.read_bytes()
    cfg = config(tmp_path, control)
    cfg["settings"]["availability_schedule"] = {
        "handle": str(m.alwaysOnDiscreteSchedule().handle())
    }
    report = preflight(model_file, cfg)
    assert report["ready"], report
    assert report == preflight(model_file, cfg)
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and result["translation"]["ok"]
    saved = o.model.Model.load(result["output_model_path"]).get()
    hx = saved.getHeatExchangerAirToAirSensibleAndLatents()[0]
    curve = hx.sensibleEffectivenessofHeatingAirFlowCurve().get().to_TableLookup().get()
    assert list(curve.outputValues()) == pytest.approx([0.8, 0.7])
    assert curve.normalizationDivisor() == pytest.approx(0.7)
    assert list(curve.independentVariables()[0].values()) == [0.75, 1.0]
    assert curve.independentVariables()[0].extrapolationMethod() == "Constant"
    assert saved.getControllerOutdoorAir(c.handle()).is_initialized()
    assert model_file.read_bytes() == original


@pytest.mark.parametrize(
    "fault", ["missing", "zero100", "double", "no_reference", "wrong_availability"]
)
def test_attach_rejects_incomplete_or_unverifiable_choices(
    sdk, model_file, tmp_path, fault
):
    o = sdk[0]
    m, c = fixture(o, model_file, tmp_path)
    cfg = config(tmp_path)
    cfg["settings"]["availability_schedule"] = {
        "handle": str(m.alwaysOnDiscreteSchedule().handle())
    }
    if fault == "missing":
        del cfg["settings"]["nominal_power_w"]
    elif fault == "zero100":
        cfg["settings"]["sensible_heating_100"] = 0
    elif fault == "double":
        o.model.HeatExchangerAirToAirSensibleAndLatent(m).addToNode(
            m.getAirLoopHVACs()[0]
            .airLoopHVACOutdoorAirSystem()
            .get()
            .outboardOANode()
            .get()
        )
    elif fault == "no_reference":
        for manager in list(m.getSetpointManagers()):
            manager.remove()
    else:
        cfg["settings"]["availability_schedule"] = {
            "handle": str(m.getPeoples()[0].activityLevelSchedule().get().handle())
        }
    m.save(str(model_file), True)
    report = preflight(model_file, cfg)
    assert not report["ready"], report


@pytest.mark.parametrize(
    "fault", ["extra_fan", "curve", "bypass", "zone", "outlet_control"]
)
def test_attachment_validation_blocks_unrequested_changes(
    sdk, model_file, tmp_path, fault
):
    o = sdk[0]
    m, c = fixture(o, model_file, tmp_path)
    cfg = config(tmp_path)
    cfg["settings"]["availability_schedule"] = {
        "handle": str(m.alwaysOnDiscreteSchedule().handle())
    }
    report = preflight(model_file, cfg)

    def bad(model, native, planned):
        result = hr.execute(model, native, planned)
        hx = model.getHeatExchangerAirToAirSensibleAndLatents()[0]
        if fault == "extra_fan":
            native.model.FanVariableVolume(model)
        elif fault == "curve":
            hx.sensibleEffectivenessofHeatingAirFlowCurve().get().to_TableLookup().get().setNormalizationDivisor(
                0.3
            )
        elif fault == "bypass":
            model.getControllerOutdoorAirs()[0].setHeatRecoveryBypassControlType(
                "BypassWhenWithinEconomizerLimits"
            )
        elif fault == "zone":
            model.getThermalZones()[0].setMultiplier(3)
        else:
            hx.setSupplyAirOutletTemperatureControl(False)
        return result

    with pytest.raises(ValueError, match="validation"):
        apply(report, tmp_path, bad)
    assert not (tmp_path / "recovery.osm").exists()


def test_rating_edit_preserves_references_and_curves(sdk, model_file, tmp_path):
    o = sdk[0]
    m, c = fixture(o, model_file, tmp_path)
    cfg = config(tmp_path)
    cfg["settings"]["availability_schedule"] = {
        "handle": str(m.alwaysOnDiscreteSchedule().handle())
    }
    result = apply(preflight(model_file, cfg), tmp_path)
    source = __import__("pathlib").Path(result["output_model_path"])
    model = o.model.Model.load(str(source)).get()
    hx = model.getHeatExchangerAirToAirSensibleAndLatents()[0]
    cost = o.model.LifeCycleCost.createLifeCycleCost(
        "Cost", hx, 100, "CostPerEach", "Construction", 10
    ).get()
    model.save(str(source), True)
    edit = dict(
        output_model_path=str(tmp_path / "edited.osm"),
        mode="edit",
        air_loop={"name": "Existing Air Loop"},
        heat_exchanger={"handle": str(hx.handle())},
        settings={"nominal_power_w": 80, "sensible_heating_100": 0.65},
    )
    report = preflight(source, edit)
    assert report["ready"]
    assert report == preflight(source, edit)
    result = apply(report, tmp_path)
    saved = o.model.Model.load(result["output_model_path"]).get()
    assert saved.getHeatExchangerAirToAirSensibleAndLatent(hx.handle()).is_initialized()
    assert saved.getLifeCycleCost(cost.handle()).is_initialized()
    assert result["validation"]["ok"]


@pytest.mark.parametrize(
    "fault", ["mode_fields", "fraction", "limits", "stale", "tampered"]
)
def test_contract_or_review_binding_rejects_invalid_requests(
    sdk, model_file, tmp_path, fault
):
    o = sdk[0]
    m, c = fixture(o, model_file, tmp_path)
    cfg = config(tmp_path)
    cfg["settings"]["availability_schedule"] = {
        "handle": str(m.alwaysOnDiscreteSchedule().handle())
    }
    if fault == "mode_fields":
        cfg["heat_exchanger"] = {"name": "Unexpected"}
    elif fault == "fraction":
        cfg["settings"]["initial_defrost_fraction"] = 1.1
    elif fault == "limits":
        cfg["pretreat_limits"]["minimum_temperature_c"] = 100
    if fault == "fraction":
        with pytest.raises(ValueError, match="Invalid"):
            preflight(model_file, cfg)
        return
    report = preflight(model_file, cfg)
    if fault in ("mode_fields", "limits"):
        assert not report["ready"]
        return
    if fault == "stale":
        model_file.write_bytes(model_file.read_bytes() + b"\n")
    else:
        report["plan"]["after_values"]["nominal_power_w"] = 999
    with pytest.raises(ValueError, match="Stale|differs"):
        apply(report, tmp_path)


def native_recovery_run(sdk, tmp_path, system, control):
    from pathlib import Path
    import sqlite3, subprocess
    from test_supply_fan_performance import native_cli
    from vav_fixture import prepare_vav_fixture
    from common import cav_system
    from common.vav_plan import plan as plan_vav
    from common.vav_create import create as create_vav

    tmp_path.mkdir(parents=True, exist_ok=True)
    o = sdk[0]
    source, base, _, _ = prepare_vav_fixture(o, tmp_path, True)
    model = o.osversion.VersionTranslator().loadModel(str(source)).get()
    base.update(
        system_name="Existing Air Loop",
        outdoor_air_schedule=None,
        economizer="NoEconomizer",
    )
    if system == "CAV":
        base["defaults_profile"] = "prototype_cav_v1"
        cav_system.create(model, o, cav_system.plan(model, o, base))
    else:
        from common.hvac_inventory import inventory as hvac_inventory

        create_vav(model, o, plan_vav(base, hvac_inventory(model), None))
    model.getAirLoopHVACs()[0].setAvailabilitySchedule(model.alwaysOnDiscreteSchedule())
    c = model.getControllerOutdoorAirs()[0]
    if control == "economizer_lockout":
        c.setEconomizerControlType("FixedDryBulb")
        c.setEconomizerMaximumLimitDryBulbTemperature(50)
        c.setEconomizerMinimumLimitDryBulbTemperature(-100)
        on = model.alwaysOnDiscreteSchedule()
        c.setTimeofDayEconomizerControlSchedule(on)
    if control == "new_intake":
        model.getAirLoopHVACs()[0].airLoopHVACOutdoorAirSystem().get().remove()
    model.save(str(source), True)
    if control == "new_intake":
        from test_outdoor_air_attach import (
            config as intake_config,
            preflight as intake_plan,
            apply as intake_apply,
        )

        intake = intake_apply(
            intake_plan(source, intake_config(tmp_path, model)), tmp_path
        )
        source = Path(intake["output_model_path"])
        model = o.model.Model.load(str(source)).get()
    cfg = config(tmp_path, control == "pretreat")
    cfg["settings"]["availability_schedule"] = {
        "handle": str(model.alwaysOnDiscreteSchedule().handle())
    }
    report = preflight(source, cfg)
    assert report["ready"], report
    result = apply(report, tmp_path)
    saved = o.model.Model.load(result["output_model_path"]).get()
    weather = Path(str(saved.getWeatherFile().path().get()))
    if not weather.is_absolute():
        weather = Path(result["output_model_path"]).parent / weather
    assert o.model.WeatherFile.setWeatherFile(
        saved, o.EpwFile(str(weather.resolve()))
    ).is_initialized()
    variables = [
        "Heat Exchanger Sensible Heating Rate",
        "Heat Exchanger Sensible Cooling Rate",
        "Heat Exchanger Electricity Rate",
        "Heat Exchanger Supply Air Bypass Mass Flow Rate",
        "Air System Outdoor Air Economizer Status",
    ]
    energy_variables = [
        "Heat Exchanger Sensible Heating Energy",
        "Heat Exchanger Electricity Energy",
        "Cooling Coil Total Cooling Energy",
        "Heating Coil Heating Energy",
    ]
    for name in variables + energy_variables:
        v = o.model.OutputVariable(name, saved)
        v.setKeyValue("*")
        v.setReportingFrequency("Hourly")
    loop = saved.getAirLoopHVACs()[0]
    mixed = loop.airLoopHVACOutdoorAirSystem().get().mixedAirModelObject().get()
    for name in ("System Node Temperature", "System Node Setpoint Temperature"):
        v = o.model.OutputVariable(name, saved)
        v.setKeyValue(mixed.nameString())
        v.setReportingFrequency("Hourly")
    central_heating = [
        x.nameString()
        for x in loop.supplyComponents()
        if x.iddObjectType().valueName().startswith("OS_Coil_Heating_")
    ]
    central_cooling = [
        x.nameString()
        for x in loop.supplyComponents()
        if x.iddObjectType().valueName().startswith("OS_Coil_Cooling_")
    ]
    instrumented = tmp_path / "native.osm"
    saved.save(str(instrumented), True)
    workflow = tmp_path / "native.osw"
    workflow.write_text(json.dumps(dict(seed_file=str(instrumented), steps=[])))
    run = subprocess.run(
        [str(native_cli()), "run", "-w", str(workflow)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    (tmp_path / "cli.log").write_text(run.stdout + run.stderr)
    assert run.returncode == 0, run.stdout + run.stderr
    err = (tmp_path / "run/eplusout.err").read_text()
    assert "** Severe **" not in err and "**  Fatal  **" not in err, err
    with sqlite3.connect(tmp_path / "run/eplusout.sql") as sql:
        data = {
            name: sql.execute(
                "SELECT MIN(r.Value),MAX(r.Value),SUM(r.Value) FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE d.Name=? AND t.WarmupFlag=0",
                (name,),
            ).fetchone()
            for name in variables
        }
        days = {x.nameString().casefold(): x.dayType() for x in saved.getDesignDays()}
        periods = []
        for index, name in sql.execute(
            "SELECT EnvironmentPeriodIndex, EnvironmentName FROM EnvironmentPeriods"
        ):

            def energy(variable, keys=None):
                query = "SELECT COUNT(*), SUM(r.Value) FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE d.Name=? AND d.Units='J' AND t.WarmupFlag=0 AND t.EnvironmentPeriodIndex=?"
                args = [variable, index]
                if keys is not None:
                    query += (
                        " AND LOWER(d.KeyValue) IN ("
                        + ",".join("?" for _ in keys)
                        + ")"
                    )
                    args += [key.lower() for key in keys]
                count, total = sql.execute(query, args).fetchone()
                assert count > 0, (variable, keys, name)
                return total / 3.6e6

            heating_total = energy("Heating Coil Heating Energy")
            central_heat = energy("Heating Coil Heating Energy", central_heating)
            node_rows = sql.execute(
                "SELECT t.TimeIndex, MAX(CASE WHEN d.Name='System Node Temperature' THEN r.Value END), MAX(CASE WHEN d.Name='System Node Setpoint Temperature' THEN r.Value END) FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE LOWER(d.KeyValue)=? AND d.Name IN ('System Node Temperature','System Node Setpoint Temperature') AND t.WarmupFlag=0 AND t.EnvironmentPeriodIndex=? GROUP BY t.TimeIndex",
                (mixed.nameString().lower(), index),
            ).fetchall()
            assert node_rows and all(
                t is not None and sp is not None and sp > -100 for _, t, sp in node_rows
            )
            periods.append(
                dict(
                    environment=name,
                    day_type=days[name.casefold()],
                    recovered_sensible_heating_kwh=energy(
                        "Heat Exchanger Sensible Heating Energy"
                    ),
                    hx_electricity_kwh=energy("Heat Exchanger Electricity Energy"),
                    central_cooling_thermal_kwh=energy(
                        "Cooling Coil Total Cooling Energy", central_cooling
                    ),
                    central_heating_thermal_kwh=central_heat,
                    zone_reheat_thermal_kwh=heating_total - central_heat,
                    mixed_air_max_above_setpoint_k=max(
                        t - sp for _, t, sp in node_rows
                    ),
                )
            )
    assert data[variables[0]][1] is not None, data
    if control == "economizer_lockout":
        assert data[variables[-1]][1] == pytest.approx(1), data
        assert data[variables[0]][1] == pytest.approx(0, abs=1e-6), data
        assert data[variables[1]][1] == pytest.approx(0, abs=1e-6), data
        assert data[variables[2]][1] == pytest.approx(0, abs=1e-6), data
    else:
        assert data[variables[0]][1] > 0, data
        assert data[variables[2]][1] == pytest.approx(100), data
    evidence = dict(
        system=system,
        control=control,
        outputs=data,
        periods=periods,
        energy_basis="Hourly summed thermal coil loads in kWh, excluding warmup; HX electricity reported separately. Coil loads are not fuel/input energy or net HVAC savings.",
    )
    (tmp_path / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    return evidence


@pytest.mark.parametrize("control", ["economizer_lockout", "new_intake"])
@pytest.mark.parametrize("system", ["VAV", "CAV"])
def test_native_recovery_transfer_and_control(sdk, tmp_path, system, control):
    native_recovery_run(sdk, tmp_path, system, control)


@pytest.mark.parametrize("system", ["VAV", "CAV"])
def test_native_outlet_control_limits_unnecessary_cooling(sdk, tmp_path, system):
    off = native_recovery_run(sdk, tmp_path / "off", system, "none")
    controlled = native_recovery_run(sdk, tmp_path / "pretreat", system, "pretreat")
    before = next(x for x in off["periods"] if x["day_type"] == "WinterDesignDay")
    after = next(x for x in controlled["periods"] if x["day_type"] == "WinterDesignDay")
    assert before["environment"] == after["environment"]
    assert (
        before["recovered_sensible_heating_kwh"]
        > after["recovered_sensible_heating_kwh"]
    )
    assert (
        before["central_cooling_thermal_kwh"] > after["central_cooling_thermal_kwh"] + 1
    )
    assert (
        before["mixed_air_max_above_setpoint_k"]
        > after["mixed_air_max_above_setpoint_k"] + 0.1
    )
    extra_recovery = (
        before["recovered_sensible_heating_kwh"]
        - after["recovered_sensible_heating_kwh"]
    )
    extra_cooling = (
        before["central_cooling_thermal_kwh"] - after["central_cooling_thermal_kwh"]
    )
    assert extra_cooling == pytest.approx(extra_recovery, rel=0.01, abs=0.1)
    for key in ("central_heating_thermal_kwh", "zone_reheat_thermal_kwh"):
        assert before[key] == pytest.approx(after[key], rel=0.001, abs=0.1)
    (tmp_path / "comparison.json").write_text(
        json.dumps(
            dict(
                system=system,
                winter_off=before,
                winter_pretreat=after,
                energy_basis=off["energy_basis"],
            ),
            indent=2,
        )
        + "\n"
    )


@pytest.mark.parametrize(
    "fault",
    [
        "effectiveness",
        "curve",
        "metadata",
        "extra_object",
        "missing_control",
        "outside_mode",
    ],
)
def test_edit_preservation_and_control_review(sdk, model_file, tmp_path, fault):
    from pathlib import Path

    o = sdk[0]
    m, c = fixture(o, model_file, tmp_path)
    cfg = config(tmp_path)
    cfg["settings"]["availability_schedule"] = {
        "handle": str(m.alwaysOnDiscreteSchedule().handle())
    }
    source = Path(apply(preflight(model_file, cfg), tmp_path)["output_model_path"])
    m = o.model.Model.load(str(source)).get()
    hx = m.getHeatExchangerAirToAirSensibleAndLatents()[0]
    hx.additionalProperties().setFeature("review_tag", "Keep")
    actuator = o.model.EnergyManagementSystemActuator(
        hx, "Heat Exchanger", "Sensible Effectiveness"
    )
    if fault == "missing_control":
        for spm in list(m.getSetpointManagers()):
            spm.remove()
    m.save(str(source), True)
    cfg = dict(
        output_model_path=str(tmp_path / "edited.osm"),
        mode="edit",
        air_loop={"name": "Existing Air Loop"},
        heat_exchanger={"handle": str(hx.handle())},
        settings={"nominal_power_w": 80},
    )
    if fault == "effectiveness":
        cfg["settings"] = {"sensible_heating_100": 1}
    if fault == "outside_mode":
        cfg["bypass_control"] = "BypassWhenWithinEconomizerLimits"
    report = preflight(source, cfg)
    if fault in ("effectiveness", "outside_mode"):
        assert not report["ready"]
        return
    if fault == "missing_control":
        assert report["ready"] and not report["plan"]["simulation_ready"]
        assert apply(report, tmp_path)["validation"]["ok"]
        return

    def bad(model, native, planned):
        result = hr.execute(model, native, planned)
        h = model.getHeatExchangerAirToAirSensibleAndLatents()[0]
        if fault == "curve":
            h.sensibleEffectivenessofHeatingAirFlowCurve().get().to_TableLookup().get().setNormalizationDivisor(
                0.2
            )
        elif fault == "metadata":
            h.additionalProperties().setFeature("review_tag", "Changed")
        else:
            native.model.FanConstantVolume(model)
        return result

    with pytest.raises(ValueError, match="validation"):
        apply(report, tmp_path, bad)
    assert not (tmp_path / "edited.osm").exists()


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("operation", ["intake", "recovery", "edit"])
def test_independently_relocated_phase10c_bundle(
    sdk, model_file, tmp_path, host, operation
):
    import shutil, subprocess
    from pathlib import Path
    from adapters.claude_code_adapter import ClaudeCodeAdapter
    from adapters.codex_adapter import CodexAdapter
    from adapters.contracts import HostAdapterConfig
    from test_supply_fan_performance import native_cli
    from test_outdoor_air_attach import config as intake_config

    o = sdk[0]
    m, c = fixture(o, model_file, tmp_path)
    cfg = config(tmp_path)
    cfg["settings"]["availability_schedule"] = {
        "handle": str(m.alwaysOnDiscreteSchedule().handle())
    }
    entry = "manage_heat_recovery.py"
    skill = "openstudio-outdoor-air-connector"
    source = model_file
    if operation == "intake":
        m.getAirLoopHVACs()[0].airLoopHVACOutdoorAirSystem().get().remove()
        m.save(str(source), True)
        cfg = intake_config(tmp_path, m)
        entry = "attach_outdoor_air.py"
    elif operation == "edit":
        source = Path(apply(preflight(source, cfg), tmp_path)["output_model_path"])
        m = o.model.Model.load(str(source)).get()
        hx = m.getHeatExchangerAirToAirSensibleAndLatents()[0]
        cfg = dict(
            output_model_path=str(tmp_path / "edited.osm"),
            mode="edit",
            air_loop={"name": "Existing Air Loop"},
            heat_exchanger={"handle": str(hx.handle())},
            settings={"nominal_power_w": 85},
        )
        skill = "openstudio-heat-recovery-editor"
    setup = HostAdapterConfig(
        host_name=host, workspace_root=Path.cwd(), runtime_mode="marketplace"
    )
    adapter = ClaudeCodeAdapter(setup) if host == "claude" else CodexAdapter(setup)
    exported = tmp_path / "export"
    adapter.export_plugin(exported, dry_run=False)
    bundle = next(exported.rglob(skill + "/SKILL.md")).parent
    moved = tmp_path / "relocated"
    shutil.copytree(bundle, moved)
    shutil.rmtree(exported)
    doctor = subprocess.run(
        [
            sys.executable,
            str(moved / "scripts/doctor.py"),
            "--openstudio",
            str(native_cli()),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert doctor.returncode == 0, doctor.stdout + doctor.stderr
    validator = Path(
        "/Users/xuwe123/.codex/skills/.system/skill-creator/scripts/quick_validate.py"
    )
    if validator.is_file():
        validation = subprocess.run(
            [sys.executable, str(validator), str(moved)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert validation.returncode == 0, validation.stdout + validation.stderr
    configuration = tmp_path / "config.json"
    configuration.write_text(json.dumps(cfg))
    planfile = tmp_path / "reviewed.json"
    for args in (
        ["--input", str(source), "--report", str(tmp_path / "inventory.json")],
        [
            "--input",
            str(source),
            "--config",
            str(configuration),
            "--report",
            str(planfile),
        ],
        ["--plan", str(planfile), "--report", str(tmp_path / "applied.json")],
    ):
        run = subprocess.run(
            [
                str(native_cli()),
                "execute_python_script",
                str(moved / "scripts" / entry),
                *args,
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert run.returncode == 0, run.stdout + run.stderr
    result = json.loads((tmp_path / "applied.json").read_text())
    assert result["validation"]["ok"] and result["translation"]["ok"]


@pytest.mark.parametrize("operation", ["intake", "recovery", "edit"])
def test_workflow_weather_can_populate_empty_metadata(
    sdk, model_file, tmp_path, operation
):
    from pathlib import Path
    from test_outdoor_air_attach import (
        config as intake_config,
        preflight as intake_plan,
        apply as intake_apply,
    )

    o = sdk[0]
    m, c = fixture(o, model_file, tmp_path)
    source = model_file
    cfg = config(tmp_path)
    cfg["settings"]["availability_schedule"] = {
        "handle": str(m.alwaysOnDiscreteSchedule().handle())
    }
    if operation == "edit":
        source = Path(apply(preflight(source, cfg), tmp_path)["output_model_path"])
        m = o.model.Model.load(str(source)).get()
        hx = m.getHeatExchangerAirToAirSensibleAndLatents()[0]
        cfg = dict(
            output_model_path=str(tmp_path / "edited.osm"),
            mode="edit",
            air_loop={"name": "Existing Air Loop"},
            heat_exchanger={"handle": str(hx.handle())},
            settings={"nominal_power_w": 85},
        )
    elif operation == "intake":
        m.getAirLoopHVACs()[0].airLoopHVACOutdoorAirSystem().get().remove()
        cfg = intake_config(tmp_path, m)
    m.getWeatherFile().remove()
    m.save(str(source), True)
    folder = source.with_suffix("")
    folder.mkdir(exist_ok=True)
    weather = (
        Path(__file__).resolve().parent
        / "fixtures/USA_FL_Tampa.Intl.AP.722110_TMY3.epw"
    )
    (folder / "workflow.osw").write_text(
        json.dumps(dict(weather_file=str(weather), steps=[]))
    )
    plan = intake_plan(source, cfg) if operation == "intake" else preflight(source, cfg)
    assert plan["ready"] and plan["plan"]["weather_was_empty"]
    result = (
        intake_apply(plan, tmp_path) if operation == "intake" else apply(plan, tmp_path)
    )
    assert result["validation"]["ok"]


def test_effectiveness_roundoff_at_one_is_accepted(sdk, model_file, tmp_path):
    from pathlib import Path

    o = sdk[0]
    m, c = fixture(o, model_file, tmp_path)
    cfg = config(tmp_path)
    cfg["settings"]["availability_schedule"] = {
        "handle": str(m.alwaysOnDiscreteSchedule().handle())
    }
    source = Path(apply(preflight(model_file, cfg), tmp_path)["output_model_path"])
    cfg = dict(
        output_model_path=str(tmp_path / "edited.osm"),
        mode="edit",
        air_loop={"name": "Existing Air Loop"},
        heat_exchanger={"name": "Recovery"},
        settings={"sensible_heating_100": 0.875},
    )
    report = preflight(source, cfg)
    assert report["ready"], report
    assert apply(report, tmp_path)["validation"]["ok"]


@pytest.mark.parametrize("kind", ["VariableVolume", "ConstantVolume"])
@pytest.mark.parametrize("mode", ["attach", "edit"])
@pytest.mark.parametrize(
    "scenario", ["cooling_coil", "cool_target_only", "warm_heat_only", "controlled"]
)
def test_uncontrolled_recovery_cooling_risk_is_exposed(
    sdk, model_file, tmp_path, kind, mode, scenario
):
    from pathlib import Path

    o = sdk[0]
    m, c = fixture(o, model_file, tmp_path, kind)
    if scenario in ("cool_target_only", "warm_heat_only"):
        for coil in list(m.getCoilCoolingWaters()) + list(
            m.getCoilCoolingDXTwoSpeeds()
        ):
            coil.remove()
    if scenario == "warm_heat_only":
        manager = (
            m.getAirLoopHVACs()[0]
            .supplyOutletNode()
            .setpointManagers()[0]
            .to_SetpointManagerScheduled()
            .get()
        )
        warm = o.model.ScheduleConstant(m)
        warm.setScheduleTypeLimits(manager.schedule().scheduleTypeLimits().get())
        warm.setValue(30)
        manager.setSchedule(warm)
    m.save(str(model_file), True)
    cfg = config(tmp_path, control=scenario == "controlled")
    cfg["settings"]["availability_schedule"] = {
        "handle": str(m.alwaysOnDiscreteSchedule().handle())
    }
    source = model_file
    if mode == "edit":
        source = Path(apply(preflight(source, cfg), tmp_path)["output_model_path"])
        cfg = dict(
            output_model_path=str(tmp_path / "edited.osm"),
            mode="edit",
            air_loop={"name": "Existing Air Loop"},
            heat_exchanger={"name": "Recovery"},
            settings={"nominal_power_w": 80},
        )
    report = preflight(source, cfg)
    assert report["ready"] and report["plan"]["simulation_ready"], report
    risk = report["plan"]["impact"]["controls"]["cooling_context"]
    warnings = " ".join(report["warnings"])
    expected = scenario in ("cooling_coil", "cool_target_only")
    assert report["plan"]["impact"]["uncontrolled_recovery_cooling_risk"] is expected
    assert ("Uncontrolled heat-recovery outlet temperature" in warnings) == expected
    if expected:
        assert (
            "heat-then-cool" in warnings
            and "OutdoorAirPretreat" in warnings
            and "bypass" in warnings
        )
    if scenario == "cool_target_only":
        assert not risk["downstream_cooling_components"]
        assert risk["supply_can_be_below_zone_heating_setpoints"]
    result = apply(report, tmp_path)
    assert result["validation"]["ok"]
