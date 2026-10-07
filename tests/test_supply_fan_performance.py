"""Observable fan performance edits, ownership and protected-state regressions."""

import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import pytest
from test_vav_preflight import sdk, model_file, SCRIPTS

sys.path.insert(0, str(SCRIPTS))
from common import cav_system, fan_edit, model_transaction as tx
from common.hvac_inventory import inventory as hvac_inventory
from common.vav_plan import plan as vav_plan
from common.vav_create import create as create_vav
from common.version_guard import CompatibilityError
from vav_fixture import prepare_vav_fixture

OPERATION = "edit_supply_fan_performance"


def served_model(native, model_file, tmp_path, kind="VariableVolume"):
    model = native.model.Model.load(str(model_file)).get()
    config = dict(
        system_name="Existing Air Loop",
        defaults_profile="prototype_vav_v1",
        output_model_path=str(tmp_path / "unused.osm"),
        target_zones=[{"name": "Zone 1"}],
        central_heating={"type": "Electricity"},
        central_cooling={"type": "DXTwoSpeed", "dx_approved": True},
        reheat={"type": "Electricity"},
    )
    if kind == "VariableVolume":
        planned = vav_plan(config, hvac_inventory(model), None)
        assert planned["ready"], planned
        create_vav(model, native, planned)
    else:
        config.update(
            defaults_profile="prototype_cav_v1",
            outdoor_air_schedule=None,
            central_heating={"type": "Water", "plant_loop": {"name": "HW"}},
            reheat={"type": "Water", "plant_loop": {"name": "HW"}},
        )
        planned = cav_system.plan(model, native, config)
        assert planned["ready"], planned
        cav_system.create(model, native, planned)
    fan = getattr(model, "getFan" + kind + "s")()[0]
    fan.additionalProperties().setFeature("review_note", "retain")
    model.save(str(model_file), True)
    return model, fan


def config(tmp_path):
    return dict(
        output_model_path=str(tmp_path / "replaced.osm"),
        air_loop={"name": "Existing Air Loop"},
        fan={"total_efficiency": 0.7, "pressure_rise": 3.0, "pressure_units": "inH2O"},
    )


def preflight(source, cfg):
    return tx.preflight(source, cfg, OPERATION, fan_edit.plan)


def apply(report, tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(report))
    return tx.apply(
        path,
        OPERATION,
        fan_edit.plan,
        fan_edit.edit,
        fan_edit.validate_model,
    )


@pytest.mark.parametrize("kind", ["VariableVolume", "ConstantVolume"])
def test_edit_preserves_saved_state_and_changes_only_requested_values(
    sdk, model_file, tmp_path, kind
):
    native = sdk[0]
    _, old = served_model(native, model_file, tmp_path, kind)
    original = model_file.read_bytes()
    report = preflight(model_file, config(tmp_path))
    assert report["ready"], report
    assert report == preflight(model_file, config(tmp_path))
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and result["translation"]["ok"], result
    model = native.model.Model.load(result["output_model_path"]).get()
    fan = getattr(model, "getFan" + kind + "s")()[0]
    assert fan.handle() == old.handle()
    assert fan.additionalProperties().handle() == old.additionalProperties().handle()
    assert fan.nameString() == old.nameString()
    assert fan.fanEfficiency() == 0.7
    assert fan.pressureRise() == pytest.approx(747.26673)
    assert fan.motorEfficiency() == old.motorEfficiency()
    assert fan.availabilitySchedule().handle() == old.availabilitySchedule().handle()
    assert fan.isMaximumFlowRateAutosized() == old.isMaximumFlowRateAutosized()
    assert (
        fan.additionalProperties().getFeatureAsString("review_note").get() == "retain"
    )
    assert model_file.read_bytes() == original
    assert result["validation"]["checks"] >= 10
    with pytest.raises(ValueError):
        apply(report, tmp_path)


def test_partial_inputs_do_not_replace_or_infer_values(sdk, model_file, tmp_path):
    served_model(sdk[0], model_file, tmp_path)
    cfg = dict(output_model_path=str(tmp_path / "replaced.osm"))
    report = preflight(model_file, cfg)
    assert not report["ready"]
    assert report["plan"]["missing_inputs"] == ["air_loop", "fan"]
    with pytest.raises(ValueError, match="ready"):
        apply(report, tmp_path)
    assert not (tmp_path / "replaced.osm").exists()


