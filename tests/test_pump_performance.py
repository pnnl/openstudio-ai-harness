"""Pump performance edits must retain identity, topology and unrelated plant state."""

import json
from pathlib import Path
import subprocess
import sqlite3
import sys
import pytest
from test_vav_preflight import sdk, SCRIPTS
from test_supply_fan_performance import native_cli

sys.path.insert(0, str(SCRIPTS))
from common import pump_edit as pumps, model_transaction as tx
from common import plant_create

OPERATION = "edit_pump_performance"


def fixture(o, tmp_path, kind="VariableSpeed", side="supply"):
    m = o.model.Model()
    p = plant_create.plan(
        m,
        o,
        dict(
            output_model_path=str(tmp_path / "unused.osm"),
            defaults_profile="prototype_plants_v1",
            hot_water=dict(name="HW", source="DistrictHeatingWater"),
        ),
    )
    plant_create.create(m, o, p)
    loop = m.getPlantLoops()[0]
    pump = m.getPumpVariableSpeeds()[0]
    if kind != "VariableSpeed":
        pump.remove()
        pump = o.model.PumpConstantSpeed(m)
        assert pump.addToNode(loop.supplyInletNode())
    if side == "demand":
        assert pump.removeFromLoop()
        assert pump.addToNode(loop.demandInletNode())
    pump.setName("Selected Pump")
    pump.additionalProperties().setFeature("review_note", "retain")
    source = tmp_path / "input.osm"
    m.save(str(source), True)
    return source, m, pump


def config(tmp_path, **settings):
    return dict(
        output_model_path=str(tmp_path / "edited.osm"),
        plant_loop={"name": "HW"},
        pump={"name": "Selected Pump"},
        settings=settings or dict(head=30, head_units="ftH2O", motor_efficiency=0.95),
    )


def preflight(source, cfg):
    return tx.preflight(source, cfg, OPERATION, pumps.plan)


def apply(report, tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(report))
    return tx.apply(path, OPERATION, pumps.plan, pumps.edit, pumps.validate_model)


@pytest.mark.parametrize("kind", ["ConstantSpeed", "VariableSpeed"])
@pytest.mark.parametrize("side", ["supply", "demand"])
def test_saved_identity_references_ports_and_only_explicit_changes(
    sdk, tmp_path, kind, side
):
    o = sdk[0]
    source, m, old = fixture(o, tmp_path, kind, side)
    cost = o.model.LifeCycleCost.createLifeCycleCost(
        "Maintenance", old, 100, "CostPerEach", "Maintenance", 1, 0
    ).get()
    actuator = o.model.EnergyManagementSystemActuator(
        old, "Pump", "Pump Mass Flow Rate"
    )
    reference_fields = {str(x.handle()): str(x.idfObject()) for x in (cost, actuator)}
    metadata = str(old.additionalProperties().handle())
    m.save(str(source), True)
    original = source.read_bytes()
    report = preflight(source, config(tmp_path))
    assert report["ready"], report
    assert report == preflight(source, config(tmp_path))
    assert report["plan"]["resolved_objects"]["side"] == side
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and result["translation"]["ok"], result
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    pump = pumps.pump_object(saved, o, report["plan"]["resolved_objects"]["pump"])
    assert pump.handle() == old.handle()
    assert str(pump.additionalProperties().handle()) == metadata
    assert pump.ratedPumpHead() == pytest.approx(o.convert(30, "ftH_{2}O", "Pa").get())
    assert pump.motorEfficiency() == 0.95
    assert pump.isRatedPowerConsumptionAutosized()
    for handle, raw in reference_fields.items():
        assert str(saved.getModelObject(o.toUUID(handle)).get().idfObject()) == raw
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    "settings",
    [
        dict(control_type="Continuous"),
        dict(motor_loss_fraction_to_fluid=0.5),
        dict(rated_power_w=1000),
        dict(power_sizing_method="PowerPerFlow", electric_power_per_flow=200000),
        dict(shaft_power_per_flow_per_head=1.4),
        dict(part_load_coefficients=[0, 0.0205, 0.4101, 0.5753]),
    ],
)
def test_each_supported_change_is_saved(sdk, tmp_path, settings):
    source, _, _ = fixture(sdk[0], tmp_path)
    report = preflight(source, config(tmp_path, **settings))
    assert report["ready"], report
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and result["translation"]["ok"]


