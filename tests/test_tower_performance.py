"""Tower fan power edits preserve identities and expose coupled airflow sizing."""

import json
from pathlib import Path
import sys

import pytest
from test_vav_preflight import sdk, SCRIPTS
from test_chiller_performance import fixture as plant_fixture

sys.path.insert(0, str(SCRIPTS))
from common import tower_edit as towers, model_transaction as tx

OPERATION = "edit_tower_performance"


def fixture(o, folder, model_type="CoolToolsCrossFlow", power=400):
    source, model, _ = plant_fixture(o, folder, "WaterCooled")
    tower = model.getCoolingTowerVariableSpeeds()[0]
    tower.setName("Selected Tower")
    assert tower.setModelType(model_type)
    if power == "Autosize":
        tower.autosizeDesignFanPower()
    else:
        assert tower.setDesignFanPower(power)
    tower.additionalProperties().setFeature("review_note", "retain")
    assert model.save(str(source), True)
    return source, model, tower


def config(folder, power=500):
    return dict(
        output_model_path=str(folder / "edited.osm"),
        plant_loop=dict(name="CHW Condenser"),
        tower=dict(name="Selected Tower"),
        settings=dict(design_fan_power_w=power),
    )


def preflight(source, cfg):
    return tx.preflight(source, cfg, OPERATION, towers.plan)


def apply(report, folder, creator=None):
    path = folder / "reviewed.json"
    path.write_text(json.dumps(report))
    return tx.apply(
        path, OPERATION, towers.plan, creator or towers.edit, towers.validate_model
    )


@pytest.mark.parametrize("model_type", ["CoolToolsCrossFlow", "YorkCalc"])
@pytest.mark.parametrize(
    "before,after", [(400, 500), (400, "Autosize"), ("Autosize", 500)]
)
def test_power_and_autosize_edits_preserve_identity_graph_and_curve(
    sdk, tmp_path, model_type, before, after
):
    o = sdk[0]
    source, model, tower = fixture(o, tmp_path, model_type, before)
    original = source.read_bytes()
    metadata = str(tower.additionalProperties().handle())
    curve = tower.fanPowerRatioFunctionofAirFlowRateRatioCurve().get()
    curve_raw = str(curve.idfObject())
    report = preflight(source, config(tmp_path, after))
    assert report["ready"], report
    assert report == preflight(source, config(tmp_path, after))
    assert report["plan"]["impact"]["autosized_airflow_depends_on_fan_power"]
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and result["translation"]["ok"]
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    current = saved.getCoolingTowerVariableSpeed(tower.handle()).get()
    assert towers.values(current) == dict(design_fan_power_w=after)
    assert str(current.additionalProperties().handle()) == metadata
    assert str(saved.getCurveCubic(curve.handle()).get().idfObject()) == curve_raw
    assert (
        current.isDesignWaterFlowRateAutosized()
        and current.isDesignAirFlowRateAutosized()
    )
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    "power", [0, -1, True, "500", "autosize", float("nan"), float("inf")]
)
def test_invalid_power_rejects(sdk, tmp_path, power):
    source, _, _ = fixture(sdk[0], tmp_path)
    with pytest.raises(ValueError, match="Invalid cooling tower performance"):
        preflight(source, config(tmp_path, power))
    assert not (tmp_path / "edited.osm").exists()


