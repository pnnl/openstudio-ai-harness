"""Real fan-class changes preserve controls, nodes and unrelated equipment."""

import json
from pathlib import Path
import shutil
import sqlite3
import subprocess

import pytest
from test_vav_preflight import sdk
from test_water_coil_operations import fixture
from test_supply_fan_performance import native_cli
from common import fan_class_replacement as fans, model_transaction as tx
from common.fan_edit import fan_object, ports


def replacement_fixture(native, tmp_path, source_kind="CAV"):
    source, _, _ = fixture(native, tmp_path, "Heating", "edit", source_kind)
    model = native.model.Model.load(str(source)).get()
    old = (
        model.getFanConstantVolumes()
        if source_kind == "CAV"
        else model.getFanVariableVolumes()
    )[0]
    old.additionalProperties().setFeature("review_note", "retain")
    old.setMotorInAirstreamFraction(0.8)
    old.setMaximumFlowRate(3.0)
    model.save(str(source), True)
    cfg = dict(
        output_model_path=str(tmp_path / "fan.osm"),
        air_loop={"handle": str(old.airLoopHVAC().get().handle())},
        target_class="VariableVolume" if source_kind == "CAV" else "ConstantVolume",
        fan=dict(
            total_efficiency=0.7,
            motor_efficiency=0.9,
            pressure_rise=3,
            pressure_units="inH2O",
        ),
        sizing="Autosize",
        terminal_policy="Preserve",
        system_sizing_policy="Preserve",
        reference_policy="Reject",
    )
    if source_kind == "CAV":
        cfg["variable_volume"] = dict(
            minimum_power_flow_fraction=0.25, power_coefficients=[0, 0, 0, 1, 0]
        )
    return source, cfg, old


def prepare(source, config):
    return tx.preflight(source, config, "replace_supply_fan", fans.plan)


def apply(report, tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(report, sort_keys=True))
    return tx.apply(
        path, "replace_supply_fan", fans.plan, fans.replace, fans.validate_model
    )


@pytest.mark.parametrize("kind", ["VAV", "CAV"])
def test_saved_class_change_keeps_nodes_controls_metadata_and_terminals(
    sdk, tmp_path, kind
):
    native = sdk[0]
    source, cfg, old = replacement_fixture(native, tmp_path, kind)
    baseline = native.model.Model.load(str(source)).get()
    old = fan_object(baseline, native, fans.ref(old))
    original = source.read_bytes()
    report = prepare(source, cfg)
    assert report["ready"], report
    assert report == prepare(source, json.loads(json.dumps(cfg, sort_keys=True)))
    plan = report["plan"]
    assert (
        plan["impact"]["terminal_count"] == plan["impact"]["affected_zone_count"] == 5
    )
    assert plan["before_controls"] == plan["after_controls"]
    assert plan["impact"]["airflow_behavior"]["enforces_constant_airflow"] is False
    if cfg["target_class"] == "ConstantVolume":
        assert "proportional power" in plan["impact"]["airflow_behavior"]["description"]
    assert any(x[0] == "SetpointManager:MixedAir" for x in plan["before_controls"])
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and result["translation"]["ok"]
    saved = (
        native.osversion.VersionTranslator()
        .loadModel(result["output_model_path"])
        .get()
    )
    replacement = fan_object(saved, native, result["changes"]["replacement_fan"])
    assert str(replacement.handle()) != str(old.handle())
    assert not saved.getModelObject(old.handle()).is_initialized()
    assert ports(replacement) == ports(old)
    assert replacement.nameString() == old.nameString()
    assert (
        replacement.availabilitySchedule().handle()
        == old.availabilitySchedule().handle()
    )
    assert (
        replacement.additionalProperties().handle()
        == old.additionalProperties().handle()
    )
    assert (
        replacement.additionalProperties().getFeatureAsString("review_note").get()
        == "retain"
    )
    assert replacement.motorInAirstreamFraction() == 0.8
    assert replacement.endUseSubcategory() == old.endUseSubcategory()
    assert replacement.fanEfficiency() == 0.7
    assert replacement.motorEfficiency() == 0.9
    assert replacement.pressureRise() == pytest.approx(747.26673)
    assert replacement.isMaximumFlowRateAutosized()
    if kind == "CAV":
        assert replacement.fanPowerMinimumFlowRateInputMethod() == "Fraction"
        assert replacement.fanPowerMinimumFlowFraction() == 0.25
        assert [
            getattr(replacement, "fanPowerCoefficient" + str(i))().get()
            for i in range(1, 6)
        ] == [0, 0, 0, 1, 0]
    assert source.read_bytes() == original
    with pytest.raises(ValueError):
        apply(report, tmp_path)


