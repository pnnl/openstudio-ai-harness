"""Saved water-coil identity, attachment topology and controller lifecycle."""

import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import pytest
from test_vav_preflight import sdk, SCRIPTS
from vav_fixture import prepare_vav_fixture
from test_supply_fan_performance import native_cli

sys.path.insert(0, str(SCRIPTS))
from common import water_coil as coils, model_transaction as tx
from common.coil_equipment import CLASSES, ratings, node_ports, optional_value
from common.vav_plan import plan as vav_plan
from common.vav_create import create as create_vav
from common.hvac_inventory import inventory as hvac_inventory


def fixture(native, tmp_path, kind, mode, system_kind="VAV"):
    source, cfg, _, _ = prepare_vav_fixture(native, tmp_path, True)
    model = native.model.Model.load(str(source)).get()
    if system_kind == "VAV":
        planned = vav_plan(cfg, hvac_inventory(model), None)
        assert planned["ready"], planned
        create_vav(model, native, planned)
    else:
        from common import cav_system

        cfg.update(
            defaults_profile="prototype_cav_v1",
            outdoor_air_schedule={"builtin": "AlwaysOnDiscrete"},
        )
        planned = cav_system.plan(model, native, cfg)
        assert planned["ready"], planned
        cav_system.create(model, native, planned)
    loop = model.getAirLoopHVACs()[0]
    coil = next(
        c
        for c in getattr(model, "get" + CLASSES[kind] + "s")()
        if c.airLoopHVAC().is_initialized()
    )
    reference = coils.ref(coil)
    coil.additionalProperties().setFeature("review_note", "keep")
    if mode == "attach":
        coil.remove()
    model.save(str(source), True)
    if mode in ("edit", "settings"):
        cfg = dict(
            output_model_path=str(tmp_path / "edited.osm"),
            coil={"handle": reference["handle"]},
            ratings=(
                dict(rated_outlet_air_temperature_c=33)
                if kind == "Heating"
                else dict(design_inlet_water_temperature_c=6.666667)
            ),
        )
        if mode == "settings":
            cfg.update(
                coil_name="Reviewed Coil",
                controller_name="Reviewed Controller",
                availability_schedule={"builtin": "AlwaysOnDiscrete"},
                sizing="Autosize",
                controller=dict(
                    control_variable="Temperature",
                    minimum_flow_m3_s=0,
                    convergence_tolerance_k=0.1,
                ),
            )
    else:
        cfg = dict(
            output_model_path=str(tmp_path / "connected.osm"),
            operation="attach",
            air_loop={"handle": str(loop.handle())},
            plant_loop={"name": "Fixture HW" if kind == "Heating" else "Fixture CHW"},
            coil_name="Reviewed Coil",
            availability_schedule={"builtin": "AlwaysOnDiscrete"},
            sizing="Autosize",
            controller=dict(
                control_variable="Temperature",
                minimum_flow_m3_s=0,
                convergence_tolerance_k=0.1,
            ),
            kind=kind,
            air_node={"handle": str(loop.supplyOutletNode().handle())},
            design=(
                dict(
                    rated_inlet_water_temperature_c=82.222222,
                    rated_outlet_water_temperature_c=71.111111,
                    rated_inlet_air_temperature_c=16.6,
                    rated_outlet_air_temperature_c=32.2,
                )
                if kind == "Heating"
                else dict(
                    design_inlet_water_temperature_c=6.666667,
                    design_inlet_air_temperature_c=26.7,
                    design_outlet_air_temperature_c=12.8,
                    design_inlet_air_humidity_ratio=0.011,
                    design_outlet_air_humidity_ratio=0.008,
                    heat_exchanger_configuration="CrossFlow",
                    type_of_analysis="SimpleAnalysis",
                )
            ),
        )
    return source, cfg, reference


def preflight(source, cfg, mode):
    op = "edit_water_coil" if mode in ("edit", "settings") else "connect_water_coil"
    planner = coils.plan_edit if mode in ("edit", "settings") else coils.plan_connection
    return tx.preflight(source, cfg, op, planner)


def apply(report, tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(report))
    planner = (
        coils.plan_edit
        if report["operation"] == "edit_water_coil"
        else coils.plan_connection
    )
    return tx.apply(
        path, report["operation"], planner, coils.change, coils.validate_model
    )


@pytest.mark.parametrize("kind", ["Heating", "Cooling"])
@pytest.mark.parametrize("mode", ["edit", "attach", "settings"])
def test_saved_modes_preserve_scoped_state(sdk, tmp_path, kind, mode):
    native = sdk[0]
    src, cfg, old = fixture(native, tmp_path, kind, mode)
    original = src.read_bytes()
    report = preflight(src, cfg, mode)
    assert report["ready"], report
    assert report == preflight(src, cfg, mode)
    assert report == preflight(src, json.loads(json.dumps(cfg, sort_keys=True)), mode)
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and result["translation"]["ok"]
    assert src.read_bytes() == original
    saved = native.model.Model.load(result["output_model_path"]).get()
    new = result["changes"]["coil"]
    coil = coils.object_by_ref(saved, native, new, CLASSES[kind])
    assert ratings(coil, kind) == report["plan"]["after_values"]
    assert (
        new["handle"] == old["handle"]
        if mode in ("edit", "settings")
        else new["handle"] != old["handle"]
    )
    if mode != "attach":
        assert (
            coil.additionalProperties().getFeatureAsString("review_note").get()
            == "keep"
        )
    if mode == "settings":
        assert saved.getModelObject(native.toUUID(old["handle"])).is_initialized()
        assert node_ports(coil) == report["plan"]["resolved_objects"]["ports"]
    with pytest.raises(ValueError):
        apply(report, tmp_path)


