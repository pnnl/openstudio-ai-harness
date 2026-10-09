"""Ventilation edits preserve identity and expose occupancy/flow/sizing context."""

import json
import sys
import pytest
from test_vav_preflight import sdk, model_file, SCRIPTS
from test_supply_fan_performance import served_model

sys.path.insert(0, str(SCRIPTS))
from common import ventilation_edit as vent, model_transaction as tx

OPERATION = "edit_ventilation"


def config(tmp_path, **settings):
    return dict(
        output_model_path=str(tmp_path / "ventilated.osm"),
        air_loop={"name": "Existing Air Loop"},
        ventilation=settings or {"dcv": True, "minimum_flow_m3_s": 0},
    )


def fixture(o, model_file, tmp_path, kind="VariableVolume"):
    model, _ = served_model(o, model_file, tmp_path, kind)
    space = model.getSpaces()[0]
    space.setFloorArea(100)
    space.setVolume(300)
    definition = o.model.PeopleDefinition(model)
    definition.setNumberofPeople(10)
    people = o.model.People(definition)
    people.setSpace(space)
    occupancy = o.model.ScheduleRuleset(model)
    occupancy.setName("Occupancy")
    day = occupancy.defaultDaySchedule()
    day.addValue(o.Time(0, 6, 0, 0), 0)
    day.addValue(o.Time(0, 18, 0, 0), 1)
    day.addValue(o.Time(0, 24, 0, 0), 0)
    people.setNumberofPeopleSchedule(occupancy)
    activity = o.model.ScheduleConstant(model)
    activity.setValue(120)
    people.setActivityLevelSchedule(activity)
    oa = o.model.DesignSpecificationOutdoorAir(model)
    oa.setOutdoorAirMethod("Sum")
    oa.setOutdoorAirFlowperPerson(0.005)
    oa.setOutdoorAirFlowperFloorArea(0.0003)
    space.setDesignSpecificationOutdoorAir(oa)
    model.save(str(model_file), True)
    return (
        model,
        model.getAirLoopHVACs()[0]
        .airLoopHVACOutdoorAirSystem()
        .get()
        .getControllerOutdoorAir(),
    )


def preflight(source, cfg):
    return tx.preflight(source, cfg, OPERATION, vent.plan)


def apply(report, tmp_path, creator=None):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(report))
    return tx.apply(
        path, OPERATION, vent.plan, creator or vent.edit, vent.validate_model
    )


@pytest.mark.parametrize("kind", ["VariableVolume", "ConstantVolume"])
def test_saved_dcv_edit_preserves_inputs_and_identities(
    sdk, model_file, tmp_path, kind
):
    o = sdk[0]
    model, controller = fixture(o, model_file, tmp_path, kind)
    mv = controller.controllerMechanicalVentilation()
    original = model_file.read_bytes()
    report = preflight(model_file, config(tmp_path))
    assert report["ready"], report
    assert report == preflight(model_file, config(tmp_path))
    assert report["plan"]["simulation_ready"]
    assert report["plan"]["retained_context"]["zone_requirements"][
        "nominal_design_oa_m3_s"
    ] == pytest.approx(0.08)
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and result["translation"]["ok"]
    saved = o.model.Model.load(result["output_model_path"]).get()
    c = saved.getControllerOutdoorAir(controller.handle()).get()
    assert c.minimumOutdoorAirFlowRate().get() == 0
    assert c.controllerMechanicalVentilation().handle() == mv.handle()
    assert c.controllerMechanicalVentilation().demandControlledVentilation()
    assert c.controllerMechanicalVentilation().systemOutdoorAirMethod() == "ZoneSum"
    assert model_file.read_bytes() == original


