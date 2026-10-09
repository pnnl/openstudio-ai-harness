"""Economizer edits: explicit settings, saved preservation and native operation."""

import json
import sys
import pytest
from test_vav_preflight import sdk, model_file, SCRIPTS
from test_supply_fan_performance import served_model

sys.path.insert(0, str(SCRIPTS))
from common import economizer_edit as econ, model_transaction as tx

OPERATION = "edit_economizer"


def config(tmp_path, **settings):
    return dict(
        output_model_path=str(tmp_path / "edited.osm"),
        air_loop={"name": "Existing Air Loop"},
        economizer=settings
        or {"control_type": "FixedDryBulb", "maximum_dry_bulb_c": 24.0},
    )


def preflight(source, cfg):
    return tx.preflight(source, cfg, OPERATION, econ.plan)


def apply(report, tmp_path, creator=None):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(report))
    return tx.apply(
        path, OPERATION, econ.plan, creator or econ.edit, econ.validate_model
    )


@pytest.mark.parametrize("kind", ["VariableVolume", "ConstantVolume"])
def test_saved_edit_preserves_controller_and_ventilation(
    sdk, model_file, tmp_path, kind
):
    o = sdk[0]
    model, _ = served_model(o, model_file, tmp_path, kind)
    loop = model.getAirLoopHVACs()[0]
    controller = loop.airLoopHVACOutdoorAirSystem().get().getControllerOutdoorAir()
    controller.additionalProperties().setFeature("review", "keep")
    model.save(str(model_file), True)
    original = model_file.read_bytes()
    report = preflight(model_file, config(tmp_path))
    assert report["ready"], report
    assert report == preflight(model_file, config(tmp_path))
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and result["translation"]["ok"]
    saved = o.model.Model.load(result["output_model_path"]).get()
    c = saved.getControllerOutdoorAir(controller.handle()).get()
    assert c.getEconomizerControlType() == "FixedDryBulb"
    assert c.getEconomizerMaximumLimitDryBulbTemperature().get() == 24
    assert (
        c.getEconomizerMaximumLimitEnthalpy().get()
        == controller.getEconomizerMaximumLimitEnthalpy().get()
    )
    assert c.getLockoutType() == controller.getLockoutType()
    assert c.additionalProperties().getFeatureAsString("review").get() == "keep"
    assert model_file.read_bytes() == original
    assert result["validation"]["checks"] == 7


def controller_fixture(o, source, tmp_path):
    model, _ = served_model(o, source, tmp_path)
    return (
        model,
        model.getAirLoopHVACs()[0]
        .airLoopHVACOutdoorAirSystem()
        .get()
        .getControllerOutdoorAir(),
    )


@pytest.mark.parametrize(
    "settings",
    [
        {"lockout_type": "LockoutWithHeating"},
        {"maximum_dry_bulb_c": 22.123456789},
        {"maximum_enthalpy_j_kg": None},
        {"maximum_dewpoint_c": 15},
        {"minimum_dry_bulb_c": -4},
        {"control_type": "FixedEnthalpy"},
        {"control_type": "DifferentialDryBulb"},
        {"control_type": "DifferentialEnthalpy"},
        {"control_type": "DifferentialDryBulbAndEnthalpy"},
        {"control_type": "FixedDewPointAndDryBulb", "maximum_dewpoint_c": 13},
    ],
)
def test_explicit_partial_fields_apply(sdk, model_file, tmp_path, settings):
    controller_fixture(sdk[0], model_file, tmp_path)
    report = preflight(model_file, config(tmp_path, **settings))
    assert report["ready"], report
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and result["translation"]["ok"]
    assert all(result["changes"]["after"][k] == v for k, v in settings.items())


