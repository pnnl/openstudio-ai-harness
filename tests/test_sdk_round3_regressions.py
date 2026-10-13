"""Assertions for round-3 probes, including the actual harness simulation path."""

import json
import shutil
from pathlib import Path
import pytest
from test_vav_preflight import sdk, model_file, config, SCRIPTS
from test_vav_apply import apply_module, reviewed_plan
from test_sdk_followup_regressions import preflight, measure


def workflow(model_file, data):
    root = model_file.with_suffix("")
    root.mkdir(exist_ok=True)
    (root / "workflow.osw").write_text(json.dumps(data))
    return root


@pytest.mark.parametrize(
    "arguments",
    [
        {"output_path": ""},
        {"report_file": "results.csv"},
        {"output_csv_path": "result.csv"},
        {"input_file": ""},
        {"data_dir": "missing"},
        {"schedule_csv_path": "missing.csv"},
    ],
)
def test_nonessential_workflow_inputs_warn(
    sdk, model_file, config, tmp_path, arguments
):
    root = workflow(
        model_file, {"steps": [{"measure_dir_name": "example", "arguments": arguments}]}
    )
    measure(sdk[0], root / "measures/example")
    result = preflight(sdk, model_file, config, tmp_path)
    assert result["ready"], result["errors"]
    assert (
        result["plan"]["companions"]["workflow"]["steps"][0]["arguments"] == arguments
    )
    assert ".." not in result["plan"]["companions"]["workflow"]["file_paths"]
    if "schedule_csv_path" in arguments:
        assert not result["simulation_ready"] and any(
            "Workflow input" in x for x in result["warnings"]
        )
    else:
        assert not any("Workflow input" in x for x in result["warnings"])


def test_missing_measure_warns(sdk, apply_module, model_file, config, tmp_path):
    workflow(
        model_file, {"steps": [{"measure_dir_name": "not_downloaded", "arguments": {}}]}
    )
    result = apply_module.apply(reviewed_plan(sdk, model_file, config, tmp_path))
    assert result["ok"] and not result["simulation_ready"]
    assert any("Referenced measure" in x for x in result["warnings"])
    assert (
        json.loads(Path(result["workflow_path"]).read_text())["steps"][0][
            "measure_dir_name"
        ]
        == "not_downloaded"
    )


@pytest.mark.parametrize("filename", ["id_schedule.csv", "credentials_report.pdf"])
def test_explicit_data_not_mistaken_for_secrets(
    sdk, model_file, config, tmp_path, filename
):
    root = workflow(model_file, {"steps": []})
    model = sdk[0].osversion.VersionTranslator().loadModel(str(model_file)).get()
    model.setWorkflowJSON(sdk[0].WorkflowJSON(str(root / "workflow.osw")))
    (root / "files").mkdir()
    data = root / "files" / filename
    data.write_text("v\n" + "0.5\n" * 8760)
    sdk[0].model.ScheduleFile(
        sdk[0].model.ExternalFile.getExternalFile(model, str(data)).get()
    )
    model.save(str(model_file), True)
    assert preflight(sdk, model_file, config, tmp_path)["ready"]


def test_heat_pump_is_not_circulation_pump(sdk):
    from common.vav_inventory import inventory

    model = sdk[0].model.Model()
    loop = sdk[0].model.PlantLoop(model)
    loop.sizingPlant().setLoopType("Heating")
    loop.addSupplyBranchForComponent(
        sdk[0].model.HeatPumpWaterToWaterEquationFitHeating(model)
    )
    assert not inventory(model)["plant_loops"][0]["supply_pumps"]
    pump = sdk[0].model.PumpVariableSpeed(model)
    pump.addToNode(loop.supplyInletNode())
    assert len(inventory(model)["plant_loops"][0]["supply_pumps"]) == 1


def test_manifest_tracking_skips_without_checkout(tmp_path, monkeypatch):
    import runpy

    checks = runpy.run_path(str(Path("tests/test_harness_asset_manifest.py").resolve()))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(pytest.skip.Exception):
        checks["test_manifest_sources_are_tracked_in_git"]()


def test_harness_native_simulation_preserves_schedule_files(
    sdk, apply_module, tmp_path, monkeypatch
):
    from vav_fixture import prepare_vav_fixture
    from openstudio_ai_mcp.server import OpenStudioService
    from openstudio_ai_mcp.tools.schemas import ModelLoadArgs

    exe = Path("/Applications/OpenStudio-3.11.0/bin/openstudio")
    if not exe.is_file():
        pytest.skip("Native CLI required")
    source, cfg, _, _ = prepare_vav_fixture(sdk[0], tmp_path, True)
    root = source.with_name(source.stem + "_files")
    (root / "files").mkdir()
    data = root / "files/sched.csv"
    data.write_text("v\n" + "0.5\n" * 8760)
    model = sdk[0].osversion.VersionTranslator().loadModel(str(source)).get()
    model.setWorkflowJSON(sdk[0].WorkflowJSON(str(root / "workflow.osw")))
    ext = sdk[0].model.ExternalFile.getExternalFile(model, str(data)).get()
    schedule = sdk[0].model.ScheduleFile(ext)
    schedule.setRowstoSkipatTop(1)
    model.getLightss()[0].setSchedule(schedule)
    model.save(str(source), True)
    report = apply_module.apply(reviewed_plan(sdk, source, cfg, tmp_path))
    assert report["requires_companion_workflow"]
    assert not report["external_file_validation"]["plain_load"]["ok"]
    assert report["external_file_validation"]["with_workflow"]["ok"]
    original = Path(report["output_model_path"]).read_bytes()
    service = OpenStudioService(
        workspace_root=tmp_path / "runtime",
        learning_db_path=tmp_path / "learning.sqlite",
    )
    loaded = service.model_load(
        ModelLoadArgs(model_uri=Path(report["output_model_path"]).as_uri())
    )
    model_id = loaded["model_id"]
    assert Path(report["output_model_path"]).read_bytes() == original
    # Snapshots must retain data even when the original model bundle goes away.
    shutil.rmtree(Path(report["companion_directory"]))
    Path(report["output_model_path"]).unlink()
    shutil.rmtree(root)
    job = service.job_manager.create_job(
        model_id=model_id, run_mode="sizing", options={}
    )
    monkeypatch.setattr(service, "_openstudio_executable_or_none", lambda: str(exe))
    result = service._run_openstudio_cli_sync(job.job_id, model_id, {})
    assert result["severe_count"] == 0
    workspace = service.workspace_manager.workspace_path(job.job_id)
    wf = json.loads((workspace / "in.osw").read_text())
    assert wf["steps"] == [] and wf["file_paths"] == ["in/files"]
    files = list((workspace / "in/files").glob("*sched.csv"))
    assert len(files) == 1 and files[0].is_file()