@pytest.mark.parametrize(
    "field",
    [
        "air_loop",
        "target_class",
        "fan",
        "sizing",
        "terminal_policy",
        "system_sizing_policy",
        "reference_policy",
        "fan.total_efficiency",
        "fan.motor_efficiency",
        "fan.pressure_rise",
        "fan.pressure_units",
        "variable_volume.minimum_power_flow_fraction",
        "variable_volume.power_coefficients",
    ],
)
def test_missing_choices_return_unready_without_defaults(sdk, tmp_path, field):
    source, cfg, _ = replacement_fixture(sdk[0], tmp_path)
    target = cfg
    parts = field.split(".")
    if len(parts) > 1:
        target = cfg[parts[0]]
    del target[parts[-1]]
    report = prepare(source, cfg)
    assert not report["ready"] and field in report["plan"]["missing_inputs"]
    with pytest.raises(ValueError, match="ready"):
        apply(report, tmp_path)
    assert not Path(cfg["output_model_path"]).exists()


@pytest.mark.parametrize(
    "bad",
    [
        "same_class",
        "unknown",
        "embedded",
        "multiple",
        "reference",
        "cost",
        "named_reference",
        "metadata_reference",
        "efficiency",
        "negative_curve",
        "overshoot_curve",
        "unnormalized",
        "curve_length",
        "curve_for_constant",
        "missing_fan",
    ],
)
def test_unsupported_or_inconsistent_choices_are_blocked(sdk, tmp_path, bad):
    native = sdk[0]
    source, cfg, old = replacement_fixture(native, tmp_path)
    model = native.model.Model.load(str(source)).get()
    fan = model.getFanConstantVolumes()[0]
    loop = fan.airLoopHVAC().get()
    if bad == "same_class":
        cfg["target_class"] = "ConstantVolume"
        cfg.pop("variable_volume")
    elif bad == "curve_for_constant":
        cfg["target_class"] = "ConstantVolume"
    elif bad == "unknown":
        cfg["air_loop"] = {"name": "Unknown"}
    elif bad == "embedded":
        fan.removeFromLoop()
        wrapper = native.model.AirLoopHVACUnitarySystem(model)
        wrapper.setSupplyFan(fan)
        wrapper.addToNode(loop.supplyOutletNode())
    elif bad == "multiple":
        native.model.FanConstantVolume(model).addToNode(loop.supplyInletNode())
    elif bad == "missing_fan":
        fan.remove()
    elif bad == "reference":
        native.model.EnergyManagementSystemActuator(
            fan, "Fan", "Fan Air Mass Flow Rate"
        )
    elif bad == "cost":
        native.model.LifeCycleCost.createLifeCycleCost(
            "Cost", fan, 10, "CostPerEach", "Construction", 20
        )
    elif bad == "named_reference":
        variable = native.model.OutputVariable("Fan Runtime Fraction", model)
        variable.setKeyValue(fan.nameString().swapcase())
    elif bad == "metadata_reference":
        fan.additionalProperties().setFeature("owner_handle", str(fan.handle()))
    elif bad == "efficiency":
        cfg["fan"].update(total_efficiency=0.95, motor_efficiency=0.9)
    else:
        cfg["variable_volume"]["power_coefficients"] = dict(
            negative_curve=[-0.2, 1.2, 0, 0, 0],
            overshoot_curve=[0, 5, -4, 0, 0],
            unnormalized=[0, 0, 0, 0.5, 0],
            curve_length=[0, 0, 0, 1, 0, 0],
        )[bad]
    model.save(str(source), True)
    report = prepare(source, cfg)
    assert not report["ready"] and report["plan"]["errors"], report
    assert not Path(cfg["output_model_path"]).exists()