@pytest.mark.parametrize(
    "settings",
    [
        {"control_type": "FixedDryBulb", "maximum_dry_bulb_c": None},
        {"control_type": "FixedEnthalpy", "maximum_enthalpy_j_kg": None},
        {"control_type": "FixedDewPointAndDryBulb"},
        {"control_type": "ElectronicEnthalpy"},
        {"control_type": "FixedDryBulb", "minimum_dry_bulb_c": 30},
        {"control_type": "NoEconomizer"},
    ],
)
def test_effective_controls_or_noop_block_before_apply(
    sdk, model_file, tmp_path, settings
):
    controller_fixture(sdk[0], model_file, tmp_path)
    report = preflight(model_file, config(tmp_path, **settings))
    assert not report["ready"] and report["plan"]["errors"]
    with pytest.raises(ValueError, match="ready"):
        apply(report, tmp_path)


@pytest.mark.parametrize(
    "settings",
    [
        {"control_type": "guess"},
        {"maximum_dry_bulb_c": "24"},
        {"maximum_enthalpy_j_kg": -1},
        {"lockout_type": None},
        {"dcv": True},
        {"maximum_dry_bulb_c": True},
        {"maximum_dewpoint_c": 101},
    ],
)
def test_schema_rejects_unsupported_inputs(sdk, model_file, tmp_path, settings):
    controller_fixture(sdk[0], model_file, tmp_path)
    with pytest.raises(ValueError, match="Invalid economizer"):
        preflight(model_file, config(tmp_path, **settings))


def test_missing_choices_and_duplicate_names(sdk, model_file, tmp_path):
    o = sdk[0]
    model, _ = controller_fixture(o, model_file, tmp_path)
    partial = {"output_model_path": str(tmp_path / "edited.osm")}
    assert preflight(model_file, partial)["plan"]["missing_inputs"] == [
        "air_loop",
        "economizer",
    ]
    cfg = config(tmp_path)
    cfg["economizer"] = {}
    assert not preflight(model_file, cfg)["ready"]
    second = o.model.AirLoopHVAC(model)
    second.setName("Second")
    # OpenStudio automatically disambiguates duplicate names. Missing and wrong-class
    # handles still must not select the first available controller.
    cfg["air_loop"] = {"handle": str(second.handle())}
    model.save(str(model_file), True)
    assert not preflight(model_file, cfg)["ready"]
    cfg["air_loop"] = {"name": "Missing"}
    assert not preflight(model_file, cfg)["ready"]


@pytest.mark.parametrize("curve_kind", ["Quadratic", "Cubic"])
def test_existing_electronic_curve_and_incoming_references_preserved(
    sdk, model_file, tmp_path, curve_kind
):
    o = sdk[0]
    model, c = controller_fixture(o, model_file, tmp_path)
    curve = getattr(o.model, "Curve" + curve_kind)(model)
    c.setElectronicEnthalpyLimitCurve(curve)
    c.additionalProperties().setFeature("retain", "yes")
    actuator = o.model.EnergyManagementSystemActuator(
        c, "Outdoor Air Controller", "Air Mass Flow Rate"
    )
    handle = actuator.handle()
    model.save(str(model_file), True)
    report = preflight(model_file, config(tmp_path, control_type="ElectronicEnthalpy"))
    assert report["ready"], report
    assert report["plan"]["retained_context"]["electronic_enthalpy_curve"][
        "handle"
    ] == str(curve.handle())
    result = apply(report, tmp_path)
    saved = o.model.Model.load(result["output_model_path"]).get()
    assert (
        saved.getEnergyManagementSystemActuator(handle)
        .get()
        .actuatedComponent()
        .get()
        .handle()
        == c.handle()
    )
    assert (
        saved.getControllerOutdoorAir(c.handle())
        .get()
        .electronicEnthalpyLimitCurve()
        .get()
        .handle()
        == curve.handle()
    )


