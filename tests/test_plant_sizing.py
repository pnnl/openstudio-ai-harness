"""Explicit Autosize checks use effective translation, not a raw default flag."""

import json
from pathlib import Path
import sys

import pytest
from test_vav_preflight import sdk, SCRIPTS
from test_boiler_performance import (
    fixture as boiler_fixture,
    config as boiler_config,
    parasitic_fixture,
    native_run,
)
from test_tower_performance import fixture as tower_fixture, config as tower_config
from test_district_capacity import (
    fixture as district_fixture,
    config as district_config,
)

sys.path.insert(0, str(SCRIPTS))
from common import (
    boiler_edit,
    tower_edit,
    district_edit,
    chiller_edit,
    model_transaction as tx,
)
from common.plant_sizing import sizing_context


def operation(o, folder, kind):
    if kind == "chiller":
        from test_chiller_performance import fixture, config

        source, model, obj = fixture(o, folder)
        obj.setReferenceCapacity(10000)
        cfg = config(folder)
        cfg["settings"] = dict(reference_capacity_w="Autosize")
        return source, model, obj, chiller_edit, "edit_chiller_performance", cfg
    if kind == "boiler":
        source, model, obj = boiler_fixture(o, folder)
        obj.setNominalCapacity(10000)
        return (
            source,
            model,
            obj,
            boiler_edit,
            "edit_boiler_performance",
            boiler_config(folder, nominal_capacity_w="Autosize"),
        )
    if kind == "tower":
        source, model, obj = tower_fixture(o, folder)
        return (
            source,
            model,
            obj,
            tower_edit,
            "edit_tower_performance",
            tower_config(folder, "Autosize"),
        )
    source, model, obj = district_fixture(o, folder, before=10000)
    return (
        source,
        model,
        obj,
        district_edit,
        "edit_district_capacity",
        district_config(folder, "Autosize"),
    )


@pytest.mark.parametrize("kind", ["boiler", "tower", "district", "chiller"])
@pytest.mark.parametrize(
    "days,flag,effective,ready",
    [
        (0, None, False, False),
        (1, None, True, True),
        (1, False, False, False),
        (1, True, True, True),
        (0, True, True, False),
    ],
)
def test_explicit_autosize_reports_effective_sizing_and_preserves_controls(
    sdk, tmp_path, kind, days, flag, effective, ready
):
    o = sdk[0]
    source, model, _, editor, name, config = operation(o, tmp_path, kind)
    for _ in range(days):
        o.model.DesignDay(model)
    if flag is not None:
        model.getSimulationControl().setDoPlantSizingCalculation(flag)
    weather = Path(__file__).parent / "fixtures/USA_FL_Tampa.Intl.AP.722110_TMY3.epw"
    o.model.WeatherFile.setWeatherFile(model, o.EpwFile(str(weather.resolve())))
    assert model.save(str(source), True)
    original = source.read_bytes()
    report = tx.preflight(source, config, name, editor.plan)
    assert report["ready"], report
    assert report == tx.preflight(source, config, name, editor.plan)
    context = report["plan"]["impact"]["plant_sizing"]
    assert context == dict(
        design_day_count=days,
        sizing_period_count=days,
        plant_sizing_flag_defaulted=flag is None,
        requested_plant_sizing=flag,
        effective_plant_sizing=effective,
        translated_control_verified=True,
    )
    assert report["plan"]["simulation_ready"] is ready
    assert ("not ready to simulate" in " ".join(report["warnings"])) is (not ready)
    reviewed = tmp_path / "reviewed.json"
    reviewed.write_text(json.dumps(report))
    result = tx.apply(reviewed, name, editor.plan, editor.edit, editor.validate_model)
    assert result["validation"]["ok"] and result["translation"]["ok"]
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    ft = o.energyplus.ForwardTranslator()
    assert sizing_context(saved, o, ft.translateModel(saved)) == context
    assert source.read_bytes() == original


def test_context_does_not_materialize_missing_simulation_control(sdk):
    o = sdk[0]
    model = o.model.Model()
    workspace = o.Workspace(o.StrictnessLevel("Draft"), o.IddFileType("EnergyPlus"))
    obj = o.IdfObject(o.IddObjectType("SimulationControl"))
    obj.setString(
        obj.iddObject().getFieldIndex("Do Plant Sizing Calculation").get(), "No"
    )
    workspace.addObject(obj)
    before = {str(x.handle()) for x in model.modelObjects()}
    context = sizing_context(model, o, workspace)
    assert context["plant_sizing_flag_defaulted"]
    assert context["effective_plant_sizing"] is False
    assert not model.getOptionalSimulationControl().is_initialized()
    assert {str(x.handle()) for x in model.modelObjects()} == before


