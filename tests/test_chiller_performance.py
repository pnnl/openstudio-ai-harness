"""EIR chiller COP transactions preserve circuits, controls, references and sizing."""

import json
import re
from pathlib import Path
import sys

import pytest
from test_vav_preflight import sdk, SCRIPTS

sys.path.insert(0, str(SCRIPTS))
from common import chiller_edit as chillers, plant_create, model_transaction as tx

OPERATION = "edit_chiller_performance"


def fixture(o, folder, kind="AirCooled"):
    model = o.model.Model()
    planned = plant_create.plan(
        model,
        o,
        dict(
            output_model_path=str(folder / "unused.osm"),
            defaults_profile="prototype_plants_v1",
            chilled_water=dict(name="CHW", source=kind),
        ),
    )
    plant_create.create(model, o, planned)
    chiller = model.getChillerElectricEIRs()[0]
    chiller.setName("Selected Chiller")
    chiller.setReferenceCOP(4)
    chiller.additionalProperties().setFeature("review_note", "retain")
    source = folder / "source.osm"
    assert model.save(str(source), True)
    return source, model, chiller


def config(folder, cop=5):
    return dict(
        output_model_path=str(folder / "edited.osm"),
        plant_loop=dict(name="CHW"),
        chiller=dict(name="Selected Chiller"),
        settings=dict(reference_cop=cop),
    )


def preflight(source, cfg):
    return tx.preflight(source, cfg, OPERATION, chillers.plan)


def apply(report, folder, creator=None):
    path = folder / "reviewed.json"
    path.write_text(json.dumps(report))
    return tx.apply(
        path,
        OPERATION,
        chillers.plan,
        creator or chillers.edit,
        chillers.validate_model,
    )


@pytest.mark.parametrize("kind", ["AirCooled", "WaterCooled"])
def test_cop_edit_preserves_graph_curves_and_autosizing(sdk, tmp_path, kind):
    o = sdk[0]
    source, model, chiller = fixture(o, tmp_path, kind)
    before = source.read_bytes()
    metadata = str(chiller.additionalProperties().handle())
    curves = [
        chiller.coolingCapacityFunctionOfTemperature(),
        chiller.electricInputToCoolingOutputRatioFunctionOfTemperature(),
        chiller.electricInputToCoolingOutputRatioFunctionOfPLR(),
    ]
    raw = {str(x.handle()): str(x.idfObject()) for x in curves}
    report = preflight(source, config(tmp_path))
    assert report["ready"], report
    assert report == preflight(source, config(tmp_path))
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and result["translation"]["ok"], result
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    current = saved.getChillerElectricEIR(chiller.handle()).get()
    assert current.referenceCOP() == 5
    assert str(current.additionalProperties().handle()) == metadata
    assert current.isReferenceCapacityAutosized()
    assert chillers.connections(current) == chillers.connections(chiller)
    for handle, fields in raw.items():
        assert str(saved.getModelObject(o.toUUID(handle)).get().idfObject()) == fields
    assert source.read_bytes() == before


@pytest.mark.parametrize("cop", [0, -1, True, float("nan"), float("inf"), "5"])
def test_invalid_cop_rejects_without_output(sdk, tmp_path, cop):
    source, _, _ = fixture(sdk[0], tmp_path)
    with pytest.raises(ValueError, match="Invalid chiller performance"):
        preflight(source, config(tmp_path, cop))
    assert not (tmp_path / "edited.osm").exists()


def native_run(o, source, folder, chiller_handle, extra_outputs=()):
    import sqlite3
    import subprocess
    from test_supply_fan_performance import native_cli

    folder.mkdir()
    model = o.osversion.VersionTranslator().loadModel(str(source)).get()
    chiller = model.getChillerElectricEIR(o.toUUID(chiller_handle)).get()
    variables = [
        "Chiller Evaporator Cooling Energy",
        "Chiller Electricity Energy",
        "Chiller Part Load Ratio",
        "Chiller Evaporator Outlet Temperature",
        "Chiller Condenser Heat Transfer Energy",
        "Chiller Cycling Ratio",
        "Chiller False Load Heat Transfer Energy",
    ]
    for variable in variables:
        output = o.model.OutputVariable(variable, model)
        output.setKeyValue(chiller.nameString())
        output.setReportingFrequency("Hourly")
    for key, variable in extra_outputs:
        output = o.model.OutputVariable(variable, model)
        output.setKeyValue(key)
        output.setReportingFrequency("Hourly")
    auxiliary = {}
    condenser = chiller.secondaryPlantLoop()
    if condenser.is_initialized():
        for obj in condenser.get().supplyComponents():
            kind = obj.iddObjectType().valueName()
            variable = (
                "Pump Electricity Energy"
                if kind.startswith(("OS_Pump_", "OS_HeaderedPumps_"))
                else (
                    "Cooling Tower Fan Electricity Energy"
                    if kind.startswith("OS_CoolingTower_")
                    else None
                )
            )
            if variable:
                output = o.model.OutputVariable(variable, model)
                output.setKeyValue(obj.nameString())
                output.setReportingFrequency("Hourly")
                auxiliary[obj.nameString()] = dict(type=kind, variable=variable)
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
    assert "EnergyPlus Completed Successfully" in err and not re.search(
        r"\*\*\s*(?:Severe|Fatal)\s*\*\*", err, re.IGNORECASE
    ), err
    with sqlite3.connect(folder / "run/eplusout.sql") as sql:
        data = {}
        for variable in variables:
            rows = sql.execute(
                "SELECT t.EnvironmentPeriodIndex,t.SimulationDays,t.Hour,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE d.Name=? AND lower(d.KeyValue)=lower(?) AND t.WarmupFlag=0 ORDER BY t.TimeIndex",
                (variable, chiller.nameString()),
            ).fetchall()
            assert rows, variable
            data[variable] = rows
        sizes = sql.execute(
            "SELECT Description,Value FROM ComponentSizes WHERE lower(CompName)=lower(?)",
            (chiller.nameString(),),
        ).fetchall()
        extra_data = {}
        for key, variable in extra_outputs:
            rows = sql.execute(
                "SELECT t.EnvironmentPeriodIndex,t.SimulationDays,t.Hour,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE d.Name=? AND lower(d.KeyValue)=lower(?) AND t.WarmupFlag=0 ORDER BY t.TimeIndex",
                (variable, key),
            ).fetchall()
            assert rows, (key, variable)
            extra_data.setdefault(key, {})[variable] = rows
        for name, details in auxiliary.items():
            rows = sql.execute(
                "SELECT r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE d.Name=? AND lower(d.KeyValue)=lower(?) AND t.WarmupFlag=0",
                (details["variable"], name),
            ).fetchall()
            assert rows, (name, details)
            details["electricity_j"] = sum(row[0] for row in rows)
            details["sizes"] = sql.execute(
                "SELECT Description,Value FROM ComponentSizes WHERE lower(CompName)=lower(?)",
                (name,),
            ).fetchall()
    observed = dict(
        hours=len(data[variables[0]]),
        cooling_j=sum(x[3] for x in data[variables[0]]),
        electricity_j=sum(x[3] for x in data[variables[1]]),
        plr_range=[
            min(x[3] for x in data[variables[2]]),
            max(x[3] for x in data[variables[2]]),
        ],
        outlet_range_c=[
            min(x[3] for x in data[variables[3]]),
            max(x[3] for x in data[variables[3]]),
        ],
        condenser_heat_j=sum(x[3] for x in data[variables[4]]),
        cycling_range=[
            min(x[3] for x in data[variables[5]]),
            max(x[3] for x in data[variables[5]]),
        ],
        false_load_j=sum(x[3] for x in data[variables[6]]),
        sizes=sizes,
        warnings=err,
        condenser_equipment=auxiliary,
        extra_outputs=extra_data,
        condenser_auxiliary_electricity_j=sum(
            item["electricity_j"] for item in auxiliary.values()
        ),
    )
    observed["chiller_plus_condenser_auxiliary_electricity_j"] = (
        observed["electricity_j"] + observed["condenser_auxiliary_electricity_j"]
    )
    (folder / "hourly.json").write_text(json.dumps(data, indent=2))
    (folder / "observed.json").write_text(json.dumps(observed, indent=2))
    return observed