@pytest.mark.parametrize("kind", ["VAV", "CAV"])
@pytest.mark.parametrize(
    "variable_name",
    [
        "Fan Electricity Rate",
        "Fan Electricity Energy",
        "Fan Rise in Air Temperature",
        "Fan Heat Gain to Air",
        "Fan Air Mass Flow Rate",
    ],
)
def test_shared_name_keyed_output_variables_are_retained(
    sdk, tmp_path, kind, variable_name
):
    native = sdk[0]
    source, cfg, _ = replacement_fixture(native, tmp_path, kind)
    model = native.model.Model.load(str(source)).get()
    old = (
        model.getFanConstantVolumes()
        if kind == "CAV"
        else model.getFanVariableVolumes()
    )[0]
    variable = native.model.OutputVariable(variable_name, model)
    variable.setKeyValue(old.nameString().swapcase())
    before = fans.raw_fields(variable)
    model.save(str(source), True)
    report = prepare(source, cfg)
    assert report["ready"], report
    assert report["plan"]["impact"]["retained_output_reference_count"] == 1
    assert (
        report["plan"]["impact"]["retained_output_references"][0]["keys"][0]["variable"]
        == variable_name
    )
    result = apply(report, tmp_path)
    saved = native.model.Model.load(result["output_model_path"]).get()
    assert fans.raw_fields(saved.getOutputVariable(variable.handle()).get()) == before


@pytest.mark.parametrize("kind", ["VAV", "CAV"])
@pytest.mark.parametrize("decrement", [False, True])
def test_custom_meter_keys_and_output_requests_are_retained(
    sdk, tmp_path, kind, decrement
):
    native = sdk[0]
    source, cfg, _ = replacement_fixture(native, tmp_path, kind)
    model = native.model.Model.load(str(source)).get()
    old = (
        model.getFanConstantVolumes()
        if kind == "CAV"
        else model.getFanVariableVolumes()
    )[0]
    meter = (
        native.model.MeterCustomDecrement(model, "Electricity:Facility")
        if decrement
        else native.model.MeterCustom(model)
    )
    meter.setFuelType("Electricity")
    assert meter.addKeyVarGroup(old.nameString().swapcase(), "Fan Electricity Energy")
    assert meter.addKeyVarGroup(old.nameString(), "Fan Electricity Energy")
    request = native.model.OutputMeter(model)
    request.setName(meter.nameString())
    before = {str(x.handle()): fans.raw_fields(x) for x in (meter, request)}
    model.save(str(source), True)
    report = prepare(source, cfg)
    assert report["ready"], report
    assert report["plan"]["impact"]["retained_output_reference_count"] == 2
    assert any(
        x["object"]["type"] == "OS_Output_Meter"
        for x in report["plan"]["retained_output_references"]
    )
    result = apply(report, tmp_path)
    saved = native.model.Model.load(result["output_model_path"]).get()
    for handle, fields in before.items():
        assert (
            fans.raw_fields(saved.getModelObject(native.toUUID(handle)).get()) == fields
        )


