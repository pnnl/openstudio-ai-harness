"""Genuine class conversion binds performance, graph, controls and identity impact."""

import json
from pathlib import Path
import shutil
import sqlite3
import subprocess

import pytest
from test_vav_preflight import sdk
from test_water_coil_operations import fixture
from test_supply_fan_performance import native_cli
from common import (
    coil_conversion as conversion,
    model_transaction as tx,
    water_coil as coils,
)


def conversion_fixture(native, tmp_path, system_kind="CAV"):
    source, _, reference = fixture(native, tmp_path, "Heating", "edit", system_kind)
    return (
        source,
        dict(
            output_model_path=str(tmp_path / "electric.osm"),
            coil={"handle": reference["handle"]},
            efficiency=0.98,
            temperature_control="Preserve",
            sizing="Autosize",
            reference_policy="Reject",
        ),
        reference,
    )


def prepare(source, cfg):
    return tx.preflight(source, cfg, "replace_coil", conversion.plan)


def apply_conversion(report, tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(report, sort_keys=True))
    return tx.apply(
        path,
        "replace_coil",
        conversion.plan,
        conversion.convert,
        conversion.validate_model,
    )


@pytest.mark.parametrize("system_kind", ["VAV", "CAV"])
def test_saved_conversion_preserves_air_nodes_schedule_and_metadata(
    sdk, tmp_path, system_kind
):
    native = sdk[0]
    source, cfg, reference = conversion_fixture(native, tmp_path, system_kind)
    original = source.read_bytes()
    report = prepare(source, cfg)
    assert report["ready"], report
    assert report == prepare(source, json.loads(json.dumps(cfg, sort_keys=True)))
    result = apply_conversion(report, tmp_path)
    assert result["validation"]["ok"] and result["translation"]["ok"]
    saved = (
        native.osversion.VersionTranslator()
        .loadModel(result["output_model_path"])
        .get()
    )
    replacement = coils.object_by_ref(
        saved, native, result["changes"]["coil"], "CoilHeatingElectric"
    )
    assert (
        replacement.additionalProperties().getFeatureAsString("review_note").get()
        == "keep"
    )
    assert str(replacement.handle()) != reference["handle"]
    assert not saved.getModelObject(native.toUUID(reference["handle"])).is_initialized()
    assert source.read_bytes() == original
    assert report["plan"]["impact"]["source_plant_remaining_coil_count"] == 5
    assert report["plan"]["impact"]["temperature_control"] == "Preserve"
    assert not any(
        kind.startswith(("OS_Schedule", "OS_SetpointManager"))
        for kind in report["plan"]["added_counts"]
    )

    # Inspect EnergyPlus fields independently of the planner's context helper.
    def translated(model, coil):
        getter = getattr(coil, "airOutletModelObject", None) or coil.outletModelObject
        outlet = getter().get().nameString()
        ws = native.energyplus.ForwardTranslator().translateModel(model)
        return sorted(
            tuple(x.getString(i).get() for i in range(1, x.numFields()))
            for x in ws.getObjectsByType(
                native.IddObjectType("SetpointManager:MixedAir")
            )
            if x.getString(5).get() == outlet
        )

    baseline = native.model.Model.load(str(source)).get()
    old = coils.object_by_ref(baseline, native, reference, "CoilHeatingWater")
    before_managers = translated(baseline, old)
    assert before_managers and translated(saved, replacement) == before_managers


@pytest.mark.parametrize("system_kind", ["VAV", "CAV"])
def test_conversion_retains_existing_outlet_setpoint_manager(
    sdk, tmp_path, system_kind
):
    native = sdk[0]
    source, cfg, reference = conversion_fixture(native, tmp_path, system_kind)
    model = native.model.Model.load(str(source)).get()
    coil = coils.object_by_ref(model, native, reference, "CoilHeatingWater")
    schedule = native.model.ScheduleConstant(model)
    schedule.setValue(12.8)
    manager = native.model.SetpointManagerScheduled(model, schedule)
    manager.addToNode(coil.airOutletModelObject().get().to_Node().get())
    original = str(manager.idfObject())
    handle = manager.handle()
    model.save(str(source), True)
    report = prepare(source, cfg)
    assert report["ready"], report
    result = apply_conversion(report, tmp_path)
    saved = native.model.Model.load(result["output_model_path"]).get()
    assert str(saved.getModelObject(handle).get().idfObject()) == original