@pytest.mark.parametrize(
    "kind,autosized_condenser,rejection_fraction",
    [
        ("AirCooled", False, 1.0),
        ("WaterCooled", False, 0.8),
        ("WaterCooled", True, 0.8),
    ],
)
def test_native_cop_edit_cooling_electricity_and_sizing(
    sdk, tmp_path, kind, autosized_condenser, rejection_fraction
):
    source, model, chiller, original_fixture, original_bytes = native_fixture(
        sdk, tmp_path, kind, autosized_condenser, rejection_fraction
    )
    o = sdk[0]
    original = source.read_bytes()
    request = config(tmp_path)
    request.update(
        plant_loop=dict(name="Fixture CHW"), chiller=dict(name="Native Chiller")
    )
    report = preflight(source, request)
    assert report["ready"] and report["plan"]["simulation_ready"], report
    result = apply(report, tmp_path)
    before = native_run(o, source, tmp_path / "before_run", str(chiller.handle()))
    after = native_run(
        o,
        Path(result["output_model_path"]),
        tmp_path / "after_run",
        str(chiller.handle()),
    )
    assert before["hours"] == after["hours"] == 72
    assert before["cooling_j"] > 1e8
    assert after["cooling_j"] == pytest.approx(before["cooling_j"], rel=1e-4)
    assert after["electricity_j"] < before["electricity_j"]
    if not autosized_condenser:
        assert after["electricity_j"] / before["electricity_j"] == pytest.approx(
            4 / 5, rel=1e-4
        )
    before_sizes, after_sizes = dict(before["sizes"]), dict(after["sizes"])
    if kind == "WaterCooled":
        key = "Design Size Reference Condenser Fluid Flow Rate"
        fraction = chiller.fractionofCompressorElectricConsumptionRejectedbyCondenser()
        before_cop = report["plan"]["before_values"]["reference_cop"]
        after_cop = report["plan"]["after_values"]["reference_cop"]
        assert after_sizes.pop(key) / before_sizes.pop(key) == pytest.approx(
            (1 + fraction / after_cop) / (1 + fraction / before_cop), rel=1e-6
        )
    assert after_sizes == before_sizes
    if autosized_condenser:
        impact = report["plan"]["impact"]["condenser_sizing"]
        assert impact["reference_condenser_flow_autosized"]
        assert len(impact["autosized_equipment"]) == 2
        for name, before_equipment in before["condenser_equipment"].items():
            after_equipment = after["condenser_equipment"][name]
            old = dict(before_equipment["sizes"])
            new = dict(after_equipment["sizes"])
            assert old.keys() == new.keys()
            assert any(new[key] < value for key, value in old.items())
            assert after_equipment["electricity_j"] < before_equipment["electricity_j"]
    assert (
        source.read_bytes() == original
        and original_fixture.read_bytes() == original_bytes
    )
    (tmp_path / "native_evidence.json").write_text(
        json.dumps(
            dict(
                kind=kind,
                autosized_condenser=autosized_condenser,
                compressor_heat_rejection_fraction=rejection_fraction,
                before=before,
                after=after,
                source_unchanged=True,
                validation=result["validation"],
                translation=result["translation"],
            ),
            indent=2,
        )
    )


@pytest.mark.parametrize("missing", ["plant_loop", "chiller", "settings"])
def test_missing_choices_stay_unready(sdk, tmp_path, missing):
    source, _, _ = fixture(sdk[0], tmp_path)
    cfg = config(tmp_path)
    cfg.pop(missing)
    report = preflight(source, cfg)
    assert not report["ready"] and not report["plan"]["simulation_ready"]
    assert missing in report["plan"]["missing_inputs"]