@pytest.mark.parametrize("kind", ["Heating", "Cooling"])
@pytest.mark.parametrize("reference_kind", ["ems", "cost"])
def test_rating_and_full_settings_edits_keep_incoming_references(
    sdk, tmp_path, kind, reference_kind
):
    native = sdk[0]
    src, cfg, reference = fixture(native, tmp_path, kind, "edit")
    model = native.model.Model.load(str(src)).get()
    coil = coils.object_by_ref(model, native, reference, CLASSES[kind])
    if reference_kind == "ems":
        obj = native.model.EnergyManagementSystemActuator(
            coil, "Coil", "On/Off Supervisory"
        )
    else:
        obj = native.model.LifeCycleCost.createLifeCycleCost(
            "Maintenance", coil, 100, "CostPerEach", "Maintenance", 1, 0
        ).get()
    original_ref = str(obj.idfObject())
    handle = obj.handle()
    controller = coil.controllerWaterCoil().get().handle()
    ports = node_ports(coil)
    model.save(str(src), True)
    result = apply(preflight(src, cfg, "edit"), tmp_path)
    saved = native.model.Model.load(result["output_model_path"]).get()
    assert str(saved.getModelObject(handle).get().idfObject()) == original_ref
    edited = coils.object_by_ref(saved, native, reference, CLASSES[kind])
    assert edited.controllerWaterCoil().get().handle() == controller
    assert node_ports(edited) == ports
    cfg.update(
        output_model_path=str(tmp_path / "settings.osm"),
        coil_name="Reconfigured Coil",
        controller_name="Reconfigured Controller",
        availability_schedule={"builtin": "AlwaysOnDiscrete"},
        sizing="Autosize",
        controller=dict(convergence_tolerance_k=0.1),
    )
    result = apply(preflight(src, cfg, "settings"), tmp_path)
    saved = native.model.Model.load(result["output_model_path"]).get()
    edited = coils.object_by_ref(saved, native, reference, CLASSES[kind])
    assert str(saved.getModelObject(handle).get().idfObject()) == original_ref
    assert edited.controllerWaterCoil().get().handle() == controller
    assert node_ports(edited) == ports
    assert edited.nameString() == "Reconfigured Coil"
    assert edited.controllerWaterCoil().get().nameString() == "Reconfigured Controller"


@pytest.mark.parametrize("mode", ["edit", "attach", "settings"])
def test_missing_choices_stay_unready(sdk, tmp_path, mode):
    source, cfg, _ = fixture(sdk[0], tmp_path, "Heating", mode)
    cfg = {"output_model_path": str(tmp_path / "out.osm")}
    report = preflight(source, cfg, mode)
    assert not report["ready"] and report["plan"]["missing_inputs"]
    with pytest.raises(ValueError, match="ready"):
        apply(report, tmp_path)
    assert not (tmp_path / "out.osm").exists()


@pytest.mark.parametrize(
    "bad",
    [
        "wrong_plant",
        "missing_pump",
        "missing_source",
        "missing_spm",
        "inverted_air",
        "inverted_water",
        "missing_temperature",
        "no_setpoint",
        "foreign_node",
        "foreign_fields",
        "bad_units",
        "nan",
        "empty_demand",
    ],
)
def test_attachment_checks_inputs_and_plant(sdk, tmp_path, bad):
    native = sdk[0]
    src, cfg, _ = fixture(native, tmp_path, "Heating", "attach")
    model = native.model.Model.load(str(src)).get()
    plant = model.getPlantLoopByName("Fixture HW").get()
    if bad == "wrong_plant":
        cfg["plant_loop"] = {"name": "Fixture CHW"}
    elif bad == "missing_pump":
        (
            model.getPumpVariableSpeeds()[0].remove()
            if model.getPumpVariableSpeeds()[0].plantLoop().get().handle()
            == plant.handle()
            else next(
                x
                for x in model.getPumpVariableSpeeds()
                if x.plantLoop().get().handle() == plant.handle()
            ).remove()
        )
    elif bad == "missing_source":
        model.getDistrictHeatingWaters()[0].remove()
    elif bad == "missing_spm":
        plant.supplyOutletNode().setpointManagers()[0].remove()
    elif bad == "inverted_air":
        cfg["design"]["rated_outlet_air_temperature_c"] = 10
    elif bad == "inverted_water":
        cfg["design"]["rated_outlet_water_temperature_c"] = 90
    elif bad == "missing_temperature":
        del cfg["design"]["rated_inlet_air_temperature_c"]
    elif bad == "no_setpoint":
        model.getAirLoopHVACs()[0].supplyOutletNode().setpointManagers()[0].remove()
    elif bad == "foreign_node":
        cfg["air_node"] = {"handle": str(plant.supplyOutletNode().handle())}
    elif bad == "foreign_fields":
        cfg["design"]["design_air_flow_m3_s"] = 1
    elif bad == "bad_units":
        cfg["design"]["rated_inlet_water_temperature_c"] = "180F"
    elif bad == "nan":
        cfg["design"]["rated_inlet_water_temperature_c"] = float("nan")
    else:
        for x in list(plant.demandComponents()):
            if x.to_PipeAdiabatic().is_initialized():
                x.remove()
    model.save(str(src), True)
    if bad in ("bad_units", "nan", "foreign_fields"):
        with pytest.raises(ValueError, match="Invalid"):
            preflight(src, cfg, "attach")
    else:
        report = preflight(src, cfg, "attach")
        if bad in ("empty_demand", "missing_temperature"):
            assert report["ready"], report
            assert apply(report, tmp_path)["validation"]["ok"]
        else:
            assert not report["ready"], report