@pytest.mark.parametrize(
    "changed", ["unrequested_fan", "thermostat", "plant", "extra_fan", "wrong_setter"]
)
def test_bad_edit_does_not_publish(sdk, model_file, tmp_path, monkeypatch, changed):
    served_model(sdk[0], model_file, tmp_path)
    report = preflight(model_file, config(tmp_path))
    original_replace = fan_edit.edit
    if changed == "wrong_setter":
        monkeypatch.setattr(
            sdk[0].model.FanVariableVolume, "setFanEfficiency", lambda *args: True
        )
    else:

        def bad_replace(model, native, planned):
            result = original_replace(model, native, planned)
            fan = model.getFanVariableVolumes()[0]
            if changed == "unrequested_fan":
                fan.setFanPowerCoefficient1(0.9)
            elif changed == "thermostat":
                model.getThermostatSetpointDualSetpoints()[
                    0
                ].resetHeatingSetpointTemperatureSchedule()
            elif changed == "plant":
                model.getPlantLoops()[0].sizingPlant().setDesignLoopExitTemperature(70)
            else:
                native.model.FanConstantVolume(model)
            return result

        monkeypatch.setattr(fan_edit, "edit", bad_replace)
    with pytest.raises(ValueError, match="validation"):
        apply(report, tmp_path)
    assert not (tmp_path / "replaced.osm").exists()
    assert not (tmp_path / "replaced").exists()


@pytest.mark.parametrize("kind", ["VariableVolume", "ConstantVolume"])
@pytest.mark.parametrize("position", ["inlet", "middle"])
def test_other_direct_supply_positions_and_fixed_flow(
    sdk, model_file, tmp_path, kind, position
):
    model, fan = served_model(sdk[0], model_file, tmp_path, kind)
    loop = model.getAirLoopHVACs()[0]
    node = (
        loop.supplyInletNode()
        if position == "inlet"
        else model.getCoilCoolingDXTwoSpeeds()[0]
        .inletModelObject()
        .get()
        .to_Node()
        .get()
    )
    assert fan.removeFromLoop()
    assert fan.addToNode(node)
    fan.setMaximumFlowRate(2.5)
    boundary = fan.outletModelObject().get().to_Node().get()
    manager = sdk[0].model.SetpointManagerScheduled(
        model, model.getScheduleRulesets()[0]
    )
    assert manager.addToNode(boundary)
    manager_handle, boundary_handle = str(manager.handle()), str(boundary.handle())
    model.save(str(model_file), True)
    cfg = config(tmp_path)
    cfg["fan"] = {"motor_efficiency": 0.95}
    result = apply(preflight(model_file, cfg), tmp_path)
    saved = sdk[0].model.Model.load(result["output_model_path"]).get()
    edited = getattr(saved, "getFan" + kind + "s")()[0]
    assert edited.maximumFlowRate().get() == 2.5
    assert not edited.isMaximumFlowRateAutosized()
    assert edited.motorEfficiency() == 0.95
    assert edited.fanEfficiency() == fan.fanEfficiency()
    saved_manager = saved.getSetpointManagerScheduled(
        sdk[0].toUUID(manager_handle)
    ).get()
    assert str(saved_manager.setpointNode().get().handle()) == boundary_handle


@pytest.mark.parametrize("bad", ["multiple", "embedded", "other_class", "missing"])
def test_unsupported_targets_are_blocked(sdk, model_file, tmp_path, bad):
    native = sdk[0]
    model, fan = served_model(native, model_file, tmp_path)
    loop = model.getAirLoopHVACs()[0]
    if bad == "multiple":
        native.model.FanConstantVolume(model).addToNode(loop.supplyInletNode())
    elif bad == "embedded":
        fan.removeFromLoop()
        unitary = native.model.AirLoopHVACUnitarySystem(model)
        unitary.setSupplyFan(fan)
        unitary.addToNode(loop.supplyOutletNode())
    elif bad == "other_class":
        fan.remove()
        native.model.FanOnOff(model).addToNode(loop.supplyOutletNode())
    model.save(str(model_file), True)
    cfg = config(tmp_path)
    if bad == "missing":
        cfg["air_loop"] = {"name": "Missing Loop"}
    report = preflight(model_file, cfg)
    assert not report["ready"] and report["plan"]["errors"]
    assert not (tmp_path / "replaced.osm").exists()