@pytest.mark.parametrize(
    "case",
    [
        "noop",
        "unknown_loop",
        "unknown_chiller",
        "heating",
        "condenser",
        "reformulated",
        "detached",
        "thermosiphon",
        "evaporative",
        "heat_recovery",
    ],
)
def test_scope_and_inventory_agree(sdk, tmp_path, case):
    o = sdk[0]
    source, model, chiller = fixture(
        o, tmp_path, "WaterCooled" if case == "heat_recovery" else "AirCooled"
    )
    loop = model.getPlantLoopByName("CHW").get()
    cfg = config(tmp_path)
    if case == "noop":
        cfg["settings"]["reference_cop"] = 4
    elif case == "unknown_loop":
        cfg["plant_loop"] = dict(name="absent")
    elif case == "unknown_chiller":
        cfg["chiller"] = dict(name="absent")
    elif case in ("heating", "condenser"):
        loop.sizingPlant().setLoopType(case.title())
    elif case == "reformulated":
        other = o.model.ChillerElectricReformulatedEIR(model)
        other.setName("Other Chiller")
        assert loop.addSupplyBranchForComponent(other)
        cfg["chiller"] = dict(name="Other Chiller")
    elif case == "detached":
        assert loop.removeSupplyBranchWithComponent(chiller)
    elif case == "thermosiphon":
        assert chiller.setThermosiphonCapacityFractionCurve(
            o.model.CurveQuadratic(model)
        )
    elif case == "evaporative":
        assert chiller.setCondenserType("EvaporativelyCooled")
    elif case == "heat_recovery":
        assert o.model.PlantLoop(model).addDemandBranchForComponent(chiller)
        assert chiller.heatRecoveryLoop().is_initialized()
    assert model.save(str(source), True)
    report = preflight(source, cfg)
    assert not report["ready"], report
    if case in (
        "heating",
        "condenser",
        "reformulated",
        "thermosiphon",
        "evaporative",
        "heat_recovery",
    ):
        candidates = next(
            x["chillers"]
            for x in chillers.inventory(model)["plant_loops"]
            if x["name"] == "CHW"
        )
        assert not next(x for x in candidates if x["name"] == cfg["chiller"]["name"])[
            "supported"
        ]
    assert not (tmp_path / "edited.osm").exists()


@pytest.mark.parametrize(
    "kind,missing",
    [
        ("AirCooled", "pump"),
        ("AirCooled", "setpoint"),
        ("WaterCooled", "condenser_pump"),
        ("WaterCooled", "condenser_setpoint"),
        ("WaterCooled", "heat_rejection"),
        ("WaterCooled", "condenser_loop"),
    ],
)
def test_incomplete_existing_plants_warn_without_blocking_edit(
    sdk, tmp_path, kind, missing
):
    o = sdk[0]
    source, model, chiller = fixture(o, tmp_path, kind)
    condenser = chiller.secondaryPlantLoop()
    loop = (
        condenser.get()
        if missing.startswith("condenser_") or missing == "heat_rejection"
        else model.getPlantLoopByName("CHW").get()
    )
    if missing.endswith("pump"):
        for obj in list(loop.supplyComponents()):
            if (
                obj.iddObjectType()
                .valueName()
                .startswith(("OS_Pump_", "OS_HeaderedPumps_"))
            ):
                obj.remove()
    elif missing.endswith("setpoint"):
        for manager in list(loop.supplyOutletNode().setpointManagers()):
            manager.remove()
    elif missing == "heat_rejection":
        for obj in list(model.getCoolingTowerSingleSpeeds()):
            obj.remove()
        for obj in list(model.getCoolingTowerVariableSpeeds()):
            obj.remove()
        for obj in list(model.getCoolingTowerTwoSpeeds()):
            obj.remove()
    else:
        assert loop.removeDemandBranchWithComponent(chiller)
        # The SDK may reset condenser type during detachment. Preserve the explicit
        # water-cooled input as a malformed imported model, without repairing it.
        index = chiller.iddObject().getFieldIndex("Condenser Type").get()
        assert chiller.setString(index, "WaterCooled")
    assert model.save(str(source), True)
    report = preflight(source, config(tmp_path))
    assert report["ready"] and not report["plan"]["simulation_ready"], report
    assert report["warnings"]
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and not result["simulation_ready"]


@pytest.mark.parametrize(
    "mutation",
    [
        "cop",
        "capacity",
        "flow",
        "plr",
        "curve",
        "metadata",
        "condenser_type",
        "pump",
        "sizing",
        "dispatch",
        "ports",
        "new_object",
        "condenser_pump",
    ],
)
def test_unrequested_side_effects_never_publish(sdk, tmp_path, mutation):
    o = sdk[0]
    source, _, _ = fixture(o, tmp_path, "WaterCooled")
    report = preflight(source, config(tmp_path))
    assert report["ready"]

    def changed(model, sdk, planned):
        result = chillers.edit(model, sdk, planned)
        c = chillers.chiller_object(model, sdk, planned["resolved_objects"]["chiller"])
        if mutation == "cop":
            c.setReferenceCOP(3)
        elif mutation == "capacity":
            c.setReferenceCapacity(12345)
        elif mutation == "flow":
            c.setReferenceChilledWaterFlowRate(0.001)
        elif mutation == "plr":
            c.setMinimumPartLoadRatio(0.2)
        elif mutation == "curve":
            c.coolingCapacityFunctionOfTemperature().to_CurveBiquadratic().get().setCoefficient1Constant(
                0.5
            )
        elif mutation == "metadata":
            c.additionalProperties().setFeature("review_note", "changed")
        elif mutation == "condenser_type":
            assert c.setString(
                c.iddObject().getFieldIndex("Condenser Type").get(), "AirCooled"
            )
        elif mutation in ("pump", "condenser_pump"):
            loop = (
                c.secondaryPlantLoop().get()
                if mutation == "condenser_pump"
                else c.plantLoop().get()
            )
            for obj in loop.supplyComponents():
                if obj.to_PumpVariableSpeed().is_initialized():
                    obj.to_PumpVariableSpeed().get().setRatedPumpHead(999)
                if obj.to_PumpConstantSpeed().is_initialized():
                    obj.to_PumpConstantSpeed().get().setRatedPumpHead(999)
        elif mutation == "sizing":
            c.plantLoop().get().sizingPlant().setLoopDesignTemperatureDifference(15)
        elif mutation == "dispatch":
            c.plantLoop().get().setLoadDistributionScheme("SequentialLoad")
        elif mutation == "ports":
            model.disconnect(c, c.supplyInletPort())
        else:
            o.model.ChillerElectricEIR(model)
        return result

    with pytest.raises(ValueError):
        apply(report, tmp_path, changed)
    assert not (tmp_path / "edited.osm").exists()


