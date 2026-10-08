"""Air relocation preserves coil/controller/plant identity and both air paths."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest
from test_vav_preflight import sdk
from test_water_coil_operations import fixture, preflight, apply
from test_coil_conversion import run_design_days
from test_supply_fan_performance import native_cli
from vav_fixture import prepare_vav_fixture
from common import water_coil as coils, coil_relocation as relocation
from common.coil_equipment import CLASSES, node_ports
from common.vav_plan import plan as vav_plan
from common.vav_create import create as create_vav
from common.hvac_inventory import inventory


def relocation_fixture(
    native, tmp_path, kind="Heating", cross=False, system_kind="VAV"
):
    if not cross:
        source, _, reference = fixture(native, tmp_path, kind, "edit", system_kind)
        model = native.model.Model.load(str(source)).get()
        coil = coils.object_by_ref(model, native, reference, CLASSES[kind])
        target = coil.airLoopHVAC().get()
    else:
        source, config, _, _ = prepare_vav_fixture(native, tmp_path, True)
        model = native.model.Model.load(str(source)).get()
        zones = config["target_zones"]
        loops = []
        for name, selected in (
            ("Source Air", zones[:3]),
            ("Destination Air", zones[3:]),
        ):
            config.update(system_name=name, target_zones=selected)
            if system_kind == "VAV":
                planned = vav_plan(config, inventory(model), None)
                assert planned["ready"], planned
                create_vav(model, native, planned)
            else:
                from common import cav_system

                config.update(
                    defaults_profile="prototype_cav_v1",
                    outdoor_air_schedule={"builtin": "AlwaysOnDiscrete"},
                )
                planned = cav_system.plan(model, native, config)
                assert planned["ready"], planned
                cav_system.create(model, native, planned)
            loops.append(model.getAirLoopHVACByName(name).get())
        coil = next(
            x
            for x in getattr(model, "get" + CLASSES[kind] + "s")()
            if x.airLoopHVAC().is_initialized()
            and x.airLoopHVAC().get().handle() == loops[0].handle()
        )
        reference = coils.ref(coil)
        coil.additionalProperties().setFeature("review_note", "keep")
        target = loops[1]
        # Restore conditioning at the destination by moving the source coil;
        # the fixture itself leaves destination space/terminal assignments intact.
        other = next(
            x
            for x in getattr(model, "get" + CLASSES[kind] + "s")()
            if x.airLoopHVAC().is_initialized()
            and x.airLoopHVAC().get().handle() == target.handle()
        )
        other.remove()
        model.save(str(source), True)
    return (
        source,
        dict(
            output_model_path=str(tmp_path / "relocated.osm"),
            operation="relocate_air",
            coil={"handle": reference["handle"]},
            air_loop={"handle": str(target.handle())},
            air_node={"handle": str(target.supplyOutletNode().handle())},
            sizing="Autosize",
        ),
        reference,
    )


@pytest.mark.parametrize("kind", ["Heating", "Cooling"])
@pytest.mark.parametrize("cross", [False, True])
@pytest.mark.parametrize("system_kind", ["VAV", "CAV"])
def test_saved_air_relocation_preserves_plant_controller_and_equipment(
    sdk, tmp_path, kind, cross, system_kind
):
    native = sdk[0]
    source, cfg, reference = relocation_fixture(
        native, tmp_path, kind, cross, system_kind
    )
    original = source.read_bytes()
    before = native.model.Model.load(str(source)).get()
    old = coils.object_by_ref(before, native, reference, CLASSES[kind])
    water = node_ports(old)[2:]
    controller = str(old.controllerWaterCoil().get().handle())
    plant = str(old.plantLoop().get().handle())
    report = preflight(source, cfg, "attach")
    assert report["ready"], report
    assert report == preflight(
        source, json.loads(json.dumps(cfg, sort_keys=True)), "attach"
    )
    assert report["plan"]["impact"]["affected_zone_count"] == 5
    impact = report["plan"]["impact"]
    assert "upstream" in impact["before_control"]["position_relative_to_fan"]
    assert "downstream" in impact["after_control"]["position_relative_to_fan"]
    assert impact["before_control"]["managers"][0]["type"] == "SetpointManager:MixedAir"
    assert impact["after_control"]["managers"][0]["type"] == "SetpointManager:Scheduled"
    assert any(
        "fan heat compensation" in x.casefold()
        and "draw-through" in x
        and "blow-through" in x
        for x in report["warnings"]
    )
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and result["translation"]["ok"]
    saved = (
        native.osversion.VersionTranslator()
        .loadModel(result["output_model_path"])
        .get()
    )
    moved = coils.object_by_ref(saved, native, reference, CLASSES[kind])
    assert str(moved.controllerWaterCoil().get().handle()) == controller
    assert (
        node_ports(moved)[2:] == water
        and str(moved.plantLoop().get().handle()) == plant
    )
    assert node_ports(moved)[1] == cfg["air_node"]["handle"]
    assert (
        moved.additionalProperties().getFeatureAsString("review_note").get() == "keep"
    )
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    "bad",
    [
        "interior",
        "inlet",
        "wrong_loop_node",
        "no_setpoint",
        "custom_sensor",
        "custom_actuator",
        "minimum_flow",
        "node_reference",
        "named_node_reference",
        "same_location",
        "empty_destination",
        "fan_control",
        "missing_coil",
        "missing_loop",
        "missing_node",
        "missing_sizing",
    ],
)
def test_air_relocation_preflight_agrees_with_supported_locations(sdk, tmp_path, bad):
    native = sdk[0]
    source, cfg, reference = relocation_fixture(native, tmp_path)
    model = native.model.Model.load(str(source)).get()
    coil = coils.object_by_ref(model, native, reference, "CoilHeatingWater")
    loop = coil.airLoopHVAC().get()
    controller = coil.controllerWaterCoil().get()
    if bad == "interior":
        node = coil.airInletModelObject().get().to_Node().get()
        schedule = native.model.ScheduleConstant(model)
        schedule.setValue(20)
        native.model.SetpointManagerScheduled(model, schedule).addToNode(node)
        cfg["air_node"] = {"handle": str(node.handle())}
    elif bad == "inlet":
        cfg["air_node"] = {"handle": str(loop.supplyInletNode().handle())}
    elif bad == "wrong_loop_node":
        cfg["air_node"] = {
            "handle": str(native.model.AirLoopHVAC(model).supplyOutletNode().handle())
        }
    elif bad == "no_setpoint":
        for manager in loop.supplyOutletNode().setpointManagers():
            manager.remove()
    elif bad == "custom_sensor":
        controller.setSensorNode(loop.supplyInletNode())
    elif bad == "custom_actuator":
        controller.setActuatorNode(coil.plantLoop().get().supplyInletNode())
    elif bad == "minimum_flow":
        controller.setMinimumActuatedFlow(0.001)
    elif bad == "node_reference":
        native.model.EnergyManagementSystemActuator(
            coil.airOutletModelObject().get().to_Node().get(),
            "System Node Setpoint",
            "Temperature Setpoint",
        )
    elif bad == "named_node_reference":
        sensor = native.model.EnergyManagementSystemSensor(
            model, "System Node Temperature"
        )
        sensor.setKeyName(coil.airOutletModelObject().get().nameString().upper())
    elif bad == "same_location":
        planned = preflight(source, cfg, "attach")["plan"]
        relocation.relocate(model, native, planned)
    elif bad == "empty_destination":
        target = native.model.AirLoopHVAC(model)
        schedule = native.model.ScheduleConstant(model)
        schedule.setValue(20)
        native.model.SetpointManagerScheduled(model, schedule).addToNode(
            target.supplyOutletNode()
        )
        cfg.update(
            air_loop={"handle": str(target.handle())},
            air_node={"handle": str(target.supplyOutletNode().handle())},
        )
    elif bad == "fan_control":
        manager = native.model.SetpointManagerMixedAir(model)
        manager.setReferenceSetpointNode(loop.supplyOutletNode())
        manager.setFanInletNode(loop.supplyInletNode())
        manager.setFanOutletNode(loop.supplyOutletNode())
        manager.addToNode(loop.supplyInletNode())
    else:
        del cfg[
            bad.removeprefix("missing_")
            .replace("loop", "air_loop")
            .replace("node", "air_node")
        ]
    model.save(str(source), True)
    report = preflight(source, cfg, "attach")
    assert not report["ready"] and (
        report["plan"]["errors"] or report["plan"]["missing_inputs"]
    )
    if bad == "fan_control":
        assert any("fan control node" in x for x in report["plan"]["errors"])
    assert not Path(cfg["output_model_path"]).exists()


@pytest.mark.parametrize("kind", ["Heating", "Cooling"])
def test_move_from_source_outlet_preserves_source_boundary_and_plant(
    sdk, tmp_path, kind
):
    native = sdk[0]
    source, cfg, reference = relocation_fixture(native, tmp_path, kind, cross=True)
    model = native.model.Model.load(str(source)).get()
    coil = coils.object_by_ref(model, native, reference, CLASSES[kind])
    source_loop = coil.airLoopHVAC().get()
    first = dict(
        cfg,
        air_loop={"handle": str(source_loop.handle())},
        air_node={"handle": str(source_loop.supplyOutletNode().handle())},
    )
    ready = coils.plan_connection(model, native, first)
    assert ready["ready"], ready
    relocation.relocate(model, native, ready)
    original_outlet = str(source_loop.supplyOutletNode().handle())
    model.save(str(source), True)
    result = apply(preflight(source, cfg, "attach"), tmp_path)
    saved = native.model.Model.load(result["output_model_path"]).get()
    loop = coils.object_by_ref(saved, native, coils.ref(source_loop), "AirLoopHVAC")
    assert str(loop.supplyOutletNode().handle()) == original_outlet
    assert result["validation"]["ok"] and result["translation"]["ok"]


@pytest.mark.parametrize("mutation", ["source", "configuration", "impact"])
def test_air_relocation_rejects_stale_review(sdk, tmp_path, mutation):
    source, cfg, _ = relocation_fixture(sdk[0], tmp_path)
    report = preflight(source, cfg, "attach")
    if mutation == "source":
        source.write_bytes(source.read_bytes() + b"\n")
    elif mutation == "configuration":
        report["configuration"]["air_node"] = {"name": "Missing"}
    else:
        report["plan"]["impact"]["affected_zone_count"] = 0
    with pytest.raises(ValueError, match="Stale|differs"):
        apply(report, tmp_path)
    assert not Path(cfg["output_model_path"]).exists()


@pytest.mark.parametrize("reference_kind", ["ems", "cost", "controller_metadata"])
def test_air_relocation_preserves_incoming_equipment_references(
    sdk, tmp_path, reference_kind
):
    native = sdk[0]
    source, cfg, reference = relocation_fixture(native, tmp_path, cross=True)
    model = native.model.Model.load(str(source)).get()
    coil = coils.object_by_ref(model, native, reference, "CoilHeatingWater")
    if reference_kind == "ems":
        obj = native.model.EnergyManagementSystemActuator(
            coil, "Coil", "On/Off Supervisory"
        )
    elif reference_kind == "cost":
        obj = native.model.LifeCycleCost.createLifeCycleCost(
            "Maintenance", coil, 100, "CostPerEach", "Maintenance", 1, 0
        ).get()
    else:
        obj = coil.controllerWaterCoil().get().additionalProperties()
        obj.setFeature("keep", "original")
    handle, raw = obj.handle(), str(obj.idfObject())
    model.save(str(source), True)
    result = apply(preflight(source, cfg, "attach"), tmp_path)
    saved = native.model.Model.load(result["output_model_path"]).get()
    assert str(saved.getModelObject(handle).get().idfObject()) == raw


@pytest.mark.parametrize(
    "mutation",
    [
        "name",
        "sensor",
        "actuator",
        "water_node",
        "plant",
        "other_air_loop",
        "extra",
        "reported_nodes",
        "reported_loop",
    ],
)
def test_relocation_validator_rejects_unapproved_graph_and_result(
    sdk, tmp_path, monkeypatch, mutation
):
    source, cfg, _ = relocation_fixture(sdk[0], tmp_path, cross=True)
    report = preflight(source, cfg, "attach")
    original = relocation.relocate

    def bad(model, native, planned):
        result = original(model, native, planned)
        if "companions" not in planned:
            return result  # exercise the saved validator rather than preview rejection
        r = planned["resolved_objects"]
        coil = coils.object_by_ref(model, native, result["coil"], "CoilHeatingWater")
        if mutation == "name":
            coil.setName("Changed")
        elif mutation == "sensor":
            coil.controllerWaterCoil().get().setSensorNode(
                coil.airLoopHVAC().get().supplyInletNode()
            )
        elif mutation == "actuator":
            coil.controllerWaterCoil().get().setActuatorNode(
                coil.plantLoop().get().supplyInletNode()
            )
        elif mutation == "water_node":
            coil.waterInletModelObject().get().setName("Changed")
        elif mutation == "plant":
            coil.plantLoop().get().sizingPlant().setDesignLoopExitTemperature(60)
        elif mutation == "other_air_loop":
            coils.object_by_ref(
                model, native, r["source_air_loop"], "AirLoopHVAC"
            ).setName("Changed")
        elif mutation == "extra":
            native.model.Node(model)
        elif mutation == "reported_nodes":
            result["after_air_nodes"] = list(reversed(result["after_air_nodes"]))
        else:
            result["source_air_loop"] = r["air_loop"]
        return result

    monkeypatch.setattr(relocation, "relocate", bad)
    with pytest.raises(ValueError):
        apply(report, tmp_path)
    assert not Path(cfg["output_model_path"]).exists()


@pytest.mark.parametrize("kind", ["Heating", "Cooling"])
@pytest.mark.parametrize("cross", [False, True])
def test_native_relocation_design_days(sdk, tmp_path, kind, cross):
    source, cfg, _ = relocation_fixture(sdk[0], tmp_path, kind, cross, "CAV")
    result = apply(preflight(source, cfg, "attach"), tmp_path)
    run_design_days(
        result,
        tmp_path,
        "Coil:" + kind + ":Water",
        (
            "Design Size Rated Capacity"
            if kind == "Heating"
            else "Design Size Design Coil Load"
        ),
        substantial=not cross,
        minimum_capacity_w=1000,
    )


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_relocated_native_air_relocation_bundle(sdk, tmp_path, host):
    from adapters.claude_code_adapter import ClaudeCodeAdapter
    from adapters.codex_adapter import CodexAdapter
    from adapters.contracts import HostAdapterConfig

    source, cfg, _ = relocation_fixture(sdk[0], tmp_path, cross=True)
    adapter = (ClaudeCodeAdapter if host == "claude" else CodexAdapter)(
        HostAdapterConfig(
            host_name=host, workspace_root=Path.cwd(), runtime_mode="marketplace"
        )
    )
    exported = tmp_path / "export"
    adapter.export_plugin(exported, dry_run=False)
    relocated = tmp_path / "relocated-skill"
    shutil.copytree(
        next(exported.rglob("openstudio-water-coil-connector/SKILL.md")).parent,
        relocated,
    )
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
                str(relocated / "scripts/connect_water_coil.py"),
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