@pytest.mark.parametrize(
    "bad",
    ["partial_pressure", "inefficient_motor", "noop", "unknown", "nan", "overflow"],
)
def test_bad_inputs_do_not_approve_an_edit(sdk, model_file, tmp_path, bad):
    _, fan = served_model(sdk[0], model_file, tmp_path)
    cfg = config(tmp_path)
    if bad == "partial_pressure":
        del cfg["fan"]["pressure_units"]
    elif bad == "inefficient_motor":
        cfg["fan"] = {"motor_efficiency": 0.5}
    elif bad == "noop":
        cfg["fan"] = {"total_efficiency": fan.fanEfficiency()}
    elif bad == "unknown":
        cfg["fan"]["type"] = "ConstantVolume"
    elif bad == "nan":
        cfg["fan"]["total_efficiency"] = float("nan")
    else:
        cfg["fan"]["pressure_rise"] = 1e308
    if bad in ("unknown", "nan"):
        with pytest.raises(ValueError, match="Invalid fan performance"):
            preflight(model_file, cfg)
    else:
        assert not preflight(model_file, cfg)["ready"]
    assert not (tmp_path / "replaced.osm").exists()


@pytest.mark.parametrize("bad", ["stale", "parameters", "operation", "companion"])
def test_changed_plan_or_resources_block_apply(sdk, model_file, tmp_path, bad):
    served_model(sdk[0], model_file, tmp_path)
    if bad == "companion":
        source, _, _, _ = prepare_vav_fixture(sdk[0], tmp_path, True)
        # The existing served fixture is enough for source hash checks, but weather
        # must be explicitly attached to bind a companion resource into its plan.
        model = sdk[0].model.Model.load(str(model_file)).get()
        weather = source.with_name(source.stem + "_files") / "weather.epw"
        sdk[0].model.WeatherFile.setWeatherFile(model, sdk[0].EpwFile(str(weather)))
        model.save(str(model_file), True)
    report = preflight(model_file, config(tmp_path))
    assert report["ready"], report
    if bad == "stale":
        model_file.write_bytes(model_file.read_bytes() + b"\n")
    elif bad == "parameters":
        report["plan"]["parameters"]["fan"]["total_efficiency"] = 0.8
    elif bad == "operation":
        report["operation"] = "create_cav_system"
    else:
        resource = Path(report["plan"]["companions"]["resources"][0]["source"])
        resource.write_bytes(resource.read_bytes() + b"\n")
    with pytest.raises(ValueError):
        apply(report, tmp_path)
    assert not (tmp_path / "replaced.osm").exists()


def native_cli():
    path = Path(
        os.environ.get(
            "OPENSTUDIO_SKILL_TEST_EXE",
            "/Applications/OpenStudio-3.11.0/bin/openstudio",
        )
    )
    if not path.is_file():
        pytest.skip("Native 3.11.0 CLI required")
    return path


def test_incompatible_sdk_blocks_before_input_access(sdk, tmp_path, monkeypatch):
    monkeypatch.setattr(sdk[0], "openStudioVersion", lambda: "3.12.0")
    with pytest.raises(CompatibilityError, match="3.11.0"):
        preflight(tmp_path / "missing.osm", config(tmp_path))
    assert not (tmp_path / "replaced.osm").exists()


