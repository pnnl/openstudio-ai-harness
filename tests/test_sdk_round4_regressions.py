"""Runtime CSV durability and best-effort load regressions for the round-4 review."""

from pathlib import Path
import hashlib
import json
import shutil
import pytest
from test_vav_preflight import sdk
from openstudio_ai_mcp.server import OpenStudioService
from openstudio_ai_mcp.tools.schemas import (
    ModelLoadArgs,
    ModelCloneArgs,
    SessionCreateArgs,
    ModelApplyMeasureArgs,
    ModelSetWeatherArgs,
)
from openstudio_ai_mcp.model_resources import copy_model_resources


def service(tmp_path):
    return OpenStudioService(
        workspace_root=tmp_path / "runtime",
        learning_db_path=tmp_path / "learning.sqlite",
    )


def csv_model(o, tmp_path, names=("sched.csv",)):
    model = o.model.Model()
    source = tmp_path / "input.osm"
    for i, name in enumerate(names):
        data = tmp_path / name
        data.parent.mkdir(parents=True, exist_ok=True)
        data.write_text((str(i + 1) + "\n") * 8760)
        o.model.ScheduleFile(
            o.model.ExternalFile.getExternalFile(model, str(data), False).get(), 1, 0
        )
    model.save(str(source), True)
    return source


def test_absolute_snapshot_survives_osm_only_copy(sdk, tmp_path):
    source = csv_model(sdk[0], tmp_path)
    target = tmp_path / "snapshot/source.osm"
    target.parent.mkdir()
    shutil.copy2(source, target)
    copy_model_resources(source, target)
    alone = tmp_path / "measure/out.osm"
    alone.parent.mkdir()
    shutil.copy2(target, alone)
    model = sdk[0].osversion.VersionTranslator().loadModel(str(alone)).get()
    file = model.getExternalFiles()[0]
    assert Path(file.fileName()).is_absolute() and Path(str(file.filePath())).is_file()
    staged = tmp_path / "simulation/in.osm"
    staged.parent.mkdir()
    shutil.copy2(alone, staged)
    copy_model_resources(alone, staged)
    assert (
        Path(
            str(
                sdk[0]
                .osversion.VersionTranslator()
                .loadModel(str(staged))
                .get()
                .getExternalFiles()[0]
                .filePath()
            )
        ).name
        == Path(str(file.filePath())).name
    )
    assert (
        sdk[0]
        .osversion.VersionTranslator()
        .loadModel(str(staged))
        .get()
        .getExternalFiles()[0]
        .fileName()
    )


@pytest.mark.parametrize("workflow", ["{}", "{invalid json"])
def test_newer_non_csv_model_load_avoids_sdk(sdk, tmp_path, monkeypatch, workflow):
    model = sdk[0].model.Model()
    source = tmp_path / "newer.osm"
    model.save(str(source), True)
    source.write_bytes(source.read_bytes().replace(b"3.11.0", b"3.14.0"))
    source.with_suffix("").mkdir()
    (source.with_suffix("") / "workflow.osw").write_text(workflow)

    def forbidden(*args):
        raise AssertionError("Non-CSV load used the SDK")

    monkeypatch.setattr(sdk[0].osversion.VersionTranslator, "loadModel", forbidden)
    svc = service(tmp_path)
    result = svc.model_load(ModelLoadArgs(model_uri=source.as_uri()))
    assert not result["warnings"]
    snapshot = svc._resolve_model_path(
        svc._get_model_state(result["model_id"]).metadata["model_uri"]
    )
    assert snapshot.read_bytes() == source.read_bytes()


def test_missing_csv_loads_with_persistent_warning_then_fails_simulation(sdk, tmp_path):
    source = csv_model(sdk[0], tmp_path)
    (tmp_path / "sched.csv").unlink()
    svc = service(tmp_path)
    result = svc.model_load(ModelLoadArgs(model_uri=source.as_uri()))
    state = svc._get_model_state(result["model_id"])
    snapshot = svc._resolve_model_path(state.metadata["model_uri"])
    assert snapshot.read_bytes() == source.read_bytes()
    assert result["warnings"] and state.metadata["resource_warnings"]
    assert not snapshot.with_suffix("").exists()
    assert not svc.runtime_storage_usage()["unregistered_workspaces"]
    restarted = service(tmp_path)
    assert (
        restarted._get_model_state(result["model_id"]).metadata["resource_warnings"]
        == result["warnings"]
    )
    with pytest.raises(
        ValueError, match="Resource snapshot incomplete.*Cannot resolve external file"
    ):
        restarted._run_openstudio_cli_sync(
            "not-created", result["model_id"], {"epw_path": "replacement.epw"}
        )