def test_unverifiable_translated_control_is_not_inferred_ready(
    sdk, tmp_path, monkeypatch
):
    o = sdk[0]
    source, model, _, editor, name, config = operation(o, tmp_path, "boiler")
    o.model.DesignDay(model)
    model.save(str(source), True)
    original = editor.translated_workspace

    def missing(*args):
        workspace = original(*args)
        for obj in workspace.getObjectsByType(o.IddObjectType("SimulationControl")):
            obj.remove()
        return workspace

    monkeypatch.setattr(editor, "translated_workspace", missing)
    report = tx.preflight(source, config, name, editor.plan)
    assert report["ready"]
    assert report["plan"]["impact"]["plant_sizing"]["effective_plant_sizing"] is None
    assert report["plan"]["simulation_ready"] is False


def test_multiple_boilers_capacity_context_is_bounded(sdk, tmp_path):
    o = sdk[0]
    source, model, obj, editor, name, config = operation(o, tmp_path, "boiler")
    loop = obj.plantLoop().get()
    for i in range(10):
        other = o.model.BoilerHotWater(model)
        other.setName(f"Other {i:02}")
        other.setSizingFactor(0.5)
        if i % 2 == 0:
            other.setNominalCapacity(5000)
        loop.addSupplyBranchForComponent(other)
    model.save(str(source), True)
    report = tx.preflight(source, config, name, editor.plan)
    assert report["ready"], report
    impact = report["plan"]["impact"]
    assert impact["nominal_capacity_w"] == 10000
    edit = impact["capacity_edit"]
    assert edit["after_w"] == "Autosize"
    assert edit["other_boiler_count"] == 10
    assert len(edit["other_boilers"]) == 8 and edit["omitted_other_boiler_count"] == 2
    assert {x["nominal_capacity_w"] for x in edit["other_boilers"]} == {
        5000,
        "Autosize",
    }
    assert {x["sizing_factor"] for x in edit["other_boilers"]} == {0.5}
    assert "not an automatically divided share" in " ".join(report["warnings"])


def test_native_two_autosized_boilers_each_receive_whole_design(sdk, tmp_path):
    import sqlite3
    from test_supply_fan_performance import native_cli

    native_cli()
    o = sdk[0]
    source, model, obj = parasitic_fixture(o, tmp_path, "NaturalGas")
    obj.setNominalCapacity(1e6)
    obj.setSizingFactor(1)
    second = o.model.BoilerHotWater(model)
    second.setName("Other Boiler")
    second.autosizeNominalCapacity()
    second.setSizingFactor(1)
    second.setDesignWaterFlowRate(0.001)
    obj.plantLoop().get().addSupplyBranchForComponent(second)
    model.getSimulationControl().setDoPlantSizingCalculation(True)
    model.save(str(source), True)
    original = source.read_bytes()
    report = tx.preflight(
        source,
        boiler_config(tmp_path, nominal_capacity_w="Autosize"),
        "edit_boiler_performance",
        boiler_edit.plan,
    )
    assert report["ready"] and report["plan"]["simulation_ready"], report
    assert (
        report["plan"]["impact"]["capacity_edit"]["other_boilers"][0][
            "nominal_capacity_w"
        ]
        == "Autosize"
    )
    reviewed = tmp_path / "reviewed.json"
    reviewed.write_text(json.dumps(report))
    result = tx.apply(
        reviewed,
        "edit_boiler_performance",
        boiler_edit.plan,
        boiler_edit.edit,
        boiler_edit.validate_model,
    )
    observed = native_run(
        o, Path(result["output_model_path"]), tmp_path / "sizing_run", str(obj.handle())
    )
    with sqlite3.connect(tmp_path / "sizing_run/run/eplusout.sql") as sql:
        sizes = dict(
            sql.execute(
                "SELECT CompName,Value FROM ComponentSizes WHERE CompType='Boiler:HotWater' AND Description='Design Size Nominal Capacity'"
            ).fetchall()
        )
    assert set(sizes) == {obj.nameString().upper(), second.nameString().upper()}
    assert list(sizes.values()) == pytest.approx([45718.8, 45718.8], rel=1e-9)
    assert sum(sizes.values()) == pytest.approx(91437.6, rel=1e-9)
    assert source.read_bytes() == original
    (tmp_path / "native_evidence.json").write_text(
        json.dumps(
            dict(
                observed=observed,
                boiler_sizes_w=sizes,
                source_unchanged=True,
                validation=result["validation"],
                translation=result["translation"],
            ),
            indent=2,
        )
    )