@pytest.mark.parametrize(
    "settings",
    [
        {"minimum_flow_m3_s": 0.1},
        {"minimum_flow_m3_s": 0},
        {"maximum_flow_m3_s": 1},
        {"minimum_limit_type": "ProportionalMinimum"},
        {"minimum_flow_schedule": {"name": "Occupancy"}},
        {"minimum_fraction_schedule": {"name": "Occupancy"}},
        {"maximum_fraction_schedule": {"name": "Occupancy"}},
        {"dcv": True},
    ],
)
def test_partial_changes_keep_all_other_fields(sdk, model_file, tmp_path, settings):
    fixture(sdk[0], model_file, tmp_path)
    report = preflight(model_file, config(tmp_path, **settings))
    assert report["ready"], report["plan"]
    result = apply(report, tmp_path)
    for key, before in report["plan"]["before_values"].items():
        if key not in settings:
            assert result["changes"]["after"][key] == before
    assert result["validation"]["ok"]
    if settings == {"dcv": True}:
        assert result["changes"]["after"]["minimum_flow_m3_s"] == "Autosize"
        assert report["plan"]["impact"]["dcv_effective"] is None
        assert any("translates the EnergyPlus minimum" in w for w in result["warnings"])


@pytest.mark.parametrize(
    "key",
    ["minimum_flow_schedule", "minimum_fraction_schedule", "maximum_fraction_schedule"],
)
def test_explicit_schedule_reset(sdk, model_file, tmp_path, key):
    o = sdk[0]
    model, c = fixture(o, model_file, tmp_path)
    suffix = vent.FIELDS[key][0]
    assert getattr(c, "set" + suffix)(model.getScheduleRulesetByName("Occupancy").get())
    model.save(str(model_file), True)
    result = apply(preflight(model_file, config(tmp_path, **{key: None})), tmp_path)
    assert result["changes"]["after"][key] is None


@pytest.mark.parametrize(
    "settings",
    [
        {"minimum_flow_m3_s": -1},
        {"minimum_flow_m3_s": True},
        {"maximum_flow_m3_s": None},
        {"dcv": "Yes"},
        {"outdoor_air_method": "ZoneSum"},
        {"economizer": "NoEconomizer"},
        {"minimum_limit_type": "Fixed"},
    ],
)
def test_schema_rejects_implicit_or_invalid_controls(
    sdk, model_file, tmp_path, settings
):
    fixture(sdk[0], model_file, tmp_path)
    with pytest.raises(ValueError, match="Invalid ventilation"):
        preflight(model_file, config(tmp_path, **settings))


def test_missing_choices_unsupported_method_and_noop(sdk, model_file, tmp_path):
    model, c = fixture(sdk[0], model_file, tmp_path)
    assert preflight(
        model_file, {"output_model_path": str(tmp_path / "ventilated.osm")}
    )["plan"]["missing_inputs"] == ["air_loop", "ventilation"]
    cfg = config(tmp_path)
    cfg["ventilation"] = {}
    assert not preflight(model_file, cfg)["ready"]
    assert not preflight(model_file, config(tmp_path, dcv=False))["ready"]
    c.controllerMechanicalVentilation().setSystemOutdoorAirMethod(
        "Standard62.1VentilationRateProcedure"
    )
    model.save(str(model_file), True)
    report = preflight(model_file, config(tmp_path))
    assert not report["ready"] and any("ZoneSum" in e for e in report["plan"]["errors"])
    # A flow-only edit preserves that existing method instead of refusing unrelated work.
    assert preflight(model_file, config(tmp_path, minimum_flow_m3_s=0.1))["ready"]


@pytest.mark.parametrize("value", [-0.1, 1.1])
@pytest.mark.parametrize("special", ["default", "holiday", "winter"])
def test_schedule_checks_actual_values_including_special_days(
    sdk, model_file, tmp_path, value, special
):
    o = sdk[0]
    model, _ = fixture(o, model_file, tmp_path)
    schedule = model.getScheduleRulesetByName("Occupancy").get()
    if special == "default":
        day = schedule.defaultDaySchedule()
        day.clearValues()
        day.addValue(o.Time(0, 24, 0, 0), value)
    else:
        day = o.model.ScheduleDay(model)
        day.addValue(o.Time(0, 24, 0, 0), value)
        # Ruleset setters copy ScheduleDay; populate before assigning it.
        assert getattr(
            schedule,
            (
                "setHolidaySchedule"
                if special == "holiday"
                else "setWinterDesignDaySchedule"
            ),
        )(day)
    model.save(str(model_file), True)
    report = preflight(
        model_file, config(tmp_path, minimum_fraction_schedule={"name": "Occupancy"})
    )
    assert not report["ready"] and report["plan"]["errors"]


