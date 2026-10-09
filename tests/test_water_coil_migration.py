"""Plant migration preserves equipment identities and unrelated demand branches."""

import json
from pathlib import Path
import shutil
import sqlite3
import subprocess

import pytest
from test_vav_preflight import sdk
from test_water_coil_operations import fixture, preflight, apply
from test_supply_fan_performance import native_cli
from common import water_coil as coils, plant_create, model_transaction as tx
from common.coil_equipment import CLASSES, node_ports, ratings


def migration_fixture(
    native, tmp_path, kind="Heating", system_kind="VAV", *, match_design=False
):
    source, _, reference = fixture(native, tmp_path, kind, "edit", system_kind)
    model = native.model.Model.load(str(source)).get()
    role = "hot_water" if kind == "Heating" else "chilled_water"
    config = dict(
        output_model_path=str(tmp_path / "plants.osm"),
        defaults_profile="prototype_plants_v1",
        **{
            role: dict(
                name="Destination Plant",
                source=(
                    "DistrictHeatingWater" if kind == "Heating" else "DistrictCooling"
                ),
            )
        },
    )
    if match_design:
        existing = coils.object_by_ref(model, native, reference, CLASSES[kind])
        sizing = existing.plantLoop().get().sizingPlant()
        config[role].update(
            supply_temperature_c=sizing.designLoopExitTemperature(),
            delta_temperature_k=sizing.loopDesignTemperatureDifference(),
        )
    plant_create.create(model, native, plant_create.plan(model, native, config))
    target = model.getPlantLoopByName("Destination Plant").get()
    # An occupied destination demonstrates preservation of its existing branch.
    other = getattr(native.model, CLASSES[kind])(model)
    other.setName("Existing Destination Coil")
    assert target.addDemandBranchForComponent(other)
    air = native.model.AirLoopHVAC(model)
    assert other.addToNode(air.supplyOutletNode())
    model.save(str(source), True)
    return (
        source,
        dict(
            output_model_path=str(tmp_path / "migrated.osm"),
            operation="migrate_plant",
            coil={"handle": reference["handle"]},
            plant_loop={"handle": str(target.handle())},
            sizing="Autosize",
        ),
        reference,
    )


@pytest.mark.parametrize("kind", ["Heating", "Cooling"])
@pytest.mark.parametrize("system_kind", ["VAV", "CAV"])
def test_saved_migration_preserves_coil_controller_air_and_branches(
    sdk, tmp_path, kind, system_kind
):
    native = sdk[0]
    source, cfg, reference = migration_fixture(native, tmp_path, kind, system_kind)
    original = source.read_bytes()
    model = native.model.Model.load(str(source)).get()
    coil = coils.object_by_ref(model, native, reference, CLASSES[kind])
    controller = coil.controllerWaterCoil().get().handle()
    ports = node_ports(coil)
    report = preflight(source, cfg, "attach")
    assert report["ready"], report["plan"]["errors"]
    assert "source_plant" in report["plan"]["impact"]
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and result["translation"]["ok"]
    saved = (
        native.osversion.VersionTranslator()
        .loadModel(result["output_model_path"])
        .get()
    )
    moved = coils.object_by_ref(saved, native, reference, CLASSES[kind])
    assert moved.controllerWaterCoil().get().handle() == controller
    assert node_ports(moved)[:2] == ports[:2]
    assert str(moved.plantLoop().get().handle()) == cfg["plant_loop"]["handle"]
    assert source.read_bytes() == original
    other = next(
        c
        for c in getattr(saved, "get" + CLASSES[kind] + "s")()
        if c.nameString() == "Existing Destination Coil"
    )
    assert other.plantLoop().get().handle() == moved.plantLoop().get().handle()


@pytest.mark.parametrize("kind", ["Heating", "Cooling"])
@pytest.mark.parametrize("reference_kind", ["ems", "cost", "controller_metadata"])
def test_migration_preserves_incoming_references_and_metadata(
    sdk, tmp_path, kind, reference_kind
):
    native = sdk[0]
    source, cfg, reference = migration_fixture(native, tmp_path, kind)
    model = native.model.Model.load(str(source)).get()
    coil = coils.object_by_ref(model, native, reference, CLASSES[kind])
    if reference_kind == "ems":
        obj = native.model.EnergyManagementSystemActuator(
            coil, "Coil", "On/Off Supervisory"
        )
    elif reference_kind == "cost":
        obj = native.model.LifeCycleCost.createLifeCycleCost(
            "Maintenance", coil, 100, "CostPerEach", "Maintenance", 1, 0
        ).get()
    else:
        coil.controllerWaterCoil().get().additionalProperties().setFeature(
            "keep", "original"
        )
        obj = coil.controllerWaterCoil().get().additionalProperties()
    handle = obj.handle()
    before = str(obj.idfObject())
    model.save(str(source), True)
    result = apply(preflight(source, cfg, "attach"), tmp_path)
    saved = native.model.Model.load(result["output_model_path"]).get()
    assert str(saved.getModelObject(handle).get().idfObject()) == before