@pytest.mark.parametrize("mode", ["stale", "tampered"])
def test_exact_source_and_review_checks_remain(sdk, tmp_path, mode):
    source, _, _ = fixture(sdk[0], tmp_path)
    report = preflight(source, config(tmp_path))
    if mode == "stale":
        source.write_bytes(source.read_bytes() + b"\n! changed\n")
    else:
        report["plan"]["parameters"]["settings"]["reference_cop"] = 7
    with pytest.raises(ValueError):
        apply(report, tmp_path)
    assert not (tmp_path / "edited.osm").exists()


@pytest.mark.parametrize("weather", [False, True])
def test_combined_readiness_is_explicit_and_checks_companions(sdk, tmp_path, weather):
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
    assert report["plan"]["simulation_readiness_scope"] == "operation_and_companions"
    assert report["plan"]["simulation_ready"] is weather
    assert apply(report, tmp_path)["simulation_ready"] is weather


def test_fixed_sizing_other_chiller_references_and_metadata_are_preserved(
    sdk, tmp_path
):
    o = sdk[0]
    source, model, chiller = fixture(o, tmp_path, "WaterCooled")
    chiller.setReferenceCapacity(50000)
    chiller.setReferenceChilledWaterFlowRate(0.002)
    chiller.setReferenceCondenserFluidFlowRate(0.003)
    other = o.model.ChillerElectricEIR(model)
    other.setName("Other Chiller")
    assert chiller.plantLoop().get().addSupplyBranchForComponent(other)
    actuator = o.model.EnergyManagementSystemActuator(
        chiller, "Plant Component Chiller:Electric:EIR", "On/Off Supervisory"
    )
    cost = o.model.LifeCycleCost.createLifeCycleCost(
        "Chiller cost", chiller, 500, "CostPerEach", "Construction", 20
    ).get()
    output = o.model.OutputVariable("Chiller Electricity Energy", model)
    output.setKeyValue(chiller.nameString())
    protected = {
        str(x.handle()): str(x.idfObject()) for x in (other, actuator, cost, output)
    }
    model.save(str(source), True)
    report = preflight(source, config(tmp_path))
    assert report["plan"]["impact"]["ems_actuator_count"] == 1
    assert report["plan"]["impact"]["supply_chiller_count"] == 2
    result = apply(report, tmp_path)
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    current = saved.getChillerElectricEIR(chiller.handle()).get()
    assert (
        current.referenceCapacity().get() == 50000
        and not current.isReferenceCapacityAutosized()
    )
    assert current.referenceChilledWaterFlowRate().get() == 0.002
    assert current.referenceCondenserFluidFlowRate().get() == 0.003
    for handle, raw in protected.items():
        assert str(saved.getModelObject(o.toUUID(handle)).get().idfObject()) == raw


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
    model.getPlantLoopByName("CHW").get().addDemandBranchForComponent(load)
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
@pytest.mark.parametrize("capacity", [False, True])
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
    skill = next(
        exported.rglob("openstudio-chiller-performance-editor/SKILL.md")
    ).parent
    for relative in [
        "scripts/doctor.py",
        "scripts/sdk_probe.py",
        "scripts/prepare_model.py",
        "references/model_preparation.md",
        "references/chiller_performance.md",
        "references/chiller_performance.schema.json",
    ]:
        assert (skill / relative).is_file()
    skill = copy_plugin_for_skill(skill, tmp_path / "relocated")
    shutil.rmtree(exported)
    cfg = tmp_path / "request.json"
    request = config(tmp_path)
    if capacity:
        request["settings"] = dict(reference_capacity_w=60000)
    cfg.write_text(json.dumps(request))
    plan = tmp_path / "reviewed.json"
    repeated = tmp_path / "repeated.json"
    script = skill / "scripts/edit_chiller_performance.py"
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


@pytest.mark.parametrize(
    "cop,unusual",
    [(0.6, True), (1.99, True), (2, False), (10, False), (10.01, True), (35, True)],
)
def test_unusual_cop_warns_without_changing_explicit_value(sdk, tmp_path, cop, unusual):
    o = sdk[0]
    source, model, _ = fixture(o, tmp_path)
    cfg = config(tmp_path, cop)
    planned = chillers.plan(model, o, cfg)
    assert planned["ready"] and planned["simulation_ready"]
    warnings = " ".join(planned["warnings"])
    assert ("typical review range" in warnings) is unusual
    if unusual:
        assert "COP = 3.517 / (kW per ton)" in warnings
        assert "COP = EER / 3.412" in warnings
    result = apply(preflight(source, cfg), tmp_path)
    assert result["validation"]["ok"]
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    assert saved.getChillerElectricEIRs()[0].referenceCOP() == cop