def test_colliding_basenames_and_clone_hashes(sdk, tmp_path):
    source = csv_model(sdk[0], tmp_path, ("a/s.csv", "b/s.csv"))
    svc = service(tmp_path)
    session = svc.session_create(SessionCreateArgs(goal="CSV lineage"))["session"][
        "session_id"
    ]
    loaded = svc.model_load(
        ModelLoadArgs(model_uri=source.as_uri(), session_id=session)
    )
    assert not loaded["warnings"]
    snapshot = svc._resolve_model_path(
        svc._get_model_state(loaded["model_id"]).metadata["model_uri"]
    )
    model = sdk[0].osversion.VersionTranslator().loadModel(str(snapshot)).get()
    paths = [Path(str(f.filePath())) for f in model.getExternalFiles()]
    assert len(set(paths)) == 2 and all(p.is_file() for p in paths)
    assert {p.read_text().splitlines()[0] for p in paths} == {"1", "2"}
    clone = svc.model_clone(ModelCloneArgs(model_id=loaded["model_id"]))
    parent = svc.state_store.get_model_revision(loaded["model_revision_id"])
    child = svc.state_store.get_model_revision(clone["model_revision_id"])
    assert (
        child["source_sha256"]
        == parent["source_sha256"]
        == hashlib.sha256(snapshot.read_bytes()).hexdigest()
    )
    assert (
        svc.artifacts.must_get(loaded["model_id"]).metadata["original_source_sha256"]
        == hashlib.sha256(source.read_bytes()).hexdigest()
    )


def test_quota_checks_before_resource_copy(sdk, tmp_path, monkeypatch):
    source = csv_model(sdk[0], tmp_path)
    target = tmp_path / "out.osm"
    target.write_bytes(source.read_bytes())

    def forbidden(*args):
        raise AssertionError("Resource copied before size check")

    monkeypatch.setattr(shutil, "copy2", forbidden)
    with pytest.raises(ValueError, match="quota"):
        copy_model_resources(source, target, max_resource_bytes=1)
    assert not target.with_suffix("").exists()


def test_fatal_load_copy_failure_cleans_workspace(sdk, tmp_path):
    source = csv_model(sdk[0], tmp_path)
    svc = service(tmp_path)
    svc.workspace_manager.max_workspace_bytes = 1
    with pytest.raises(ValueError, match="quota"):
        svc.model_load(ModelLoadArgs(model_uri=source.as_uri()))
    assert not list((tmp_path / "runtime").glob("model-*"))


def test_native_load_measure_simulate_chain(sdk, tmp_path, monkeypatch):
    from vav_fixture import prepare_vav_fixture
    from openstudio_ai_mcp.runtime.measure_registry import MeasureSpec

    exe = Path("/Applications/OpenStudio-3.11.0/bin/openstudio")
    if not exe.is_file():
        pytest.skip("Native CLI required")
    source, _, _, _ = prepare_vav_fixture(sdk[0], tmp_path, True)
    model = sdk[0].osversion.VersionTranslator().loadModel(str(source)).get()
    # Existing fixture HVAC was removed; this test needs a valid native system.
    for zone in model.getThermalZones():
        zone.setUseIdealAirLoads(True)
    data = tmp_path / "sched.csv"
    data.write_text("0.5\n" * 8760)
    schedule = sdk[0].model.ScheduleFile(
        sdk[0].model.ExternalFile.getExternalFile(model, str(data), False).get(), 1, 0
    )
    model.getLightss()[0].setSchedule(schedule)
    model.save(str(source), True)
    svc = service(tmp_path)
    loaded = svc.model_load(ModelLoadArgs(model_uri=source.as_uri()))
    entry = tmp_path / "check_and_copy.py"
    entry.write_text("""import os, openstudio as o
from pathlib import Path
m=o.osversion.VersionTranslator().loadModel(os.environ['OSM_INPUT_PATH']).get()
for f in m.getExternalFiles():
    assert Path(str(f.filePath())).is_file(), str(f.filePath())
assert m.save(os.environ['OSM_OUTPUT_PATH'],True)
""")
    spec = MeasureSpec(
        "test-copy", entry, "Read schedule data then save model", True, 120, {}
    )
    monkeypatch.setattr(svc.measure_registry, "get", lambda _: spec)
    monkeypatch.setattr(svc.measure_registry, "normalize_args", lambda *args: {})
    monkeypatch.setattr(svc, "_openstudio_executable_or_none", lambda: str(exe))
    data.unlink()
    measured = svc.model_apply_measure(
        ModelApplyMeasureArgs(
            model_id=loaded["model_id"], measure_id="test-copy", args={}
        )
    )
    job = svc.job_manager.create_job(
        model_id=measured["model_id"], run_mode="sizing", options={}
    )
    result = svc._run_openstudio_cli_sync(job.job_id, measured["model_id"], {})
    assert result["severe_count"] == 0
    workspace = svc.workspace_manager.workspace_path(job.job_id)
    assert json.loads((workspace / "in.osw").read_text())["steps"] == []
    assert not list((workspace / "in/files").glob("*.epw"))