@pytest.mark.parametrize(
    "bad",
    [
        "same_plant",
        "wrong_type",
        "pump",
        "equipment",
        "setpoint",
        "fluid",
        "serial",
        "node_reference",
        "controller",
        "sizing_missing",
        "coil_missing",
        "target_missing",
    ],
)
def test_migration_preflight_blocks_unsupported_choices(sdk, tmp_path, bad):
    native = sdk[0]
    source, cfg, reference = migration_fixture(native, tmp_path)
    model = native.model.Model.load(str(source)).get()
    coil = coils.object_by_ref(model, native, reference, "CoilHeatingWater")
    target = coils.object_by_ref(model, native, cfg["plant_loop"], "PlantLoop")
    if bad == "same_plant":
        cfg["plant_loop"] = {"handle": str(coil.plantLoop().get().handle())}
    elif bad == "wrong_type":
        target.sizingPlant().setLoopType("Cooling")
    elif bad == "pump":
        next(
            x
            for x in target.supplyComponents()
            if x.to_PumpVariableSpeed().is_initialized()
            or x.to_PumpConstantSpeed().is_initialized()
        ).remove()
    elif bad == "equipment":
        next(
            x
            for x in target.supplyComponents()
            if x.to_DistrictHeatingWater().is_initialized()
        ).remove()
    elif bad == "setpoint":
        for spm in target.supplyOutletNode().setpointManagers():
            spm.remove()
    elif bad == "fluid":
        target.setFluidType("PropyleneGlycol")
        target.setGlycolConcentration(30)
    elif bad == "serial":
        assert native.model.PipeAdiabatic(model).addToNode(
            coil.waterInletModelObject().get().to_Node().get()
        )
    elif bad == "node_reference":
        native.model.EnergyManagementSystemActuator(
            coil.waterOutletModelObject().get().to_Node().get(),
            "System Node Setpoint",
            "Temperature Setpoint",
        )
    elif bad == "controller":
        coil.controllerWaterCoil().get().setMinimumActuatedFlow(0.1)
    else:
        del cfg[
            {
                "sizing_missing": "sizing",
                "coil_missing": "coil",
                "target_missing": "plant_loop",
            }[bad]
        ]
    model.save(str(source), True)
    original = source.read_bytes()
    report = preflight(source, cfg, "attach")
    assert not report["ready"]
    assert report["plan"]["errors"] or report["plan"]["missing_inputs"]
    assert (
        source.read_bytes() == original and not Path(cfg["output_model_path"]).exists()
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "name",
        "air_node",
        "source_equipment",
        "other_coil",
        "extra",
        "sensor",
        "actuator",
        "sizing",
        "controller_identity",
        "reported_nodes",
        "reported_removed",
        "reported_operation",
    ],
)
def test_migration_validator_rejects_unapproved_changes(
    sdk, tmp_path, monkeypatch, mutation
):
    native = sdk[0]
    source, cfg, _ = migration_fixture(native, tmp_path)
    report = preflight(source, cfg, "attach")
    original = coils.change

    def bad(model, sdk, planned):
        result = original(model, sdk, planned)
        coil = coils.object_by_ref(model, sdk, result["coil"], "CoilHeatingWater")
        r = planned["resolved_objects"]
        if mutation == "name":
            coil.setName("Unapproved")
        elif mutation == "air_node":
            model.getNode(sdk.toUUID(node_ports(coil)[0])).get().setName("Unapproved")
        elif mutation == "source_equipment":
            coils.object_by_ref(
                model, sdk, r["source_plant_loop"], "PlantLoop"
            ).setName("Unapproved")
        elif mutation == "other_coil":
            next(
                x
                for x in model.getCoilHeatingWaters()
                if x.nameString() == "Existing Destination Coil"
            ).setRatedCapacity(10)
        elif mutation == "extra":
            sdk.model.CoilHeatingWater(model)
        elif mutation in ("sensor", "actuator"):
            controller = coil.controllerWaterCoil().get()
            getattr(controller, "set" + mutation.title() + "Node")(
                model.getNode(sdk.toUUID(node_ports(coil)[0])).get()
            )
        elif mutation == "sizing":
            coil.setUFactorTimesAreaValue(100)
        elif mutation == "controller_identity":
            controller = coil.controllerWaterCoil().get()
            cloned = controller.clone(model).to_ControllerWaterCoil().get()
            controller.remove()
            result["controller"] = coils.ref(cloned)
        elif mutation == "reported_nodes":
            result["after_water_nodes"] = []
        elif mutation == "reported_removed":
            result["removed_handles"] = []
        else:
            result["operation"] = "edit"
        return result

    monkeypatch.setattr(coils, "change", bad)
    with pytest.raises(ValueError):
        apply(report, tmp_path)
    assert not Path(cfg["output_model_path"]).exists()
    assert not Path(cfg["output_model_path"]).with_suffix("").exists()