@pytest.mark.parametrize("mode", ["prototype", "fixed", "flow_only", "equipment_only"])
def test_condenser_autosizing_impact_identifies_pump_and_tower(sdk, tmp_path, mode):
    o = sdk[0]
    source, model, chiller = fixture(o, tmp_path, "WaterCooled")
    condenser = chiller.secondaryPlantLoop().get()
    original_sizing = chillers.condenser_sizing(chiller, condenser)
    if mode in ("fixed", "equipment_only"):
        chiller.setReferenceCondenserFluidFlowRate(0.005)
    if mode in ("fixed", "flow_only"):
        for entry in original_sizing["autosized_equipment"]:
            obj = model.getModelObject(o.toUUID(entry["handle"])).get()
            for field in entry["sizing_fields"]:
                assert obj.setDouble(
                    obj.iddObject().getFieldIndex(field["field"]).get(), 1
                )
    model.save(str(source), True)
    original = source.read_bytes()
    report = preflight(source, config(tmp_path))
    assert report["ready"]
    impact = report["plan"]["impact"]["condenser_sizing"]
    assert impact["reference_condenser_flow_autosized"] is (
        mode in ("prototype", "flow_only")
    )
    equipment = impact["autosized_equipment"]
    if mode in ("prototype", "equipment_only"):
        assert {x["type"] for x in equipment} == {
            "OS_CoolingTower_VariableSpeed",
            "OS_Pump_ConstantSpeed",
        }
        assert {x["handle"] for x in equipment} == {
            x["handle"] for x in original_sizing["autosized_equipment"]
        }
        assert all(x["sizing_fields"] for x in equipment)
    else:
        assert equipment == []
    warnings = " ".join(report["warnings"])
    assert ("Condenser flow is autosized" in warnings) is (
        mode in ("prototype", "flow_only")
    )
    assert (
        "condenser equipment" in warnings or "condenser pumps" in warnings.lower()
    ) is (mode != "fixed")
    result = apply(report, tmp_path)
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    current = saved.getChillerElectricEIR(chiller.handle()).get()
    assert (
        chillers.condenser_sizing(current, current.secondaryPlantLoop().get()) == impact
    )
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    "problem",
    [
        "cop",
        "capacity",
        "capacity_text",
        "capacity_empty",
        "capacity_curve",
        "eir_temperature_curve",
        "eir_plr_curve",
    ],
)
def test_source_translation_problems_are_plan_errors_without_failure_capture(
    sdk, tmp_path, monkeypatch, problem
):
    o = sdk[0]
    source, _, _ = fixture(o, tmp_path)
    original = source.read_bytes()
    translate = chillers.translated_workspace

    def altered(model, sdk, label):
        workspace = translate(model, sdk, label)
        obj = workspace.getObjectsByType(sdk.IddObjectType("Chiller_Electric_EIR"))[0]
        field = {
            "cop": "Reference COP",
            "capacity": "Reference Capacity",
            "capacity_text": "Reference Capacity",
            "capacity_empty": "Reference Capacity",
            "capacity_curve": "Cooling Capacity Function of Temperature Curve Name",
            "eir_temperature_curve": "Electric Input to Cooling Output Ratio Function of Temperature Curve Name",
            "eir_plr_curve": "Electric Input to Cooling Output Ratio Function of Part Load Ratio Curve Name",
        }[problem]
        index = obj.iddObject().getFieldIndex(field).get()
        if problem in ("cop", "capacity"):
            assert obj.setDouble(index, 8)
        elif problem == "capacity_text":
            assert obj.setString(index, "not-a-number")
        else:
            assert obj.setString(index, "")
        return workspace

    monkeypatch.setattr(chillers, "translated_workspace", altered)
    captured = []
    monkeypatch.setattr(
        tx, "capture_exception", lambda *args, **kwargs: captured.append(args) or {}
    )
    cfg = tmp_path / "request.json"
    request = config(tmp_path)
    if problem in ("capacity", "capacity_text", "capacity_empty"):
        request["settings"] = dict(reference_capacity_w=60000)
    cfg.write_text(json.dumps(request))
    output = tmp_path / "blocked.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "edit_chiller_performance.py",
            "--input",
            str(source),
            "--config",
            str(cfg),
            "--report",
            str(output),
        ],
    )
    assert (
        tx.cli(
            OPERATION,
            chillers.plan,
            chillers.edit,
            chillers.validate_model,
            chillers.inventory,
        )
        == 2
    )
    report = json.loads(output.read_text())
    assert (
        not report["ok"]
        and not report["ready"]
        and not report["plan"]["simulation_ready"]
    )
    expected = (
        "Reference Capacity is not"
        if problem in ("capacity_text", "capacity_empty")
        else (
            "COP disagrees"
            if problem in ("cop", "capacity")
            else "curves do not survive"
        )
    )
    assert expected in " ".join(report["plan"]["errors"])
    assert captured == []
    assert source.read_bytes() == original
    assert not (tmp_path / "edited.osm").exists()


@pytest.mark.parametrize(
    "pump_class",
    [
        "PumpConstantSpeed",
        "PumpVariableSpeed",
        "HeaderedPumpsConstantSpeed",
        "HeaderedPumpsVariableSpeed",
    ],
)
def test_defaulted_pump_autosizing_is_listed(sdk, tmp_path, pump_class):
    o = sdk[0]
    _, model, chiller = fixture(o, tmp_path, "WaterCooled")
    condenser = chiller.secondaryPlantLoop().get()
    pump = getattr(o.model, pump_class)(model)
    assert pump.addToNode(condenser.supplyInletNode())
    impact = chillers.condenser_sizing(chiller, condenser)
    item = next(
        x for x in impact["autosized_equipment"] if x["handle"] == str(pump.handle())
    )
    fields = {x["field"] for x in item["sizing_fields"]}
    assert "Rated Power Consumption" in fields
    assert (
        "Total Rated Flow Rate"
        if pump_class.startswith("Headered")
        else "Rated Flow Rate"
    ) in fields
    if pump_class == "PumpVariableSpeed":
        index = pump.iddObject().getFieldIndex("Rated Flow Rate").get()
        assert pump.getString(index).get() == ""
        assert pump.isRatedFlowRateAutosized()


