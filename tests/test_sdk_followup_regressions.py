"""Regression assertions for the follow-up's probes and remaining partial fixes."""

import json
import shutil
from pathlib import Path
import pytest
from test_vav_preflight import (
    sdk,
    model_file,
    config,
    catalog,
    modules,
    SCRIPTS,
    prepare_existing_plant,
)
from test_vav_apply import apply_module, reviewed_plan

EPW = Path(__file__).parent / "fixtures/USA_FL_Tampa.Intl.AP.722110_TMY3.epw"


def preflight(sdk, model_file, config, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config))
    return sdk[1].preflight(model_file, cfg)


def measure(o, directory):
    o.BCLMeasure(
        "Example",
        "Example",
        o.path(str(directory)),
        "HVAC",
        o.MeasureType("ModelMeasure"),
        "Description",
        "Model description",
    )


def test_app_lookup_reference_only_and_relocation(
    sdk, apply_module, model_file, config, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    o = sdk[0]
    root = model_file.with_suffix("")
    (root / "files").mkdir(parents=True)
    shutil.copy(EPW, root / "files/w.epw")
    measure(o, root / "measures/example")
    (root / "measures/example/.git").mkdir()
    (root / "measures/example/.git/HEAD").write_text("metadata")
    (root / "measures/example/.gitkeep").write_text("")
    (root / "measures/unused").mkdir()
    (root / "measures/unused/.env").write_text("must not read")
    (root / "workflow.osw").write_text(
        json.dumps(
            {"weather_file": "w.epw", "steps": [{"measure_dir_name": "example"}]}
        )
    )
    lookup = o.WorkflowJSON(str(root / "workflow.osw"))
    assert lookup.findFile("w.epw").is_initialized()
    model = o.osversion.VersionTranslator().loadModel(str(model_file)).get()
    o.model.WeatherFile.setWeatherFile(model, o.EpwFile(str(root / "files/w.epw")))
    csv = root / "files/schedule.csv"
    csv.write_text("value\n" + "0.5\n" * 8760)
    o.model.ScheduleFile(o.model.ExternalFile.getExternalFile(model, str(csv)).get())
    model.save(str(model_file), True)
    report = preflight(sdk, model_file, config, tmp_path)
    assert report["ready"], report["errors"]
    resources = report["plan"]["companions"]["resources"]
    assert len([r for r in resources if r["source"].endswith("w.epw")]) == 1
    assert all(
        "unused" not in r["source"] and ".git" not in r["target"] for r in resources
    )
    assert report["plan"]["companions"]["skipped_metadata"]
    result = apply_module.apply(reviewed_plan(sdk, model_file, config, tmp_path))
    directory = Path(result["companion_directory"])
    assert directory == Path(result["output_model_path"]).with_suffix("")
    moved = tmp_path / "moved"
    moved.mkdir()
    shutil.move(result["output_model_path"], moved / "out.osm")
    shutil.move(str(directory), moved / "out")
    monkeypatch.chdir(moved)
    saved = o.osversion.VersionTranslator().loadModel(str(moved / "out.osm")).get()
    url = Path(str(saved.getWeatherFile().path().get()))
    assert not url.is_absolute() and url.is_file()
    saved.workflowJSON().setOswPath(str(moved / "out/workflow.osw"))
    external = saved.getExternalFiles()[0]
    assert not Path(external.fileName()).is_absolute()
    assert Path(str(external.filePath())).read_bytes() == csv.read_bytes()
    wf = o.WorkflowJSON(str(moved / "out/workflow.osw"))
    assert wf.findFile(wf.weatherFile().get()).is_initialized()
    assert wf.findMeasure("example").is_initialized()


def test_stale_absolute_weather_allows_edit(
    sdk, apply_module, model_file, config, tmp_path
):
    o = sdk[0]
    weather = tmp_path / "gone.epw"
    shutil.copy(EPW, weather)
    model = o.osversion.VersionTranslator().loadModel(str(model_file)).get()
    o.model.WeatherFile.setWeatherFile(model, o.EpwFile(str(weather)))
    model.save(str(model_file), True)
    weather.unlink()
    result = apply_module.apply(reviewed_plan(sdk, model_file, config, tmp_path))
    assert result["ok"] and not result["simulation_ready"]
    assert any("unavailable" in x for x in result["warnings"])


def test_latin1_model_version_sniff(sdk, model_file):
    data = model_file.read_bytes().replace(b"HW", b"HW\xe9", 1)
    model_file.write_bytes(data)
    assert (
        sdk[0].osversion.VersionTranslator().loadModel(str(model_file)).is_initialized()
    )
    assert sdk[1].preflight(model_file)["ok"]


def test_unreferenced_neighbor_measures_ignored(sdk, model_file, config, tmp_path):
    folder = tmp_path / "measures/unused"
    folder.mkdir(parents=True)
    (folder / ".gitkeep").write_text("")
    (folder / ".env").write_text("must not read")
    result = preflight(sdk, model_file, config, tmp_path)
    assert result["ready"] and not result["plan"]["companions"]["resources"]


def test_referenced_secrets_block(sdk, model_file, config, tmp_path):
    root = model_file.with_suffix("")
    measure(sdk[0], root / "measures/example")
    (root / "measures/example/.env.local").write_text("must not copy")
    (root / "workflow.osw").write_text(
        json.dumps({"steps": [{"measure_dir_name": "example"}]})
    )
    result = preflight(sdk, model_file, config, tmp_path)
    assert not result["ready"] and any("Sensitive" in x for x in result["errors"])


def test_history_merge_scoped_and_assumption_event_preserved():
    from blackboard.operations import record_assumption, apply_state_patch

    assert record_assumption({"assumptions": ["a"]}, "a")["assumptions"] == ["a", "a"]
    result = apply_state_patch(
        {"nested": {"assumptions": ["old"]}}, {"nested": {"assumptions": ["new"]}}
    )
    assert result["nested"]["assumptions"] == ["new"]
    empty_steps = apply_state_patch(
        {"completed_steps": [], "assumptions": ["old"]},
        {"completed_steps": [], "assumptions": ["new"]},
    )
    assert empty_steps["assumptions"] == ["old", "new"]


def test_hardlink_fsync_before_publication(tmp_path, monkeypatch, modules):
    from common import files

    source = tmp_path / "staged"
    source.write_bytes(b"durable")
    calls = []
    sync, link = files.os.fsync, files.os.link

    def fsync(fd):
        calls.append("fsync")
        sync(fd)

    def publish(*args):
        calls.append("link")
        link(*args)

    monkeypatch.setattr(files.os, "fsync", fsync)
    monkeypatch.setattr(files.os, "link", publish)
    files.publish(source, tmp_path / "output")
    assert calls[:2] == ["fsync", "link"]


@pytest.mark.parametrize("issue", ["terminal_minimum", "thermostat", "pump"])
def test_remaining_input_cross_checks(modules, catalog, config, tmp_path, issue):
    if issue == "terminal_minimum":
        config["minimum_terminal_airflow_fraction"] = 0.5
    elif issue == "thermostat":
        catalog["zones"][0]["has_dual_setpoint_schedules"] = False
    else:
        catalog["plant_loops"][0]["supply_pumps"] = []
    result = modules[1](config, catalog, tmp_path / "in.osm")
    assert not result["ready"] and result["errors"]


def test_every_behavior_control_consumed_by_builder_and_validator(
    sdk, apply_module, model_file, config, tmp_path, monkeypatch
):
    from common.vav_plan import CONTROLS, PROFILE_NOTES

    consumed = {"build": set(), "validate": set()}

    class Tracking(dict):
        def __init__(self, values, phase):
            super().__init__(values)
            self.phase = phase

        def __getitem__(self, key):
            consumed[self.phase].add(key)
            return super().__getitem__(key)

    original_create, original_validate = (
        apply_module.create,
        apply_module.validate_model,
    )

    def create(model, o, planned):
        planned["controls"] = Tracking(planned["controls"], "build")
        return original_create(model, o, planned)

    def validate(model, o, planned, *args):
        planned["controls"] = Tracking(planned["controls"], "validate")
        return original_validate(model, o, planned, *args)

    monkeypatch.setattr(apply_module, "create", create)
    monkeypatch.setattr(apply_module, "validate_model", validate)
    o = sdk[0]
    model = o.osversion.VersionTranslator().loadModel(str(model_file)).get()
    chw = o.model.PlantLoop(model)
    chw.setName("CHW")
    chw.sizingPlant().setLoopType("Cooling")
    prepare_existing_plant(o, model, chw, False)
    model.save(str(model_file), True)
    for i, (heat, cool, reheat) in enumerate(
        [("Water", "Water", "Water"), ("NaturalGas", "DXTwoSpeed", "Electricity")]
    ):
        case = tmp_path / str(i)
        case.mkdir()
        config["output_model_path"] = str(case / "out.osm")
        for role, kind in zip(
            ("central_heating", "central_cooling", "reheat"), (heat, cool, reheat)
        ):
            config[role] = {"type": kind}
            if kind == "Water":
                config[role]["plant_loop"] = {
                    "name": "CHW" if role == "central_cooling" else "HW"
                }
            if kind == "DXTwoSpeed":
                config[role]["dx_approved"] = True
        plan = reviewed_plan(sdk, model_file, config, case)
        assumptions = json.loads(plan.read_text())["assumptions"]
        assert all(
            any(f"controls.{key}:" in x for x in assumptions)
            for key in {*CONTROLS, *PROFILE_NOTES}
        )
        assert apply_module.apply(plan)["validation"]["ok"]
    assert consumed["build"] == set(CONTROLS)
    assert consumed["validate"] == set(CONTROLS)


def test_actual_missing_dual_schedule_blocks(sdk, model_file, config, tmp_path):
    model = sdk[0].osversion.VersionTranslator().loadModel(str(model_file)).get()
    zone = model.getThermalZoneByName("Zone 1").get()
    zone.thermostatSetpointDualSetpoint().get().resetCoolingSetpointTemperatureSchedule()
    model.save(str(model_file), True)
    result = preflight(sdk, model_file, config, tmp_path)
    assert not result["ready"] and any("dual-setpoint" in x for x in result["errors"])


@pytest.mark.parametrize(
    "source_type",
    [
        "WaterHeaterMixed",
        "WaterHeaterStratified",
        "PlantComponentTemperatureSource",
        "PlantComponentUserDefined",
    ],
)
def test_water_heater_supply_is_recognized(
    sdk, model_file, config, tmp_path, source_type
):
    model = sdk[0].osversion.VersionTranslator().loadModel(str(model_file)).get()
    loop = model.getPlantLoopByName("HW").get()
    for source in list(model.getDistrictHeatingWaters()):
        source.remove()
    loop.addSupplyBranchForComponent(getattr(sdk[0].model, source_type)(model))
    model.save(str(model_file), True)
    result = preflight(sdk, model_file, config, tmp_path)
    assert result["ready"], result["errors"]


def test_osw_duplicate_keys_rejected(sdk, model_file, config, tmp_path):
    root = model_file.with_suffix("")
    root.mkdir()
    (root / "workflow.osw").write_text('{"steps": [], "steps": []}')
    result = preflight(sdk, model_file, config, tmp_path)
    assert not result["ready"] and any(
        "Duplicate JSON field" in x for x in result["errors"]
    )


def test_companion_io_errors_are_plan_errors(
    sdk, model_file, config, tmp_path, monkeypatch
):
    def fail(*args):
        raise PermissionError("resource is unreadable")

    monkeypatch.setattr(sdk[1], "inspect_companions", fail)
    result = preflight(sdk, model_file, config, tmp_path)
    assert not result["ready"] and result["errors"] == ["resource is unreadable"]