@pytest.mark.parametrize("bad", ["stale", "tampered", "operation"])
def test_migration_plan_integrity(sdk, tmp_path, bad):
    source, cfg, _ = migration_fixture(sdk[0], tmp_path)
    report = preflight(source, cfg, "attach")
    if bad == "stale":
        source.write_bytes(source.read_bytes() + b"\n")
    elif bad == "tampered":
        report["plan"]["resolved_objects"]["source_plant_loop"]["name"] = "Unapproved"
    else:
        report["configuration"]["operation"] = "attach"
    with pytest.raises(ValueError):
        apply(report, tmp_path)
    assert not Path(cfg["output_model_path"]).exists()


@pytest.mark.parametrize("kind,expected", [("Heating", 5), ("Cooling", 0)])
def test_source_plant_remaining_coils_are_visible(sdk, tmp_path, kind, expected):
    source, cfg, _ = migration_fixture(sdk[0], tmp_path, kind)
    report = preflight(source, cfg, "attach")
    assert report["ready"], report["plan"]["errors"]
    impact = report["plan"]["impact"]
    assert impact["source_plant_remaining_coil_count"] == expected
    assert impact["source_plant_remaining_demand_equipment_count"] == expected
    assert impact["source_plant_will_be_unserved"] == (expected == 0)
    cleanup = [x for x in report["warnings"] if "will serve 0 coils" in x]
    if expected:
        assert not cleanup
    else:
        assert len(cleanup) == 1
        assert (
            "openstudio-hvac-remover" in cleanup[0]
            and "excludes plant deletion" in cleanup[0]
        )
        assert "Autosize" in cleanup[0]
        result = apply(report, tmp_path)
        assert cleanup[0] in result["warnings"]
        saved = sdk[0].model.Model.load(result["output_model_path"]).get()
        old_plant = coils.object_by_ref(
            saved,
            sdk[0],
            report["plan"]["resolved_objects"]["source_plant_loop"],
            "PlantLoop",
        )
        assert (
            old_plant.supplyComponents()
        ), "An unserved plant must not be silently deleted"


def test_source_with_other_demand_equipment_is_not_called_unserved(sdk, tmp_path):
    native = sdk[0]
    source, cfg, reference = migration_fixture(native, tmp_path, "Cooling")
    model = native.model.Model.load(str(source)).get()
    coil = coils.object_by_ref(model, native, reference, "CoilCoolingWater")
    assert (
        coil.plantLoop()
        .get()
        .addDemandBranchForComponent(native.model.HeatExchangerFluidToFluid(model))
    )
    model.save(str(source), True)
    report = preflight(source, cfg, "attach")
    assert report["ready"], report["plan"]["errors"]
    impact = report["plan"]["impact"]
    assert impact["source_plant_remaining_coil_count"] == 0
    assert impact["source_plant_remaining_demand_equipment_count"] == 1
    assert not impact["source_plant_will_be_unserved"]
    warning = next(x for x in report["warnings"] if "will serve 0 coils" in x)
    assert "1 other demand equipment" in warning