@pytest.mark.parametrize(
    "setting", ["action", "minimum_flow", "control_variable", "actuator"]
)
def test_preserve_mode_rejects_different_water_controller_strategy(
    sdk, tmp_path, setting
):
    native = sdk[0]
    source, cfg, reference = conversion_fixture(native, tmp_path)
    model = native.model.Model.load(str(source)).get()
    coil = coils.object_by_ref(model, native, reference, "CoilHeatingWater")
    controller = coil.controllerWaterCoil().get()
    if setting == "action":
        assert controller.setAction("Reverse")
    elif setting == "minimum_flow":
        assert controller.setMinimumActuatedFlow(0.001)
    elif setting == "actuator":
        assert controller.setActuatorNode(coil.plantLoop().get().supplyInletNode())
    else:
        assert controller.setControlVariable("TemperatureAndHumidityRatio")
    model.save(str(source), True)
    report = prepare(source, cfg)
    assert not report["ready"] and any(
        "Preserve control requires" in x for x in report["plan"]["errors"]
    )


@pytest.mark.parametrize(
    "missing",
    ["coil", "efficiency", "temperature_control", "sizing", "reference_policy"],
)
def test_missing_conversion_choices_are_unready(sdk, tmp_path, missing):
    source, cfg, _ = conversion_fixture(sdk[0], tmp_path)
    del cfg[missing]
    report = prepare(source, cfg)
    assert not report["ready"] and missing in report["plan"]["missing_inputs"]


@pytest.mark.parametrize(
    "bad",
    [
        "cooling",
        "serial",
        "ems",
        "cost",
        "water_node_reference",
        "controller_reference",
        "metadata_node_reference",
        "named_reference",
        "custom_sensor",
    ],
)
def test_conversion_rejects_unsupported_topology_and_references(sdk, tmp_path, bad):
    native = sdk[0]
    source, cfg, reference = conversion_fixture(native, tmp_path)
    model = native.model.Model.load(str(source)).get()
    coil = coils.object_by_ref(model, native, reference, "CoilHeatingWater")
    if bad == "cooling":
        cfg["coil"] = {"handle": str(model.getCoilCoolingWaters()[0].handle())}
    elif bad == "serial":
        assert native.model.PipeAdiabatic(model).addToNode(
            coil.waterInletModelObject().get().to_Node().get()
        )
    elif bad == "ems":
        native.model.EnergyManagementSystemActuator(coil, "Coil", "On/Off Supervisory")
    elif bad == "cost":
        native.model.LifeCycleCost.createLifeCycleCost(
            "Maintenance", coil, 100, "CostPerEach", "Maintenance", 1, 0
        )
    elif bad == "water_node_reference":
        native.model.EnergyManagementSystemActuator(
            coil.waterOutletModelObject().get().to_Node().get(),
            "System Node Setpoint",
            "Temperature Setpoint",
        )
    elif bad == "controller_reference":
        native.model.LifeCycleCost.createLifeCycleCost(
            "Controller cost",
            coil.controllerWaterCoil().get(),
            100,
            "CostPerEach",
            "Maintenance",
            1,
            0,
        )
    elif bad == "metadata_node_reference":
        coil.additionalProperties().setFeature(
            "referenced_water_node", str(coil.waterInletModelObject().get().handle())
        )
    elif bad == "named_reference":
        sensor = native.model.EnergyManagementSystemSensor(
            model, "Heating Coil Heating Rate"
        )
        sensor.setKeyName(coil.nameString().upper())
    else:
        coil.controllerWaterCoil().get().setSensorNode(
            coil.airLoopHVAC().get().supplyOutletNode()
        )
    model.save(str(source), True)
    original = source.read_bytes()
    report = prepare(source, cfg)
    assert not report["ready"] and report["plan"]["errors"]
    assert (
        source.read_bytes() == original and not Path(cfg["output_model_path"]).exists()
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("efficiency", 0),
        ("efficiency", 1.01),
        ("outlet_temperature_c", 32.2),
        ("temperature_control", "Constant"),
        ("reference_policy", "Transfer"),
        ("sizing", "Preserve"),
        ("operation", "replace"),
    ],
)
def test_conversion_schema_rejects_unimplemented_choices(sdk, tmp_path, field, value):
    source, cfg, _ = conversion_fixture(sdk[0], tmp_path)
    cfg[field] = value
    with pytest.raises(ValueError, match="Invalid config"):
        prepare(source, cfg)