def native_fixture(o, folder, autosized_airflow, model_type="CoolToolsCrossFlow"):
    from vav_fixture import prepare_vav_fixture
    from common import vav_create, vav_plan
    from common.hvac_inventory import inventory

    unserved, cfg, original_fixture, original_bytes = prepare_vav_fixture(
        o, folder, True
    )
    model = o.osversion.VersionTranslator().loadModel(str(unserved)).get()
    planned = vav_plan.plan(cfg, inventory(model), unserved)
    assert planned["ready"]
    vav_create.create(model, o, planned)
    chilled = model.getPlantLoopByName("Fixture CHW").get()
    model.getDistrictCoolings()[0].remove()
    chiller = o.model.ChillerElectricEIR(model)
    chiller.setName("Native Chiller")
    chiller.setReferenceCOP(4)
    chiller.setReferenceLeavingChilledWaterTemperature(6.666667)
    assert chilled.addSupplyBranchForComponent(chiller)
    condenser = o.model.PlantLoop(model)
    condenser.setName("Native Condenser")
    condenser.sizingPlant().setLoopType("Condenser")
    condenser.sizingPlant().setDesignLoopExitTemperature(29)
    condenser.sizingPlant().setLoopDesignTemperatureDifference(5)
    pump = o.model.PumpVariableSpeed(model)
    assert pump.addToNode(condenser.supplyInletNode())
    tower = o.model.CoolingTowerVariableSpeed(model)
    tower.setName("Native Tower")
    assert tower.setModelType(model_type)
    tower.setDesignRangeTemperature(5)
    tower.setDesignApproachTemperature(3.4)
    tower.setDesignWaterFlowRate(0.005)
    tower.setDesignFanPower(500)
    if not autosized_airflow:
        tower.setDesignAirFlowRate(2)
    assert condenser.addSupplyBranchForComponent(tower)
    assert condenser.addDemandBranchForComponent(chiller)
    assert chiller.setCondenserType("WaterCooled")
    chiller.setReferenceCondenserFluidFlowRate(0.005)
    for side in ("Supply", "Demand"):
        assert getattr(condenser, "add" + side + "BranchForComponent")(
            o.model.PipeAdiabatic(model)
        )
    schedule = o.model.ScheduleConstant(model)
    schedule.setValue(29)
    assert o.model.SetpointManagerScheduled(model, schedule).addToNode(
        condenser.supplyOutletNode()
    )
    source = folder / "before.osm"
    assert model.save(str(source), True)
    return source, model, tower, chiller, original_fixture, original_bytes


@pytest.mark.parametrize("model_type", ["CoolToolsCrossFlow", "YorkCalc"])
@pytest.mark.parametrize(
    "airflow,target", [("fixed", 750), ("autosized", 750), ("autosized", "Autosize")]
)
def test_native_power_airflow_and_auxiliary_energy(
    sdk, tmp_path, airflow, target, model_type
):
    from test_chiller_performance import native_run
    from test_supply_fan_performance import native_cli

    native_cli()
    o = sdk[0]
    source, model, tower, chiller, seed, seed_bytes = native_fixture(
        o, tmp_path, airflow == "autosized", model_type
    )
    original = source.read_bytes()
    cfg = config(tmp_path, target)
    cfg.update(
        plant_loop=dict(name="Native Condenser"), tower=dict(name="Native Tower")
    )
    report = preflight(source, cfg)
    assert report["ready"] and report["plan"]["simulation_ready"], report
    result = apply(report, tmp_path)
    extra_outputs = [
        (tower.nameString(), variable)
        for variable in (
            "Cooling Tower Make Up Water Volume",
            "Cooling Tower Water Evaporation Volume",
            "Cooling Tower Outlet Temperature",
            "Cooling Tower Air Flow Rate Ratio",
        )
    ] + [
        (chiller.nameString(), variable)
        for variable in (
            "Chiller Condenser Inlet Temperature",
            "Chiller Condenser Outlet Temperature",
        )
    ]
    assert tower.evaporationLossMode() == "SaturatedExit"
    assert report["plan"]["impact"]["evaporation_loss_mode"] == "SaturatedExit"
    assert report["plan"]["impact"]["condenser_design_delta_t_k"] == 5
    before = native_run(
        o, source, tmp_path / "before_run", str(chiller.handle()), extra_outputs
    )
    after = native_run(
        o,
        Path(result["output_model_path"]),
        tmp_path / "after_run",
        str(chiller.handle()),
        extra_outputs,
    )
    b, a = (
        before["condenser_equipment"]["Native Tower"],
        after["condenser_equipment"]["Native Tower"],
    )
    assert before["hours"] == after["hours"] == 72
    assert b["electricity_j"] > 0 and a["electricity_j"] > 0

    def design_value(record, token, fixed_value=None):
        rows = [
            (name, value)
            for name, value in record["sizes"]
            if token in name
            and "free convection" not in name
            and not (token == "Air Flow Rate" and "Fan Power" in name)
        ]
        if not rows and fixed_value is not None:
            return fixed_value
        assert rows, (token, record)
        rows.sort(key=lambda x: "User-Specified" not in x[0])
        return rows[0][1]

    before_power, after_power = design_value(b, "Fan Power", 500), design_value(
        a, "Fan Power", target if target != "Autosize" else None
    )
    before_air, after_air = design_value(
        b, "Air Flow Rate", 2 if airflow == "fixed" else None
    ), design_value(a, "Air Flow Rate", 2 if airflow == "fixed" else None)
    assert before_power == pytest.approx(500)
    if target != "Autosize":
        assert after_power == pytest.approx(target)
    else:
        # Fixed 0.005 m3/s tower water flow and 5 K loop delta T: about 1.10 kW,
        # using the pinned engine's water density/specific heat at sizing conditions.
        assert after_power == pytest.approx(1097.085585855, rel=1e-6)
    assert a["electricity_j"] / b["electricity_j"] == pytest.approx(
        after_power / before_power, rel=1e-5
    )
    assert after["cooling_j"] == pytest.approx(before["cooling_j"], rel=1e-6)
    assert after["electricity_j"] == pytest.approx(before["electricity_j"], rel=1e-6)
    for key, item in before["condenser_equipment"].items():
        if item["type"].startswith(("OS_Pump_", "OS_HeaderedPumps_")):
            assert after["condenser_equipment"][key]["electricity_j"] == pytest.approx(
                item["electricity_j"], rel=1e-6
            )
    for key, variable in extra_outputs:
        if variable.endswith("Temperature") or variable.endswith("Air Flow Rate Ratio"):
            assert [
                row[3] for row in after["extra_outputs"][key][variable]
            ] == pytest.approx(
                [row[3] for row in before["extra_outputs"][key][variable]],
                rel=1e-6,
                abs=1e-6,
            )
    water = {}
    for variable in (
        "Cooling Tower Make Up Water Volume",
        "Cooling Tower Water Evaporation Volume",
    ):
        before_water = sum(
            row[3] for row in before["extra_outputs"][tower.nameString()][variable]
        )
        after_water = sum(
            row[3] for row in after["extra_outputs"][tower.nameString()][variable]
        )
        assert before_water > 0 and after_water > 0
        if airflow == "fixed":
            assert after_water == pytest.approx(before_water, rel=1e-6)
        else:
            assert abs(after_water - before_water) > before_water * 1e-5
        water[variable] = dict(before_m3=before_water, after_m3=after_water)
    if airflow == "fixed":
        assert after_air == before_air == 2
    else:
        assert after_air / before_air == pytest.approx(
            after_power / before_power, rel=1e-6
        )
        assert report["plan"]["impact"]["autosized_airflow_depends_on_fan_power"]
    assert source.read_bytes() == original and seed.read_bytes() == seed_bytes
    (tmp_path / "native_evidence.json").write_text(
        json.dumps(
            dict(
                airflow=airflow,
                target=target,
                thermal_model=model_type,
                before=before,
                after=after,
                design_power_before_w=before_power,
                design_power_after_w=after_power,
                design_air_before_m3_s=before_air,
                design_air_after_m3_s=after_air,
                source_unchanged=True,
                validation=result["validation"],
                translation=result["translation"],
                water_use=water,
            ),
            indent=2,
        )
    )