@pytest.mark.parametrize("kind", ["Heating", "Cooling"])
def test_pinned_sdk_branch_removal_and_attachment_controller_lifecycle(kind):
    # Deliberately avoid the 3.11-only fixture: this probe should run and explain
    # a changed native lifecycle when the package SDK pin is bumped.
    native = pytest.importorskip("openstudio")
    model = native.model.Model()
    coil = getattr(native.model, CLASSES[kind])(model)
    source, target = native.model.PlantLoop(model), native.model.PlantLoop(model)
    air = native.model.AirLoopHVAC(model)
    assert source.addDemandBranchForComponent(coil)
    assert coil.addToNode(air.supplyOutletNode())
    original = coil.controllerWaterCoil().get().handle()
    version = native.openStudioVersion()
    assert source.removeDemandBranchWithComponent(coil)
    assert not coil.controllerWaterCoil().is_initialized(), (
        f"OpenStudio {version}: branch removal no longer clears coil controller ownership; "
        "review the migration controller hand-off"
    )
    assert not model.getModelObject(
        original
    ).is_initialized(), (
        f"OpenStudio {version}: branch removal no longer deletes the owned controller"
    )
    assert model.getModelObject(coil.handle()).is_initialized()
    assert target.addDemandBranchForComponent(coil)
    assert coil.controllerWaterCoil().is_initialized(), (
        f"OpenStudio {version}: demand attachment no longer creates a controller; "
        "review the migration controller hand-off"
    )
    replacement = coil.controllerWaterCoil().get()
    assert replacement.handle() != original
    assert replacement.waterCoil().get().handle() == coil.handle()


@pytest.mark.parametrize(
    "case", ["cooling_fixed", "cooling_autosized", "heating_nominal", "heating_ua"]
)
def test_retained_water_ratings_name_followup_editor(sdk, tmp_path, case):
    native = sdk[0]
    kind = "Cooling" if case.startswith("cooling") else "Heating"
    source, cfg, reference = migration_fixture(native, tmp_path, kind)
    model = native.model.Model.load(str(source)).get()
    coil = coils.object_by_ref(model, native, reference, CLASSES[kind])
    target = coils.object_by_ref(model, native, cfg["plant_loop"], "PlantLoop")
    target.sizingPlant().setDesignLoopExitTemperature(7.5 if kind == "Cooling" else 60)
    if case == "cooling_fixed":
        coil.setDesignInletWaterTemperature(6.666667)
    elif case == "cooling_autosized":
        coil.autosizeDesignInletWaterTemperature()
    elif case == "heating_nominal":
        coil.setPerformanceInputMethod("NominalCapacity")
    original = ratings(coil, kind)
    model.save(str(source), True)
    report = preflight(source, cfg, "attach")
    assert report["ready"], report["plan"]["errors"]
    mismatches = report["plan"]["impact"]["retained_water_rating_mismatches"]
    followup = [x for x in report["warnings"] if "openstudio-water-coil-editor" in x]
    active = case in ("cooling_fixed", "heating_nominal")
    assert bool(mismatches) == active and bool(followup) == active
    if active:
        assert all(key in followup[0] for key in mismatches)
        for key in mismatches:
            assert report["plan"]["after_values"][key] == original[key]
        result = apply(report, tmp_path)
        assert followup[0] in result["warnings"]
        saved = native.model.Model.load(result["output_model_path"]).get()
        moved = coils.object_by_ref(saved, native, reference, CLASSES[kind])
        assert all(ratings(moved, kind)[key] == original[key] for key in mismatches)