@pytest.mark.parametrize("mutation", ["source", "configuration", "impact"])
def test_conversion_rejects_stale_review(sdk, tmp_path, mutation):
    source, cfg, _ = conversion_fixture(sdk[0], tmp_path)
    report = prepare(source, cfg)
    if mutation == "source":
        source.write_bytes(source.read_bytes() + b"\n")
    elif mutation == "configuration":
        report["configuration"]["efficiency"] = 0.9
    else:
        report["plan"]["impact"]["after"]["efficiency"] = 0.9
    with pytest.raises(ValueError, match="Stale|differs"):
        apply_conversion(report, tmp_path)
    assert not Path(cfg["output_model_path"]).exists()


@pytest.mark.parametrize("weather_exists", [False, True])
def test_conversion_workflow_weather_and_readiness(sdk, tmp_path, weather_exists):
    native = sdk[0]
    source, cfg, _ = conversion_fixture(native, tmp_path)
    model = native.model.Model.load(str(source)).get()
    model.getWeatherFile().remove()
    model.save(str(source), True)
    if not weather_exists:
        (source.parent / (source.stem + "_files") / "weather.epw").unlink()
    result = apply_conversion(prepare(source, cfg), tmp_path)
    assert result["validation"]["ok"] and result["simulation_ready"] == weather_exists


@pytest.mark.parametrize(
    "mutation",
    [
        "efficiency",
        "capacity",
        "name",
        "schedule",
        "temperature",
        "control_node",
        "metadata",
        "plant",
        "other_coil",
        "extra",
        "reported_coil",
        "reported_source",
    ],
)
def test_saved_conversion_validator_rejects_unapproved_changes(
    sdk, tmp_path, monkeypatch, mutation
):
    source, cfg, _ = conversion_fixture(sdk[0], tmp_path)
    report = prepare(source, cfg)
    assert report["ready"]
    original = conversion.convert

    def bad(model, native, planned):
        result = original(model, native, planned)
        if "companions" not in planned:
            return result  # mutate apply only, after fresh preflight succeeds
        coil = coils.object_by_ref(model, native, result["coil"], "CoilHeatingElectric")
        if mutation == "efficiency":
            coil.setEfficiency(0.8)
        elif mutation == "capacity":
            coil.setNominalCapacity(20000)
        elif mutation == "name":
            coil.setName("Unapproved")
        elif mutation == "schedule":
            coil.setAvailabilitySchedule(model.alwaysOffDiscreteSchedule())
        elif mutation == "temperature":
            manager = (
                coil.airLoopHVAC()
                .get()
                .supplyOutletNode()
                .setpointManagers()[0]
                .to_SetpointManagerScheduled()
                .get()
            )
            schedule = manager.schedule().to_ScheduleRuleset().get()
            schedule.defaultDaySchedule().clearValues()
            schedule.defaultDaySchedule().addValue(native.Time(0, 24, 0, 0), 40)
        elif mutation == "control_node":
            manager = (
                coil.airLoopHVAC()
                .get()
                .supplyOutletNode()
                .setpointManagers()[0]
                .to_SetpointManagerScheduled()
                .get()
            )
            native.model.SetpointManagerScheduled(model, manager.schedule()).addToNode(
                coil.outletModelObject().get().to_Node().get()
            )
        elif mutation == "metadata":
            coil.additionalProperties().setFeature("review_note", "corrupt")
        elif mutation == "plant":
            coils.object_by_ref(
                model, native, planned["resolved_objects"]["plant_loop"], "PlantLoop"
            ).setName("Changed")
        elif mutation == "other_coil":
            model.getCoilHeatingWaters()[0].setRatedInletWaterTemperature(70)
        elif mutation == "extra":
            native.model.CoilHeatingElectric(model)
        elif mutation == "reported_coil":
            result["coil"]["name"] = "Incorrect"
        else:
            result["source_coil"]["handle"] = "{00000000-0000-0000-0000-000000000000}"
        return result

    monkeypatch.setattr(conversion, "convert", bad)
    with pytest.raises(ValueError):
        apply_conversion(report, tmp_path)
    assert not Path(cfg["output_model_path"]).exists()