def native_fixture(
    sdk, tmp_path, kind="AirCooled", autosized_condenser=False, rejection_fraction=0.8
):
    from vav_fixture import prepare_vav_fixture
    from test_supply_fan_performance import native_cli
    from common import vav_create, vav_plan

    native_cli()
    o = sdk[0]
    unserved, cfg, original_fixture, original_bytes = prepare_vav_fixture(
        o, tmp_path, True
    )
    model = o.osversion.VersionTranslator().loadModel(str(unserved)).get()
    from common.hvac_inventory import inventory as model_inventory

    planned = vav_plan.plan(cfg, model_inventory(model), unserved)
    assert planned["ready"], planned
    vav_create.create(model, o, planned)
    loop = model.getPlantLoopByName("Fixture CHW").get()
    model.getDistrictCoolings()[0].remove()
    chiller = o.model.ChillerElectricEIR(model)
    chiller.setName("Native Chiller")
    chiller.setReferenceCOP(4)
    assert chiller.setFractionofCompressorElectricConsumptionRejectedbyCondenser(
        rejection_fraction
    )
    if kind == "AirCooled":
        assert chiller.setCondenserType(kind)
    chiller.setReferenceLeavingChilledWaterTemperature(6.666667)
    chiller.setChillerFlowMode("LeavingSetpointModulated")
    chiller.autosizeReferenceCapacity()
    chiller.autosizeReferenceChilledWaterFlowRate()
    assert loop.addSupplyBranchForComponent(chiller)
    supply_temperature = o.model.ScheduleConstant(model)
    supply_temperature.setValue(6.666667)
    assert o.model.SetpointManagerScheduled(model, supply_temperature).addToNode(
        chiller.supplyOutletModelObject().get().to_Node().get()
    )
    if kind == "WaterCooled":
        condenser = o.model.PlantLoop(model)
        condenser.setName("Native Condenser")
        condenser.sizingPlant().setLoopType("Condenser")
        condenser.sizingPlant().setDesignLoopExitTemperature(29)
        condenser.sizingPlant().setLoopDesignTemperatureDifference(5)
        pump = o.model.PumpVariableSpeed(model)
        assert pump.addToNode(condenser.supplyInletNode())
        if autosized_condenser:
            source = o.model.CoolingTowerVariableSpeed(model)
            source.setDesignRangeTemperature(5)
            source.setDesignApproachTemperature(3.4)
        else:
            source = o.model.CoolingTowerSingleSpeed(model)
            assert source.setPerformanceInputMethod(
                "UFactorTimesAreaAndDesignWaterFlowRate"
            )
            source.setUFactorTimesAreaValueatDesignAirFlowRate(10000)
            source.setUFactorTimesAreaValueatFreeConvectionAirFlowRate(0)
            source.setDesignWaterFlowRate(0.005)
            source.setDesignAirFlowRate(10)
            source.setFanPoweratDesignAirFlowRate(500)
        assert condenser.addSupplyBranchForComponent(source)
        assert condenser.addDemandBranchForComponent(chiller)
        for side in ("Supply", "Demand"):
            assert getattr(condenser, "add" + side + "BranchForComponent")(
                o.model.PipeAdiabatic(model)
            )
        schedule = o.model.ScheduleConstant(model)
        schedule.setValue(29)
        assert o.model.SetpointManagerScheduled(model, schedule).addToNode(
            condenser.supplyOutletNode()
        )
        assert chiller.setCondenserType("WaterCooled")
        if autosized_condenser:
            chiller.autosizeReferenceCondenserFluidFlowRate()
        else:
            chiller.setReferenceCondenserFluidFlowRate(0.005)
    source = tmp_path / "before.osm"
    assert model.save(str(source), True)
    return source, model, chiller, original_fixture, original_bytes


@pytest.mark.parametrize("kind", ["AirCooled", "WaterCooled"])
@pytest.mark.parametrize("capacity", [60000, "Autosize"])
@pytest.mark.parametrize("with_cop", [False, True])
def test_reference_capacity_edit_preserves_graph(
    sdk, tmp_path, kind, capacity, with_cop
):
    o = sdk[0]
    source, model, chiller = fixture(o, tmp_path, kind)
    chiller.setReferenceCapacity(100000)
    model.save(str(source), True)
    original = source.read_bytes()
    cfg = config(tmp_path)
    cfg["settings"] = dict(reference_capacity_w=capacity)
    if with_cop:
        cfg["settings"]["reference_cop"] = 5
    report = preflight(source, cfg)
    assert report["ready"], report
    assert report == preflight(source, cfg)
    plan = report["plan"]
    assert plan["impact"]["reference_capacity_w"] == 100000
    assert plan["impact"]["capacity_edit"]["after_w"] == capacity
    assert plan["parameters"]["settings"] == cfg["settings"]
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and result["translation"]["ok"]
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    current = saved.getChillerElectricEIR(chiller.handle()).get()
    assert chillers.sized(current, "ReferenceCapacity") == capacity
    assert current.referenceCOP() == (5 if with_cop else 4)
    assert chillers.connections(current) == chillers.connections(chiller)
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    "capacity",
    [0, -1, True, float("nan"), float("inf"), "60000", "Autocalculate", None],
)
def test_invalid_reference_capacity(sdk, tmp_path, capacity):
    source, _, _ = fixture(sdk[0], tmp_path)
    cfg = config(tmp_path)
    cfg["settings"] = dict(reference_capacity_w=capacity)
    with pytest.raises(ValueError, match="Invalid chiller performance"):
        preflight(source, cfg)
    assert not (tmp_path / "edited.osm").exists()


@pytest.mark.parametrize("capacity", [100000, "Autosize"])
def test_capacity_noop_rejected(sdk, tmp_path, capacity):
    source, model, chiller = fixture(sdk[0], tmp_path)
    if capacity != "Autosize":
        chiller.setReferenceCapacity(capacity)
    model.save(str(source), True)
    cfg = config(tmp_path)
    cfg["settings"] = dict(reference_capacity_w=capacity)
    report = preflight(source, cfg)
    assert not report["ready"] and "must change" in " ".join(report["plan"]["errors"])


def test_capacity_other_chillers_bounded(sdk, tmp_path):
    o = sdk[0]
    source, model, chiller = fixture(o, tmp_path)
    loop = chiller.plantLoop().get()
    for i in range(10):
        other = o.model.ChillerElectricEIR(model)
        other.setName(f"Other {i:02}")
        other.setSizingFactor(0.5)
        if i % 2 == 0:
            other.setReferenceCapacity(50000)
        loop.addSupplyBranchForComponent(other)
    model.save(str(source), True)
    cfg = config(tmp_path)
    cfg["settings"] = dict(reference_capacity_w=60000)
    report = preflight(source, cfg)
    assert report["ready"], report
    impact = report["plan"]["impact"]["capacity_edit"]
    assert impact["other_chiller_count"] == 10
    assert (
        len(impact["other_chillers"]) == 8
        and impact["omitted_other_chiller_count"] == 2
    )
    assert {x["sizing_factor"] for x in impact["other_chillers"]} == {0.5}
    assert {x["reference_capacity_w"] for x in impact["other_chillers"]} == {
        50000,
        "Autosize",
    }