@pytest.mark.parametrize("missing", ["plant_loop", "tower", "settings"])
def test_missing_choices_stay_unready(sdk, tmp_path, missing):
    source, _, _ = fixture(sdk[0], tmp_path)
    cfg = config(tmp_path)
    cfg.pop(missing)
    report = preflight(source, cfg)
    assert not report["ready"] and missing in report["plan"]["missing_inputs"]


@pytest.mark.parametrize(
    "case",
    [
        "noop",
        "unknown_loop",
        "unknown_tower",
        "cooling_loop",
        "heating_loop",
        "single",
        "two",
        "user_model",
        "detached",
    ],
)
def test_scope_and_inventory_agree(sdk, tmp_path, case):
    o = sdk[0]
    source, model, tower = fixture(o, tmp_path)
    cfg = config(tmp_path)
    loop = tower.plantLoop().get()
    if case == "noop":
        cfg["settings"]["design_fan_power_w"] = 400
    elif case == "unknown_loop":
        cfg["plant_loop"] = {"name": "absent"}
    elif case == "unknown_tower":
        cfg["tower"] = {"name": "absent"}
    elif case in ("cooling_loop", "heating_loop"):
        loop.sizingPlant().setLoopType(case.split("_")[0].title())
    elif case in ("single", "two"):
        other = getattr(
            o.model,
            "CoolingTowerSingleSpeed" if case == "single" else "CoolingTowerTwoSpeed",
        )(model)
        other.setName("Other Tower")
        assert loop.addSupplyBranchForComponent(other)
        cfg["tower"] = {"name": "Other Tower"}
    elif case == "user_model":
        assert tower.setModelType("CoolToolsUserDefined")
    else:
        assert loop.removeSupplyBranchWithComponent(tower)
    model.save(str(source), True)
    report = preflight(source, cfg)
    assert not report["ready"], report
    if case in ("single", "two", "user_model", "cooling_loop", "heating_loop"):
        candidates = next(
            x["towers"]
            for x in towers.inventory(model)["plant_loops"]
            if x["name"] == "CHW Condenser"
        )
        assert not next(x for x in candidates if x["name"] == cfg["tower"]["name"])[
            "supported"
        ]
    assert not (tmp_path / "edited.osm").exists()