@pytest.mark.parametrize(
    "mutated", ["rating", "controller", "neighbor", "plant", "extra_coil", "extra_node"]
)
@pytest.mark.parametrize("mode", ["edit", "attach", "settings"])
def test_bad_changes_are_not_published(sdk, tmp_path, monkeypatch, mutated, mode):
    source, cfg, _ = fixture(sdk[0], tmp_path, "Heating", mode)
    report = preflight(source, cfg, mode)
    original = coils.change

    def bad(model, native, planned):
        result = original(model, native, planned)
        coil = coils.object_by_ref(model, native, result["coil"], "CoilHeatingWater")
        if mutated == "rating":
            coil.setRatedOutletAirTemperature(40)
        elif mutated == "controller":
            coil.controllerWaterCoil().get().setMinimumActuatedFlow(0.1)
        elif mutated == "neighbor":
            model.getFanVariableVolumes()[0].setFanEfficiency(0.5)
        elif mutated == "plant":
            coil.plantLoop().get().sizingPlant().setDesignLoopExitTemperature(60)
        elif mutated == "extra_coil":
            native.model.CoilHeatingWater(model)
        else:
            native.model.Node(model)
        return result

    monkeypatch.setattr(coils, "change", bad)
    with pytest.raises(ValueError, match="validation"):
        apply(report, tmp_path)
    assert not Path(cfg["output_model_path"]).exists()
    assert not Path(cfg["output_model_path"]).with_suffix("").exists()


@pytest.mark.parametrize("kind", ["Heating", "Cooling"])
@pytest.mark.parametrize("mode", ["edit", "attach", "settings"])
@pytest.mark.parametrize("system_kind", ["VAV", "CAV"])
def test_native_design_days(sdk, tmp_path, kind, mode, system_kind):
    source, cfg, _ = fixture(sdk[0], tmp_path, kind, mode, system_kind=system_kind)
    report = preflight(source, cfg, mode)
    assert report["ready"], report
    result = apply(report, tmp_path)
    moved = tmp_path / "moved"
    moved.mkdir()
    target = moved / Path(result["output_model_path"]).name
    shutil.move(result["output_model_path"], target)
    folder = moved / target.stem
    shutil.move(result["companion_directory"], folder)
    workflow = folder / "workflow.osw"
    run = subprocess.run(
        [str(native_cli()), "run", "-w", str(workflow)],
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
        and "** Severe **" not in errors
        and "**  Fatal  **" not in errors
    ), errors
    desc = (
        "Design Size Rated Capacity"
        if kind == "Heating"
        else "Design Size Design Coil Load"
    )
    with sqlite3.connect(folder / "run/eplusout.sql") as sql:
        rows = sql.execute(
            "SELECT Value FROM ComponentSizes WHERE CompType=? AND upper(CompName)=? AND Description=?",
            (
                "Coil:" + kind + ":Water",
                result["changes"]["coil"]["name"].upper(),
                desc,
            ),
        ).fetchall()
    assert len(rows) == 1 and rows[0][0] > 0, rows


@pytest.mark.parametrize("mode", ["edit", "attach", "settings"])
@pytest.mark.parametrize("bad", ["stale", "tampered", "wrong_operation"])
def test_stale_or_cross_operation_plans_do_not_apply(sdk, tmp_path, mode, bad):
    source, cfg, _ = fixture(sdk[0], tmp_path, "Heating", mode)
    report = preflight(source, cfg, mode)
    if bad == "stale":
        source.write_bytes(source.read_bytes() + b"\n! stale\n")
    elif bad == "tampered":
        report["plan"]["after_values"]["rated_outlet_air_temperature_c"] = 40
    else:
        report["operation"] = "other_coil_operation"
    if bad == "wrong_operation":
        path = tmp_path / "wrong.json"
        path.write_text(json.dumps(report))
        with pytest.raises(ValueError, match="matching"):
            tx.apply(
                path,
                (
                    "edit_water_coil"
                    if mode in ("edit", "settings")
                    else "connect_water_coil"
                ),
                (
                    coils.plan_edit
                    if mode in ("edit", "settings")
                    else coils.plan_connection
                ),
                coils.change,
                coils.validate_model,
            )
    else:
        with pytest.raises(ValueError):
            apply(report, tmp_path)
    assert not Path(cfg["output_model_path"]).exists()