@pytest.mark.parametrize("field", ["cop", "flow", "factor", "curve", "capacity"])
def test_capacity_unrequested_changes_fail_validation(sdk, tmp_path, field):
    source, _, _ = fixture(sdk[0], tmp_path)
    cfg = config(tmp_path)
    cfg["settings"] = dict(reference_capacity_w=60000)
    report = preflight(source, cfg)

    def changed(model, o, planned):
        result = chillers.edit(model, o, planned)
        obj = chillers.chiller_object(model, o, planned["resolved_objects"]["chiller"])
        if field == "cop":
            obj.setReferenceCOP(9)
        elif field == "flow":
            obj.setReferenceChilledWaterFlowRate(0.01)
        elif field == "factor":
            obj.setSizingFactor(0.5)
        elif field == "curve":
            obj.coolingCapacityFunctionOfTemperature().setName("Changed Curve")
        else:
            obj.setReferenceCapacity(70000)
        return result

    with pytest.raises(ValueError, match="validation"):
        apply(report, tmp_path, changed)
    assert not (tmp_path / "edited.osm").exists()


@pytest.mark.parametrize(
    "kind,capacity",
    [
        ("AirCooled", 100000),
        ("AirCooled", "Autosize"),
        ("WaterCooled", 100000),
        ("AirCooled", 1000),
    ],
)
def test_native_reference_capacity_part_load_and_sizing(sdk, tmp_path, kind, capacity):
    o = sdk[0]
    source, model, chiller, _, _ = native_fixture(
        sdk, tmp_path, kind, kind == "WaterCooled"
    )
    chiller.setReferenceCapacity(200000)
    if capacity == 1000:
        chiller.setChillerFlowMode("ConstantFlow")
    assert model.save(str(source), True)
    original = source.read_bytes()
    request = config(tmp_path)
    request.update(
        plant_loop=dict(name="Fixture CHW"),
        chiller=dict(name="Native Chiller"),
        settings=dict(reference_capacity_w=capacity),
    )
    report = preflight(source, request)
    assert report["ready"] and report["plan"]["simulation_ready"], report
    result = apply(report, tmp_path)
    before = native_run(o, source, tmp_path / "before_run", str(chiller.handle()))
    after = native_run(
        o,
        Path(result["output_model_path"]),
        tmp_path / "after_run",
        str(chiller.handle()),
    )
    assert before["hours"] == after["hours"] == 72
    assert before["cooling_j"] > 1e8
    assert after["cooling_j"] > 0
    # Capacity changes can change delivered cooling; this is not a savings test.
    if capacity == 1000:
        assert after["cooling_j"] < before["cooling_j"]
        assert after["outlet_range_c"][1] > 6.666667 + 1
    else:
        assert after["outlet_range_c"] == pytest.approx([6.666667, 6.666667], abs=1e-5)
    assert after["plr_range"][1] > before["plr_range"][1]
    old_sizes, new_sizes = dict(before["sizes"]), dict(after["sizes"])
    assert old_sizes["User-Specified Reference Capacity"] == 200000
    if capacity == "Autosize":
        actual = new_sizes["Design Size Reference Capacity"]
        assert 10000 < actual < 200000
    else:
        actual = new_sizes["User-Specified Reference Capacity"]
        assert actual == capacity
    assert new_sizes["Design Size Reference Chilled Water Flow Rate"] == pytest.approx(
        old_sizes["Design Size Reference Chilled Water Flow Rate"], rel=1e-6
    )
    if kind == "WaterCooled":
        key = "Design Size Reference Condenser Fluid Flow Rate"
        assert new_sizes[key] / old_sizes[key] == pytest.approx(
            actual / 200000, rel=1e-6
        )
        for name, old in before["condenser_equipment"].items():
            new = after["condenser_equipment"][name]
            assert any(dict(new["sizes"])[key] < value for key, value in old["sizes"])
    assert source.read_bytes() == original
    (tmp_path / "native_capacity_evidence.json").write_text(
        json.dumps(
            dict(
                kind=kind,
                requested_capacity_w=capacity,
                before=before,
                after=after,
                validation=result["validation"],
                translation=result["translation"],
                source_unchanged=True,
            ),
            indent=2,
        )
    )


@pytest.mark.parametrize("fixed_flow", [False, True])
def test_native_capacity_autosize_basis(sdk, tmp_path, fixed_flow):
    import sqlite3

    o = sdk[0]
    source, model, chiller, _, _ = native_fixture(sdk, tmp_path)
    chiller.setReferenceCapacity(200000)
    loop = chiller.plantLoop().get()
    if fixed_flow:
        chiller.setReferenceChilledWaterFlowRate(0.004)
        chiller.setSizingFactor(0.5)
    else:
        other = chiller.clone(model).to_ChillerElectricEIR().get()
        other.setName("Second Chiller")
        other.autosizeReferenceCapacity()
        other.setSizingFactor(1)
        assert loop.addSupplyBranchForComponent(other)
    assert model.save(str(source), True)
    cfg = config(tmp_path)
    cfg.update(
        plant_loop=dict(name="Fixture CHW"),
        chiller=dict(name="Native Chiller"),
        settings=dict(reference_capacity_w="Autosize"),
    )
    report = preflight(source, cfg)
    assert report["ready"] and report["plan"]["simulation_ready"], report
    basis = report["plan"]["impact"]["capacity_edit"]["autosize_flow_basis"]
    assert basis == (
        "retained_fixed_evaporator_flow"
        if fixed_flow
        else "plant_design_flow_times_sizing_factor"
    )
    result = apply(report, tmp_path)
    observed = native_run(
        o,
        Path(result["output_model_path"]),
        tmp_path / "after_run",
        str(chiller.handle()),
    )
    capacity = dict(observed["sizes"])["Design Size Reference Capacity"]
    evidence = dict(fixed_evaporator_flow=fixed_flow, basis=basis, observed=observed)
    if fixed_flow:
        expected = (
            0.004 * 4180 * 1000 * loop.sizingPlant().loopDesignTemperatureDifference()
        )
        assert capacity == pytest.approx(expected, rel=0.01)
        evidence["approximate_fluid_property_capacity_w"] = expected
    else:
        with sqlite3.connect(tmp_path / "after_run/run/eplusout.sql") as sql:
            other_capacity = sql.execute(
                "SELECT Value FROM ComponentSizes WHERE lower(CompName)=lower(?) AND Description=?",
                ("Second Chiller", "Design Size Reference Capacity"),
            ).fetchone()[0]
        assert capacity == pytest.approx(other_capacity, rel=1e-6)
        assert capacity > 10000
        evidence["other_capacity_w"] = other_capacity
    (tmp_path / "native_capacity_basis_evidence.json").write_text(
        json.dumps(evidence, indent=2)
    )