@pytest.mark.parametrize(
    "case, phrase, simulation_ready",
    [
        ("full_oa", "100% outdoor air", False),
        ("oa_cap", "override minimum ventilation", True),
        ("zero_cap", "suppress/contradict", False),
        ("conflicting_flow", "flow constraints conflict", False),
        ("force_schedule", "force maximum outdoor air", True),
        ("bypass", "MinimumFlowWithBypass", True),
    ],
)
def test_retained_controls_are_visible(
    sdk, model_file, tmp_path, case, phrase, simulation_ready
):
    o = sdk[0]
    model, c = controller_fixture(o, model_file, tmp_path)
    if case in ("full_oa", "oa_cap", "zero_cap", "force_schedule"):
        schedule = o.model.ScheduleConstant(model)
        schedule.setValue(
            {"full_oa": 1, "oa_cap": 0.4, "zero_cap": 0, "force_schedule": 1}[case]
        )
        setter = {
            "full_oa": "setMinimumFractionofOutdoorAirSchedule",
            "oa_cap": "setMaximumFractionofOutdoorAirSchedule",
            "zero_cap": "setMaximumFractionofOutdoorAirSchedule",
            "force_schedule": "setTimeofDayEconomizerControlSchedule",
        }[case]
        assert getattr(c, setter)(schedule)
    elif case == "conflicting_flow":
        assert c.setMinimumOutdoorAirFlowRate(2)
        assert c.setMaximumOutdoorAirFlowRate(1)
    else:
        assert c.setEconomizerControlActionType("MinimumFlowWithBypass")
    model.save(str(model_file), True)
    report = preflight(model_file, config(tmp_path))
    assert report["ready"] and report["plan"]["simulation_ready"] == simulation_ready
    assert any(phrase in warning for warning in report["warnings"])
    # Default false OptionalBool must not produce a spurious humidity warning.
    assert not any("high-humidity" in w for w in report["warnings"])


@pytest.mark.parametrize(
    "fault",
    [
        "setting",
        "ventilation",
        "schedule",
        "sizing",
        "object",
        "curve",
        "metadata",
        "result",
    ],
)
def test_corruption_is_rejected_before_publishing(sdk, model_file, tmp_path, fault):
    o = sdk[0]
    controller_fixture(o, model_file, tmp_path)
    report = preflight(model_file, config(tmp_path))

    def bad_edit(model, native, planned):
        result = econ.edit(model, native, planned)
        c = model.getControllerOutdoorAirs()[0]
        if fault == "setting":
            c.setEconomizerMaximumLimitDryBulbTemperature(27)
        elif fault == "ventilation":
            c.setMinimumOutdoorAirFlowRate(8)
        elif fault == "schedule":
            c.setMinimumOutdoorAirSchedule(model.alwaysOnDiscreteSchedule())
        elif fault == "sizing":
            model.getAirLoopHVACs()[0].sizingSystem().setAllOutdoorAirinCooling(True)
        elif fault == "object":
            native.model.ScheduleConstant(model)
        elif fault == "curve":
            c.setElectronicEnthalpyLimitCurve(native.model.CurveQuadratic(model))
        elif fault == "metadata":
            c.additionalProperties().setFeature("unauthorized", True)
        else:
            result["after"]["control_type"] = "NoEconomizer"
        return result

    with pytest.raises(ValueError, match="validation"):
        apply(report, tmp_path, bad_edit)
    assert not (tmp_path / "edited.osm").exists()
    assert not (tmp_path / "edited").exists()


def test_plan_tampering_and_stale_source_rejected(sdk, model_file, tmp_path):
    controller_fixture(sdk[0], model_file, tmp_path)
    report = preflight(model_file, config(tmp_path))
    report["plan"]["after_values"]["maximum_dry_bulb_c"] = 31
    with pytest.raises(ValueError, match="differs"):
        apply(report, tmp_path)
    report = preflight(model_file, config(tmp_path))
    model_file.write_bytes(model_file.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="Stale"):
        apply(report, tmp_path)