def test_mixed_meter_does_not_exempt_unsupported_or_uuid_keys(sdk, tmp_path):
    source, cfg, _ = replacement_fixture(sdk[0], tmp_path)
    model = sdk[0].model.Model.load(str(source)).get()
    fan = model.getFanConstantVolumes()[0]
    meter = sdk[0].model.MeterCustom(model)
    meter.addKeyVarGroup(fan.nameString(), "Fan Electricity Energy")
    meter.addKeyVarGroup(fan.nameString(), "Fan Runtime Fraction")
    assert not fans.plan(model, sdk[0], cfg)["ready"]
    meter.removeAllKeyVarGroups()
    meter.addKeyVarGroup(str(fan.handle()), "Fan Electricity Energy")
    assert not fans.plan(model, sdk[0], cfg)["ready"]


@pytest.mark.parametrize("kind", ["VAV", "CAV"])
def test_retained_reporting_label_warns_and_explicit_choice_is_applied(
    sdk, tmp_path, kind
):
    source, cfg, _ = replacement_fixture(sdk[0], tmp_path, kind)
    report = prepare(source, cfg)
    assert any("names the old fan/system type" in x for x in report["warnings"])
    assert report["plan"]["impact"]["end_use_subcategory_policy"] == "Preserve"
    cfg["end_use_subcategory"] = "Reviewed Supply Fans"
    report = prepare(source, cfg)
    assert not any("names the old fan/system type" in x for x in report["warnings"])
    assert any("subcategory meter names" in x for x in report["warnings"])
    assert report["plan"]["impact"]["end_use_subcategory_policy"] == "Explicit"
    result = apply(report, tmp_path)
    saved = sdk[0].model.Model.load(result["output_model_path"]).get()
    replacement = fan_object(saved, sdk[0], result["changes"]["replacement_fan"])
    assert replacement.endUseSubcategory() == "Reviewed Supply Fans"


@pytest.mark.parametrize("bad", ["", "  ", True, None])
def test_invalid_reporting_label_is_rejected(sdk, tmp_path, bad):
    source, cfg, _ = replacement_fixture(sdk[0], tmp_path)
    cfg["end_use_subcategory"] = bad
    with pytest.raises(ValueError, match="Invalid"):
        prepare(source, cfg)


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), -2, 0])
def test_invalid_scalar_schema(sdk, tmp_path, bad):
    source, cfg, _ = replacement_fixture(sdk[0], tmp_path)
    cfg["fan"]["total_efficiency"] = bad
    with pytest.raises(ValueError, match="Invalid"):
        prepare(source, cfg)


def test_curve_extrema_between_sample_points_are_checked():
    # Extremely narrow negative minimum at 0.5005: endpoint/grid checks miss it.
    c = [0.25050015, -1.001, 1, 0, 0]
    c = [x / sum(c) for x in c]
    assert all(fans.polynomial(c, x) >= 0 for x in (0, 0.5, 0.501, 1))
    assert fans.curve_errors(dict(power_coefficients=c))
    assert fans.roots_in_unit_interval([0.25, -1, 1]) == pytest.approx([0.5])
    assert not fans.curve_errors(dict(power_coefficients=[0, 0, 0, 1, 0]))