@pytest.mark.parametrize(
    "bad",
    [
        "terminal",
        "embedded",
        "wrong_class_fields",
        "inactive_capacity",
        "manual_size",
        "missing_schedule",
        "wrong_schedule",
        "other_plant",
    ],
)
def test_operation_scope_and_conflicting_choices(sdk, tmp_path, bad):
    native = sdk[0]
    mode = (
        "edit"
        if bad in ("terminal", "embedded", "wrong_class_fields", "inactive_capacity")
        else "settings"
    )
    src, cfg, reference = fixture(native, tmp_path, "Heating", mode)
    model = native.model.Model.load(str(src)).get()
    coil = coils.object_by_ref(model, native, reference, "CoilHeatingWater")
    if bad == "terminal":
        terminal_coil = next(
            x
            for x in model.getCoilHeatingWaters()
            if not x.airLoopHVAC().is_initialized()
        )
        cfg["coil"] = {"handle": str(terminal_coil.handle())}
    elif bad == "embedded":
        loop = coil.airLoopHVAC().get()
        embedded = native.model.CoilHeatingWater(model)
        assert coil.plantLoop().get().addDemandBranchForComponent(embedded)
        unit = native.model.AirLoopHVACUnitarySystem(model)
        assert unit.setHeatingCoil(embedded)
        assert unit.addToNode(loop.supplyOutletNode())
        cfg["coil"] = {"handle": str(embedded.handle())}
    elif bad == "wrong_class_fields":
        cfg["ratings"] = {"design_air_flow_m3_s": 1}
    elif bad == "inactive_capacity":
        cfg["ratings"] = {"rated_capacity_w": 5000}
    elif bad == "manual_size":
        cfg["ratings"] = {"maximum_water_flow_m3_s": 0.001}
    elif bad == "missing_schedule":
        cfg["availability_schedule"] = {"name": "Not Found"}
    elif bad == "wrong_schedule":
        cfg["availability_schedule"] = {
            "handle": str(model.getScheduleRulesets()[0].handle())
        }
    elif bad == "other_plant":
        cfg["plant_loop"] = {"name": "Fixture CHW"}
    model.save(str(src), True)
    if bad == "other_plant":
        with pytest.raises(ValueError, match="Invalid"):
            preflight(src, cfg, mode)
    else:
        report = preflight(src, cfg, mode)
        assert not report["ready"], report


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("mode", ["edit", "attach", "settings"])
def test_relocated_native_coil_bundle(sdk, tmp_path, host, mode):
    from adapters.claude_code_adapter import ClaudeCodeAdapter
    from adapters.codex_adapter import CodexAdapter
    from adapters.contracts import HostAdapterConfig

    src, cfg, _ = fixture(sdk[0], tmp_path, "Cooling", mode)
    setup = HostAdapterConfig(
        host_name=host, workspace_root=Path.cwd(), runtime_mode="marketplace"
    )
    adapter = ClaudeCodeAdapter(setup) if host == "claude" else CodexAdapter(setup)
    exported = tmp_path / "export"
    adapter.export_plugin(exported, dry_run=False)
    assert not list(exported.rglob("openstudio-water-coil-ratings-editor/SKILL.md"))
    assert not list(exported.rglob("coil_replacement.py"))
    name = (
        "openstudio-water-coil-editor"
        if mode in ("edit", "settings")
        else "openstudio-water-coil-connector"
    )
    bundle = next(exported.rglob(name + "/SKILL.md")).parent
    relocated = tmp_path / "relocated"
    shutil.copytree(bundle, relocated)
    shutil.rmtree(exported)
    entry = (
        "edit_water_coil.py"
        if mode in ("edit", "settings")
        else "connect_water_coil.py"
    )
    if mode != "settings":
        diagnosed = subprocess.run(
            [
                sys.executable,
                str(relocated / "scripts/doctor.py"),
                "--openstudio",
                str(native_cli()),
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert diagnosed.returncode == 0, diagnosed.stdout + diagnosed.stderr
        assert json.loads(diagnosed.stdout)["sdk_version"] == report_version()
    config = tmp_path / "config.json"
    config.write_text(json.dumps(cfg))
    plan = tmp_path / "reviewed.json"
    applied = tmp_path / "applied.json"
    for args in (
        ["--input", str(src), "--config", str(config), "--report", str(plan)],
        ["--plan", str(plan), "--report", str(applied)],
    ):
        run = subprocess.run(
            [
                str(native_cli()),
                "execute_python_script",
                str(relocated / "scripts" / entry),
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


@pytest.mark.parametrize(
    "profile", ["heating_ua", "heating_capacity", "cooling_design"]
)
def test_supported_rating_methods_and_fixed_design_values(sdk, tmp_path, profile):
    kind = "Cooling" if profile == "cooling_design" else "Heating"
    source, cfg, _ = fixture(sdk[0], tmp_path, kind, "edit")
    if profile == "heating_capacity":
        cfg["ratings"] = dict(
            performance_input_method="NominalCapacity", rated_capacity_w=9000
        )
    elif profile == "heating_ua":
        cfg["ratings"] = dict(ua_w_per_k=500, maximum_water_flow_m3_s=0.001)
    else:
        cfg["ratings"] = dict(
            design_water_flow_m3_s=0.001,
            design_air_flow_m3_s=1.6,
            design_inlet_water_temperature_c=6.666667,
            design_inlet_air_temperature_c=26.7,
            design_outlet_air_temperature_c=12.8,
            design_inlet_air_humidity_ratio=0.011,
            design_outlet_air_humidity_ratio=0.008,
            heat_exchanger_configuration="CounterFlow",
            type_of_analysis="DetailedAnalysis",
        )
    report = preflight(source, cfg, "edit")
    assert report["ready"], report
    result = apply(report, tmp_path)
    saved = sdk[0].model.Model.load(result["output_model_path"]).get()
    coil = coils.object_by_ref(saved, sdk[0], result["changes"]["coil"], CLASSES[kind])
    for key, value in cfg["ratings"].items():
        assert ratings(coil, kind)[key] == value


def test_supply_inlet_is_not_an_upstream_insertion_target(sdk, tmp_path):
    src, cfg, _ = fixture(sdk[0], tmp_path, "Heating", "attach")
    model = sdk[0].model.Model.load(str(src)).get()
    loop = model.getAirLoopHVACs()[0]
    schedule = sdk[0].model.ScheduleConstant(model)
    schedule.setValue(16)
    manager = sdk[0].model.SetpointManagerScheduled(model, schedule)
    assert manager.addToNode(loop.supplyInletNode())
    cfg["air_node"] = {"handle": str(loop.supplyInletNode().handle())}
    model.save(str(src), True)
    report = preflight(src, cfg, "attach")
    assert not report["ready"]
    assert any("supply outlet node" in text for text in report["plan"]["errors"])


@pytest.mark.parametrize("kind", ["Heating", "Cooling"])
def test_interior_node_with_temperature_setpoint_is_unready(sdk, tmp_path, kind):
    native = sdk[0]
    src, cfg, _ = fixture(native, tmp_path, kind, "attach")
    model = native.model.Model.load(str(src)).get()
    node = model.getFanVariableVolumes()[0].inletModelObject().get().to_Node().get()
    schedule = native.model.ScheduleConstant(model)
    schedule.setValue(13)
    assert native.model.SetpointManagerScheduled(model, schedule).addToNode(node)
    cfg["air_node"] = {"handle": str(node.handle())}
    model.save(str(src), True)
    original = src.read_bytes()
    report = preflight(src, cfg, "attach")
    assert not report["ready"]
    assert any("supply outlet node" in error for error in report["plan"]["errors"])
    candidates = coils.inventory(model)["supply_nodes"]
    assert not next(x for x in candidates if x["handle"] == str(node.handle()))[
        "attachment_supported"
    ]
    with pytest.raises(ValueError, match="ready"):
        apply(report, tmp_path)
    assert src.read_bytes() == original
    assert not Path(cfg["output_model_path"]).exists()


def test_inventory_stdout_is_bounded_but_report_keeps_all_nodes(
    sdk, tmp_path, monkeypatch, capsys
):
    source, cfg, _ = fixture(sdk[0], tmp_path, "Heating", "attach")
    model = sdk[0].model.Model.load(str(source)).get()
    loop = model.getAirLoopHVACs()[0]
    for _ in range(12):
        sdk[0].model.FanConstantVolume(model).addToNode(loop.supplyOutletNode())
    model.save(str(source), True)
    report_path = tmp_path / "inventory.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["connect_water_coil.py", "--input", str(source), "--report", str(report_path)],
    )
    assert (
        tx.cli(
            "connect_water_coil",
            coils.plan_connection,
            coils.change,
            coils.validate_model,
            coils.inventory,
        )
        == 0
    )
    report = json.loads(report_path.read_text())
    summary = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert len(report["candidates"]["supply_nodes"]) > 8
    assert len(summary["candidates"]["supply_nodes"]) == 8
    assert "supply_nodes" not in summary["candidates"]["air_loops"][0]
    assert summary["candidate_counts"]["supply_nodes"] == len(
        report["candidates"]["supply_nodes"]
    )


@pytest.mark.parametrize("mode", ["edit", "attach", "settings"])
def test_workflow_weather_hydrates_empty_model_metadata(sdk, tmp_path, mode):
    source, cfg, _ = fixture(sdk[0], tmp_path, "Heating", mode)
    model = sdk[0].model.Model.load(str(source)).get()
    model.getWeatherFile().remove()
    model.save(str(source), True)
    report = preflight(source, cfg, mode)
    assert report["ready"], report
    result = apply(report, tmp_path)
    assert result["validation"]["ok"]
    assert result["simulation_ready"]


def test_coil_entrypoints_guard_sdk_before_model_access(sdk, tmp_path, monkeypatch):
    from common.version_guard import CompatibilityError

    monkeypatch.setattr(sdk[0], "openStudioVersion", lambda: "3.12.0")
    for mode in ["edit", "attach"]:
        with pytest.raises(CompatibilityError):
            preflight(
                tmp_path / "missing.osm",
                {"output_model_path": str(tmp_path / "out.osm")},
                mode,
            )


@pytest.mark.parametrize("mode", ["edit", "attach", "settings"])
def test_missing_weather_resource_warns_without_blocking(sdk, tmp_path, mode):
    source, cfg, _ = fixture(sdk[0], tmp_path, "Heating", mode)
    model = sdk[0].model.Model.load(str(source)).get()
    model.getWeatherFile().remove()
    model.save(str(source), True)
    (source.parent / (source.stem + "_files") / "weather.epw").unlink()
    report = preflight(source, cfg, mode)
    assert report["ready"], report
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and not result["simulation_ready"]


def report_version():
    from common.version_guard import load_contract

    return load_contract()["required_openstudio_version"]


@pytest.mark.parametrize("kind", ["Heating", "Cooling"])
@pytest.mark.parametrize("mode", ["edit", "attach", "settings"])
def test_cav_main_supply_operations(sdk, tmp_path, kind, mode):
    source, cfg, _ = fixture(sdk[0], tmp_path, kind, mode, system_kind="CAV")
    report = preflight(source, cfg, mode)
    assert report["ready"], report
    result = apply(report, tmp_path)
    saved = sdk[0].model.Model.load(result["output_model_path"]).get()
    assert result["validation"]["ok"] and len(saved.getFanConstantVolumes()) == 1
    assert not saved.getFanVariableVolumes()


@pytest.mark.parametrize("kind", ["Heating", "Cooling"])
@pytest.mark.parametrize(
    "setting",
    [
        "name",
        "controller_name",
        "builtin_schedule",
        "existing_schedule",
        "sizing",
        "controller",
        "controller_autosize",
    ],
)
def test_each_setting_edits_in_place_and_preserves_unspecified_fields(
    sdk, tmp_path, kind, setting
):
    native = sdk[0]
    source, cfg, reference = fixture(native, tmp_path, kind, "edit")
    model = native.model.Model.load(str(source)).get()
    coil = coils.object_by_ref(model, native, reference, CLASSES[kind])
    cfg.pop("ratings")
    if setting == "name":
        cfg["coil_name"] = "Renamed Coil"
    elif setting == "controller_name":
        cfg["controller_name"] = "Renamed Controller"
    elif setting == "builtin_schedule":
        cfg["availability_schedule"] = {"builtin": "AlwaysOffDiscrete"}
    elif setting == "existing_schedule":
        schedule = native.model.ScheduleConstant(model)
        schedule.setName("Selected Availability")
        schedule.setScheduleTypeLimits(
            model.alwaysOnDiscreteSchedule().scheduleTypeLimits().get()
        )
        schedule.setValue(0.5)
        cfg["availability_schedule"] = {"handle": str(schedule.handle())}
    elif setting == "sizing":
        if kind == "Heating":
            coil.setRatedCapacity(9000)
            coil.setUFactorTimesAreaValue(500)
            coil.setMaximumWaterFlowRate(0.001)
        else:
            coil.setDesignWaterFlowRate(0.001)
            coil.setDesignAirFlowRate(1)
        coil.controllerWaterCoil().get().setMaximumActuatedFlow(0.001)
        cfg["sizing"] = "Autosize"
    elif setting == "controller":
        cfg["controller"] = {"convergence_tolerance_k": 0.2, "maximum_flow_m3_s": 0.001}
    else:
        coil.controllerWaterCoil().get().setControllerConvergenceTolerance(0.2)
        cfg["controller"] = {"convergence_tolerance_k": "Autosize"}
    model.save(str(source), True)
    original = source.read_bytes()
    handles = coils.original_types(model)
    controller_handle = coil.controllerWaterCoil().get().handle()
    ports = node_ports(coil)
    report = preflight(source, cfg, "edit")
    assert report["ready"], report
    assert report == preflight(source, cfg, "edit")
    result = apply(report, tmp_path)
    saved = native.model.Model.load(result["output_model_path"]).get()
    edited = coils.object_by_ref(saved, native, reference, CLASSES[kind])
    assert edited.controllerWaterCoil().get().handle() == controller_handle
    assert node_ports(edited) == ports
    assert handles.items() <= coils.original_types(saved).items()
    assert not report["plan"]["removed_objects"]
    assert source.read_bytes() == original
    if setting != "builtin_schedule":
        assert handles == coils.original_types(saved)
    if setting == "sizing":
        assert all(
            ratings(edited, kind)[key] == "Autosize"
            for key in coils.autosized_sizes(kind)
        )
        assert edited.controllerWaterCoil().get().isMaximumActuatedFlowAutosized()
    if setting not in ("controller", "controller_autosize", "sizing"):
        assert (
            coils.settings(edited)["controller"]
            == report["plan"]["before_settings"]["controller"]
        )


@pytest.mark.parametrize(
    "bad",
    ["noop", "empty", "action", "flow_bounds", "controller_name", "fixed_maximum"],
)
def test_settings_preflight_rejects_noops_and_conflicts(sdk, tmp_path, bad):
    source, cfg, reference = fixture(sdk[0], tmp_path, "Heating", "edit")
    model = sdk[0].model.Model.load(str(source)).get()
    coil = coils.object_by_ref(model, sdk[0], reference, "CoilHeatingWater")
    cfg.pop("ratings")
    if bad == "noop":
        cfg["coil_name"] = coil.nameString()
    elif bad == "empty":
        cfg["controller"] = {}
    elif bad == "action":
        cfg["controller"] = {"action": "Reverse"}
    elif bad == "flow_bounds":
        cfg["controller"] = {"minimum_flow_m3_s": 0.002, "maximum_flow_m3_s": 0.001}
    elif bad == "controller_name":
        cfg["controller_name"] = next(
            x.nameString()
            for x in model.getControllerWaterCoils()
            if x.handle() != coil.controllerWaterCoil().get().handle()
        )
    else:
        cfg.update(sizing="Autosize", controller={"maximum_flow_m3_s": 0.001})
    report = preflight(source, cfg, "edit")
    assert not report["ready"], report


@pytest.mark.parametrize("mutated", ["name", "schedule", "convergence", "sensor"])
def test_requested_settings_are_checked_independently_before_publishing(
    sdk, tmp_path, monkeypatch, mutated
):
    source, cfg, _ = fixture(sdk[0], tmp_path, "Heating", "settings")
    report = preflight(source, cfg, "settings")
    original = coils.change

    def bad(model, native, planned):
        result = original(model, native, planned)
        coil = coils.object_by_ref(model, native, result["coil"], "CoilHeatingWater")
        if mutated == "name":
            coil.setName("Unapproved Name")
        elif mutated == "schedule":
            coil.setAvailabilitySchedule(model.alwaysOffDiscreteSchedule())
        elif mutated == "convergence":
            coil.controllerWaterCoil().get().setControllerConvergenceTolerance(0.2)
        else:
            coil.controllerWaterCoil().get().setSensorNode(
                coil.airInletModelObject().get().to_Node().get()
            )
        # Even a self-consistent report from the builder cannot approve a change.
        result["coil"] = coils.ref(coil)
        result["after_settings"] = coils.settings(coil)
        return result

    monkeypatch.setattr(coils, "change", bad)
    with pytest.raises(ValueError, match="validation"):
        apply(report, tmp_path)
    assert not Path(cfg["output_model_path"]).exists()


@pytest.mark.parametrize("entry", ["edit", "connection"])
def test_same_class_replacement_is_not_an_exported_operation(sdk, tmp_path, entry):
    source, cfg, _ = fixture(
        sdk[0], tmp_path, "Heating", "attach" if entry == "connection" else "edit"
    )
    cfg["operation"] = "replace"
    with pytest.raises(ValueError, match="Invalid"):
        preflight(source, cfg, "attach" if entry == "connection" else "edit")


@pytest.mark.parametrize("kind", ["Heating", "Cooling"])
def test_deferred_clone_reconnect_primitive_retains_boundary_nodes(sdk, tmp_path, kind):
    from common.coil_replacement import clone_and_reconnect

    native = sdk[0]
    source, cfg, reference = fixture(native, tmp_path, kind, "settings")
    report = preflight(source, cfg, "settings")
    planned = report["plan"]
    model = native.model.Model.load(str(source)).get()
    # This exercises only the retained algorithm, not a publicly approved replacement.
    planned["parameters"]["ratings"] = planned["after_values"]
    result = clone_and_reconnect(model, native, planned)
    output = tmp_path / "primitive.osm"
    assert model.save(str(output), True)
    saved = native.model.Model.load(str(output)).get()
    coil = coils.object_by_ref(saved, native, result["coil"], CLASSES[kind])
    assert node_ports(coil) == planned["resolved_objects"]["ports"]
    assert result["coil"]["handle"] != reference["handle"]
    assert not saved.getModelObject(native.toUUID(reference["handle"])).is_initialized()
    assert not saved.getModelObject(
        native.toUUID(planned["resolved_objects"]["controller"]["handle"])
    ).is_initialized()
    assert coil.controllerWaterCoil().get().waterCoil().get().handle() == coil.handle()
    assert coil.additionalProperties().getFeatureAsString("review_note").get() == "keep"
    translator = native.energyplus.ForwardTranslator()
    translator.translateModel(saved)
    assert not translator.errors()


@pytest.mark.parametrize("kind", ["Heating", "Cooling"])
@pytest.mark.parametrize("mode", ["edit", "settings"])
@pytest.mark.parametrize("missing", ["pump", "setpoint", "equipment"])
def test_incomplete_plant_warns_but_allows_in_place_edit(
    sdk, tmp_path, kind, mode, missing
):
    native = sdk[0]
    source, cfg, reference = fixture(native, tmp_path, kind, mode)
    model = native.model.Model.load(str(source)).get()
    coil = coils.object_by_ref(model, native, reference, CLASSES[kind])
    plant = coil.plantLoop().get()
    if missing == "pump":
        for obj in list(plant.supplyComponents()):
            if (
                obj.iddObjectType()
                .valueName()
                .startswith(("OS_Pump_", "OS_HeaderedPumps_"))
            ):
                obj.remove()
    elif missing == "setpoint":
        for manager in list(plant.supplyOutletNode().setpointManagers()):
            manager.remove()
    else:
        for obj in list(plant.supplyComponents()):
            if obj.iddObjectType().valueName().startswith("OS_District"):
                obj.remove()
    model.save(str(source), True)
    before = source.read_bytes()
    original_handles = coils.original_types(model)
    plant_snapshot = coils.snapshot(model)
    controller_handle = str(coil.controllerWaterCoil().get().handle())
    report = preflight(source, cfg, mode)
    assert report["ready"], report
    assert not report["plan"]["companions"]["simulation_ready"]
    assert any(
        "Plant is missing" in warning and "repair" in warning
        for warning in report["warnings"]
    )
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and result["translation"]["ok"]
    assert not result["simulation_ready"]
    saved = native.model.Model.load(result["output_model_path"]).get()
    edited = coils.object_by_ref(saved, native, reference, CLASSES[kind])
    assert str(edited.controllerWaterCoil().get().handle()) == controller_handle
    assert original_handles == coils.original_types(saved)
    assert (
        coils.snapshot(saved)[str(plant.handle())]
        == plant_snapshot[str(plant.handle())]
    )
    assert source.read_bytes() == before


@pytest.mark.parametrize("omitted", ["all", "partial"])
def test_ua_attachment_rated_temperatures_are_optional_and_informational(
    sdk, tmp_path, omitted
):
    source, cfg, _ = fixture(sdk[0], tmp_path, "Heating", "attach")
    if omitted == "all":
        cfg.pop("design")
    else:
        cfg["design"] = {"rated_inlet_water_temperature_c": 120}
    report = preflight(source, cfg, "attach")
    assert report["ready"], report
    planned = report["plan"]
    usage = planned["rating_usage"]
    assert usage == planned["impact"]["rating_usage"]
    assert usage["rated_temperature_role"] == "informational"
    assert not usage["rated_temperatures_set_ua_design_point"]
    assert len(usage["defaulted_rating_fields"]) == (4 if omitted == "all" else 3)
    assert planned["assumption_review"]["items"][0] == usage
    assert "do not set the coil design point" in usage["message"]
    result = apply(report, tmp_path)
    assert result["validation"]["ok"]
    saved = sdk[0].model.Model.load(result["output_model_path"]).get()
    coil = coils.object_by_ref(
        saved, sdk[0], result["changes"]["coil"], "CoilHeatingWater"
    )
    assert ratings(coil, "Heating") == planned["after_values"]


@pytest.mark.parametrize("mode", ["edit", "attach"])
def test_ua_rating_metadata_does_not_gate_plant_operating_temperatures(
    sdk, tmp_path, mode
):
    source, cfg, _ = fixture(sdk[0], tmp_path, "Heating", mode)
    metadata = dict(
        rated_inlet_water_temperature_c=120,
        rated_outlet_water_temperature_c=100,
        rated_inlet_air_temperature_c=5,
        rated_outlet_air_temperature_c=95,
    )
    cfg["ratings" if mode == "edit" else "design"] = metadata
    report = preflight(source, cfg, mode)
    assert report["ready"], report
    assert not any("Rated water conditions differ" in x for x in report["warnings"])
    usage = report["plan"]["rating_usage"]
    assert (
        usage["sizing_context"]["plant_supply_temperature_c"]
        < metadata["rated_outlet_air_temperature_c"]
    )
    assert apply(report, tmp_path)["validation"]["ok"]


def test_nominal_capacity_retains_active_rating_checks(sdk, tmp_path):
    source, cfg, _ = fixture(sdk[0], tmp_path, "Heating", "edit")
    cfg["ratings"].update(
        performance_input_method="NominalCapacity", rated_capacity_w=9000
    )
    report = preflight(source, cfg, "edit")
    assert report["ready"]
    assert (
        report["plan"]["rating_usage"]["rated_temperature_role"]
        == "nominal_capacity_rating"
    )
    cfg["ratings"].update(
        rated_inlet_water_temperature_c=120,
        rated_outlet_water_temperature_c=100,
        rated_outlet_air_temperature_c=95,
    )
    report = preflight(source, cfg, "edit")
    assert not report["ready"]
    assert any("plant design supply must exceed" in x for x in report["plan"]["errors"])


@pytest.mark.parametrize("system_kind", ["VAV", "CAV"])
def test_native_ua_sizing_ignores_optional_rated_temperatures(
    sdk, tmp_path, system_kind
):
    sized = []
    for case, metadata in (
        ("default", None),
        (
            "changed",
            dict(
                rated_inlet_water_temperature_c=120,
                rated_outlet_water_temperature_c=100,
                rated_inlet_air_temperature_c=5,
                rated_outlet_air_temperature_c=95,
            ),
        ),
    ):
        folder = tmp_path / case
        folder.mkdir()
        source, cfg, _ = fixture(
            sdk[0], folder, "Heating", "attach", system_kind=system_kind
        )
        if metadata is None:
            cfg.pop("design")
        else:
            cfg["design"] = metadata
        report = preflight(source, cfg, "attach")
        assert report["ready"], report
        result = apply(report, folder)
        companions = Path(result["companion_directory"])
        run = subprocess.run(
            [str(native_cli()), "run", "-w", str(companions / "workflow.osw")],
            cwd=companions,
            capture_output=True,
            text=True,
            timeout=120,
        )
        (folder / "cli.log").write_text(run.stdout + run.stderr)
        assert run.returncode == 0, run.stdout + run.stderr
        errors = (companions / "run/eplusout.err").read_text()
        assert "EnergyPlus Completed Successfully" in errors
        assert "** Severe **" not in errors and "**  Fatal  **" not in errors, errors
        with sqlite3.connect(companions / "run/eplusout.sql") as sql:
            rows = dict(
                sql.execute(
                    "SELECT Description, Value FROM ComponentSizes WHERE CompType='Coil:Heating:Water' AND upper(CompName)=?",
                    (result["changes"]["coil"]["name"].upper(),),
                ).fetchall()
            )
        wanted = {
            key: rows[key]
            for key in (
                "Design Size Rated Capacity",
                "Design Size U-Factor Times Area Value",
                "Design Size Maximum Water Flow Rate",
            )
        }
        assert all(value > 0 for value in wanted.values()), wanted
        sized.append(wanted)
        (folder / "sizing-evidence.json").write_text(
            json.dumps(
                dict(case=case, ratings=report["plan"]["after_values"], sizing=wanted),
                indent=2,
            )
        )
    assert sized[0] == pytest.approx(sized[1], rel=1e-9, abs=1e-12)


def test_ua_rating_role_is_visible_in_bounded_cli_preview(
    sdk, tmp_path, monkeypatch, capsys
):
    source, cfg, _ = fixture(sdk[0], tmp_path, "Heating", "attach")
    cfg.pop("design")
    config = tmp_path / "config.json"
    config.write_text(json.dumps(cfg))
    report = tmp_path / "preview.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "connect_water_coil.py",
            "--input",
            str(source),
            "--config",
            str(config),
            "--report",
            str(report),
        ],
    )
    assert (
        tx.cli(
            "connect_water_coil",
            coils.plan_connection,
            coils.change,
            coils.validate_model,
            coils.inventory,
        )
        == 0
    )
    compact = json.loads(capsys.readouterr().out)
    assert compact["ready"]
    assert (
        "do not set the coil design point"
        in compact["impact"]["rating_usage"]["message"]
    )
    assert compact["assumption_review"]["status"] == "informational"
    assert len(compact["impact"]["rating_usage"]["defaulted_rating_fields"]) == 4


@pytest.mark.parametrize("kind", ["Heating", "Cooling"])
def test_edit_still_requires_matching_plant_type(sdk, tmp_path, kind):
    source, cfg, reference = fixture(sdk[0], tmp_path, kind, "edit")
    model = sdk[0].model.Model.load(str(source)).get()
    coil = coils.object_by_ref(model, sdk[0], reference, CLASSES[kind])
    assert (
        coil.plantLoop()
        .get()
        .sizingPlant()
        .setLoopType("Cooling" if kind == "Heating" else "Heating")
    )
    model.save(str(source), True)
    report = preflight(source, cfg, "edit")
    assert not report["ready"]
    assert any("matching Heating/Cooling type" in x for x in report["plan"]["errors"])