def native_economizer_run(o, source, folder):
    """Instrument a separate copy; inspect actual OA response in native SQL."""
    import sqlite3
    import subprocess
    from pathlib import Path
    from test_supply_fan_performance import native_cli

    folder.mkdir()
    model = o.osversion.VersionTranslator().loadModel(str(source)).get()
    loop = model.getAirLoopHVACs()[0]
    for variable in (
        "Air System Outdoor Air Economizer Status",
        "Air System Outdoor Air Mass Flow Rate",
        "Air System Mixed Air Mass Flow Rate",
    ):
        out = o.model.OutputVariable(variable, model)
        out.setKeyValue(loop.nameString())
        out.setReportingFrequency("Detailed")
    weather = model.getWeatherFile().path().get()
    epw = Path(str(weather))
    if not epw.is_absolute():
        epw = source.parent / epw
    assert o.model.WeatherFile.setWeatherFile(
        model, o.EpwFile(str(epw.resolve()))
    ).is_initialized()
    instrumented = folder / "instrumented.osm"
    assert model.save(str(instrumented), True)
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
        series = {}
        for variable in (
            "Air System Outdoor Air Economizer Status",
            "Air System Outdoor Air Mass Flow Rate",
            "Air System Mixed Air Mass Flow Rate",
        ):
            rows = sql.execute(
                "SELECT r.TimeIndex, r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE d.KeyValue=? AND d.Name=? AND t.WarmupFlag=0",
                (loop.nameString().upper(), variable),
            ).fetchall()
            assert rows, variable
            series[variable] = dict(rows)
    oa = series["Air System Outdoor Air Mass Flow Rate"]
    mixed = series["Air System Mixed Air Mass Flow Rate"]
    series["Air System Outdoor Air Mass Flow Fraction"] = {
        t: q / mixed[t] if mixed[t] > 1e-9 else 0 for t, q in oa.items()
    }
    return series


@pytest.mark.parametrize("system", ["VAV", "CAV"])
def test_native_economizer_response(sdk, tmp_path, system):
    from pathlib import Path
    from vav_fixture import prepare_vav_fixture
    from common import cav_system
    from common.hvac_inventory import inventory as hvac_inventory
    from common.vav_plan import plan as vav_plan
    from common.vav_create import create as create_vav

    o = sdk[0]
    source, base, _, _ = prepare_vav_fixture(o, tmp_path, True)
    model = o.osversion.VersionTranslator().loadModel(str(source)).get()
    base.update(
        system_name="Economizer Evidence",
        economizer="NoEconomizer",
        outdoor_air_schedule=None,
    )
    if system == "CAV":
        base["defaults_profile"] = "prototype_cav_v1"
        cav_system.create(model, o, cav_system.plan(model, o, base))
    else:
        create_vav(model, o, vav_plan(base, hvac_inventory(model), None))
    loop = model.getAirLoopHVACs()[0]
    loop.setAvailabilitySchedule(model.alwaysOnDiscreteSchedule())
    c = loop.airLoopHVACOutdoorAirSystem().get().getControllerOutdoorAir()
    # Isolate dry-bulb operation from additive cutoffs. These are fixture inputs,
    # not inferred resets performed by the editor.
    c.resetEconomizerMaximumLimitEnthalpy()
    c.resetEconomizerMaximumLimitDewpointTemperature()
    c.resetEconomizerMinimumLimitDryBulbTemperature()
    c.setLockoutType("NoLockout")
    # A mild sunny cooling design day exercises free cooling, unlike hot peak sizing.
    cooling = next(d for d in model.getDesignDays() if d.dayType() == "SummerDesignDay")
    cooling.setMaximumDryBulbTemperature(20)
    cooling.setDailyDryBulbTemperatureRange(6)
    cooling.setHumidityConditionType("Wetbulb")
    cooling.setWetBulbOrDewPointAtMaximumDryBulb(13)
    model.save(str(source), True)
    cfg = config(tmp_path, control_type="FixedDryBulb", maximum_dry_bulb_c=24)
    cfg["air_loop"] = {"handle": str(loop.handle())}
    report = preflight(source, cfg)
    assert report["ready"], report
    result = apply(report, tmp_path)
    before = native_economizer_run(o, source, tmp_path / "before")
    after = native_economizer_run(
        o, Path(result["output_model_path"]), tmp_path / "after"
    )
    status = "Air System Outdoor Air Economizer Status"
    fraction = "Air System Outdoor Air Mass Flow Fraction"
    assert max(before[status].values()) == 0
    active = [t for t, v in after[status].items() if v > 0.5]
    assert active
    matched = [t for t in active if t in before[fraction]]
    increases = [after[fraction][t] - before[fraction][t] for t in matched]
    assert max(increases) > 0.05, (before, after)
    evidence = dict(
        system=system,
        native_version=o.openStudioVersion(),
        enabled_steps=len(active),
        maximum_fraction_before=max(before[fraction].values()),
        maximum_fraction_after=max(after[fraction].values()),
        largest_matched_fraction_increase=max(increases),
        severe_errors=0,
        note="Mild design-day operational evidence; not annual savings or ventilation compliance",
    )
    (tmp_path / "native_evidence.json").write_text(json.dumps(evidence, indent=2))


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_relocated_economizer_bundle(sdk, model_file, tmp_path, host):
    import shutil
    import subprocess
    from pathlib import Path
    from adapters.claude_code_adapter import ClaudeCodeAdapter
    from adapters.codex_adapter import CodexAdapter
    from adapters.contracts import HostAdapterConfig
    from test_supply_fan_performance import native_cli

    controller_fixture(sdk[0], model_file, tmp_path)
    setup = HostAdapterConfig(
        host_name=host, workspace_root=Path.cwd(), runtime_mode="marketplace"
    )
    adapter = ClaudeCodeAdapter(setup) if host == "claude" else CodexAdapter(setup)
    exported = tmp_path / "export"
    adapter.export_plugin(exported, dry_run=False)
    bundle = next(exported.rglob("openstudio-economizer-editor/SKILL.md")).parent
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
                str(moved / "scripts/edit_economizer.py"),
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