@pytest.mark.parametrize("method", ["PowerPerFlow", "PowerPerFlowPerPressure"])
def test_fixed_power_and_autosize_are_explicit(sdk, tmp_path, method):
    source, model, pump = fixture(sdk[0], tmp_path)
    pump.setRatedPowerConsumption(1000)
    pump.setDesignPowerSizingMethod(method)
    model.save(str(source), True)
    report = preflight(source, config(tmp_path))
    assert any("fixed" in w for w in report["warnings"])
    assert report["plan"]["after_values"]["rated_power_w"] == 1000
    report = preflight(source, config(tmp_path, rated_power_w="Autosize"))
    assert report["plan"]["after_values"]["rated_power_w"] == "Autosize"
    assert any("flow" in w for w in report["warnings"])
    assert apply(report, tmp_path)["validation"]["ok"]


@pytest.mark.parametrize(
    "settings",
    [
        dict(head=-1, head_units="Pa"),
        dict(head=True, head_units="Pa"),
        dict(head=1, head_units="bar"),
        dict(head=1e308, head_units="ftH2O"),
        dict(part_load_coefficients=[1, 2, 3, 4, 5]),
        dict(motor_efficiency=0),
        dict(motor_efficiency=1.1),
        dict(motor_efficiency=float("nan")),
        dict(motor_loss_fraction_to_fluid=2),
        dict(control_type="Variable"),
        dict(rated_power_w=0),
        dict(power_sizing_method="Auto"),
        dict(unknown=1),
        dict(shaft_power_per_flow_per_head=0.5),
    ],
)
def test_invalid_schema_blocks(sdk, tmp_path, settings):
    source, _, _ = fixture(sdk[0], tmp_path)
    with pytest.raises(ValueError, match="Invalid pump"):
        preflight(source, config(tmp_path, **settings))


@pytest.mark.parametrize(
    "settings",
    [
        dict(head=20),
        dict(head_units="Pa"),
        dict(part_load_coefficients=[0, -1, 1, 0]),
        dict(part_load_coefficients=[0, 0, 0, 0]),
    ],
)
def test_unready_semantic_inputs(sdk, tmp_path, settings):
    source, _, _ = fixture(sdk[0], tmp_path)
    report = preflight(source, config(tmp_path, **settings))
    assert not report["ready"], report


def test_constant_speed_curve_noop_missing_selection_and_hydraulic_impossibility(
    sdk, tmp_path
):
    source, model, pump = fixture(sdk[0], tmp_path, "ConstantSpeed")
    for cfg in [
        config(tmp_path, part_load_coefficients=[0, 1, 0, 0]),
        config(tmp_path, motor_efficiency=pump.motorEfficiency()),
        dict(output_model_path=str(tmp_path / "edited.osm")),
        dict(config(tmp_path), pump={"name": "Missing"}),
    ]:
        assert not preflight(source, cfg)["ready"]
    pump.setRatedFlowRate(0.01)
    pump.setRatedPowerConsumption(100)
    model.save(str(source), True)
    report = preflight(source, config(tmp_path))
    assert not report["ready"]
    assert "hydraulic" in str(report["plan"]["errors"])


@pytest.mark.parametrize(
    "changed",
    ["wrong_setter", "curve", "flow", "plant", "new_pump", "metadata", "connections"],
)
def test_independent_validation_rejects_unrequested_changes(
    sdk, tmp_path, monkeypatch, changed
):
    o = sdk[0]
    source, _, _ = fixture(o, tmp_path)
    report = preflight(source, config(tmp_path))
    real = pumps.edit

    def bad(model, native, planned):
        result = real(model, native, planned)
        pump = model.getPumpVariableSpeeds()[0]
        if changed == "wrong_setter":
            pump.setMotorEfficiency(0.9)
        elif changed == "curve":
            pump.setCoefficient1ofthePartLoadPerformanceCurve(0.5)
        elif changed == "flow":
            pump.setRatedFlowRate(0.002)
        elif changed == "plant":
            model.getPlantLoops()[0].sizingPlant().setDesignLoopExitTemperature(60)
        elif changed == "new_pump":
            native.model.PumpConstantSpeed(model)
        elif changed == "metadata":
            pump.additionalProperties().setFeature("review_note", "changed")
        else:
            pump.removeFromLoop()
            pump.addToNode(model.getPlantLoops()[0].demandInletNode())
        return result

    monkeypatch.setattr(pumps, "edit", bad)
    with pytest.raises(ValueError, match="validation"):
        apply(report, tmp_path)
    assert not (tmp_path / "edited.osm").exists()
    assert not (tmp_path / "edited").exists()