@pytest.mark.parametrize(
    "mutation",
    [
        "performance",
        "curve",
        "flow",
        "metadata",
        "terminal",
        "sizing",
        "plant",
        "schedule",
        "extra_fan",
        "controls",
        "reported_mapping",
        "end_use",
    ],
)
def test_saved_validator_rejects_unreviewed_changes(
    sdk, tmp_path, monkeypatch, mutation
):
    source, cfg, _ = replacement_fixture(sdk[0], tmp_path)
    report = prepare(source, cfg)
    original = fans.replace

    def changed(model, native, planned):
        result = original(model, native, planned)
        if "companions" not in planned:
            return result
        fan = fan_object(model, native, result["replacement_fan"])
        loop = fan.airLoopHVAC().get()
        if mutation == "performance":
            fan.setFanEfficiency(0.5)
        elif mutation == "curve":
            fan.setFanPowerCoefficient3(0.3)
        elif mutation == "flow":
            fan.setMaximumFlowRate(3)
        elif mutation == "metadata":
            fan.additionalProperties().setFeature("review_note", "corrupt")
        elif mutation == "terminal":
            model.getAirTerminalSingleDuctVAVReheats()[
                0
            ].setConstantMinimumAirFlowFraction(0.8)
        elif mutation == "sizing":
            loop.sizingSystem().setCentralCoolingDesignSupplyAirTemperature(18)
        elif mutation == "plant":
            model.getPlantLoops()[0].setName("Changed")
        elif mutation == "schedule":
            fan.setAvailabilitySchedule(model.alwaysOffDiscreteSchedule())
        elif mutation == "extra_fan":
            native.model.FanConstantVolume(model)
        elif mutation == "controls":
            manager = (
                loop.supplyOutletNode()
                .setpointManagers()[0]
                .to_SetpointManagerScheduled()
                .get()
            )
            schedule = (
                manager.schedule().to_ScheduleRuleset().get().defaultDaySchedule()
            )
            schedule.clearValues()
            schedule.addValue(native.Time(0, 24, 0, 0), 35)
        elif mutation == "end_use":
            fan.setEndUseSubcategory("Unreviewed Label")
        else:
            result["removed_fan"]["name"] = "Incorrect"
        return result

    monkeypatch.setattr(fans, "replace", changed)
    with pytest.raises(ValueError):
        apply(report, tmp_path)
    assert not Path(cfg["output_model_path"]).exists()
    assert not Path(cfg["output_model_path"]).with_suffix("").exists()


def test_stale_and_tampered_plan_rejected(sdk, tmp_path):
    source, cfg, _ = replacement_fixture(sdk[0], tmp_path)
    report = prepare(source, cfg)
    report["plan"]["after_values"]["pressure_rise_pa"] = 999
    with pytest.raises(ValueError, match="fresh preflight"):
        apply(report, tmp_path)
    report = prepare(source, cfg)
    source.write_bytes(source.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="hash"):
        apply(report, tmp_path)


@pytest.mark.parametrize("kind", ["VAV", "CAV"])
@pytest.mark.parametrize("position", ["inlet", "interior"])
def test_replacement_retains_other_supply_positions_and_outlet_manager(
    sdk, tmp_path, kind, position
):
    source, cfg, _ = replacement_fixture(sdk[0], tmp_path, kind)
    native = sdk[0]
    model = native.model.Model.load(str(source)).get()
    old = (
        model.getFanConstantVolumes()
        if kind == "CAV"
        else model.getFanVariableVolumes()
    )[0]
    loop = old.airLoopHVAC().get()
    node = (
        loop.supplyInletNode()
        if position == "inlet"
        else model.getCoilCoolingWaters()[0].airInletModelObject().get().to_Node().get()
    )
    assert old.removeFromLoop() and old.addToNode(node)
    boundary = old.outletModelObject().get().to_Node().get()
    manager = native.model.SetpointManagerScheduled(
        model,
        loop.supplyOutletNode()
        .setpointManagers()[0]
        .to_SetpointManagerScheduled()
        .get()
        .schedule(),
    )
    assert manager.addToNode(boundary)
    manager_handle, boundary_handle = manager.handle(), boundary.handle()
    model.save(str(source), True)
    report = prepare(source, cfg)
    assert report["ready"], report
    result = apply(report, tmp_path)
    saved = native.model.Model.load(result["output_model_path"]).get()
    assert (
        saved.getSetpointManagerScheduled(manager_handle)
        .get()
        .setpointNode()
        .get()
        .handle()
        == boundary_handle
    )


def test_exact_sdk_guard_runs_before_model_access(sdk, tmp_path, monkeypatch):
    monkeypatch.setattr(sdk[0], "openStudioVersion", lambda: "3.12.0")
    with pytest.raises(Exception, match="3.11.0"):
        prepare(
            tmp_path / "missing.osm", {"output_model_path": str(tmp_path / "fan.osm")}
        )