def test_sdk_version_pin_precedes_source_loading(sdk, tmp_path, monkeypatch):
    from common.version_guard import CompatibilityError

    monkeypatch.setattr(sdk[0], "openStudioVersion", lambda: "3.12.0")
    with pytest.raises(CompatibilityError, match="3.11.0"):
        preflight(tmp_path / "missing.osm", config(tmp_path))


def test_disable_retains_limits_and_translated_control(sdk, model_file, tmp_path):
    o = sdk[0]
    model, c = controller_fixture(o, model_file, tmp_path)
    c.setEconomizerControlType("FixedDryBulb")
    c.setEconomizerMaximumLimitDryBulbTemperature(23)
    model.save(str(model_file), True)
    result = apply(
        preflight(model_file, config(tmp_path, control_type="NoEconomizer")), tmp_path
    )
    saved = o.model.Model.load(result["output_model_path"]).get()
    assert (
        saved.getControllerOutdoorAir(c.handle())
        .get()
        .getEconomizerMaximumLimitDryBulbTemperature()
        .get()
        == 23
    )
    workspace = o.energyplus.ForwardTranslator().translateModel(saved)
    translated = workspace.getObjectsByType(o.IddObjectType("Controller_OutdoorAir"))[0]
    field = translated.iddObject().getFieldIndex("Economizer Control Type").get()
    assert translated.getString(field).get() == "NoEconomizer"
    assert any("inactive" in w for w in result["warnings"])


def test_hydronic_lockout_warning_names_retained_limitation(sdk, model_file, tmp_path):
    o = sdk[0]
    model, _ = served_model(o, model_file, tmp_path, "ConstantVolume")
    # Add a hydronic cooling coil to this disposable direct-supply fixture.
    coil = o.model.CoilCoolingWater(model)
    assert model.getPlantLoops()[0].addDemandBranchForComponent(coil)
    assert coil.addToNode(model.getAirLoopHVACs()[0].supplyOutletNode())
    model.save(str(model_file), True)
    report = preflight(
        model_file, config(tmp_path, lockout_type="LockoutWithCompressor")
    )
    assert report["ready"], report
    assert any("retained hydronic cooling coil" in w for w in report["warnings"])