@pytest.mark.parametrize(
    "case, phrase",
    [
        ("flow_conflict", "exceeds maximum"),
        ("zero_maximum", "maximum OA flow is zero"),
        ("supply_cap", "below nominal zone OA"),
        ("design_oa", "fixed system design OA"),
        ("full_oa", "100% OA"),
        ("no_oa", "Missing zone/space"),
        ("no_occupancy", "Unverified People"),
        ("zero_fraction", "prevent/contradict"),
    ],
)
def test_readiness_cross_checks_and_warning_propagation(
    sdk, model_file, tmp_path, case, phrase
):
    o = sdk[0]
    model, c = fixture(o, model_file, tmp_path)
    loop = model.getAirLoopHVACs()[0]
    cfg = config(tmp_path)
    if case == "flow_conflict":
        cfg["ventilation"].update(minimum_flow_m3_s=2, maximum_flow_m3_s=1)
    elif case == "zero_maximum":
        cfg["ventilation"]["maximum_flow_m3_s"] = 0
    elif case == "supply_cap":
        loop.setDesignSupplyAirFlowRate(0.01)
    elif case == "design_oa":
        loop.sizingSystem().setDesignOutdoorAirFlowRate(0.01)
        cfg["ventilation"]["minimum_flow_m3_s"] = 0.1
    elif case in ("full_oa", "zero_fraction"):
        schedule = o.model.ScheduleConstant(model)
        schedule.setName("Selected Fraction")
        schedule.setValue(1 if case == "full_oa" else 0)
        limits = o.model.ScheduleTypeLimits(model)
        limits.setLowerLimitValue(0)
        limits.setUpperLimitValue(1)
        limits.setNumericType("Continuous")
        limits.setUnitType("Dimensionless")
        schedule.setScheduleTypeLimits(limits)
        cfg["ventilation"][
            (
                "minimum_fraction_schedule"
                if case == "full_oa"
                else "maximum_fraction_schedule"
            )
        ] = {"name": "Selected Fraction"}
    elif case == "no_oa":
        model.getSpaces()[0].resetDesignSpecificationOutdoorAir()
    else:
        model.getPeoples()[0].resetNumberofPeopleSchedule()
    model.save(str(model_file), True)
    report = preflight(model_file, cfg)
    assert report["ready"], report["plan"]
    assert report["plan"]["simulation_ready"] is False
    assert any(phrase in w for w in report["warnings"])
    result = apply(report, tmp_path)
    assert result["simulation_ready"] is False
    assert any(phrase in w for w in result["warnings"])


@pytest.mark.parametrize(
    "fault",
    [
        "zone_oa",
        "people",
        "schedule",
        "sizing",
        "economizer",
        "mv_method",
        "extra_object",
        "setting",
    ],
)
def test_saved_protection_rejects_unrequested_changes(sdk, model_file, tmp_path, fault):
    o = sdk[0]
    fixture(o, model_file, tmp_path)
    report = preflight(model_file, config(tmp_path))

    def bad(model, native, planned):
        result = vent.edit(model, native, planned)
        c = model.getControllerOutdoorAirs()[0]
        if fault == "zone_oa":
            model.getDesignSpecificationOutdoorAirs()[0].setOutdoorAirFlowperPerson(0.1)
        elif fault == "people":
            model.getPeopleDefinitions()[0].setNumberofPeople(100)
        elif fault == "schedule":
            model.getScheduleRulesetByName(
                "Occupancy"
            ).get().defaultDaySchedule().addValue(native.Time(0, 24, 0, 0), 0.2)
        elif fault == "sizing":
            model.getAirLoopHVACs()[0].sizingSystem().setAllOutdoorAirinHeating(True)
        elif fault == "economizer":
            c.setEconomizerMaximumLimitDryBulbTemperature(25)
        elif fault == "mv_method":
            c.controllerMechanicalVentilation().setSystemOutdoorAirMethod(
                "Standard62.1VentilationRateProcedure"
            )
        elif fault == "extra_object":
            native.model.ScheduleConstant(model)
        else:
            c.setMinimumOutdoorAirFlowRate(0.2)
        return result

    with pytest.raises(ValueError, match="validation"):
        apply(report, tmp_path, bad)
    assert not (tmp_path / "ventilated.osm").exists()