@pytest.mark.parametrize("kind", ["Heating", "Cooling"])
@pytest.mark.parametrize("system_kind", ["VAV", "CAV"])
def test_native_matched_migration_retains_sizing(sdk, tmp_path, kind, system_kind):
    executable = str(native_cli())
    source, cfg, reference = migration_fixture(
        sdk[0], tmp_path, kind, system_kind, match_design=True
    )
    native = sdk[0]
    model = native.model.Model.load(str(source)).get()
    # Remove the fixture's unrelated destination coil/empty air loop before both
    # runs; source model and migrated model then differ only by the reviewed move.
    other = next(
        x
        for x in getattr(model, "get" + CLASSES[kind] + "s")()
        if x.nameString() == "Existing Destination Coil"
    )
    other.airLoopHVAC().get().remove()
    other.remove()
    model.save(str(source), True)
    original = source.read_bytes()
    report = preflight(source, cfg, "attach")
    assert report["ready"], report["plan"]["errors"]
    impact = report["plan"]["impact"]
    assert (
        impact["source_design"] == impact["destination_design"]
    ), "Parity requires identical plant design conditions"
    result = apply(report, tmp_path)
    sizes = []
    for case, workflow in (
        ("before", source.with_name(source.stem + "_files") / "workflow.osw"),
        ("after", Path(result["companion_directory"]) / "workflow.osw"),
    ):
        run = subprocess.run(
            [executable, "run", "-w", str(workflow)],
            cwd=workflow.parent,
            capture_output=True,
            text=True,
            timeout=120,
        )
        (tmp_path / (case + "-cli.log")).write_text(run.stdout + run.stderr)
        assert run.returncode == 0, run.stdout + run.stderr
        errors = (workflow.parent / "run/eplusout.err").read_text()
        assert "EnergyPlus Completed Successfully" in errors
        assert "** Severe **" not in errors and "**  Fatal  **" not in errors, errors
        with sqlite3.connect(workflow.parent / "run/eplusout.sql") as sql:
            rows = dict(
                sql.execute(
                    "SELECT Description,Value FROM ComponentSizes WHERE CompType=? AND upper(CompName)=?",
                    ("Coil:" + kind + ":Water", reference["name"].upper()),
                ).fetchall()
            )
        fields = (
            {
                "capacity_w": "Design Size Rated Capacity",
                "ua_w_per_k": "Design Size U-Factor Times Area Value",
                "water_flow_m3_s": "Design Size Maximum Water Flow Rate",
            }
            if kind == "Heating"
            else {
                "capacity_w": "Design Size Design Coil Load",
                "water_flow_m3_s": "Design Size Design Water Flow Rate",
                "air_flow_m3_s": "Design Size Design Air Flow Rate",
            }
        )
        values = {key: rows[description] for key, description in fields.items()}
        assert all(value > 0 for value in values.values()), values
        sizes.append(values)
    assert source.read_bytes() == original
    assert sizes[0] == pytest.approx(sizes[1], rel=1e-9, abs=1e-12)
    if system_kind == "CAV" and kind == "Heating":
        assert (
            sizes[0]["capacity_w"] > 10000
        ), "Include a substantial heating load in sizing parity evidence"
    (tmp_path / "matched-sizing-evidence.json").write_text(
        json.dumps(
            dict(
                system_kind=system_kind,
                coil_kind=kind,
                coil_name=reference["name"],
                source_design=impact["source_design"],
                destination_design=impact["destination_design"],
                before=sizes[0],
                after=sizes[1],
                relative_tolerance=1e-9,
                absolute_tolerance=1e-12,
            ),
            indent=2,
        )
        + "\n"
    )


@pytest.mark.parametrize("kind", ["Heating", "Cooling"])
@pytest.mark.parametrize("system_kind", ["VAV", "CAV"])
def test_native_migration_design_days(sdk, tmp_path, kind, system_kind):
    source, cfg, _ = migration_fixture(sdk[0], tmp_path, kind, system_kind)
    # The added destination air loop has no zones; remove its unrelated test coil.
    model = sdk[0].model.Model.load(str(source)).get()
    other = next(
        x
        for x in getattr(model, "get" + CLASSES[kind] + "s")()
        if x.nameString() == "Existing Destination Coil"
    )
    other.airLoopHVAC().get().remove()
    other.remove()
    model.save(str(source), True)
    result = apply(preflight(source, cfg, "attach"), tmp_path)
    folder = Path(result["companion_directory"])
    run = subprocess.run(
        [str(native_cli()), "run", "-w", str(folder / "workflow.osw")],
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
    with sqlite3.connect(folder / "run/eplusout.sql") as sql:
        values = sql.execute(
            "SELECT Value FROM ComponentSizes WHERE CompType=? AND upper(CompName)=? AND Description=?",
            (
                "Coil:" + kind + ":Water",
                result["changes"]["coil"]["name"].upper(),
                (
                    "Design Size Rated Capacity"
                    if kind == "Heating"
                    else "Design Size Design Coil Load"
                ),
            ),
        ).fetchall()
    assert len(values) == 1 and values[0][0] > 0


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_relocated_native_migration_bundle(sdk, tmp_path, host):
    from adapters.claude_code_adapter import ClaudeCodeAdapter
    from adapters.codex_adapter import CodexAdapter
    from adapters.contracts import HostAdapterConfig

    source, cfg, _ = migration_fixture(sdk[0], tmp_path)
    adapter = (ClaudeCodeAdapter if host == "claude" else CodexAdapter)(
        HostAdapterConfig(
            host_name=host, workspace_root=Path.cwd(), runtime_mode="marketplace"
        )
    )
    exported = tmp_path / "export"
    adapter.export_plugin(exported, dry_run=False)
    bundle = next(exported.rglob("openstudio-water-coil-connector/SKILL.md")).parent
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