@pytest.mark.parametrize("kind", ["VariableVolume", "ConstantVolume"])
@pytest.mark.parametrize("already_enabled", [False, True])
def test_missing_mixed_air_setpoint_warns_and_cannot_claim_simulation_readiness(
    sdk, model_file, tmp_path, kind, already_enabled
):
    o = sdk[0]
    model, _ = served_model(o, model_file, tmp_path, kind)
    loop = model.getAirLoopHVACs()[0]
    controller = loop.airLoopHVACOutdoorAirSystem().get().getControllerOutdoorAir()
    if already_enabled:
        controller.setEconomizerControlType("FixedDryBulb")
    for manager in loop.supplyOutletNode().setpointManagers():
        manager.remove()
    assert model.save(str(model_file), True)
    original = model_file.read_bytes()
    cfg = (
        config(tmp_path, lockout_type="LockoutWithHeating")
        if already_enabled
        else config(tmp_path)
    )
    report = preflight(model_file, cfg)
    assert report["ready"], report
    assert report == preflight(model_file, cfg)
    assert report["plan"]["simulation_ready"] is False
    assert report["plan"]["companions"]["simulation_ready"] is False
    control = report["plan"]["retained_context"]["mixed_air_control"]
    assert not control["temperature_setpoint_verified"]
    assert control["temperature_managers"] == []
    assert (
        control["mixed_air_node"]
        == loop.airLoopHVACOutdoorAirSystem()
        .get()
        .mixedAirModelObject()
        .get()
        .nameString()
    )
    assert (
        report["plan"]["impact"]["retained_ventilation"]["mixed_air_control"] == control
    )
    assert any(
        "no verified translated Temperature setpoint" in w for w in report["warnings"]
    )
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and result["simulation_ready"] is False
    assert any("mixed-air node" in w for w in result["warnings"])
    assert model_file.read_bytes() == original


@pytest.mark.parametrize(
    "source", ["generated", "direct", "humidity", "dual", "disabled"]
)
def test_mixed_air_control_uses_translated_temperature_target(
    sdk, model_file, tmp_path, source
):
    o = sdk[0]
    model, c = controller_fixture(o, model_file, tmp_path)
    loop = model.getAirLoopHVACs()[0]
    mixed = (
        loop.airLoopHVACOutdoorAirSystem()
        .get()
        .mixedAirModelObject()
        .get()
        .to_Node()
        .get()
    )
    if source != "generated":
        for manager in loop.supplyOutletNode().setpointManagers():
            manager.remove()
    if source in ("direct", "humidity", "dual"):
        schedule = o.model.ScheduleConstant(model)
        schedule.setValue(12.8 if source != "humidity" else 0.008)
        if source == "dual":
            manager = o.model.SetpointManagerScheduledDualSetpoint(model)
            assert manager.setHighSetpointSchedule(schedule)
            assert manager.setLowSetpointSchedule(schedule)
        else:
            manager = o.model.SetpointManagerScheduled(model, schedule)
            assert manager.setControlVariable(
                "MaximumHumidityRatio" if source == "humidity" else "Temperature"
            )
        assert manager.addToNode(mixed)
    assert model.save(str(model_file), True)
    cfg = (
        config(tmp_path, maximum_dry_bulb_c=23)
        if source == "disabled"
        else config(tmp_path)
    )
    report = preflight(model_file, cfg)
    assert report["ready"], report
    control = report["plan"]["retained_context"]["mixed_air_control"]
    if source == "disabled":
        assert control is None
        assert report["plan"]["simulation_ready"]
        assert not any("no verified translated" in w for w in report["warnings"])
    else:
        verified = source in ("generated", "direct")
        assert control["temperature_setpoint_verified"] is verified
        assert report["plan"]["simulation_ready"] is verified
        if verified:
            kinds = {x["type"] for x in control["temperature_managers"]}
            assert (
                "SetpointManager:MixedAir"
                if source == "generated"
                else "SetpointManager:Scheduled"
            ) in kinds
    assert apply(report, tmp_path)["validation"]["ok"]