def test_inherited_oa_people_multiplier_and_raw_mv_pointer(sdk, model_file, tmp_path):
    o = sdk[0]
    model, c = fixture(o, model_file, tmp_path)
    space = model.getSpaces()[0]
    st = o.model.SpaceType(model)
    st.setDesignSpecificationOutdoorAir(space.designSpecificationOutdoorAir().get())
    space.resetDesignSpecificationOutdoorAir()
    space.setSpaceType(st)
    p = model.getPeoples()[0]
    p.setSpaceType(st)
    model.getThermalZones()[0].setMultiplier(3)
    model.save(str(model_file), True)
    report = preflight(model_file, config(tmp_path))
    assert report["ready"], report["plan"]
    assert report["plan"]["impact"]["nominal_design_oa_m3_s"] == pytest.approx(0.24)
    assert report["plan"]["impact"]["mechanical_ventilation_context"]["handle"] == str(
        c.controllerMechanicalVentilation().handle()
    )
    assert apply(report, tmp_path)["validation"]["ok"]


def test_stale_and_tampered_plans(sdk, model_file, tmp_path):
    fixture(sdk[0], model_file, tmp_path)
    report = preflight(model_file, config(tmp_path))
    report["plan"]["after_values"]["minimum_flow_m3_s"] = 0.5
    with pytest.raises(ValueError, match="differs"):
        apply(report, tmp_path)
    report = preflight(model_file, config(tmp_path))
    model_file.write_bytes(model_file.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="Stale"):
        apply(report, tmp_path)


def native_run(o, source, folder):
    from pathlib import Path
    import sqlite3
    import subprocess
    from test_supply_fan_performance import native_cli

    folder.mkdir()
    model = o.osversion.VersionTranslator().loadModel(str(source)).get()
    loop = model.getAirLoopHVACs()[0]
    variables = (
        "Air System Outdoor Air Mass Flow Rate",
        "Air System Outdoor Air Mechanical Ventilation Requested Mass Flow Rate",
    )
    for variable in variables:
        output = o.model.OutputVariable(variable, model)
        output.setKeyValue(loop.nameString())
        output.setReportingFrequency("Hourly")
    output = o.model.OutputVariable("Zone People Occupant Count", model)
    output.setKeyValue("*")
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
        for name in (*variables, "Zone People Occupant Count"):
            rows = sql.execute(
                "SELECT t.EnvironmentPeriodIndex, t.SimulationDays, t.Hour, SUM(r.Value) FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE d.Name=? AND t.WarmupFlag=0 GROUP BY t.EnvironmentPeriodIndex, t.SimulationDays, t.Hour",
                (name,),
            ).fetchall()
            assert rows, name
            result[name] = {tuple(row[:3]): row[3] for row in rows}
    return result