@pytest.mark.parametrize("kind", ["VAV", "CAV"])
def test_native_fan_class_change_design_days(sdk, tmp_path, kind):
    source, cfg, _ = replacement_fixture(sdk[0], tmp_path, kind)
    if cfg["target_class"] == "VariableVolume":
        cfg["variable_volume"]["minimum_power_flow_fraction"] = 0.5
    cfg["end_use_subcategory"] = "Reviewed Replacement Fans"
    baseline = sdk[0].model.Model.load(str(source)).get()
    old = (
        baseline.getFanConstantVolumes()
        if kind == "CAV"
        else baseline.getFanVariableVolumes()
    )[0]
    for name in ("Fan Electricity Rate", "Fan Electricity Energy"):
        request = sdk[0].model.OutputVariable(name, baseline)
        request.setKeyValue(old.nameString())
        request.setReportingFrequency("Detailed")
    meter = sdk[0].model.MeterCustom(baseline)
    meter.setName("Retained Fan Electricity")
    meter.setFuelType("Electricity")
    assert meter.addKeyVarGroup(old.nameString(), "Fan Electricity Energy")
    meter_request = sdk[0].model.OutputMeter(baseline)
    meter_request.setName(meter.nameString())
    meter_request.setReportingFrequency("Timestep")
    baseline.save(str(source), True)
    result = apply(prepare(source, cfg), tmp_path)
    folder = Path(result["companion_directory"])
    # Instrument a separate copy; validated output and input remain unchanged.
    model = sdk[0].model.Model.load(result["output_model_path"]).get()
    fan = fan_object(model, sdk[0], result["changes"]["replacement_fan"])
    inlet_name = fan.inletModelObject().get().nameString()
    for name, key in [
        ("System Node Standard Density Volume Flow Rate", inlet_name),
    ]:
        variable = sdk[0].model.OutputVariable(name, model)
        variable.setKeyValue(key)
        variable.setReportingFrequency("Detailed")
    instrumented = tmp_path / "instrumented.osm"
    model.save(str(instrumented), True)
    workflow = json.loads((folder / "workflow.osw").read_text())
    workflow["seed_file"] = str(instrumented)
    (folder / "power.osw").write_text(json.dumps(workflow))
    run = subprocess.run(
        [str(native_cli()), "run", "-w", str(folder / "power.osw")],
        cwd=folder,
        capture_output=True,
        text=True,
        timeout=120,
    )
    (tmp_path / "cli.log").write_text(run.stdout + run.stderr)
    assert run.returncode == 0, run.stdout + run.stderr
    err = (folder / "run/eplusout.err").read_text()
    assert (
        "EnergyPlus Completed Successfully" in err
        and "** Severe" not in err
        and "**  Fatal" not in err
    ), err
    with sqlite3.connect(folder / "run/eplusout.sql") as sql:
        rows = sql.execute(
            "SELECT CompType,CompName,Description,Value FROM ComponentSizes WHERE CompType=?",
            ("Fan:" + cfg["target_class"],),
        ).fetchall()
        series = {
            (key, name): dict(
                sql.execute(
                    "SELECT d.TimeIndex,d.Value FROM ReportData d JOIN Time t ON t.TimeIndex=d.TimeIndex WHERE d.ReportDataDictionaryIndex=? AND t.WarmupFlag=0",
                    (index,),
                )
            )
            for index, key, name in sql.execute(
                "SELECT ReportDataDictionaryIndex,KeyValue,Name FROM ReportDataDictionary WHERE Name IN ('Fan Electricity Rate','System Node Standard Density Volume Flow Rate')"
            ).fetchall()
        }

        def energy_total(name, key=None):
            return sql.execute(
                "SELECT SUM(d.Value) FROM ReportData d JOIN Time t ON t.TimeIndex=d.TimeIndex JOIN ReportDataDictionary r ON r.ReportDataDictionaryIndex=d.ReportDataDictionaryIndex WHERE t.WarmupFlag=0 AND upper(r.Name)=? AND (? IS NULL OR r.KeyValue=?)",
                (name.upper(), key, key),
            ).fetchone()[0]

        meter_energy = energy_total("Retained Fan Electricity")
        fan_energy = energy_total("Fan Electricity Energy", fan.nameString().upper())
    assert meter_energy is not None and meter_energy > 0
    assert meter_energy == pytest.approx(fan_energy, rel=1e-8)
    flows = [x[3] for x in rows if x[2] == "Design Size Maximum Flow Rate"]
    assert flows and all(x > 0 for x in flows), rows
    (tmp_path / "sizing-evidence.json").write_text(json.dumps(rows, indent=2) + "\n")
    volumes = series[
        (inlet_name.upper(), "System Node Standard Density Volume Flow Rate")
    ]
    power = series[(fan.nameString().upper(), "Fan Electricity Rate")]
    pressure = fan.pressureRise()
    full_power = flows[0] * pressure / fan.fanEfficiency()
    errors, fractions = [], []
    for time, actual in power.items():
        x = volumes[time] / flows[0]
        if x < 0.1:
            continue
        fractions.append(x)
        # Independent reference formulas from EnergyPlus 25.2.0 Fans.cc.
        expected = volumes[time] * pressure / fan.fanEfficiency()
        if cfg["target_class"] == "VariableVolume":
            expected = full_power * max(0.5, min(x, 1.0)) ** 3
        errors.append(abs(actual - expected) / full_power)
    assert errors and max(errors) < 0.001, errors
    assert any(x < 0.95 for x in fractions), "Require actual part-load operation"
    floor_timesteps = sum(x < 0.5 for x in fractions)
    if cfg["target_class"] == "VariableVolume":
        assert floor_timesteps, "Require operation below the chosen power-flow floor"
    (tmp_path / "power-evidence.json").write_text(
        json.dumps(
            dict(
                target_class=cfg["target_class"],
                maximum_flow_m3_s=flows[0],
                active_timesteps=len(errors),
                part_load_timesteps=sum(x < 0.95 for x in fractions),
                minimum_flow_fraction=min(fractions),
                power_floor_timesteps=(
                    floor_timesteps if cfg["target_class"] == "VariableVolume" else 0
                ),
                retained_meter_energy_j=meter_energy,
                retained_variable_energy_j=fan_energy,
                end_use_subcategory=fan.endUseSubcategory(),
                maximum_normalized_power_error=max(errors),
            ),
            indent=2,
        )
        + "\n"
    )


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_relocated_native_fan_bundle(sdk, tmp_path, host):
    from adapters.claude_code_adapter import ClaudeCodeAdapter
    from adapters.codex_adapter import CodexAdapter
    from adapters.contracts import HostAdapterConfig

    source, cfg, _ = replacement_fixture(sdk[0], tmp_path)
    root = tmp_path / "export"
    cls = ClaudeCodeAdapter if host == "claude" else CodexAdapter
    cls(
        HostAdapterConfig(
            host_name=host, workspace_root=Path.cwd(), runtime_mode="marketplace"
        )
    ).export_plugin(root, dry_run=False)
    bundle = next(root.rglob("openstudio-supply-fan-replacer/SKILL.md")).parent
    relocated = tmp_path / "relocated"
    shutil.copytree(bundle, relocated)
    shutil.rmtree(root)
    config = tmp_path / "config.json"
    config.write_text(json.dumps(cfg))
    plan_path, applied = tmp_path / "plan.json", tmp_path / "apply.json"
    for args in (
        ["--input", str(source), "--config", str(config), "--report", str(plan_path)],
        ["--plan", str(plan_path), "--report", str(applied)],
    ):
        run = subprocess.run(
            [
                str(native_cli()),
                "execute_python_script",
                str(relocated / "scripts/replace_supply_fan.py"),
                *args,
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(applied.read_text())["validation"]["ok"]