@pytest.mark.parametrize("delta, accepted", [(1e-10, True), (1e-5, False)])
@pytest.mark.parametrize("location", ["saved", "reported"])
def test_only_tiny_numeric_rounding_is_accepted(
    sdk, model_file, tmp_path, delta, accepted, location
):
    o = sdk[0]
    controller_fixture(o, model_file, tmp_path)
    report = preflight(model_file, config(tmp_path))

    def rounded(model, native, planned):
        result = econ.edit(model, native, planned)
        if location == "saved":
            c = model.getControllerOutdoorAirs()[0]
            assert c.setEconomizerMaximumLimitDryBulbTemperature(24 + delta)
        else:
            result["after"]["maximum_dry_bulb_c"] += delta
        return result

    if accepted:
        assert apply(report, tmp_path, rounded)["validation"]["ok"]
    else:
        with pytest.raises(ValueError, match="validation"):
            apply(report, tmp_path, rounded)
        assert not (tmp_path / "edited.osm").exists()


@pytest.mark.parametrize(
    "key, value", [("maximum_dewpoint_c", 0), ("control_type", "fixeddrybulb")]
)
def test_rounding_tolerance_does_not_relax_nulls_or_enums(
    sdk, model_file, tmp_path, key, value
):
    controller_fixture(sdk[0], model_file, tmp_path)
    report = preflight(model_file, config(tmp_path))

    def incorrect_report(model, native, planned):
        result = econ.edit(model, native, planned)
        result["after"][key] = value
        return result

    with pytest.raises(ValueError, match="validation"):
        apply(report, tmp_path, incorrect_report)


def test_translated_target_matching_expands_node_lists_and_ignores_reference_nodes(
    sdk, model_file, tmp_path
):
    from common.temperature_control import node_temperature_managers

    o = sdk[0]
    model, _ = controller_fixture(o, model_file, tmp_path)
    workspace = o.energyplus.ForwardTranslator().translateModel(model)
    for obj in list(workspace.objects()):
        if obj.iddObject().name().startswith("SetpointManager:"):
            obj.remove()
    target = "Mixed Air Test Node"
    objects = [
        "NodeList, Test Targets, Mixed Air Test Node, Other Node;",
        "SetpointManager:Scheduled, Direct Test, Temperature, Always On Discrete, Test Targets;",
        "SetpointManager:MixedAir, Reference Only, Temperature, Mixed Air Test Node, Fan Inlet, Fan Outlet, Other Target;",
    ]
    for text in objects:
        raw = o.IdfObject.load(text)
        assert raw.is_initialized()
        assert workspace.addObject(raw.get()).is_initialized()
    managers = node_temperature_managers(workspace, o, target)
    assert len(managers) == 1
    assert managers[0]["type"] == "SetpointManager:Scheduled"
    assert managers[0]["fields"]["Setpoint Node or NodeList Name"] == "Test Targets"


def test_load_controlled_unitary_without_supply_setpoint_warns(
    sdk, model_file, tmp_path
):
    o = sdk[0]
    model = o.model.Model.load(str(model_file)).get()
    loop = o.model.AirLoopHVAC(model)
    loop.setName("Existing Air Loop")
    controller = o.model.ControllerOutdoorAir(model)
    oa = o.model.AirLoopHVACOutdoorAirSystem(model, controller)
    assert oa.addToNode(loop.supplyInletNode())
    zone = model.getThermalZoneByName("Zone 1").get()
    assert loop.addBranchForZone(zone)
    unitary = o.model.AirLoopHVACUnitarySystem(model)
    assert unitary.setControlType("Load")
    assert unitary.setControllingZoneorThermostatLocation(zone)
    assert unitary.setSupplyFan(o.model.FanConstantVolume(model))
    assert unitary.setHeatingCoil(o.model.CoilHeatingElectric(model))
    assert unitary.setCoolingCoil(o.model.CoilCoolingDXSingleSpeed(model))
    assert unitary.addToNode(loop.supplyOutletNode())
    assert not loop.supplyOutletNode().setpointManagers()
    assert model.save(str(model_file), True)
    report = preflight(model_file, config(tmp_path))
    assert report["ready"] and report["plan"]["simulation_ready"] is False
    assert not report["plan"]["retained_context"]["mixed_air_control"][
        "temperature_managers"
    ]
    assert any(
        "OS_AirLoopHVAC_UnitarySystem" == x["type"]
        for x in report["plan"]["retained_context"]["cooling_components"]
    )
    assert apply(report, tmp_path)["simulation_ready"] is False