@pytest.mark.parametrize("system", ["VAV", "CAV"])
@pytest.mark.parametrize("floor", ["zero", "Autosize", "design_fixed"])
def test_native_dcv_changes_requested_and_actual_outdoor_air(
    sdk, tmp_path, system, floor
):
    from pathlib import Path
    from vav_fixture import prepare_vav_fixture
    from common import cav_system
    from common.hvac_inventory import inventory as hvac_inventory
    from common.vav_plan import plan as vav_plan
    from common.vav_create import create as create_vav

    o = sdk[0]
    source, base, _, _ = prepare_vav_fixture(o, tmp_path, True)
    model = o.osversion.VersionTranslator().loadModel(str(source)).get()
    for person in list(model.getPeoples()):
        person.remove()
    for space in model.getSpaces():
        oa = o.model.DesignSpecificationOutdoorAir(model)
        oa.setOutdoorAirMethod("Sum")
        oa.setOutdoorAirFlowperPerson(0.005)
        oa.setOutdoorAirFlowperFloorArea(0.0001)
        space.setDesignSpecificationOutdoorAir(oa)
        pd = o.model.PeopleDefinition(model)
        pd.setNumberofPeople(100)
        people = o.model.People(pd)
        people.setSpace(space)
        schedule = o.model.ScheduleRuleset(model)
        day = schedule.defaultDaySchedule()
        day.addValue(o.Time(0, 12, 0, 0), 0.1)
        day.addValue(o.Time(0, 24, 0, 0), 1)
        schedule.setSummerDesignDaySchedule(day)
        schedule.setWinterDesignDaySchedule(day)
        people.setNumberofPeopleSchedule(schedule)
        activity = o.model.ScheduleConstant(model)
        activity.setValue(120)
        people.setActivityLevelSchedule(activity)
    base.update(
        system_name="Ventilation Evidence",
        outdoor_air_schedule=None,
        economizer="NoEconomizer",
    )
    if system == "CAV":
        base["defaults_profile"] = "prototype_cav_v1"
        cav_system.create(model, o, cav_system.plan(model, o, base))
    else:
        create_vav(model, o, vav_plan(base, hvac_inventory(model), None))
    loop = model.getAirLoopHVACs()[0]
    loop.setAvailabilitySchedule(model.alwaysOnDiscreteSchedule())
    c = loop.airLoopHVACOutdoorAirSystem().get().getControllerOutdoorAir()
    if floor == "zero":
        c.setMinimumOutdoorAirFlowRate(0)
    else:
        assert c.isMinimumOutdoorAirFlowRateAutosized()
        if floor == "design_fixed":
            c.setMinimumOutdoorAirFlowRate(
                vent.zone_requirements(loop)["nominal_design_oa_m3_s"]
            )
    model.save(str(source), True)
    cfg = config(tmp_path, dcv=True)
    cfg["air_loop"] = {"handle": str(loop.handle())}
    report = preflight(source, cfg)
    assert report["ready"] and report["plan"]["simulation_ready"], report["plan"]
    assert report["plan"]["impact"]["dcv_effective"] is (
        False if floor == "design_fixed" else None
    )
    result = apply(report, tmp_path)
    assert result["simulation_ready"]
    before = native_run(o, source, tmp_path / "before")
    after = native_run(o, Path(result["output_model_path"]), tmp_path / "after")
    req = "Air System Outdoor Air Mechanical Ventilation Requested Mass Flow Rate"
    flow = "Air System Outdoor Air Mass Flow Rate"
    pop = "Zone People Occupant Count"
    common = before[req].keys() & after[req].keys()
    low = [
        t
        for t in common
        if before[pop][t] < max(before[pop].values()) * 0.5 and before[req][t] > 0
    ]
    high = [
        t
        for t in common
        if before[pop][t] > max(before[pop].values()) * 0.99 and before[req][t] > 0
    ]
    assert low and high
    assert any(after[req][t] < before[req][t] * 0.8 for t in low)
    if floor != "design_fixed":
        assert any(after[flow][t] < before[flow][t] * 0.8 for t in low)
    else:
        assert all(
            after[flow][t] == pytest.approx(before[flow][t], rel=1e-6, abs=1e-6)
            for t in low + high
        )
    assert all(after[req][t] == pytest.approx(before[req][t], rel=1e-6) for t in high)
    evidence = dict(
        system=system,
        minimum_flow_policy=floor,
        dcv_effective=report["plan"]["impact"]["dcv_effective"],
        low_occupancy_hours=len(low),
        high_occupancy_hours=len(high),
        minimum_requested_ratio=min(after[req][t] / before[req][t] for t in low),
        minimum_actual_ratio=min(
            after[flow][t] / before[flow][t] for t in low if before[flow][t] > 0
        ),
        severe_errors=0,
        note="Paired ZoneSum DCV with zero, retained autosized or fixed design floor; separate instrumented copies; no annual savings/compliance claim",
    )
    (tmp_path / "native_evidence.json").write_text(json.dumps(evidence, indent=2))


@pytest.mark.parametrize(
    "key",
    ["minimum_flow_schedule", "minimum_fraction_schedule", "maximum_fraction_schedule"],
)
def test_untyped_schedule_is_unready_before_sdk_can_mutate_it(
    sdk, model_file, tmp_path, key
):
    o = sdk[0]
    model, _ = fixture(o, model_file, tmp_path)
    schedule = o.model.ScheduleConstant(model)
    schedule.setName("Untyped")
    schedule.setValue(0.5)
    model.save(str(model_file), True)
    original = model_file.read_bytes()
    report = preflight(model_file, config(tmp_path, **{key: {"name": "Untyped"}}))
    assert not report["ready"]
    assert any("type limits" in e for e in report["plan"]["errors"])
    assert model_file.read_bytes() == original