@pytest.mark.parametrize("system_kind", ["VAV", "CAV"])
def test_native_electric_conversion_design_days(sdk, tmp_path, system_kind):
    source, cfg, _ = conversion_fixture(sdk[0], tmp_path, system_kind)
    result = apply_conversion(prepare(source, cfg), tmp_path)
    run_design_days(
        result,
        tmp_path,
        "Coil:Heating:Electric",
        "Design Size Nominal Capacity",
        substantial=system_kind == "CAV",
    )


def run_design_days(
    result,
    tmp_path,
    comp_type,
    description,
    *,
    substantial=False,
    minimum_capacity_w=0,
    workflow_name="workflow.osw",
):
    folder = Path(result["companion_directory"])
    run = subprocess.run(
        [str(native_cli()), "run", "-w", str(folder / workflow_name)],
        cwd=folder,
        capture_output=True,
        text=True,
        timeout=120,
    )
    (tmp_path / "cli.log").write_text(run.stdout + run.stderr)
    assert run.returncode == 0, run.stdout + run.stderr
    errors = (folder / "run/eplusout.err").read_text()
    assert (
        "EnergyPlus Completed Successfully" in errors
        and "** Severe" not in errors
        and "**  Fatal" not in errors
    ), errors
    with sqlite3.connect(folder / "run/eplusout.sql") as sql:
        rows = sql.execute(
            "SELECT Value FROM ComponentSizes WHERE CompType=? AND upper(CompName)=? AND Description=?",
            (comp_type, result["changes"]["coil"]["name"].upper(), description),
        ).fetchall()
    assert len(rows) == 1 and rows[0][0] > (
        10000 if substantial else minimum_capacity_w
    ), rows
    (tmp_path / "sizing-evidence.json").write_text(
        json.dumps(
            dict(
                coil=result["changes"]["coil"],
                capacity_w=rows[0][0],
                description=description,
            ),
            indent=2,
        )
        + "\n"
    )