@pytest.mark.parametrize("missing", ["pump", "setpoint"])
def test_incomplete_existing_plant_warns_without_repair(sdk, tmp_path, missing):
    source, model, tower = fixture(sdk[0], tmp_path)
    loop = tower.plantLoop().get()
    for obj in list(
        loop.supplyComponents()
        if missing == "pump"
        else loop.supplyOutletNode().setpointManagers()
    ):
        if missing == "setpoint" or obj.iddObjectType().valueName().startswith(
            ("OS_Pump_", "OS_HeaderedPumps_")
        ):
            obj.remove()
    model.save(str(source), True)
    report = preflight(source, config(tmp_path))
    assert report["ready"] and not report["plan"]["simulation_ready"]
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and not result["simulation_ready"]


@pytest.mark.parametrize(
    "mutation",
    [
        "power",
        "water_flow",
        "air_flow",
        "curve",
        "thermal",
        "minimum_airflow",
        "free_convection",
        "cells",
        "metadata",
        "pump",
        "chiller",
        "setpoint",
        "dispatch",
        "ports",
        "new_object",
    ],
)
def test_unrequested_side_effects_never_publish(sdk, tmp_path, mutation):
    o = sdk[0]
    source, _, _ = fixture(o, tmp_path)
    report = preflight(source, config(tmp_path))
    assert report["ready"]

    def changed(model, sdk, planned):
        result = towers.edit(model, sdk, planned)
        t = towers.tower_object(model, sdk, planned["resolved_objects"]["tower"])
        if mutation == "power":
            t.setDesignFanPower(900)
        elif mutation == "water_flow":
            t.setDesignWaterFlowRate(0.001)
        elif mutation == "air_flow":
            t.setDesignAirFlowRate(2)
        elif mutation == "curve":
            t.fanPowerRatioFunctionofAirFlowRateRatioCurve().get().setCoefficient3xPOW2(
                0.2
            )
        elif mutation == "thermal":
            t.setDesignApproachTemperature(5)
        elif mutation == "minimum_airflow":
            t.setMinimumAirFlowRateRatio(0.4)
        elif mutation == "free_convection":
            t.setFractionofTowerCapacityinFreeConvectionRegime(0.2)
        elif mutation == "cells":
            t.setNumberofCells(3)
        elif mutation == "metadata":
            t.additionalProperties().setFeature("review_note", "changed")
        elif mutation == "pump":
            model.getPumpConstantSpeeds()[0].setRatedPumpHead(123)
        elif mutation == "chiller":
            model.getChillerElectricEIRs()[0].setReferenceCOP(9)
        elif mutation == "setpoint":
            t.plantLoop().get().supplyOutletNode().setpointManagers()[0].remove()
        elif mutation == "dispatch":
            t.plantLoop().get().setLoadDistributionScheme("SequentialLoad")
        elif mutation == "ports":
            model.disconnect(t, t.inletPort())
        else:
            o.model.CoolingTowerVariableSpeed(model)
        return result

    with pytest.raises(ValueError):
        apply(report, tmp_path, changed)
    assert not (tmp_path / "edited.osm").exists()


@pytest.mark.parametrize("mode", ["stale", "tampered"])
def test_source_and_review_checks_remain_exact(sdk, tmp_path, mode):
    source, _, _ = fixture(sdk[0], tmp_path)
    report = preflight(source, config(tmp_path))
    if mode == "stale":
        source.write_bytes(source.read_bytes() + b"\n! changed\n")
    else:
        report["plan"]["parameters"]["settings"]["design_fan_power_w"] = 600
    with pytest.raises(ValueError):
        apply(report, tmp_path)
    assert not (tmp_path / "edited.osm").exists()


@pytest.mark.parametrize("weather", [False, True])
def test_combined_readiness_includes_companions(sdk, tmp_path, weather):
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
    assert report["plan"]["simulation_ready"] is weather
    assert apply(report, tmp_path)["simulation_ready"] is weather