def test_preview_rejects_unrequested_setter_side_effect(
    sdk, model_file, tmp_path, monkeypatch
):
    fixture(sdk[0], model_file, tmp_path)
    original = vent.set_settings

    def side_effect(model, native, controller, mv, patch):
        original(model, native, controller, mv, patch)
        model.getPeopleDefinitions()[0].setNumberofPeople(50)

    monkeypatch.setattr(vent, "set_settings", side_effect)
    report = preflight(model_file, config(tmp_path))
    assert not report["ready"]
    assert any("protected objects" in e for e in report["plan"]["errors"])


def test_autosize_and_disable_are_explicit(sdk, model_file, tmp_path):
    model, c = fixture(sdk[0], model_file, tmp_path)
    c.setMinimumOutdoorAirFlowRate(0.1)
    c.setMaximumOutdoorAirFlowRate(1)
    c.controllerMechanicalVentilation().setDemandControlledVentilation(True)
    model.save(str(model_file), True)
    result = apply(
        preflight(
            model_file,
            config(
                tmp_path,
                dcv=False,
                minimum_flow_m3_s="Autosize",
                maximum_flow_m3_s="Autosize",
            ),
        ),
        tmp_path,
    )
    assert result["changes"]["after"]["dcv"] is False
    assert result["changes"]["after"]["minimum_flow_m3_s"] == "Autosize"
    assert result["changes"]["after"]["maximum_flow_m3_s"] == "Autosize"