@pytest.mark.parametrize("mode", ["stale", "tampered"])
def test_reference_capacity_exact_source_and_plan_checks(sdk, tmp_path, mode):
    source, _, _ = fixture(sdk[0], tmp_path)
    request = config(tmp_path)
    request["settings"] = dict(reference_capacity_w=60000)
    report = preflight(source, request)
    if mode == "stale":
        source.write_bytes(source.read_bytes() + b"\n! changed\n")
    else:
        report["plan"]["parameters"]["settings"]["reference_capacity_w"] = 70000
    with pytest.raises(ValueError):
        apply(report, tmp_path)
    assert not (tmp_path / "edited.osm").exists()


@pytest.mark.parametrize("kind", ["AirCooled", "WaterCooled"])
@pytest.mark.parametrize(
    "before,after", [(50000, 100000), ("Autosize", 100000), (50000, "Autosize")]
)
@pytest.mark.parametrize("ratio", [0, 0.02])
def test_capacity_condenser_fan_scaling_is_reviewed(
    sdk, tmp_path, kind, before, after, ratio
):
    o = sdk[0]
    source, model, chiller = fixture(o, tmp_path, kind)
    if before != "Autosize":
        chiller.setReferenceCapacity(before)
    assert chiller.setCondenserFanPowerRatio(ratio)
    assert model.save(str(source), True)
    original = source.read_bytes()
    cfg = config(tmp_path)
    cfg["settings"] = dict(reference_capacity_w=after)
    report = preflight(source, cfg)
    assert report["ready"], report
    assert report == preflight(source, cfg)
    warnings = " ".join(report["warnings"])
    assert ("condenser fan power ratio is positive" in warnings) is (ratio > 0)
    impact = report["plan"]["impact"]["capacity_edit"]
    if ratio:
        assert impact["condenser_fan"] == dict(
            power_ratio=ratio,
            before_full_cycling_w=(
                before * ratio
                if isinstance(before, (int, float))
                else "Requires sizing"
            ),
            after_full_cycling_w=(
                after * ratio if isinstance(after, (int, float)) else "Requires sizing"
            ),
        )
        assert "including WaterCooled" in warnings
    else:
        assert "condenser_fan" not in impact
    assert apply(report, tmp_path)["validation"]["ok"]
    assert source.read_bytes() == original


@pytest.mark.parametrize("capacity", [100000, "Autosize"])
def test_capacity_dispatch_numbers_exclude_temperature_curve(sdk, tmp_path, capacity):
    o = sdk[0]
    source, model, chiller = fixture(o, tmp_path)
    chiller.setReferenceCapacity(50000)
    chiller.setMinimumPartLoadRatio(0.1)
    chiller.setMaximumPartLoadRatio(1.1)
    chiller.setOptimumPartLoadRatio(0.7)
    curve = chiller.coolingCapacityFunctionOfTemperature().to_CurveBiquadratic().get()
    curve.setCoefficient1Constant(0.8)
    assert model.save(str(source), True)
    cfg = config(tmp_path)
    cfg["settings"] = dict(reference_capacity_w=capacity)
    report = preflight(source, cfg)
    assert report["ready"], report
    impact = report["plan"]["impact"]["capacity_edit"]
    assert impact["dispatch_load_limits_w"] == {
        key: (
            capacity * fraction
            if isinstance(capacity, (int, float))
            else "Requires sizing"
        )
        for key, fraction in [("minimum", 0.1), ("maximum", 1.1), ("optimal", 0.7)]
    }
    assert impact["dispatch_limits_exclude_temperature_curve"] is True
    assert (
        impact["load_distribution_scheme"]
        == chiller.plantLoop().get().loadDistributionScheme()
    )
    assert apply(report, tmp_path)["validation"]["ok"]


def test_native_condenser_fan_scales_with_capacity_at_equal_cooling(sdk, tmp_path):
    o = sdk[0]
    source, model, chiller, _, _ = native_fixture(sdk, tmp_path)
    chiller.setReferenceCapacity(50000)
    chiller.setMinimumPartLoadRatio(0.001)
    chiller.setMinimumUnloadingRatio(0.001)
    chiller.setCondenserFanPowerRatio(0.02)
    assert model.save(str(source), True)
    original = source.read_bytes()
    cfg = config(tmp_path)
    cfg.update(
        plant_loop=dict(name="Fixture CHW"),
        chiller=dict(name="Native Chiller"),
        settings=dict(reference_capacity_w=100000),
    )
    report = preflight(source, cfg)
    assert report["ready"] and report["plan"]["simulation_ready"], report
    assert "condenser fan power ratio is positive" in " ".join(report["warnings"])
    result = apply(report, tmp_path)
    extra = [
        (chiller.nameString(), "Chiller Condenser Fan Electricity Energy"),
        (chiller.nameString(), "Chiller Condenser Fan Electricity Rate"),
    ]
    before = native_run(
        o, source, tmp_path / "before_run", str(chiller.handle()), extra
    )
    after = native_run(
        o,
        Path(result["output_model_path"]),
        tmp_path / "after_run",
        str(chiller.handle()),
        extra,
    )
    assert before["hours"] == after["hours"] == 72
    assert before["cooling_j"] > 1e8
    assert after["cooling_j"] == pytest.approx(before["cooling_j"], rel=1e-5)
    for observed, watts in [(before, 1000), (after, 2000)]:
        assert observed["cycling_range"] == pytest.approx([1, 1])
        outputs = observed["extra_outputs"][chiller.nameString()]
        power = [row[3] for row in outputs["Chiller Condenser Fan Electricity Rate"]]
        assert min(power) == pytest.approx(watts) and max(power) == pytest.approx(watts)
        observed["condenser_fan_electricity_j"] = sum(
            row[3] for row in outputs["Chiller Condenser Fan Electricity Energy"]
        )
    assert after["condenser_fan_electricity_j"] / before[
        "condenser_fan_electricity_j"
    ] == pytest.approx(2)
    assert source.read_bytes() == original
    (tmp_path / "native_condenser_fan_evidence.json").write_text(
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