@pytest.mark.parametrize("changed", ["source", "plan", "operation", "configuration"])
def test_hash_bound_plan(sdk, tmp_path, changed):
    source, _, _ = fixture(sdk[0], tmp_path)
    report = preflight(source, config(tmp_path))
    if changed == "source":
        source.write_bytes(source.read_bytes() + b"\n")
    elif changed == "plan":
        report["plan"]["after_values"]["motor_efficiency"] = 0.99
    elif changed == "configuration":
        report["configuration"]["settings"]["motor_efficiency"] = 0.99
    else:
        report["operation"] = "create_plant_loops"
    with pytest.raises(ValueError):
        apply(report, tmp_path)


def test_multiple_pumps_individual_selection_and_unsupported_headered(sdk, tmp_path):
    source, model, _ = fixture(sdk[0], tmp_path)
    loop = model.getPlantLoops()[0]
    other = sdk[0].model.PumpConstantSpeed(model)
    other.setName("Other pump")
    assert other.addToNode(loop.demandInletNode())
    model.save(str(source), True)
    assert apply(preflight(source, config(tmp_path)), tmp_path)["validation"]["ok"]
    other.remove()
    headered = sdk[0].model.HeaderedPumpsVariableSpeed(model)
    headered.setName("Bank")
    assert headered.addToNode(loop.demandInletNode())
    model.save(str(source), True)
    cfg = dict(
        config(tmp_path),
        output_model_path=str(tmp_path / "bank.osm"),
        pump={"name": "Bank"},
    )
    assert not preflight(source, cfg)["ready"]