def test_sdk_version_pin_precedes_loading(sdk, tmp_path, monkeypatch):
    from common.version_guard import CompatibilityError

    monkeypatch.setattr(sdk[0], "openStudioVersion", lambda: "3.12.0")
    with pytest.raises(CompatibilityError, match="3.11.0"):
        preflight(tmp_path / "missing.osm", config(tmp_path))


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_relocated_ventilation_bundle(sdk, model_file, tmp_path, host):
    import shutil
    import subprocess
    from pathlib import Path
    from adapters.claude_code_adapter import ClaudeCodeAdapter
    from adapters.codex_adapter import CodexAdapter
    from adapters.contracts import HostAdapterConfig
    from test_supply_fan_performance import native_cli

    fixture(sdk[0], model_file, tmp_path)
    setup = HostAdapterConfig(
        host_name=host, workspace_root=Path.cwd(), runtime_mode="marketplace"
    )
    adapter = ClaudeCodeAdapter(setup) if host == "claude" else CodexAdapter(setup)
    exported = tmp_path / "export"
    adapter.export_plugin(exported, dry_run=False)
    bundle = next(exported.rglob("openstudio-ventilation-editor/SKILL.md")).parent
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
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config(tmp_path)))
    plan = tmp_path / "reviewed.json"
    for args in (
        ["--input", str(model_file), "--report", str(tmp_path / "inventory.json")],
        ["--input", str(model_file), "--config", str(cfg), "--report", str(plan)],
        ["--plan", str(plan), "--report", str(tmp_path / "applied.json")],
    ):
        run = subprocess.run(
            [
                str(native_cli()),
                "execute_python_script",
                str(moved / "scripts/edit_ventilation.py"),
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


def test_constant_occupancy_above_design_is_not_simulation_ready(
    sdk, model_file, tmp_path
):
    o = sdk[0]
    model, _ = fixture(o, model_file, tmp_path)
    day = model.getScheduleRulesetByName("Occupancy").get().defaultDaySchedule()
    day.clearValues()
    day.addValue(o.Time(0, 24, 0, 0), 1.2)
    model.save(str(model_file), True)
    report = preflight(model_file, config(tmp_path))
    assert report["ready"] and not report["plan"]["simulation_ready"]
    assert any("exceeds nominal" in w for w in report["warnings"])


def test_incoming_references_and_metadata_stay_intact(sdk, model_file, tmp_path):
    o = sdk[0]
    model, c = fixture(o, model_file, tmp_path)
    actuator = o.model.EnergyManagementSystemActuator(
        c, "Outdoor Air Controller", "Air Mass Flow Rate"
    )
    c.additionalProperties().setFeature("user_tag", "keep")
    model.save(str(model_file), True)
    result = apply(preflight(model_file, config(tmp_path)), tmp_path)
    saved = o.model.Model.load(result["output_model_path"]).get()
    assert (
        saved.getEnergyManagementSystemActuator(actuator.handle())
        .get()
        .actuatedComponent()
        .get()
        .handle()
        == c.handle()
    )
    assert (
        saved.getControllerOutdoorAir(c.handle())
        .get()
        .additionalProperties()
        .getFeatureAsString("user_tag")
        .get()
        == "keep"
    )
    assert any("EMS actuators target OA/MV" in w for w in result["warnings"])


@pytest.mark.parametrize("kind", ["VariableVolume", "ConstantVolume"])
@pytest.mark.parametrize(
    "floor, blocked",
    [("Autosize", False), (0.08, True), (0.1, True), (0.04, False), (0, False)],
)
def test_dcv_floor_impact_and_explicit_guidance(
    sdk, model_file, tmp_path, kind, floor, blocked
):
    model, controller = fixture(sdk[0], model_file, tmp_path, kind)
    if floor != "Autosize":
        controller.setMinimumOutdoorAirFlowRate(floor)
    model.save(str(model_file), True)
    report = preflight(model_file, config(tmp_path, dcv=True))
    assert report["ready"] and report["plan"]["simulation_ready"]
    impact = report["plan"]["impact"]
    assert impact["dcv_effective"] is (False if blocked else None)
    assert impact["dcv_floor"]["blocks_design_oa_reductions"] is blocked
    assert impact["after"]["minimum_flow_m3_s"] == floor
    direct = [w for w in report["warnings"] if "DCV will have no effect" in w]
    assert bool(direct) is blocked
    if blocked:
        assert "minimum_flow_m3_s" in direct[0] and "for example 0" in direct[0]
    elif floor == "Autosize":
        assert impact["dcv_floor"]["translated_minimum_flow_m3_s"] == 0
        assert any("translates the EnergyPlus minimum" in w for w in report["warnings"])
    elif floor > 0:
        assert any("can mask DCV" in w for w in report["warnings"])
    result = apply(report, tmp_path)
    assert result["changes"]["after"]["minimum_flow_m3_s"] == floor
    assert (
        result["simulation_ready"] is report["plan"]["companions"]["simulation_ready"]
    )
    assert (
        bool([w for w in result["warnings"] if "DCV will have no effect" in w])
        is blocked
    )


@pytest.mark.parametrize(
    "case",
    [
        "varying_schedule",
        "zero_schedule",
        "half_schedule",
        "unverified_schedule",
        "proportional",
        "fixed_sizing_below_nominal",
    ],
)
def test_lower_or_unverified_effective_floor_keeps_qualified_warning(
    sdk, model_file, tmp_path, case
):
    o = sdk[0]
    model, controller = fixture(o, model_file, tmp_path)
    if case == "proportional":
        controller.setMinimumOutdoorAirFlowRate(0.08)
        controller.setMinimumLimitType("ProportionalMinimum")
    elif case == "fixed_sizing_below_nominal":
        model.getAirLoopHVACs()[0].sizingSystem().setDesignOutdoorAirFlowRate(0.04)
    else:
        controller.setMinimumOutdoorAirFlowRate(0.08)
        if case == "varying_schedule":
            schedule = model.getScheduleRulesetByName("Occupancy").get()
        elif case == "unverified_schedule":
            schedule = o.model.ScheduleCompact(model)
        else:
            schedule = o.model.ScheduleConstant(model)
            schedule.setValue(0 if case == "zero_schedule" else 0.5)
        controller.setMinimumOutdoorAirSchedule(schedule)
    model.save(str(model_file), True)
    report = preflight(model_file, config(tmp_path, dcv=True))
    assert report["ready"]
    assert report["plan"]["impact"]["dcv_effective"] is None
    assert not any("DCV will have no effect" in w for w in report["warnings"])
    phrase = (
        "translates the EnergyPlus minimum"
        if case == "fixed_sizing_below_nominal"
        else "can mask DCV"
    )
    assert any(phrase in w for w in report["warnings"])