@pytest.mark.parametrize("system_kind", ["VAV", "CAV"])
def test_native_preserved_supply_control_temperature_and_zero_unneeded_heat(
    sdk, tmp_path, system_kind
):
    native = sdk[0]
    source, cfg, _ = conversion_fixture(native, tmp_path, system_kind)
    original = source.read_bytes()
    result = apply_conversion(prepare(source, cfg), tmp_path)
    model = native.model.Model.load(result["output_model_path"]).get()
    coil = coils.object_by_ref(
        model, native, result["changes"]["coil"], "CoilHeatingElectric"
    )
    loop = coil.airLoopHVAC().get()
    fan = (
        model.getFanVariableVolumes()
        if system_kind == "VAV"
        else model.getFanConstantVolumes()
    )[0]
    nodes = dict(
        inlet=coil.inletModelObject().get().nameString(),
        outlet=coil.outletModelObject().get().nameString(),
        supply=loop.supplyOutletNode().nameString(),
        fan_inlet=fan.inletModelObject().get().nameString(),
        fan_outlet=fan.outletModelObject().get().nameString(),
    )
    for name in set(nodes.values()):
        for variable in (
            "System Node Temperature",
            "System Node Setpoint Temperature",
            "System Node Mass Flow Rate",
        ):
            output = native.model.OutputVariable(variable, model)
            output.setKeyValue(name)
            output.setReportingFrequency("Timestep")
    for variable in ("Heating Coil Heating Rate", "Heating Coil Electricity Rate"):
        output = native.model.OutputVariable(variable, model)
        output.setKeyValue(coil.nameString())
        output.setReportingFrequency("Timestep")
    # Instrument a separate model/workflow; retain the validated output and source.
    instrumented = tmp_path / "instrumented.osm"
    model.save(str(instrumented), True)
    folder = Path(result["companion_directory"])
    workflow = json.loads((folder / "workflow.osw").read_text())
    workflow["seed_file"] = str(instrumented)
    (folder / "control.osw").write_text(json.dumps(workflow))
    run_design_days(
        result,
        tmp_path,
        "Coil:Heating:Electric",
        "Design Size Nominal Capacity",
        substantial=system_kind == "CAV",
        workflow_name="control.osw",
    )
    with sqlite3.connect(folder / "run/eplusout.sql") as sql:
        series = {
            (key, name): dict(
                sql.execute(
                    "SELECT d.TimeIndex,d.Value FROM ReportData d JOIN Time t ON t.TimeIndex=d.TimeIndex WHERE d.ReportDataDictionaryIndex=? AND t.WarmupFlag=0",
                    (index,),
                )
            )
            for index, key, name in sql.execute(
                "SELECT ReportDataDictionaryIndex,KeyValue,Name FROM ReportDataDictionary WHERE ReportingFrequency='Zone Timestep' AND (Name LIKE 'System Node %' OR Name LIKE 'Heating Coil %')"
            ).fetchall()
        }

    def value(node, variable, time):
        return series[(nodes[node].upper(), variable)][time]

    rates = series[(coil.nameString().upper(), "Heating Coil Heating Rate")]
    electricity = series[(coil.nameString().upper(), "Heating Coil Electricity Rate")]
    errors, no_heat_rates, tracking_errors = [], [], []
    for time, rate in rates.items():
        if value("outlet", "System Node Mass Flow Rate", time) < 0.001:
            continue
        inlet = value("inlet", "System Node Temperature", time)
        setpoint = value("outlet", "System Node Setpoint Temperature", time)
        supply_setpoint = value("supply", "System Node Setpoint Temperature", time)
        fan_rise = value("fan_outlet", "System Node Temperature", time) - value(
            "fan_inlet", "System Node Temperature", time
        )
        errors.append(abs(setpoint - (supply_setpoint - fan_rise)))
        if inlet >= setpoint - 0.01:
            no_heat_rates.append(max(rate, electricity[time]))
        if abs(inlet - setpoint) < 0.01:
            tracking_errors.append(
                max(
                    abs(value("outlet", "System Node Temperature", time) - setpoint),
                    abs(
                        value("supply", "System Node Temperature", time)
                        - supply_setpoint
                    ),
                )
            )
    assert (
        errors and max(errors) < 0.02
    ), "Coil target must track the supply target minus fan heat"
    assert (
        no_heat_rates and max(no_heat_rates) < 0.1
    ), "No electric/reheat load when inlet air needs no heating"
    assert (
        tracking_errors and max(tracking_errors) < 0.02
    ), "Conditioned-air outlet and supply temperatures must track their targets"
    assert source.read_bytes() == original
    (tmp_path / "control-evidence.json").write_text(
        json.dumps(
            dict(
                system_kind=system_kind,
                active_timesteps=len(errors),
                no_heating_needed_timesteps=len(no_heat_rates),
                conditioned_air_tracking_timesteps=len(tracking_errors),
                maximum_compensation_error_k=max(errors),
                maximum_unneeded_heating_or_electricity_w=max(no_heat_rates),
                maximum_conditioned_air_tracking_error_k=max(tracking_errors),
            ),
            indent=2,
        )
        + "\n"
    )


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_relocated_native_conversion_bundle(sdk, tmp_path, host):
    from adapters.claude_code_adapter import ClaudeCodeAdapter
    from adapters.codex_adapter import CodexAdapter
    from adapters.contracts import HostAdapterConfig

    source, cfg, _ = conversion_fixture(sdk[0], tmp_path)
    adapter = (ClaudeCodeAdapter if host == "claude" else CodexAdapter)(
        HostAdapterConfig(
            host_name=host, workspace_root=Path.cwd(), runtime_mode="marketplace"
        )
    )
    exported = tmp_path / "export"
    adapter.export_plugin(exported, dry_run=False)
    bundle = next(exported.rglob("openstudio-coil-replacer/SKILL.md")).parent
    relocated = tmp_path / "relocated"
    shutil.copytree(bundle, relocated)
    shutil.rmtree(exported)
    config = tmp_path / "config.json"
    config.write_text(json.dumps(cfg))
    planned, applied = tmp_path / "plan.json", tmp_path / "apply.json"
    for args in (
        ["--input", str(source), "--config", str(config), "--report", str(planned)],
        ["--plan", str(planned), "--report", str(applied)],
    ):
        run = subprocess.run(
            [
                str(native_cli()),
                "execute_python_script",
                str(relocated / "scripts/replace_coil.py"),
                *args,
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert run.returncode == 0, run.stdout + run.stderr
    result = json.loads(applied.read_text())
    assert result["validation"]["ok"] and result["translation"]["ok"]