@pytest.mark.parametrize(
    "kind,use_csv", [("VariableVolume", False), ("ConstantVolume", True)]
)
def test_native_edit_design_day_and_companion_move(sdk, tmp_path, kind, use_csv):
    native = sdk[0]
    source, base, _, _ = prepare_vav_fixture(native, tmp_path, True)
    model = native.osversion.VersionTranslator().loadModel(str(source)).get()
    workflow = source.with_name(source.stem + "_files") / "workflow.osw"
    csv = None
    if use_csv:
        model.workflowJSON().setOswPath(str(workflow))
        csv = workflow.parent / "load.csv"
        csv.write_text("value\n" + "0.5\n" * 8760)
        external = native.model.ExternalFile.getExternalFile(model, str(csv)).get()
        schedule = native.model.ScheduleFile(external)
        schedule.setRowstoSkipatTop(1)
        model.getLightss()[0].setSchedule(schedule)
    if kind == "VariableVolume":
        create_vav(model, native, vav_plan(base, hvac_inventory(model), None))
    else:
        base.update(
            defaults_profile="prototype_cav_v1",
            outdoor_air_schedule={"builtin": "AlwaysOnDiscrete"},
        )
        cav_system.create(model, native, cav_system.plan(model, native, base))
    model.save(str(source), True)
    cfg = config(tmp_path)
    cfg["air_loop"] = {"name": base["system_name"]}
    result = apply(preflight(source, cfg), tmp_path)
    moved = tmp_path / "moved"
    moved.mkdir()
    shutil.move(result["output_model_path"], moved / "replaced.osm")
    shutil.move(result["companion_directory"], moved / "replaced")
    if csv:
        csv.unlink()
    workflow = moved / "replaced/workflow.osw"
    run = subprocess.run(
        [str(native_cli()), "run", "-w", str(workflow)],
        cwd=workflow.parent,
        capture_output=True,
        text=True,
        timeout=120,
    )
    (tmp_path / "cli.log").write_text(run.stdout + run.stderr)
    assert run.returncode == 0, run.stdout + run.stderr
    errors = (workflow.parent / "run/eplusout.err").read_text()
    assert "** Severe **" not in errors and "**  Fatal  **" not in errors, errors
    assert "EnergyPlus Completed Successfully" in errors
    with sqlite3.connect(workflow.parent / "run/eplusout.sql") as sql:
        flows = sql.execute(
            "SELECT Value FROM ComponentSizes WHERE CompType = ? AND Description = 'Design Size Maximum Flow Rate'",
            ("Fan:" + kind,),
        ).fetchall()
    assert len(flows) == 1 and flows[0][0] > 0, flows


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_native_bundle_after_relocation(sdk, model_file, tmp_path, host):
    from adapters.claude_code_adapter import ClaudeCodeAdapter
    from adapters.codex_adapter import CodexAdapter
    from adapters.contracts import HostAdapterConfig

    served_model(sdk[0], model_file, tmp_path)
    setup = HostAdapterConfig(
        host_name=host, workspace_root=Path.cwd(), runtime_mode="marketplace"
    )
    adapter = ClaudeCodeAdapter(setup) if host == "claude" else CodexAdapter(setup)
    exported = tmp_path / "export"
    adapter.export_plugin(exported, dry_run=False)
    skill = next(
        exported.rglob("openstudio-supply-fan-performance-editor/SKILL.md")
    ).parent
    moved = tmp_path / "relocated"
    shutil.copytree(skill, moved)
    shutil.rmtree(exported)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config(tmp_path)))
    script = moved / "scripts/edit_supply_fan_performance.py"
    exe = str(native_cli())
    plan_path = tmp_path / "reviewed.json"
    for args in (
        ["--input", str(model_file), "--config", str(cfg), "--report", str(plan_path)],
        ["--plan", str(plan_path), "--report", str(tmp_path / "applied.json")],
    ):
        run = subprocess.run(
            [exe, "execute_python_script", str(script), *args],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert run.returncode == 0, run.stdout + run.stderr
    applied = json.loads((tmp_path / "applied.json").read_text())
    assert applied["validation"]["ok"] and applied["translation"]["ok"]


@pytest.mark.parametrize("kind", ["VariableVolume", "ConstantVolume"])
@pytest.mark.parametrize("reference_kind", ["lifecycle_cost", "ems_actuator"])
def test_in_place_edit_preserves_incoming_references(
    sdk, model_file, tmp_path, kind, reference_kind
):
    native = sdk[0]
    model, fan = served_model(native, model_file, tmp_path, kind)
    if reference_kind == "lifecycle_cost":
        reference = native.model.LifeCycleCost.createLifeCycleCost(
            "Fan maintenance", fan, 100.0, "CostPerEach", "Maintenance", 1, 0
        ).get()
    else:
        reference = native.model.EnergyManagementSystemActuator(
            fan, "Fan", "Fan Air Mass Flow Rate"
        )
    reference_handle = str(reference.handle())
    fan_handle = str(fan.handle())
    metadata_handle = str(fan.additionalProperties().handle())
    connections = {
        str(obj.handle())
        for obj in model.modelObjects()
        if obj.iddObjectType().valueName() == "OS_Connection"
    }
    # Raw target UUIDs are important: names alone would hide replacement.
    reference_fields = str(reference.idfObject())
    model.save(str(model_file), True)
    result = apply(preflight(model_file, config(tmp_path)), tmp_path)
    saved = native.model.Model.load(result["output_model_path"]).get()
    assert result["changes"]["fan"]["handle"] == fan_handle
    edited = saved.getModelObject(native.toUUID(fan_handle)).get()
    assert str(edited.additionalProperties().handle()) == metadata_handle
    assert {
        str(obj.handle())
        for obj in saved.modelObjects()
        if obj.iddObjectType().valueName() == "OS_Connection"
    } == connections
    saved_reference = saved.getModelObject(native.toUUID(reference_handle)).get()
    assert str(saved_reference.idfObject()) == reference_fields
    assert fan_handle in str(saved_reference.idfObject())


@pytest.mark.parametrize("recipe_name", ["VAV", "PROTOTYPE_CAV"])
@pytest.mark.parametrize(
    "missing", ["total_efficiency", "motor_efficiency", "pressure_rise_pa"]
)
def test_system_fan_factory_rejects_incomplete_performance_before_creation(
    sdk, recipe_name, missing
):
    from common import air_system_recipe
    from common.air_loop_components import attach_fan

    native = sdk[0]
    model = native.model.Model()
    loop = native.model.AirLoopHVAC(model)
    before_handles = {str(x.handle()) for x in model.modelObjects()}
    performance = dict(total_efficiency=0.7, motor_efficiency=0.9, pressure_rise_pa=750)
    del performance[missing]
    with pytest.raises(ValueError, match=f"Missing fan performance values: {missing}"):
        attach_fan(
            model,
            native,
            loop,
            {"fan": performance},
            {},
            {},
            recipe=getattr(air_system_recipe, recipe_name),
        )
    assert {str(x.handle()) for x in model.modelObjects()} == before_handles


def test_full_performance_setter_rejects_before_mutating(sdk):
    from common.fan_equipment import set_performance

    fan = sdk[0].model.FanVariableVolume(sdk[0].model.Model())
    original = fan.fanEfficiency()
    with pytest.raises(ValueError, match="Missing fan performance"):
        set_performance(fan, {"total_efficiency": 0.8})
    assert fan.fanEfficiency() == original
    set_performance(fan, {"total_efficiency": 0.8}, partial=True)
    assert fan.fanEfficiency() == 0.8


@pytest.mark.parametrize(
    "value,units", [(0, "Pa"), (750, "Pa"), (0, "inH2O"), (3, "inH2O")]
)
def test_shared_pressure_conversion_agrees_with_pinned_sdk(sdk, value, units):
    from common.fan_equipment import pressure_pa

    native_units = "inH_{2}O" if units == "inH2O" else units
    expected = sdk[0].convert(value, native_units, "Pa").get()
    assert pressure_pa(value, units) == pytest.approx(expected)


@pytest.mark.parametrize("kind", ["VariableVolume", "ConstantVolume"])
@pytest.mark.parametrize("position", ["inlet", "middle", "end"])
def test_deferred_clone_reconnect_primitive_preserves_boundary_nodes(
    sdk, model_file, tmp_path, kind, position
):
    from common.fan_replacement import clone_and_reconnect

    native = sdk[0]
    model, fan = served_model(native, model_file, tmp_path, kind)
    loop = model.getAirLoopHVACs()[0]
    if position != "end":
        node = (
            loop.supplyInletNode()
            if position == "inlet"
            else (
                model.getCoilCoolingDXTwoSpeeds()[0]
                .inletModelObject()
                .get()
                .to_Node()
                .get()
            )
        )
        assert fan.removeFromLoop()
        assert fan.addToNode(node)
    fan.setMaximumFlowRate(2.5)
    planned = fan_edit.plan(model, native, config(tmp_path))
    nodes = {str(x.handle()) for x in model.getNodes()}
    result = clone_and_reconnect(model, native, planned)
    replacement = fan_edit.fan_object(model, native, result["replacement_fan"])
    assert not model.getModelObject(fan.handle()).is_initialized()
    assert replacement.handle() != fan.handle()
    assert fan_edit.ports(replacement) == planned["resolved_objects"]["ports"]
    assert {str(x.handle()) for x in model.getNodes()} == nodes
    assert replacement.maximumFlowRate().get() == 2.5
    assert (
        replacement.additionalProperties().getFeatureAsString("review_note").get()
        == "retain"
    )
    assert replacement.nameString() == planned["resolved_objects"]["fan"]["name"]
    assert fan_edit.values(replacement) == planned["after_values"]