def native_run(o, path, folder, name):
    """Instrument a separate copy so validated model hashes remain meaningful."""
    folder.mkdir()
    model = o.osversion.VersionTranslator().loadModel(str(path)).get()
    for variable in (
        "Pump Electricity Rate",
        "Pump Mass Flow Rate",
        "Pump Electricity Energy",
    ):
        output = o.model.OutputVariable(variable, model)
        output.setKeyValue(name)
        output.setReportingFrequency("Detailed")
    weather = model.getWeatherFile().path()
    if weather.is_initialized():
        epw = Path(str(weather.get()))
        if not epw.is_absolute():
            epw = path.parent / epw
        assert o.model.WeatherFile.setWeatherFile(
            model, o.EpwFile(str(epw.resolve()))
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
    errors = (folder / "run/eplusout.err").read_text()
    assert (
        "EnergyPlus Completed Successfully" in errors
        and "** Severe **" not in errors
        and "**  Fatal  **" not in errors
    ), errors
    with sqlite3.connect(folder / "run/eplusout.sql") as sql:
        sizes = sql.execute(
            "SELECT Description, Value FROM ComponentSizes WHERE CompName=?",
            (name.upper(),),
        ).fetchall()

        def rows(variable):
            return sql.execute(
                "SELECT r.TimeIndex, r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE d.KeyValue=? AND d.Name=? AND t.WarmupFlag=0",
                (name.upper(), variable),
            ).fetchall()

        power = dict(rows("Pump Electricity Rate"))
        flow = dict(rows("Pump Mass Flow Rate"))
        energy = dict(rows("Pump Electricity Energy"))
    assert (
        power
        and flow
        and energy
        and sum(energy.values()) > 0
        and max(power.values()) > 0
        and max(flow.values()) > 0
    )
    return dict(
        sizes=dict(sizes),
        electricity_energy_j=sum(energy.values()),
        max_power_w=max(power.values()),
        max_mass_flow_kg_s=max(flow.values()),
        operating_steps=sum(v > 0 for v in power.values()),
        no_load_steps=sum(v < 1e-9 for v in flow.values()),
    )


@pytest.mark.parametrize("kind", ["ConstantSpeed", "VariableSpeed"])
@pytest.mark.parametrize("power_mode", ["pressure", "flow", "fixed"])
def test_native_sizing_and_electric_power_change(sdk, tmp_path, kind, power_mode):
    from vav_fixture import prepare_vav_fixture
    from common.hvac_inventory import inventory as hvac_inventory
    from common.vav_plan import plan as vav_plan
    from common.vav_create import create as create_vav

    o = sdk[0]
    source, base, _, _ = prepare_vav_fixture(o, tmp_path, True)
    model = o.osversion.VersionTranslator().loadModel(str(source)).get()
    create_vav(model, o, vav_plan(base, hvac_inventory(model), None))
    loop = model.getPlantLoopByName("Fixture CHW").get()
    pump = next(
        x.to_PumpVariableSpeed().get()
        for x in loop.supplyComponents()
        if x.to_PumpVariableSpeed().is_initialized()
    )
    if kind == "ConstantSpeed":
        pump.remove()
        pump = o.model.PumpConstantSpeed(model)
        assert pump.addToNode(loop.supplyInletNode())
    else:
        # Linear power versus flow gives a direct observable head/efficiency comparison.
        for i, c in enumerate([0, 1, 0, 0], 1):
            getattr(pump, f"setCoefficient{i}ofthePartLoadPerformanceCurve")(c)
    pump.setName("Native Pump")
    pump.setRatedPumpHead(60000)
    pump.setMotorEfficiency(0.9)
    pump.setFractionofMotorInefficienciestoFluidStream(0)
    if power_mode == "flow":
        pump.setDesignPowerSizingMethod("PowerPerFlow")
        pump.setDesignElectricPowerPerUnitFlowRate(200000)
    elif power_mode == "fixed":
        pump.setRatedPowerConsumption(1000)
    model.save(str(source), True)
    cfg = dict(
        config(tmp_path, head=30000, head_units="Pa", motor_efficiency=0.95),
        plant_loop={"name": "Fixture CHW"},
        pump={"name": "Native Pump"},
    )
    result = apply(preflight(source, cfg), tmp_path)
    before = native_run(o, source, tmp_path / "before", pump.nameString())
    after = native_run(
        o, Path(result["output_model_path"]), tmp_path / "after", pump.nameString()
    )
    expected = 0.5 * 0.9 / 0.95 if power_mode == "pressure" else 1.0
    evidence = dict(
        kind=kind,
        power_mode=power_mode,
        before=before,
        after=after,
        expected_power_ratio=expected,
    )
    (tmp_path / "native_evidence.json").write_text(json.dumps(evidence, indent=2))
    # Check native sizing and actual EnergyPlus operation, not just translated inputs.
    for entry, head, eff in [(before, 60000, 0.9), (after, 30000, 0.95)]:
        flow = entry["sizes"]["Design Flow Rate"]
        assert flow > 0
        if power_mode != "fixed":
            power = entry["sizes"]["Design Power Consumption"]
            assert power > 0
            factor = head * 1.282051282 / eff if power_mode == "pressure" else 200000
            assert power == pytest.approx(flow * factor, rel=1e-6)
        elif kind == "ConstantSpeed":
            assert entry["max_power_w"] == pytest.approx(1000)
    assert after["max_power_w"] / before["max_power_w"] == pytest.approx(
        expected, rel=0.02
    ), evidence
    assert after["electricity_energy_j"] / before[
        "electricity_energy_j"
    ] == pytest.approx(expected, rel=0.02), evidence
    assert after["max_mass_flow_kg_s"] / before["max_mass_flow_kg_s"] == pytest.approx(
        1, rel=0.02
    ), evidence


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_exported_pump_bundle_executes_after_relocation(sdk, tmp_path, host):
    import shutil
    from adapters.claude_code_adapter import ClaudeCodeAdapter
    from adapters.codex_adapter import CodexAdapter
    from adapters.contracts import HostAdapterConfig

    source, _, _ = fixture(sdk[0], tmp_path)
    setup = HostAdapterConfig(
        host_name=host, workspace_root=Path.cwd(), runtime_mode="marketplace"
    )
    adapter = ClaudeCodeAdapter(setup) if host == "claude" else CodexAdapter(setup)
    exported = tmp_path / "export"
    adapter.export_plugin(exported, dry_run=False)
    skill = next(exported.rglob("openstudio-pump-performance-editor/SKILL.md")).parent
    moved = tmp_path / "relocated"
    shutil.copytree(skill, moved)
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
    report = tmp_path / "reviewed.json"
    for args in (
        ["--input", str(source), "--report", str(tmp_path / "inventory.json")],
        ["--input", str(source), "--config", str(cfg), "--report", str(report)],
        ["--plan", str(report), "--report", str(tmp_path / "applied.json")],
    ):
        run = subprocess.run(
            [
                str(native_cli()),
                "execute_python_script",
                str(moved / "scripts/edit_pump_performance.py"),
                *args,
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert run.returncode == 0, run.stdout + run.stderr
    applied = json.loads((tmp_path / "applied.json").read_text())
    assert applied["validation"]["ok"] and applied["translation"]["ok"]


def test_sdk_version_pin_applies_before_source_read(sdk, tmp_path, monkeypatch):
    from common.version_guard import CompatibilityError

    monkeypatch.setattr(sdk[0], "openStudioVersion", lambda: "3.12.0")
    with pytest.raises(CompatibilityError, match="3.11.0"):
        preflight(tmp_path / "missing.osm", config(tmp_path))


def test_inactive_factors_and_vfd_controls_are_visible(sdk, tmp_path):
    source, model, pump = fixture(sdk[0], tmp_path)
    assert pump.setVFDControlType("ManualControl")
    model.save(str(source), True)
    report = preflight(source, config(tmp_path, electric_power_per_flow=200000))
    assert report["ready"] and any("inactive" in w for w in report["warnings"])
    assert any("VFD" in w for w in report["warnings"])


def test_curve_rejects_negative_interior_with_positive_endpoints(sdk, tmp_path):
    source, _, _ = fixture(sdk[0], tmp_path)
    # Positive endpoint power 0.2, but -0.05 at flow fraction 0.5.
    report = preflight(source, config(tmp_path, part_load_coefficients=[0.2, -1, 1, 0]))
    assert not report["ready"]


@pytest.mark.parametrize("kind", ["ConstantSpeed", "VariableSpeed"])
def test_fixed_power_autosized_flow_warns_to_check_after_sizing(sdk, tmp_path, kind):
    o = sdk[0]
    source, model, pump = fixture(o, tmp_path, kind)
    pump.setRatedPowerConsumption(50)
    assert pump.isRatedFlowRateAutosized()
    model.save(str(source), True)
    report = preflight(source, config(tmp_path, head=600, head_units="ftH2O"))
    assert report["ready"], report
    warning = next(
        w
        for w in report["warnings"]
        if "feasibility cannot be checked before sizing" in w
    )
    assert "hydraulic efficiency" in warning and "<= 1" in warning
    maximum_flow = 50 * pump.motorEfficiency() / o.convert(600, "ftH_{2}O", "Pa").get()
    assert f"{maximum_flow:.9g} m³/s" in warning
    result = apply(report, tmp_path)
    assert warning in result["warnings"]
    assert result["changes"]["after"]["rated_power_w"] == 50
    # The same pressure expressed in Pa has identical feasibility, not a different bound.
    cfg = config(tmp_path, head=o.convert(600, "ftH_{2}O", "Pa").get(), head_units="Pa")
    cfg["output_model_path"] = str(tmp_path / "alternate.osm")
    assert preflight(source, cfg)["ready"]


@pytest.mark.parametrize("units", ["Pa", "ftH2O"])
@pytest.mark.parametrize("factor", [1, 1.0001])
def test_head_ceiling_is_unit_equivalent_and_checked_before_inventory(
    sdk, tmp_path, monkeypatch, units, factor
):
    o = sdk[0]
    source, _, _ = fixture(o, tmp_path)
    maximum = (
        o.convert(10_000_000, "Pa", "ftH_{2}O").get()
        if units == "ftH2O"
        else 10_000_000
    )
    cfg = config(tmp_path, head=maximum * factor, head_units=units)
    if factor > 1:
        monkeypatch.setattr(
            pumps,
            "inventory",
            lambda _: pytest.fail("Schema must reject before inventory"),
        )
        with pytest.raises(ValueError, match=r"settings.head: violates maximum"):
            preflight(source, cfg)
    else:
        report = preflight(source, cfg)
        assert report["ready"], report
        assert report["plan"]["after_values"]["head_pa"] == pytest.approx(10_000_000)


@pytest.mark.parametrize("count", [3, 5])
def test_curve_length_rejected_by_schema_before_inventory(
    sdk, tmp_path, monkeypatch, count
):
    source, _, _ = fixture(sdk[0], tmp_path)
    monkeypatch.setattr(
        pumps, "inventory", lambda _: pytest.fail("Schema must reject before inventory")
    )
    with pytest.raises(ValueError, match="settings.part_load_coefficients: requires"):
        preflight(source, config(tmp_path, part_load_coefficients=[1] * count))
