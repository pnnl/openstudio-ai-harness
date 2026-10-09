"""Real pump-class replacement must retain plant topology and shared controls."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import pytest
from test_vav_preflight import sdk, SCRIPTS
from test_pump_performance import fixture, native_run
from test_supply_fan_performance import native_cli

sys.path.insert(0, str(SCRIPTS))
from common import pump_class_replacement as pumps, model_transaction as tx
from common.water_coil import raw_fields

OPERATION = "replace_pump_class"


def config(tmp_path, target="VariableSpeed"):
    result = dict(
        output_model_path=str(tmp_path / "replaced.osm"),
        plant_loop={"name": "HW"},
        pump={"name": "Selected Pump"},
        target_class=target,
        flow_policy="Preserve",
        power_policy="Preserve",
        plant_policy="Preserve",
        reference_policy="Reject",
    )
    if target == "VariableSpeed":
        result["variable_speed"] = dict(
            minimum_flow_m3_s=0, power_coefficients=[0, 0.0205, 0.4101, 0.5753]
        )
    return result


def preflight(source, cfg):
    return tx.preflight(source, cfg, OPERATION, pumps.plan)


def apply(report, tmp_path, creator=None):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(report))
    return tx.apply(
        path, OPERATION, pumps.plan, creator or pumps.replace, pumps.validate_model
    )


@pytest.mark.parametrize("target", ["ConstantSpeed", "VariableSpeed"])
@pytest.mark.parametrize("side", ["supply", "demand"])
@pytest.mark.parametrize("fixed", [False, True])
def test_saved_boundaries_identity_metadata_controls_and_power(
    sdk, tmp_path, target, side, fixed
):
    o = sdk[0]
    source, model, old = fixture(
        o,
        tmp_path,
        "VariableSpeed" if target == "ConstantSpeed" else "ConstantSpeed",
        side,
    )
    if fixed:
        old.setRatedFlowRate(0.002)
        old.setRatedPowerConsumption(1000)
    old.setPumpControlType("Continuous")
    old.setMotorEfficiency(0.92)
    old.setFractionofMotorInefficienciestoFluidStream(0.25)
    old.setDesignPowerSizingMethod("PowerPerFlow")
    old.setDesignElectricPowerPerUnitFlowRate(250000)
    flow_schedule = o.model.ScheduleConstant(model)
    flow_schedule.setValue(0.8)
    old.setPumpFlowRateSchedule(flow_schedule)
    zone = o.model.ThermalZone(model)
    old.setZone(zone)
    # Include a zone split and nontrivial reporting label to detect class defaults.
    old.setSkinLossRadiativeFraction(0.35)
    old.setEndUseSubcategory("Existing Pumps")
    metadata = str(old.additionalProperties().handle())
    source_bytes = None
    model.save(str(source), True)
    source_bytes = source.read_bytes()
    cfg = config(tmp_path, target)
    report = preflight(source, cfg)
    assert report["ready"], report
    assert report == preflight(source, cfg)
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and result["translation"]["ok"], result
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    new = pumps.pump_object(saved, o, result["changes"]["replacement_pump"])
    assert new.handle() != old.handle()
    assert not saved.getModelObject(old.handle()).is_initialized()
    assert str(new.additionalProperties().handle()) == metadata
    assert (
        new.additionalProperties().getFeatureAsString("review_note").get() == "retain"
    )
    assert pumps.ports(new) == report["plan"]["resolved_objects"]["ports"]
    assert pumps.matches(pumps.settings(new), report["plan"]["after_values"])
    assert pumps.controls(saved, o) == report["plan"]["before_controls"]
    assert new.pumpFlowRateSchedule().get().handle() == flow_schedule.handle()
    assert new.zone().get().handle() == zone.handle()
    assert source.read_bytes() == source_bytes
    assert len(report["plan"]["removed_objects"]) == 3  # pump and its two connections
    assert report["plan"]["added_counts"] == {
        "OS_Pump_" + target: 1,
        "OS_Connection": 2,
    }
    if fixed:
        assert (
            new.ratedFlowRate().get() == 0.002
            and new.ratedPowerConsumption().get() == 1000
        )
    else:
        assert new.isRatedFlowRateAutosized() and new.isRatedPowerConsumptionAutosized()


@pytest.mark.parametrize("target", ["ConstantSpeed", "VariableSpeed"])
def test_blank_zone_radiation_effective_split_is_preserved(sdk, tmp_path, target):
    o = sdk[0]
    source, model, old = fixture(
        o, tmp_path, "VariableSpeed" if target == "ConstantSpeed" else "ConstantSpeed"
    )
    old.setZone(o.model.ThermalZone(model))
    model.save(str(source), True)
    expected = 0.5 if target == "ConstantSpeed" else 0.0
    report = preflight(source, config(tmp_path, target))
    assert report["ready"], report
    assert report["plan"]["after_values"]["skin_loss_radiative_fraction"] == expected
    assert apply(report, tmp_path)["validation"]["ok"]


@pytest.mark.parametrize(
    "flow_policy,power_policy",
    [("Autosize", "Preserve"), ("Preserve", "Autosize"), ("Autosize", "Autosize")],
)
def test_explicit_sizing_policies_and_deferred_motor_check(
    sdk, tmp_path, flow_policy, power_policy
):
    o = sdk[0]
    source, model, pump = fixture(o, tmp_path, "ConstantSpeed")
    pump.setRatedFlowRate(0.001)
    pump.setRatedPowerConsumption(1000)
    model.save(str(source), True)
    cfg = dict(config(tmp_path), flow_policy=flow_policy, power_policy=power_policy)
    report = preflight(source, cfg)
    assert report["ready"], report
    assert (
        "feasibility cannot be checked before sizing" in str(report["warnings"])
    ) == (flow_policy == "Autosize" and power_policy == "Preserve")
    result = apply(report, tmp_path)
    assert result["validation"]["ok"]


@pytest.mark.parametrize(
    "key",
    [
        "plant_loop",
        "pump",
        "target_class",
        "flow_policy",
        "power_policy",
        "plant_policy",
        "reference_policy",
        "variable_speed",
    ],
)
def test_missing_choices_stay_unready(sdk, tmp_path, key):
    source, _, _ = fixture(sdk[0], tmp_path, "ConstantSpeed")
    cfg = config(tmp_path)
    del cfg[key]
    report = preflight(source, cfg)
    assert not report["ready"] and report["plan"]["missing_inputs"]
    assert not (tmp_path / "replaced.osm").exists()


@pytest.mark.parametrize(
    "bad",
    [
        "same_class",
        "constant_curve",
        "negative_curve",
        "zero_curve",
        "min_flow",
        "missing_pump",
        "headered",
    ],
)
def test_semantic_rejections(sdk, tmp_path, bad):
    o = sdk[0]
    source, model, pump = fixture(o, tmp_path, "ConstantSpeed")
    cfg = config(tmp_path)
    if bad == "same_class":
        cfg["target_class"] = "ConstantSpeed"
        cfg.pop("variable_speed")
    elif bad == "constant_curve":
        cfg["target_class"] = "ConstantSpeed"
    elif bad == "negative_curve":
        cfg["variable_speed"]["power_coefficients"] = [0.2, -1, 1, 0]
    elif bad == "zero_curve":
        cfg["variable_speed"]["power_coefficients"] = [0, 0, 0, 0]
    elif bad == "min_flow":
        pump.setRatedFlowRate(0.001)
        cfg["variable_speed"]["minimum_flow_m3_s"] = 0.001
        model.save(str(source), True)
    elif bad == "missing_pump":
        cfg["pump"] = {"name": "Missing"}
    else:
        pump.remove()
        bank = o.model.HeaderedPumpsConstantSpeed(model)
        bank.setName("Bank")
        bank.addToNode(model.getPlantLoops()[0].supplyInletNode())
        model.save(str(source), True)
        cfg["pump"] = {"name": "Bank"}
    report = preflight(source, cfg)
    assert not report["ready"] and report["plan"]["errors"], report


@pytest.mark.parametrize(
    "key,value",
    [
        ("power_coefficients", [1, 2, 3]),
        ("power_coefficients", [1, 2, 3, 4, 5]),
        ("power_coefficients", [float("nan"), 0, 0, 1]),
        ("minimum_flow_m3_s", -1),
    ],
)
def test_schema_rejects_invalid_curve(sdk, tmp_path, key, value):
    source, _, _ = fixture(sdk[0], tmp_path, "ConstantSpeed")
    cfg = config(tmp_path)
    cfg["variable_speed"][key] = value
    with pytest.raises(ValueError, match="Invalid pump replacement"):
        preflight(source, cfg)


@pytest.mark.parametrize(
    "reference", ["cost", "actuator", "name_sensor", "uuid_output", "unknown_output"]
)
def test_references_requiring_migration_block(sdk, tmp_path, reference):
    o = sdk[0]
    source, model, pump = fixture(o, tmp_path, "ConstantSpeed")
    if reference == "cost":
        o.model.LifeCycleCost.createLifeCycleCost(
            "Cost", pump, 100, "CostPerEach", "Maintenance", 1, 0
        )
    elif reference == "actuator":
        o.model.EnergyManagementSystemActuator(pump, "Pump", "Pump Mass Flow Rate")
    elif reference == "name_sensor":
        sensor = o.model.EnergyManagementSystemSensor(model, "Pump Electricity Rate")
        sensor.setKeyName(pump.nameString())
    else:
        var = o.model.OutputVariable(
            (
                "Pump Electricity Rate"
                if reference != "unknown_output"
                else "Unknown Pump Output"
            ),
            model,
        )
        var.setKeyValue(
            str(pump.handle()) if reference == "uuid_output" else pump.nameString()
        )
    model.save(str(source), True)
    report = preflight(source, config(tmp_path))
    assert not report["ready"] and any(
        "Reference policy Reject" in e for e in report["plan"]["errors"]
    ), report


@pytest.mark.parametrize("kind", ["ConstantSpeed", "VariableSpeed"])
@pytest.mark.parametrize("advanced", ["impeller", "rpm", "curve", "pressure_loop"])
def test_pressure_hardware_and_control_scope_is_explicit(sdk, tmp_path, kind, advanced):
    o = sdk[0]
    source, model, pump = fixture(o, tmp_path, kind)
    if advanced == "impeller":
        pump.setImpellerDiameter(0.2)
    elif advanced == "rpm":
        if kind == "ConstantSpeed":
            pump.setRotationalSpeed(1800)
        else:
            pump.setVFDControlType("ManualControl")
    elif advanced == "curve":
        pump.setPumpCurve(o.model.CurveQuadratic(model))
    else:
        loop = model.getPlantLoops()[0]
        raw = loop.iddObject()
        index = next(
            i
            for i in range(loop.numFields())
            if raw.getField(i).get().name() == "Pressure Simulation Type"
        )
        assert loop.setString(index, "PumpPowerCorrection")
    model.save(str(source), True)
    report = preflight(
        source,
        config(
            tmp_path, "VariableSpeed" if kind == "ConstantSpeed" else "ConstantSpeed"
        ),
    )
    assert not report["ready"] and "separate replacement contract" in str(
        report["plan"]["errors"]
    ), report


@pytest.mark.parametrize(
    "bad", ["settings", "extra_field", "plant", "other_pump", "nodes", "mapping"]
)
def test_independent_saved_checks_reject_apply_mutations(
    sdk, tmp_path, monkeypatch, bad
):
    source, _, _ = fixture(sdk[0], tmp_path, "ConstantSpeed")
    report = preflight(source, config(tmp_path))
    assert report["ready"], report
    real = pumps.replace

    def faulty(model, o, planned):
        result = real(model, o, planned)
        new = pumps.pump_object(model, o, result["replacement_pump"])
        if bad == "settings":
            new.setMotorEfficiency(0.8)
        elif bad == "extra_field":
            new.setImpellerDiameter(0.1)
        elif bad == "plant":
            model.getPlantLoops()[0].sizingPlant().setDesignLoopExitTemperature(60)
        elif bad == "other_pump":
            o.model.PumpConstantSpeed(model)
        elif bad == "nodes":
            new.removeFromLoop()
            new.addToNode(model.getPlantLoops()[0].demandInletNode())
        else:
            result["water_nodes"] = list(reversed(result["water_nodes"]))
        return result

    with pytest.raises(ValueError, match="validation"):
        apply(report, tmp_path, creator=faulty)
    assert not (tmp_path / "replaced.osm").exists()


@pytest.mark.parametrize("bad", ["source", "plan", "operation"])
def test_stale_or_modified_plans_do_not_publish(sdk, tmp_path, bad):
    source, _, _ = fixture(sdk[0], tmp_path, "ConstantSpeed")
    report = preflight(source, config(tmp_path))
    if bad == "source":
        source.write_bytes(source.read_bytes() + b"\n")
    elif bad == "plan":
        report["plan"]["after_values"]["motor_efficiency"] = 0.8
    else:
        report["operation"] = "edit_pump_performance"
    with pytest.raises(ValueError):
        apply(report, tmp_path)
    assert not (tmp_path / "replaced.osm").exists()


@pytest.mark.parametrize(
    "output",
    [
        "Pump Electricity Rate",
        "Pump Electricity Energy",
        "Pump Shaft Power",
        "Pump Fluid Heat Gain Rate",
        "Pump Fluid Heat Gain Energy",
        "Pump Outlet Temperature",
        "Pump Mass Flow Rate",
    ],
)
def test_compatible_name_keyed_outputs_retained(sdk, tmp_path, output):
    o = sdk[0]
    source, model, old = fixture(o, tmp_path, "ConstantSpeed")
    var = o.model.OutputVariable(output, model)
    var.setKeyValue(old.nameString().upper())
    model.save(str(source), True)
    raw = str(var.idfObject())
    handle = var.handle()
    report = preflight(source, config(tmp_path))
    assert report["ready"], report
    assert report["plan"]["impact"]["retained_output_reference_count"] == 1
    result = apply(report, tmp_path)
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    assert str(saved.getModelObject(handle).get().idfObject()) == raw


@pytest.mark.parametrize("decrement", [False, True])
def test_custom_pump_energy_meters_and_requests_retained(sdk, tmp_path, decrement):
    o = sdk[0]
    source, model, pump = fixture(o, tmp_path, "ConstantSpeed")
    meter = (
        o.model.MeterCustomDecrement(model, "Electricity:Facility")
        if decrement
        else o.model.MeterCustom(model)
    )
    meter.setFuelType("Electricity")
    assert meter.addKeyVarGroup(pump.nameString().swapcase(), "Pump Electricity Energy")
    request = o.model.OutputMeter(model)
    request.setName(meter.nameString())
    fields = {str(x.handle()): str(x.idfObject()) for x in (meter, request)}
    model.save(str(source), True)
    report = preflight(source, config(tmp_path))
    assert report["ready"], report
    assert report["plan"]["impact"]["retained_output_reference_count"] == 2
    result = apply(report, tmp_path)
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    for handle, raw in fields.items():
        assert str(saved.getModelObject(o.toUUID(handle)).get().idfObject()) == raw


def served_fixture(o, tmp_path, target, side="supply", system="VAV"):
    from vav_fixture import prepare_vav_fixture
    from common import cav_system
    from common.hvac_inventory import inventory as hvac_inventory
    from common.vav_plan import plan as vav_plan
    from common.vav_create import create as create_vav

    source, base, _, _ = prepare_vav_fixture(o, tmp_path, True)
    model = o.osversion.VersionTranslator().loadModel(str(source)).get()
    if system == "VAV":
        create_vav(model, o, vav_plan(base, hvac_inventory(model), None))
    else:
        base.update(
            defaults_profile="prototype_cav_v1",
            outdoor_air_schedule={"builtin": "AlwaysOnDiscrete"},
        )
        cav_system.create(model, o, cav_system.plan(model, o, base))
    loop = model.getPlantLoopByName("Fixture CHW").get()
    old = next(
        x.to_PumpVariableSpeed().get()
        for x in loop.supplyComponents()
        if x.to_PumpVariableSpeed().is_initialized()
    )
    if side == "demand":
        old.removeFromLoop()
        old.addToNode(loop.demandInletNode())
        primary = o.model.PumpConstantSpeed(model)
        primary.setName("Retained Primary")
        primary.setRatedPumpHead(o.convert(15, "ftH_{2}O", "Pa").get())
        primary.addToNode(loop.supplyInletNode())
        assert loop.setCommonPipeSimulation("CommonPipe")
    if target == "VariableSpeed":
        old.remove()
        old = o.model.PumpConstantSpeed(model)
        old.addToNode(
            loop.supplyInletNode() if side == "supply" else loop.demandInletNode()
        )
    else:
        for i, c in enumerate([0, 0, 0, 1], 1):
            getattr(old, f"setCoefficient{i}ofthePartLoadPerformanceCurve")(c)
    old.setName("Selected Pump")
    old.setRatedPumpHead(60000)
    old.setMotorEfficiency(0.9)
    old.setFractionofMotorInefficienciestoFluidStream(0)
    old.additionalProperties().setFeature("native_note", "retain")
    model.save(str(source), True)
    cfg = config(tmp_path, target)
    cfg["plant_loop"] = {"name": "Fixture CHW"}
    if target == "VariableSpeed":
        cfg["variable_speed"]["power_coefficients"] = [0, 0, 0, 1]
    return source, cfg


@pytest.mark.parametrize(
    "target,side,system",
    [
        ("VariableSpeed", "supply", "VAV"),
        ("ConstantSpeed", "supply", "VAV"),
        ("VariableSpeed", "demand", "VAV"),
        ("ConstantSpeed", "demand", "VAV"),
        ("VariableSpeed", "supply", "CAV"),
        ("ConstantSpeed", "supply", "CAV"),
    ],
)
def test_native_class_power_and_plant_preservation(sdk, tmp_path, target, side, system):
    o = sdk[0]
    source, cfg = served_fixture(o, tmp_path, target, side, system)
    report = preflight(source, cfg)
    assert report["ready"], report
    result = apply(report, tmp_path)
    before = native_run(o, source, tmp_path / "before", "Selected Pump")
    after = native_run(
        o, Path(result["output_model_path"]), tmp_path / "after", "Selected Pump"
    )
    evidence = dict(
        target_class=target,
        side=side,
        system=system,
        before=before,
        after=after,
        electricity_ratio=after["electricity_energy_j"]
        / before["electricity_energy_j"],
    )
    (tmp_path / "native_evidence.json").write_text(json.dumps(evidence, indent=2))
    assert after["sizes"]["Design Flow Rate"] == pytest.approx(
        before["sizes"]["Design Flow Rate"], rel=1e-6
    ), evidence
    assert after["sizes"]["Design Power Consumption"] == pytest.approx(
        before["sizes"]["Design Power Consumption"], rel=1e-6
    ), evidence
    variable = after if target == "VariableSpeed" else before
    constant = before if target == "VariableSpeed" else after
    assert constant["max_power_w"] == pytest.approx(
        constant["sizes"]["Design Power Consumption"]
    ), evidence
    assert (
        variable["electricity_energy_j"] < constant["electricity_energy_j"] * 0.99
    ), evidence
    # Read every operating timestep, using observed nominal mass flow from the
    # constant-speed fixture and sized power. The cubic is not inferred from annual energy.
    import sqlite3

    folder = (
        tmp_path
        / ("after" if target == "VariableSpeed" else "before")
        / "run/eplusout.sql"
    )
    with sqlite3.connect(folder) as sql:
        data = sql.execute(
            "SELECT r.TimeIndex,d.Name,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE d.KeyValue='SELECTED PUMP' AND d.Name IN ('Pump Electricity Rate','Pump Mass Flow Rate') AND t.WarmupFlag=0"
        ).fetchall()
    steps = {}
    for i, name, value in data:
        steps.setdefault(i, {})[name] = value
    rated = variable["sizes"]["Design Power Consumption"]
    nominal_mass = constant["max_mass_flow_kg_s"]
    qualifying = 0
    for row in steps.values():
        fraction = row["Pump Mass Flow Rate"] / nominal_mass
        if 0.05 < fraction < 0.95:
            qualifying += 1
            assert row["Pump Electricity Rate"] / rated == pytest.approx(
                fraction**3, rel=0.015, abs=1e-4
            ), row
    assert qualifying > 50, (qualifying, evidence)
    evidence["part_load_steps_checked"] = qualifying
    (tmp_path / "native_evidence.json").write_text(json.dumps(evidence, indent=2))


@pytest.mark.parametrize("target", ["ConstantSpeed", "VariableSpeed"])
@pytest.mark.parametrize(
    "position", ["supply_outlet", "demand_outlet", "supply_branch"]
)
def test_other_plant_positions_preserve_boundary_setpoints(
    sdk, tmp_path, target, position
):
    o = sdk[0]
    source, model, old = fixture(
        o, tmp_path, "VariableSpeed" if target == "ConstantSpeed" else "ConstantSpeed"
    )
    loop = model.getPlantLoops()[0]
    if position == "supply_outlet":
        node = loop.supplyOutletNode()
    elif position == "demand_outlet":
        node = loop.demandOutletNode()
    else:
        node = (
            model.getDistrictHeatingWaters()[0]
            .outletModelObject()
            .get()
            .to_Node()
            .get()
        )
    assert old.removeFromLoop()
    assert old.addToNode(node)
    boundary = old.outletModelObject().get().to_Node().get()
    schedule = o.model.ScheduleConstant(model)
    schedule.setValue(60)
    manager = o.model.SetpointManagerScheduled(model, schedule)
    manager.addToNode(boundary)
    model.save(str(source), True)
    report = preflight(source, config(tmp_path, target))
    assert report["ready"], report
    before = report["plan"]["before_controls"]
    expected = json.loads(json.dumps(before))
    if position == "supply_branch":
        schemes = [
            fields
            for kind, fields in expected
            if kind == "PlantEquipmentOperation:ComponentSetpoint"
        ]
        assert len(schemes) == 1
        assert schemes[0][1:3] == [
            "Pump:"
            + ("VariableSpeed" if target == "ConstantSpeed" else "ConstantSpeed"),
            "Selected Pump",
        ]
        schemes[0][1] = "Pump:" + target
    assert report["plan"]["after_controls"] == sorted(expected)
    result = apply(report, tmp_path)
    assert result["validation"]["ok"]
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    assert (
        saved.getSetpointManagerScheduled(manager.handle())
        .get()
        .setpointNode()
        .get()
        .handle()
        == boundary.handle()
    )


def test_positive_minimum_flow_against_autosized_flow_warns(sdk, tmp_path):
    source, _, _ = fixture(sdk[0], tmp_path, "ConstantSpeed")
    cfg = config(tmp_path)
    cfg["variable_speed"]["minimum_flow_m3_s"] = 0.0001
    report = preflight(source, cfg)
    assert report["ready"], report
    assert any("Minimum pump flow cannot be checked" in w for w in report["warnings"])
    assert apply(report, tmp_path)["validation"]["ok"]


def test_multiple_pumps_preserve_unselected_object(sdk, tmp_path):
    o = sdk[0]
    source, model, _ = fixture(o, tmp_path, "ConstantSpeed")
    other = o.model.PumpVariableSpeed(model)
    other.setName("Unselected Secondary")
    other.addToNode(model.getPlantLoops()[0].demandInletNode())
    model.getPlantLoops()[0].setCommonPipeSimulation("CommonPipe")
    raw = str(other.idfObject())
    model.save(str(source), True)
    report = preflight(source, config(tmp_path))
    assert report["ready"], report
    result = apply(report, tmp_path)
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    assert str(saved.getModelObject(other.handle()).get().idfObject()) == raw


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_relocated_pump_replacement_bundle(sdk, tmp_path, host):
    from adapters.claude_code_adapter import ClaudeCodeAdapter
    from adapters.codex_adapter import CodexAdapter
    from adapters.contracts import HostAdapterConfig

    source, _, _ = fixture(sdk[0], tmp_path, "ConstantSpeed")
    setup = HostAdapterConfig(
        host_name=host, workspace_root=Path.cwd(), runtime_mode="marketplace"
    )
    adapter = ClaudeCodeAdapter(setup) if host == "claude" else CodexAdapter(setup)
    exported = tmp_path / "export"
    adapter.export_plugin(exported, dry_run=False)
    bundle = next(exported.rglob("openstudio-pump-replacer/SKILL.md")).parent
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
        ["--input", str(source), "--report", str(tmp_path / "inventory.json")],
        ["--input", str(source), "--config", str(cfg), "--report", str(plan)],
        ["--plan", str(plan), "--report", str(tmp_path / "applied.json")],
    ):
        run = subprocess.run(
            [
                str(native_cli()),
                "execute_python_script",
                str(moved / "scripts/replace_pump.py"),
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


def remove_demand_bypass(o, model, loop):
    """Remove actual parallel pipe branches, retaining inlet/outlet pipes."""
    removed = []
    for start in list(loop.demandSplitter().outletModelObjects()):
        branch = loop.demandComponents(
            start.to_HVACComponent().get(), loop.demandMixer()
        )
        equipment = [
            x for x in branch if x.iddObjectType().valueName() == "OS_Pipe_Adiabatic"
        ]
        if equipment and all(
            x.iddObjectType().valueName()
            in ("OS_Node", "OS_Pipe_Adiabatic", "OS_Connector_Mixer")
            for x in branch
        ):
            pipe = equipment[0].to_PipeAdiabatic().get()
            removed.append(str(pipe.handle()))
            assert loop.removeDemandBranchWithComponent(pipe)
    assert removed
    return removed


@pytest.mark.parametrize("target", ["ConstantSpeed", "VariableSpeed"])
@pytest.mark.parametrize("side", ["supply", "demand"])
@pytest.mark.parametrize("bypass", [True, False])
def test_demand_bypass_impact_and_targeted_warning(sdk, tmp_path, target, side, bypass):
    o = sdk[0]
    source, model, _ = fixture(
        o,
        tmp_path,
        "VariableSpeed" if target == "ConstantSpeed" else "ConstantSpeed",
        side,
    )
    loop = model.getPlantLoops()[0]
    assert loop.addDemandBranchForComponent(o.model.CoilHeatingWater(model))
    if not bypass:
        remove_demand_bypass(o, model, loop)
    model.save(str(source), True)
    report = preflight(source, config(tmp_path, target))
    assert report["ready"], report
    status = report["plan"]["impact"]["demand_bypass"]
    assert status["status"] == ("present" if bypass else "not_found")
    assert status["uncontrolled_branch_count"] == int(bypass)
    assert status["translated_uncontrolled_branch_count"] >= 1
    assert status["common_pipe_simulation"] == "None"
    assert status["constant_speed_supply_review"] == (
        target == "ConstantSpeed" and side == "supply"
    )
    warning = [
        w for w in report["warnings"] if "No explicit uncontrolled demand bypass" in w
    ]
    assert bool(warning) == (
        not bypass and target == "ConstantSpeed" and side == "supply"
    )
    if warning:
        assert "OpenStudio translation currently provides" in warning[0]
    before = source.read_bytes()
    result = apply(report, tmp_path)
    assert source.read_bytes() == before
    assert result["validation"]["ok"]
    assert all(w in result["warnings"] for w in warning)
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    assert (
        pumps.demand_bypass(saved.getPlantLoops()[0], o)
        == report["plan"]["demand_bypass"]
    )


def test_pipe_in_controlled_branch_is_not_a_bypass(sdk, tmp_path):
    o = sdk[0]
    source, model, _ = fixture(o, tmp_path, "VariableSpeed")
    loop = model.getPlantLoops()[0]
    coil = o.model.CoilHeatingWater(model)
    assert loop.addDemandBranchForComponent(coil)
    remove_demand_bypass(o, model, loop)
    pipe = o.model.PipeAdiabatic(model)
    assert pipe.addToNode(coil.waterInletModelObject().get().to_Node().get())
    model.save(str(source), True)
    report = preflight(source, config(tmp_path, "ConstantSpeed"))
    assert report["ready"]
    assert report["plan"]["impact"]["demand_bypass"]["status"] == "not_found"
    assert any(
        "No explicit uncontrolled demand bypass" in w for w in report["warnings"]
    )


def test_empty_parallel_demand_path_is_uncontrolled(sdk, tmp_path):
    o = sdk[0]
    _, model, _ = fixture(o, tmp_path, "VariableSpeed")
    loop = model.getPlantLoops()[0]
    start = loop.demandSplitter().outletModelObjects()[0].to_Node().get()
    pipe = start.outletModelObject().get().to_PipeAdiabatic().get()
    outlet = pipe.outletModelObject().get().to_Node().get()
    model.disconnect(pipe, pipe.inletPort())
    model.disconnect(pipe, pipe.outletPort())
    model.connect(start, start.outletPort(), outlet, outlet.inletPort())
    pipe.remove()
    status = pumps.demand_bypass(loop, o)
    assert status["status"] == "present" and status["uncontrolled_branch_count"] == 1


@pytest.mark.parametrize(
    "condition",
    [
        "moved_field",
        "missing_field",
        "empty_field",
        "PlantLoop",
        "ConnectorList",
        "Connector:Splitter",
        "Branch",
        "splitter_entry",
    ],
)
def test_translated_bypass_field_and_lookup_diagnostics(
    sdk, tmp_path, monkeypatch, condition
):
    from types import SimpleNamespace

    o = sdk[0]
    _, model, _ = fixture(o, tmp_path, "VariableSpeed")
    loop = model.getPlantLoops()[0]
    translator = o.energyplus.ForwardTranslator()
    workspace = translator.translateModel(model)
    field_name = "Demand Side Connector List Name"

    class Proxy:
        def __init__(self, obj):
            self.obj = obj

        def __getattr__(self, name):
            return getattr(self.obj, name)

    class PlantProxy(Proxy):
        def iddObject(self):
            def field_index(name):
                assert name == field_name
                return (
                    o.OptionalInt()
                    if condition == "missing_field"
                    else o.OptionalInt(18)
                )

            return SimpleNamespace(getFieldIndex=field_index)

        def getString(self, index):
            # Simulate a later IDD moving the field. Reading fixed index 17 fails.
            assert index == 18
            if condition == "empty_field":
                return o.OptionalString()
            return self.obj.getString(
                self.obj.iddObject().getFieldIndex(field_name).get()
            )

    class ConnectorProxy(Proxy):
        def extensibleGroups(self):
            return [
                group
                for group in self.obj.extensibleGroups()
                if group.getString(0).get() != "Connector:Splitter"
            ]

    def objects(kind):
        if condition in (
            "PlantLoop",
            "ConnectorList",
            "Connector:Splitter",
            "Branch",
        ) and kind == o.IddObjectType(condition):
            return []
        result = workspace.getObjectsByType(kind)
        if condition in (
            "moved_field",
            "missing_field",
            "empty_field",
        ) and kind == o.IddObjectType("PlantLoop"):
            return [PlantProxy(obj) for obj in result]
        if condition == "splitter_entry" and kind == o.IddObjectType("ConnectorList"):
            return [ConnectorProxy(obj) for obj in result]
        return result

    monkeypatch.setattr(
        o.energyplus,
        "ForwardTranslator",
        lambda: SimpleNamespace(
            translateModel=lambda _: SimpleNamespace(getObjectsByType=objects),
            errors=translator.errors,
        ),
    )
    if condition == "moved_field":
        assert pumps.demand_bypass(loop, o)["translated_uncontrolled_branch_count"] >= 1
    else:
        with pytest.raises(
            ValueError, match="Cannot verify translated demand bypass"
        ) as error:
            pumps.demand_bypass(loop, o)
        expected = (
            field_name
            if condition in ("missing_field", "empty_field")
            else "Connector:Splitter" if condition == "splitter_entry" else condition
        )
        assert expected in str(error.value)


def native_without_translated_bypass(o, after_folder, node_name):
    """Isolated EnergyPlus experiment; never alter the published OSM."""
    root = native_cli().parent.parent / "EnergyPlus"
    binary = next(
        (
            root / name
            for name in ("energyplus", "energyplus-25.2.0", "energyplus.exe")
            if (root / name).is_file()
        ),
        None,
    )
    if binary is None:
        pytest.skip("Standalone EnergyPlus binary unavailable for bypass experiment")
    workspace = o.Workspace.load(str(after_folder / "run/in.idf")).get()
    bypass_name = "Fixture HW Demand Bypass Branch"
    for kind in ("BranchList", "Connector:Splitter", "Connector:Mixer"):
        for obj in workspace.getObjectsByType(o.IddObjectType(kind)):
            for i in reversed(range(obj.numExtensibleGroups())):
                if obj.getExtensibleGroup(i).getString(0).get() == bypass_name:
                    obj.eraseExtensibleGroup(i)
    for kind, name in (
        ("Branch", bypass_name),
        ("Pipe:Adiabatic", "Fixture HW Demand Bypass Pipe"),
    ):
        next(
            obj
            for obj in workspace.getObjectsByType(o.IddObjectType(kind))
            if obj.nameString() == name
        ).remove()
    folder = after_folder / "without_bypass"
    folder.mkdir()
    idf = folder / "in.idf"
    workspace.save(str(idf), True)
    assert bypass_name not in idf.read_text()
    instrumented = (
        o.osversion.VersionTranslator()
        .loadModel(str(after_folder / "instrumented.osm"))
        .get()
    )
    weather = str(instrumented.getWeatherFile().path().get())
    run = subprocess.run(
        [str(binary), "-w", weather, "-d", str(folder), str(idf)],
        cwd=folder,
        capture_output=True,
        text=True,
        timeout=120,
    )
    (folder / "cli.log").write_text(run.stdout + run.stderr)
    errors = (folder / "eplusout.err").read_text()
    assert (
        run.returncode == 0
        and "EnergyPlus Completed Successfully" in errors
        and "** Severe **" not in errors
        and "**  Fatal  **" not in errors
    ), errors
    import sqlite3

    with sqlite3.connect(folder / "eplusout.sql") as sql:
        rows = sql.execute(
            "SELECT r.TimeIndex,d.KeyValue,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE t.WarmupFlag=0 AND ((d.Name='System Node Mass Flow Rate' AND d.KeyValue=?) OR (d.Name='Pump Mass Flow Rate' AND d.KeyValue='SELECTED PUMP'))",
            (node_name.upper(),),
        ).fetchall()
    steps = {}
    for i, key, value in rows:
        steps.setdefault(i, {})[key] = value
    fractions = [
        row[node_name.upper()] / row["SELECTED PUMP"]
        for row in steps.values()
        if row["SELECTED PUMP"] > 1e-7
    ]
    assert (
        fractions
        and min(fractions) == pytest.approx(1, abs=1e-6)
        and max(fractions) == pytest.approx(1, abs=1e-6)
    )
    return dict(
        experiment="Generated bypass removed from a separate IDF",
        coil_flow_fraction_of_pump=dict(min=min(fractions), max=max(fractions)),
        operating_steps=len(fractions),
        zero_flow_steps=sum(row["SELECTED PUMP"] < 1e-7 for row in steps.values()),
        energyplus_warnings=[
            line.strip() for line in errors.splitlines() if "** Warning **" in line
        ],
        severe_errors=0,
        fatal_errors=0,
    )


@pytest.mark.parametrize("bypass", [True, False])
def test_native_constant_supply_with_single_heating_coil(sdk, tmp_path, bypass):
    from vav_fixture import prepare_vav_fixture
    from common import hvac_inventory, vav_plan, vav_create
    import sqlite3

    o = sdk[0]
    source, cfg, _, _ = prepare_vav_fixture(o, tmp_path, True)
    model = o.osversion.VersionTranslator().loadModel(str(source)).get()
    cfg["reheat"] = {"type": "Electricity"}
    vav_create.create(
        model, o, vav_plan.plan(cfg, hvac_inventory.inventory(model), None)
    )
    air = model.getAirLoopHVACs()[0]
    air.sizingSystem().setAllOutdoorAirinHeating(True)
    air.sizingSystem().setAllOutdoorAirinCooling(True)
    oa_schedule = o.model.ScheduleConstant(model)
    oa_schedule.setValue(1)
    model.getControllerOutdoorAirs()[0].setMinimumFractionofOutdoorAirSchedule(
        oa_schedule
    )
    loop = model.getPlantLoopByName("Fixture HW").get()
    pump = next(
        x.to_PumpVariableSpeed().get()
        for x in loop.supplyComponents()
        if x.to_PumpVariableSpeed().is_initialized()
    )
    pump.setName("Selected Pump")
    # Exercise excess-flow resolution during no-load periods without accumulating
    # excessive pump heat in this small, single-coil fixture.
    pump.setPumpControlType("Continuous")
    pump.setRatedPumpHead(6000)
    coil = next(
        x.to_CoilHeatingWater().get()
        for x in loop.demandComponents()
        if x.to_CoilHeatingWater().is_initialized()
    )
    node = coil.waterInletModelObject().get().to_Node().get()
    variable = o.model.OutputVariable("System Node Mass Flow Rate", model)
    variable.setKeyValue(node.nameString())
    variable.setReportingFrequency("Detailed")
    if not bypass:
        remove_demand_bypass(o, model, loop)
    assert (
        len(
            [
                x
                for x in loop.demandComponents()
                if x.to_CoilHeatingWater().is_initialized()
            ]
        )
        == 1
    )
    model.save(str(source), True)
    replacement = config(tmp_path, "ConstantSpeed")
    replacement["plant_loop"] = {"name": "Fixture HW"}
    report = preflight(source, replacement)
    assert report["ready"], report
    assert report["plan"]["demand_bypass"]["status"] == (
        "present" if bypass else "not_found"
    )
    result = apply(report, tmp_path)
    before = native_run(o, source, tmp_path / "before", "Selected Pump")
    after = native_run(
        o, Path(result["output_model_path"]), tmp_path / "after", "Selected Pump"
    )
    evidence = dict(
        bypass=bypass, before=before, after=after, preflight_warnings=report["warnings"]
    )
    for label in ("before", "after"):
        with sqlite3.connect(tmp_path / label / "run/eplusout.sql") as sql:
            rows = sql.execute(
                "SELECT r.TimeIndex,d.KeyValue,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE t.WarmupFlag=0 AND ((d.Name='System Node Mass Flow Rate' AND d.KeyValue=?) OR (d.Name='Pump Mass Flow Rate' AND d.KeyValue='SELECTED PUMP'))",
                (node.nameString().upper(),),
            ).fetchall()
        steps = {}
        for i, key, value in rows:
            steps.setdefault(i, {})[key] = value
        active = [row for row in steps.values() if row["SELECTED PUMP"] > 1e-7]
        assert active
        fractions = [
            row[node.nameString().upper()] / row["SELECTED PUMP"] for row in active
        ]
        evidence[label]["coil_flow_fraction_of_pump"] = dict(
            min=min(fractions), max=max(fractions)
        )
        evidence[label]["energyplus_warnings"] = [
            line.strip()
            for line in (tmp_path / label / "run/eplusout.err").read_text().splitlines()
            if "** Warning **" in line
        ]
        if label == "after":
            # Both translate with a bypass in 3.11.0, even when the OSM has none.
            assert min(fractions) < 0.5
            assert (
                report["plan"]["demand_bypass"]["translated_uncontrolled_branch_count"]
                >= 1
            )
    assert after["sizes"]["Design Flow Rate"] == pytest.approx(
        before["sizes"]["Design Flow Rate"], rel=1e-6
    )
    if not bypass:
        published = Path(result["output_model_path"])
        original_bytes = published.read_bytes()
        evidence["energyplus_without_bypass"] = native_without_translated_bypass(
            o, tmp_path / "after", node.nameString()
        )
        assert published.read_bytes() == original_bytes
    (tmp_path / "native_bypass_evidence.json").write_text(
        json.dumps(evidence, indent=2)
    )