def test_sdk_unavailable_still_loads_for_inspection(sdk, tmp_path, monkeypatch):
    import sys

    source = csv_model(sdk[0], tmp_path)
    monkeypatch.setitem(sys.modules, "openstudio", None)
    svc = service(tmp_path)
    loaded = svc.model_load(ModelLoadArgs(model_uri=source.as_uri()))
    assert loaded["warnings"] and "openstudio" in loaded["warnings"][0]
    snapshot = svc._resolve_model_path(
        svc._get_model_state(loaded["model_id"]).metadata["model_uri"]
    )
    assert snapshot.read_bytes() == source.read_bytes()


def test_partial_resource_copy_restores_snapshot(sdk, tmp_path, monkeypatch):
    source = csv_model(sdk[0], tmp_path, ("a/s.csv", "b/s.csv"))
    original_copy = shutil.copy2
    copied = []

    def fail_second_resource(src, dst, *args, **kwargs):
        if Path(dst).parent.name == "files":
            copied.append(dst)
            if len(copied) == 2:
                raise OSError("resource copy failed")
        return original_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, "copy2", fail_second_resource)
    svc = service(tmp_path)
    loaded = svc.model_load(ModelLoadArgs(model_uri=source.as_uri()))
    snapshot = svc._resolve_model_path(
        svc._get_model_state(loaded["model_id"]).metadata["model_uri"]
    )
    assert copied and loaded["warnings"] == ["resource copy failed"]
    assert snapshot.read_bytes() == source.read_bytes()
    assert not snapshot.with_suffix("").exists()
    assert not svc.runtime_storage_usage()["unregistered_workspaces"]


@pytest.mark.parametrize("replacement", ["option", "set_weather"])
@pytest.mark.parametrize("has_csv", [False, True])
def test_weather_quota_warning_allows_replacement_simulation(
    sdk, tmp_path, monkeypatch, replacement, has_csv
):
    from vav_fixture import prepare_vav_fixture

    exe = Path("/Applications/OpenStudio-3.11.0/bin/openstudio")
    if not exe.is_file():
        pytest.skip("Native CLI required")
    source, _, _, _ = prepare_vav_fixture(sdk[0], tmp_path, True)
    model = sdk[0].osversion.VersionTranslator().loadModel(str(source)).get()
    for zone in model.getThermalZones():
        zone.setUseIdealAirLoads(True)
    if has_csv:
        csv = tmp_path / "schedule.csv"
        csv.write_text("0.5\n" * 8760)
        schedule = sdk[0].model.ScheduleFile(
            sdk[0].model.ExternalFile.getExternalFile(model, str(csv), False).get(),
            1,
            0,
        )
        model.getLightss()[0].setSchedule(schedule)
    model.save(str(source), True)
    weather = Path(__file__).parent / "fixtures/USA_FL_Tampa.Intl.AP.722110_TMY3.epw"
    weather = weather.resolve()
    svc = service(tmp_path)
    original_quota = svc.workspace_manager.max_workspace_bytes
    svc.workspace_manager.max_workspace_bytes = source.stat().st_size + 200_000
    loaded = svc.model_load(ModelLoadArgs(model_uri=source.as_uri()))
    assert loaded["warnings"] == ["Weather exceeds remaining workspace quota"]
    state = svc._get_model_state(loaded["model_id"])
    assert not state.metadata["resource_warnings"]
    assert state.metadata["weather_warnings"] == loaded["warnings"]
    clone = svc.model_clone(ModelCloneArgs(model_id=loaded["model_id"]))
    svc = service(tmp_path)
    state = svc._get_model_state(clone["model_id"])
    assert state.metadata["weather_warnings"] == loaded["warnings"]
    svc.workspace_manager.max_workspace_bytes = original_quota
    monkeypatch.setattr(svc, "_openstudio_executable_or_none", lambda: str(exe))
    if replacement == "option":
        options = {"epw_path": str(weather)}
    else:
        svc.model_set_weather(
            ModelSetWeatherArgs(model_id=clone["model_id"], epw_path=str(weather))
        )
        options = {}
    job = svc.job_manager.create_job(
        model_id=clone["model_id"], run_mode="sizing", options=options
    )
    result = svc._run_openstudio_cli_sync(job.job_id, clone["model_id"], options)
    assert result["severe_count"] == 0
    workspace = svc.workspace_manager.workspace_path(job.job_id)
    assert (workspace / weather.name).read_bytes() == weather.read_bytes()