@pytest.mark.parametrize("kind", ["boiler", "tower", "district"])
@pytest.mark.parametrize("blocker", ["off", "no_days"])
def test_native_blocked_autosize_probe(sdk, tmp_path, kind, blocker):
    import sqlite3
    import subprocess
    from test_supply_fan_performance import native_cli
    from test_tower_performance import native_fixture as native_tower
    from test_district_capacity import load_fixture

    exe = native_cli()
    o = sdk[0]
    if kind == "boiler":
        source, model, obj = parasitic_fixture(o, tmp_path, "NaturalGas")
        editor, name, config = (
            boiler_edit,
            "edit_boiler_performance",
            boiler_config(tmp_path, nominal_capacity_w="Autosize"),
        )
        expected_type, field = "Boiler:HotWater", "Design Size Nominal Capacity"
    elif kind == "district":
        source, model, obj = load_fixture(o, tmp_path, "DistrictHeatingWater")
        editor, name, config = (
            district_edit,
            "edit_district_capacity",
            district_config(tmp_path, "Autosize"),
        )
        expected_type, field = "DistrictHeating:Water", "Design Size Nominal Capacity"
    else:
        source, model, obj, *_ = native_tower(o, tmp_path, False)
        editor, name, config = (
            tower_edit,
            "edit_tower_performance",
            tower_config(tmp_path, "Autosize"),
        )
        config.update(
            plant_loop=dict(name="Native Condenser"), tower=dict(name="Native Tower")
        )
        expected_type, field = (
            "CoolingTower:VariableSpeed",
            "Fan Power at Design Air Flow Rate",
        )
    control = model.getSimulationControl()
    if blocker == "no_days":
        for day in list(model.getDesignDays()):
            day.remove()
        control.setDoPlantSizingCalculation(True)
        control.setRunSimulationforWeatherFileRunPeriods(True)
        period = model.getRunPeriod()
        period.setBeginMonth(1)
        period.setBeginDayOfMonth(21)
        period.setEndMonth(1)
        period.setEndDayOfMonth(21)
    else:
        control.setDoPlantSizingCalculation(False)
    model.save(str(source), True)
    original = source.read_bytes()
    report = tx.preflight(source, config, name, editor.plan)
    assert report["ready"] and not report["plan"]["simulation_ready"], report
    reviewed = tmp_path / "reviewed.json"
    reviewed.write_text(json.dumps(report))
    result = tx.apply(reviewed, name, editor.plan, editor.edit, editor.validate_model)
    assert result["validation"]["ok"] and not result["simulation_ready"]
    folder = tmp_path / "native_probe"
    folder.mkdir()
    workflow = folder / "workflow.osw"
    workflow.write_text(
        json.dumps(
            dict(
                seed_file=result["output_model_path"],
                weather_file=str(
                    (
                        Path(__file__).parent
                        / "fixtures/USA_FL_Tampa.Intl.AP.722110_TMY3.epw"
                    ).resolve()
                ),
                steps=[],
            )
        )
    )
    run = subprocess.run(
        [str(exe), "run", "-w", str(workflow)],
        cwd=folder,
        capture_output=True,
        text=True,
        timeout=120,
    )
    (folder / "cli.log").write_text(run.stdout + run.stderr)
    err_path = folder / "run/eplusout.err"
    assert err_path.is_file(), run.stdout + run.stderr
    err = err_path.read_text()
    translated = o.Workspace.load(str(folder / "run/in.idf")).get()
    translated_control = translated.getObjectsByType(
        o.IddObjectType("SimulationControl")
    )[0]
    index = (
        translated_control.iddObject()
        .getFieldIndex("Do Plant Sizing Calculation")
        .get()
    )
    idf_flag = translated_control.getString(index).get().lower() == "yes"
    assert (
        idf_flag is report["plan"]["impact"]["plant_sizing"]["effective_plant_sizing"]
    )
    sizes = []
    sql_path = folder / "run/eplusout.sql"
    if sql_path.is_file():
        with sqlite3.connect(sql_path) as sql:
            sizes = sql.execute(
                "SELECT Description,Value FROM ComponentSizes WHERE lower(CompType)=lower(?) AND lower(CompName)=lower(?)",
                (expected_type, obj.nameString()),
            ).fetchall()
    if blocker == "no_days":
        assert run.returncode != 0 and "no design environments specified" in err
        assert not sizes
    else:
        assert run.returncode == 0
        expected_size = {
            "boiler": 45718.8,
            "tower": 1097.085585855,
            "district": 46638.90901266663,
        }[kind]
        assert dict(sizes)[field] == pytest.approx(expected_size, rel=1e-9)
    observed = dict(
        idf_plant_sizing=idf_flag,
        observation=(
            "no_design_environments_fatal"
            if blocker == "no_days"
            else "positive_fixed_flow_fallback_without_sizing_run"
        ),
        kind=kind,
        blocker=blocker,
        exit_code=run.returncode,
        sizes=sizes,
        expected_field=field,
        errors=err,
        source_unchanged=source.read_bytes() == original,
        context=report["plan"]["impact"]["plant_sizing"],
        simulation_ready=False,
    )
    (tmp_path / "probe.json").write_text(json.dumps(observed, indent=2))
    assert observed["source_unchanged"]
    assert run.returncode != 0 or "EnergyPlus Completed Successfully" in err, (
        run.stdout + run.stderr
    )