def test_blank_model_type_and_implicit_curve_preserved(sdk, tmp_path):
    o = sdk[0]
    source, model, tower = fixture(o, tmp_path)
    tower.resetModelType()
    tower.resetFanPowerRatioFunctionofAirFlowRateRatioCurve()
    model.save(str(source), True)
    report = preflight(source, config(tmp_path))
    assert report["ready"], report
    assert report["plan"]["impact"]["thermal_model"] == "YorkCalc"
    assert report["plan"]["impact"]["fan_curve"] is None
    result = apply(report, tmp_path)
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    current = saved.getCoolingTowerVariableSpeed(tower.handle()).get()
    assert towers.optional_value(current.modelType()) == ""
    assert not current.fanPowerRatioFunctionofAirFlowRateRatioCurve().is_initialized()


def test_metadata_references_and_other_tower_preserved(sdk, tmp_path):
    o = sdk[0]
    source, model, tower = fixture(o, tmp_path)
    other = o.model.CoolingTowerVariableSpeed(model)
    other.setName("Other Tower")
    assert tower.plantLoop().get().addSupplyBranchForComponent(other)
    ems = o.model.EnergyManagementSystemActuator(
        tower, "Plant Component CoolingTower:VariableSpeed", "On/Off Supervisory"
    )
    cost = o.model.LifeCycleCost.createLifeCycleCost(
        "Fan cost", tower, 500, "CostPerEach", "Construction", 20
    ).get()
    output = o.model.OutputVariable("Cooling Tower Fan Electricity Energy", model)
    output.setKeyValue(tower.nameString())
    protected = {
        str(x.handle()): str(x.idfObject()) for x in [other, ems, cost, output]
    }
    model.save(str(source), True)
    report = preflight(source, config(tmp_path))
    assert report["plan"]["impact"]["ems_actuator_count"] == 1
    assert report["plan"]["impact"]["supply_tower_count"] == 2
    result = apply(report, tmp_path)
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    for handle, raw in protected.items():
        assert str(saved.getModelObject(o.toUUID(handle)).get().idfObject()) == raw


@pytest.mark.parametrize("problem", ["power", "curve", "unset"])
def test_source_translation_inconsistencies_return_unready_without_capture(
    sdk, tmp_path, monkeypatch, problem
):
    source, source_model, source_tower = fixture(sdk[0], tmp_path)
    if problem == "unset":
        assert source_tower.setString(
            source_tower.iddObject().getFieldIndex(towers.POWER_FIELD).get(), ""
        )
        assert source_model.save(str(source), True)
    translate = towers.translated_workspace

    def altered(model, sdk, label):
        workspace = translate(model, sdk, label)
        obj = next(
            x
            for x in workspace.getObjectsByType(
                sdk.IddObjectType("CoolingTower_VariableSpeed")
            )
            if x.nameString() == "Selected Tower"
        )
        index = (
            obj.iddObject()
            .getFieldIndex(
                towers.POWER_FIELD if problem == "power" else towers.CURVE_FIELD
            )
            .get()
        )
        if problem == "power":
            assert obj.setDouble(index, 999)
        else:
            assert obj.setString(index, "")
        return workspace

    monkeypatch.setattr(towers, "translated_workspace", altered)
    captured = []
    monkeypatch.setattr(
        tx, "capture_exception", lambda *a, **kw: captured.append(a) or {}
    )
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config(tmp_path)))
    output = tmp_path / "blocked.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "edit_tower_performance.py",
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
            OPERATION, towers.plan, towers.edit, towers.validate_model, towers.inventory
        )
        == 2
    )
    report = json.loads(output.read_text())
    assert not report["ready"] and report["plan"]["errors"]
    assert not captured and not (tmp_path / "edited.osm").exists()


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
    original = source.read_bytes()
    adapter = (ClaudeCodeAdapter if host == "claude" else CodexAdapter)(
        HostAdapterConfig(
            host_name=host, workspace_root=Path.cwd(), runtime_mode="marketplace"
        )
    )
    exported = tmp_path / "export"
    adapter.export_plugin(exported, dry_run=False)
    skill = next(exported.rglob("openstudio-tower-performance-editor/SKILL.md")).parent
    for relative in [
        "scripts/doctor.py",
        "scripts/sdk_probe.py",
        "scripts/prepare_model.py",
        "references/model_preparation.md",
        "references/tower_performance.md",
        "references/tower_performance.schema.json",
    ]:
        assert (skill / relative).is_file()
    skill = copy_plugin_for_skill(skill, tmp_path / "relocated")
    shutil.rmtree(exported)
    cfg = tmp_path / "request.json"
    cfg.write_text(json.dumps(config(tmp_path)))
    plan = tmp_path / "reviewed.json"
    repeated = tmp_path / "repeated.json"
    script = skill / "scripts/edit_tower_performance.py"
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
