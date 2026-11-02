"""Unused plant cascade and real source replacement preserve all other equipment."""

import json
from pathlib import Path
import sys

import pytest
from test_vav_preflight import sdk, SCRIPTS

sys.path.insert(0, str(SCRIPTS))
from common import plant_operations as plants, plant_create, model_transaction as tx
from common.water_coil import raw_fields
from common.version_guard import load_model


def fixture(o, folder, kind="NaturalGas"):
    model = o.model.Model()
    role = "hot_water" if kind == "NaturalGas" else "chilled_water"
    plant_create.create(
        model,
        o,
        plant_create.plan(
            model,
            o,
            dict(
                output_model_path=str(folder / "unused.osm"),
                defaults_profile="prototype_plants_v1",
                **{role: dict(name="Selected Plant", source=kind)},
            ),
        ),
    )
    keep = o.model.PlantLoop(model)
    keep.setName("Keep Plant")
    loop = model.getPlantLoopByName("Selected Plant").get()
    source = next(
        x
        for x in loop.supplyComponents()
        if x.iddObjectType().valueName() in plants.SOURCES
    )
    source = getattr(
        source, "to_" + plants.SOURCES[source.iddObjectType().valueName()][0]
    )().get()
    source.additionalProperties().setFeature("note", "retained metadata")
    schedule = model.alwaysOnDiscreteSchedule()
    cfg = dict(
        output_model_path=str(folder / "replaced.osm"),
        plant_loop=dict(name="Selected Plant"),
        equipment=dict(handle=str(source.handle())),
        target_class=(
            "DistrictHeatingWater" if kind == "NaturalGas" else "DistrictCooling"
        ),
        nominal_capacity_w=100000,
        capacity_fraction_schedule=dict(handle=str(schedule.handle())),
        reference_policy="Reject",
    )
    path = folder / "source.osm"
    assert model.save(str(path), True)
    return path, model, source, cfg


def removal(folder, name="Selected Plant"):
    return dict(
        output_model_path=str(folder / "removed.osm"), plant_loops=[dict(name=name)]
    )


def preflight(source, cfg, replace=False):
    return tx.preflight(
        source,
        cfg,
        "replace_plant_equipment" if replace else "remove_unused_plants",
        plants.replacement_plan if replace else plants.removal_plan,
    )


def apply(report, folder, replace=False, creator=None):
    path = folder / "reviewed.json"
    path.write_text(json.dumps(report))
    return tx.apply(
        path,
        report["operation"],
        plants.replacement_plan if replace else plants.removal_plan,
        creator or (plants.replace_source if replace else plants.remove_plants),
        plants.validate_replacement if replace else plants.validate_removal,
    )


@pytest.mark.parametrize("kind", ["NaturalGas", "AirCooled", "WaterCooled"])
def test_replacement_saved_identity_service_and_condenser_cleanup(sdk, tmp_path, kind):
    o = sdk[0]
    path, model, old, cfg = fixture(o, tmp_path, kind)
    original = path.read_bytes()
    metadata = str(old.additionalProperties().handle())
    report = preflight(path, cfg, True)
    assert report["ready"], report
    assert report == preflight(path, cfg, True)
    result = apply(report, tmp_path, True)
    assert result["validation"]["ok"] and result["translation"]["ok"]
    saved, _ = load_model(o, result["output_model_path"])
    new = getattr(saved, "get" + cfg["target_class"] + "s")()[0]
    assert not saved.getModelObject(old.handle()).is_initialized()
    assert new.nameString() == old.nameString()
    assert str(new.additionalProperties().handle()) == metadata
    assert (
        new.additionalProperties().getFeatureAsString("note").get()
        == "retained metadata"
    )
    assert new.nominalCapacity().get() == 100000
    assert (
        str(new.capacityFractionSchedule().handle())
        == cfg["capacity_fraction_schedule"]["handle"]
    )
    assert saved.getPlantLoopByName("Keep Plant").is_initialized()
    if kind == "WaterCooled":
        impact = report["plan"]["impact"]
        assert impact["condenser_remaining_demand_equipment_count"] == 0
        condenser = impact["condenser_plant"]
        cleanup_cfg = dict(
            output_model_path=str(tmp_path / "cleaned.osm"),
            plant_loops=[dict(handle=condenser["handle"])],
        )
        cleanup = preflight(Path(result["output_model_path"]), cleanup_cfg)
        assert cleanup["ready"], cleanup
        cleaned = apply(cleanup, tmp_path)
        final, _ = load_model(o, cleaned["output_model_path"])
        assert len(final.getPlantLoops()) == 2
        assert len(final.getDistrictCoolings()) == 1
    assert path.read_bytes() == original


@pytest.mark.parametrize("kind", ["NaturalGas", "AirCooled"])
def test_unused_plant_removal_preserves_shared_resources(sdk, tmp_path, kind):
    o = sdk[0]
    path, model, old, cfg = fixture(o, tmp_path, kind)
    schedules = {str(s.handle()): str(s) for s in model.getSchedules()}
    original = path.read_bytes()
    report = preflight(path, removal(tmp_path))
    assert report["ready"] and report == preflight(path, removal(tmp_path))
    result = apply(report, tmp_path)
    saved, _ = load_model(o, result["output_model_path"])
    assert len(saved.getPlantLoops()) == 1
    assert saved.getPlantLoops()[0].nameString() == "Keep Plant"
    for h, raw in schedules.items():
        assert str(saved.getModelObject(o.toUUID(h)).get()) == raw
    assert path.read_bytes() == original


@pytest.mark.parametrize("load", ["coil", "profile", "water_use", "nonadiabatic_pipe"])
def test_cleanup_rejects_all_active_demand_not_only_coils(sdk, tmp_path, load):
    o = sdk[0]
    path, model, old, cfg = fixture(o, tmp_path)
    loop = model.getPlantLoopByName("Selected Plant").get()
    obj = dict(
        coil=lambda: o.model.CoilHeatingWater(model),
        profile=lambda: o.model.LoadProfilePlant(model),
        water_use=lambda: o.model.WaterUseConnections(model),
        nonadiabatic_pipe=lambda: o.model.PipeIndoor(model),
    )[load]()
    assert loop.addDemandBranchForComponent(obj)
    assert model.save(str(path), True)
    report = preflight(path, removal(tmp_path))
    assert not report["ready"] and "active demand" in str(report["plan"]["errors"])
    assert not (tmp_path / "removed.osm").exists()


def test_cleanup_rejects_cross_loop_chiller_and_duplicate_selection(sdk, tmp_path):
    path, _, _, _ = fixture(sdk[0], tmp_path, "WaterCooled")
    report = preflight(path, removal(tmp_path))
    assert not report["ready"] and "Cross-loop" in str(report["plan"]["errors"])
    cfg = removal(tmp_path)
    cfg["plant_loops"] *= 2
    report = preflight(path, cfg)
    assert not report["ready"] and "Duplicate" in str(report["plan"]["errors"])


@pytest.mark.parametrize("replace", [False, True])
@pytest.mark.parametrize("reference", ["ems", "cost", "output"])
def test_external_source_references_block(sdk, tmp_path, replace, reference):
    o = sdk[0]
    path, model, old, cfg = fixture(o, tmp_path)
    if reference == "ems":
        o.model.EnergyManagementSystemActuator(old, "Boiler", "On/Off Supervisory")
    elif reference == "cost":
        assert o.model.LifeCycleCost.createLifeCycleCost(
            "Cost", old, 100, "CostPerEach", "Construction"
        ).is_initialized()
    else:
        request = o.model.OutputVariable("Boiler Heating Energy", model)
        request.setKeyValue(old.nameString())
    assert model.save(str(path), True)
    report = preflight(path, cfg if replace else removal(tmp_path), replace)
    assert not report["ready"] and "reference" in str(report["plan"]["errors"]).lower()


@pytest.mark.parametrize("replace", [False, True])
@pytest.mark.parametrize(
    "damage", ["stale", "tamper", "unrelated_edit", "extra_object"]
)
def test_exact_transaction_and_saved_checks_reject_changes(
    sdk, tmp_path, replace, damage
):
    o = sdk[0]
    path, model, old, cfg = fixture(o, tmp_path)
    report = preflight(path, cfg if replace else removal(tmp_path), replace)
    assert report["ready"], report
    creator = None
    if damage == "stale":
        path.write_bytes(path.read_bytes() + b"\n")
    elif damage == "tamper":
        report["plan"]["impact"]["removed_object_count"] = 999
    else:

        def creator(m, sdk, planned):
            result = (plants.replace_source if replace else plants.remove_plants)(
                m, sdk, planned
            )
            if damage == "unrelated_edit":
                m.getPlantLoopByName("Keep Plant").get().setMinimumLoopTemperature(2)
            else:
                sdk.model.FanConstantVolume(m)
            return result

    with pytest.raises(ValueError, match="Stale|differs|validation"):
        apply(report, tmp_path, replace, creator)
    assert not Path(report["output_model_path"]).exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("nominal_capacity_w", 0),
        ("nominal_capacity_w", True),
        ("nominal_capacity_w", -1),
        ("nominal_capacity_w", "100"),
        ("target_class", "BoilerHotWater"),
        ("reference_policy", "Ignore"),
        ("unknown", 1),
    ],
)
def test_replacement_invalid_config(sdk, tmp_path, field, value):
    path, _, _, cfg = fixture(sdk[0], tmp_path)
    cfg[field] = value
    with pytest.raises(ValueError, match="Invalid plant operation"):
        preflight(path, cfg, True)


@pytest.mark.parametrize("replace", [False, True])
def test_missing_selection_is_unready(sdk, tmp_path, replace):
    path, _, _, cfg = fixture(sdk[0], tmp_path)
    report = preflight(path, dict(output_model_path=cfg["output_model_path"]), replace)
    assert not report["ready"] and report["plan"]["missing_inputs"]


def test_explicit_autosize_requires_sizing_setup_for_simulation(sdk, tmp_path):
    path, _, _, cfg = fixture(sdk[0], tmp_path)
    cfg["nominal_capacity_w"] = "Autosize"
    report = preflight(path, cfg, True)
    assert report["ready"]
    assert report["plan"]["simulation_ready"] is False
    result = apply(report, tmp_path, True)
    assert result["ok"] and not result["simulation_ready"]


def native_run(o, source, folder, equipment_handle, target_class):
    """Short design-day evidence with useful heat, demand, purchased energy and pumps."""
    import re
    import sqlite3
    import subprocess
    from test_supply_fan_performance import native_cli

    folder.mkdir()
    model, _ = load_model(o, source)
    obj = model.getModelObject(o.toUUID(equipment_handle)).get()
    source_class = plants.SOURCES.get(obj.iddObjectType().valueName(), (target_class,))[
        0
    ]
    obj = getattr(obj, "to_" + source_class)().get()
    loop = obj.plantLoop().get()
    cooling = target_class == "DistrictCooling"
    source_energy = {
        "BoilerHotWater": "Boiler Heating Energy",
        "ChillerElectricEIR": "Chiller Evaporator Cooling Energy",
        "DistrictHeatingWater": "District Heating Water Energy",
        "DistrictCooling": "District Cooling Water Energy",
    }[source_class]
    outlet = {
        "BoilerHotWater": "Boiler Outlet Temperature",
        "ChillerElectricEIR": "Chiller Evaporator Outlet Temperature",
        "DistrictHeatingWater": "District Heating Water Outlet Temperature",
        "DistrictCooling": "District Cooling Water Outlet Temperature",
    }[source_class]
    variable_keys = [
        (source_energy, obj.nameString()),
        (outlet, obj.nameString()),
        ("Plant Supply Side Unmet Demand Rate", loop.nameString()),
        (
            (
                "Plant Supply Side Cooling Demand Rate"
                if cooling
                else "Plant Supply Side Heating Demand Rate"
            ),
            loop.nameString(),
        ),
    ]
    energy_input = {
        "BoilerHotWater": "Boiler NaturalGas Energy",
        "ChillerElectricEIR": "Chiller Electricity Energy",
    }.get(source_class)
    if energy_input:
        variable_keys.append((energy_input, obj.nameString()))
    meter_name = None
    if source_class == target_class:
        meter_name = (
            "DistrictCooling:Facility" if cooling else "DistrictHeatingWater:Facility"
        )
        meter = o.model.OutputMeter(model)
        meter.setName(meter_name)
        meter.setReportingFrequency("Hourly")
    pump_keys = [
        ("Pump Electricity Energy", x.nameString())
        for x in loop.supplyComponents()
        if x.iddObjectType().valueName().startswith("OS_Pump_")
    ]
    pump_heat_keys = [("Pump Fluid Heat Gain Energy", key) for _, key in pump_keys]
    variable_keys += pump_keys + pump_heat_keys
    for variable, key in variable_keys:
        output = o.model.OutputVariable(variable, model)
        output.setKeyValue(key)
        output.setReportingFrequency("Hourly")
    # Preparation/companions already supplied portable weather; set absolute only
    # inside this isolated simulation fixture, not in the operation under test.
    weather = Path(str(model.getWeatherFile().path().get()))
    if not weather.is_absolute():
        weather = source.parent / weather
    assert o.model.WeatherFile.setWeatherFile(
        model, o.EpwFile(str(weather.resolve()))
    ).is_initialized()
    instrumented = folder / "instrumented.osm"
    assert model.save(str(instrumented), True)
    workflow = folder / "workflow.osw"
    workflow.write_text(json.dumps(dict(seed_file=str(instrumented), steps=[])))
    run = subprocess.run(
        [str(native_cli()), "run", "-w", str(workflow)],
        cwd=folder,
        capture_output=True,
        text=True,
        timeout=180,
    )
    (folder / "cli.log").write_text(run.stdout + run.stderr)
    assert run.returncode == 0, run.stdout + run.stderr
    err = (folder / "run/eplusout.err").read_text()
    assert "EnergyPlus Completed Successfully" in err and not re.search(
        r"\*\*\s*(?:Severe|Fatal)\s*\*\*", err, re.I
    ), err
    data = {}
    with sqlite3.connect(folder / "run/eplusout.sql") as sql:
        for variable, key in variable_keys:
            rows = sql.execute(
                "SELECT r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE d.Name=? AND lower(d.KeyValue)=lower(?) AND t.WarmupFlag=0 ORDER BY t.TimeIndex",
                (variable, key),
            ).fetchall()
            assert rows, (variable, key)
            data[variable + "|" + key] = [x[0] for x in rows]
        purchased_j = None
        if meter_name:
            rows = sql.execute(
                "SELECT r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE lower(d.Name)=lower(?) AND d.IsMeter=1 AND d.ReportingFrequency='Hourly' AND t.WarmupFlag=0",
                (meter_name,),
            ).fetchall()
            assert rows, meter_name
            purchased_j = sum(x[0] for x in rows)
    observed = dict(
        hours=len(data[source_energy + "|" + obj.nameString()]),
        useful_thermal_j=sum(data[source_energy + "|" + obj.nameString()]),
        fuel_or_compressor_j=(
            sum(data[energy_input + "|" + obj.nameString()]) if energy_input else None
        ),
        purchased_thermal_meter_j=purchased_j,
        pump_j=sum(sum(data[v + "|" + k]) for v, k in pump_keys),
        pump_fluid_heat_gain_j=sum(sum(data[v + "|" + k]) for v, k in pump_heat_keys),
        plant_demand_j=sum(
            data[
                (
                    "Plant Supply Side Cooling Demand Rate|"
                    if cooling
                    else "Plant Supply Side Heating Demand Rate|"
                )
                + loop.nameString()
            ]
        )
        * 3600,
        peak_unmet_w=max(
            abs(x)
            for x in data["Plant Supply Side Unmet Demand Rate|" + loop.nameString()]
        ),
        outlet_range_c=[
            min(data[outlet + "|" + obj.nameString()]),
            max(data[outlet + "|" + obj.nameString()]),
        ],
    )
    (folder / "hourly.json").write_text(json.dumps(data, indent=2))
    (folder / "observed.json").write_text(json.dumps(observed, indent=2))
    return observed


@pytest.mark.parametrize("kind", ["NaturalGas", "AirCooled", "WaterCooled"])
def test_native_conversion_and_explicit_condenser_cleanup(sdk, tmp_path, kind):
    from test_supply_fan_performance import native_cli

    native_cli()
    o = sdk[0]
    if kind == "NaturalGas":
        from test_boiler_performance import parasitic_fixture

        path, model, old = parasitic_fixture(o, tmp_path, kind)
        old.setNominalCapacity(100000)
    else:
        from test_chiller_performance import native_fixture

        path, model, old, _, _ = native_fixture(
            sdk, tmp_path, kind, autosized_condenser=kind == "WaterCooled"
        )
        # This fixture adds a chiller-local setpoint to test other editors.
        # Use loop-setpoint dispatch for this explicitly scoped conversion case.
        for manager in (
            old.supplyOutletModelObject().get().to_Node().get().setpointManagers()
        ):
            manager.remove()
    assert model.save(str(path), True)
    original = path.read_bytes()
    loop = old.plantLoop().get()
    cfg = dict(
        output_model_path=str(tmp_path / "district.osm"),
        plant_loop=dict(handle=str(loop.handle())),
        equipment=dict(handle=str(old.handle())),
        target_class=(
            "DistrictHeatingWater" if kind == "NaturalGas" else "DistrictCooling"
        ),
        nominal_capacity_w=200000,
        capacity_fraction_schedule=dict(
            handle=str(model.alwaysOnDiscreteSchedule().handle())
        ),
        reference_policy="Reject",
    )
    assert model.save(str(path), True)
    original = path.read_bytes()
    report = preflight(path, cfg, True)
    assert report["ready"], report
    result = apply(report, tmp_path, True)
    after_path = Path(result["output_model_path"])
    if kind == "WaterCooled":
        condenser = report["plan"]["impact"]["condenser_plant"]
        cleanup = preflight(
            after_path,
            dict(
                output_model_path=str(tmp_path / "cleaned.osm"),
                plant_loops=[dict(handle=condenser["handle"])],
            ),
        )
        assert cleanup["ready"], cleanup
        cleaned = apply(cleanup, tmp_path)
        after_path = Path(cleaned["output_model_path"])
    before = native_run(
        o, path, tmp_path / "before-run", str(old.handle()), cfg["target_class"]
    )
    after = native_run(
        o,
        after_path,
        tmp_path / "after-run",
        result["changes"]["replacement_equipment"]["handle"],
        cfg["target_class"],
    )
    assert before["hours"] == after["hours"] == 72
    assert before["useful_thermal_j"] > 1e7 and after["useful_thermal_j"] > 1e7
    if kind == "NaturalGas":
        assert after["useful_thermal_j"] == pytest.approx(
            before["useful_thermal_j"], rel=1e-6
        )
    # District flow/dispatch differs from chiller control: preserve setpoints
    # and meet demand, rather than asserting identical plant heat/pump energy.
    assert after["outlet_range_c"] == pytest.approx(before["outlet_range_c"], abs=1e-5)
    assert before["fuel_or_compressor_j"] > 0 and after["fuel_or_compressor_j"] is None
    assert after["purchased_thermal_meter_j"] == pytest.approx(
        after["useful_thermal_j"], rel=1e-8
    )
    assert after["peak_unmet_w"] < 1
    for observed in (before, after):
        assert observed["plant_demand_j"] == pytest.approx(
            observed["useful_thermal_j"], rel=1e-8
        )
        assert 0 <= observed["pump_fluid_heat_gain_j"] <= observed["pump_j"]
    assert path.read_bytes() == original
    (tmp_path / "native_evidence.json").write_text(
        json.dumps(
            dict(
                kind=kind,
                before=before,
                after=after,
                condenser_cleanup=kind == "WaterCooled",
                source_unchanged=True,
            ),
            indent=2,
        )
    )


@pytest.mark.parametrize("kind", ["NaturalGas", "AirCooled"])
def test_component_setpoint_dispatch_is_unready(sdk, tmp_path, kind):
    o = sdk[0]
    path, model, old, cfg = fixture(o, tmp_path, kind)
    outlet = (
        (
            old.outletModelObject()
            if kind == "NaturalGas"
            else old.supplyOutletModelObject()
        )
        .get()
        .to_Node()
        .get()
    )
    schedule = o.model.ScheduleConstant(model)
    schedule.setValue(80 if kind == "NaturalGas" else 7)
    assert o.model.SetpointManagerScheduled(model, schedule).addToNode(outlet)
    assert model.save(str(path), True)
    report = preflight(path, cfg, True)
    assert not report["ready"] and "component-setpoint" in str(report["plan"]["errors"])
    assert not Path(cfg["output_model_path"]).exists()


@pytest.mark.parametrize("replace", [False, True])
def test_shared_chiller_curves_survive(sdk, tmp_path, replace):
    o = sdk[0]
    path, model, old, cfg = fixture(o, tmp_path, "AirCooled")
    shared = old.coolingCapacityFunctionOfTemperature()
    other = o.model.ChillerElectricEIR(model)
    other.setCondenserType("AirCooled")
    assert other.setCoolingCapacityFunctionOfTemperature(shared)
    assert (
        model.getPlantLoopByName("Keep Plant").get().addSupplyBranchForComponent(other)
    )
    assert model.save(str(path), True)
    raw = str(shared.idfObject())
    report = preflight(path, cfg if replace else removal(tmp_path), replace)
    assert report["ready"], report
    result = apply(report, tmp_path, replace)
    saved, _ = load_model(o, result["output_model_path"])
    assert str(saved.getModelObject(shared.handle()).get().idfObject()) == raw
    assert saved.getChillerElectricEIR(other.handle()).is_initialized()


def test_condenser_with_another_chiller_remains_loaded(sdk, tmp_path):
    o = sdk[0]
    path, model, old, cfg = fixture(o, tmp_path, "WaterCooled")
    other = o.model.ChillerElectricEIR(model)
    other.setCondenserType("WaterCooled")
    assert (
        model.getPlantLoopByName("Keep Plant").get().addSupplyBranchForComponent(other)
    )
    assert old.secondaryPlantLoop().get().addDemandBranchForComponent(other)
    assert model.save(str(path), True)
    report = preflight(path, cfg, True)
    assert report["ready"], report
    assert report["plan"]["impact"]["condenser_remaining_demand_equipment_count"] == 1
    result = apply(report, tmp_path, True)
    condenser = report["plan"]["impact"]["condenser_plant"]
    cleanup = preflight(
        Path(result["output_model_path"]), removal(tmp_path, condenser["name"])
    )
    assert not cleanup["ready"] and "active demand" in str(cleanup["plan"]["errors"])


def test_multiple_unused_plants_require_explicit_selection(sdk, tmp_path):
    path, _, _, _ = fixture(sdk[0], tmp_path)
    cfg = removal(tmp_path)
    cfg["plant_loops"].append(dict(name="Keep Plant"))
    report = preflight(path, cfg)
    assert report["ready"] and len(report["plan"]["impact"]["plant_loops"]) == 2
    result = apply(report, tmp_path)
    saved, _ = load_model(sdk[0], result["output_model_path"])
    assert not saved.getPlantLoops()


def test_saved_district_capacity_mutation_rejects(sdk, tmp_path):
    path, _, _, cfg = fixture(sdk[0], tmp_path)
    report = preflight(path, cfg, True)

    def wrong(model, o, planned):
        result = plants.replace_source(model, o, planned)
        model.getDistrictHeatingWaters()[0].setNominalCapacity(1)
        return result

    with pytest.raises(ValueError, match="validation"):
        apply(report, tmp_path, True, wrong)
    assert not Path(cfg["output_model_path"]).exists()


@pytest.mark.parametrize("host", ["claude", "codex"])
@pytest.mark.parametrize("replace", [False, True])
def test_native_relocated_exports(sdk, tmp_path, host, replace):
    import shutil
    import subprocess
    from adapters.claude_code_adapter import ClaudeCodeAdapter
    from adapters.codex_adapter import CodexAdapter
    from adapters.contracts import HostAdapterConfig
    from plugin_fixture import copy_plugin_for_skill
    from test_supply_fan_performance import native_cli

    exe = str(native_cli())
    path, _, _, cfg = fixture(sdk[0], tmp_path)
    adapter = (ClaudeCodeAdapter if host == "claude" else CodexAdapter)(
        HostAdapterConfig(
            host_name=host, workspace_root=Path.cwd(), runtime_mode="marketplace"
        )
    )
    exported = tmp_path / "export"
    adapter.export_plugin(exported, dry_run=False)
    owner = (
        "openstudio-plant-equipment-replacer" if replace else "openstudio-hvac-remover"
    )
    skill = next(exported.rglob(owner + "/SKILL.md")).parent
    for relative in (
        "scripts/doctor.py",
        "scripts/sdk_probe.py",
        "scripts/prepare_model.py",
        "../../sdk/references/model_preparation.md",
        "../../sdk/references/plant_operations.md",
    ):
        assert (skill / relative).is_file()
    skill = copy_plugin_for_skill(skill, tmp_path / "relocated plugin")
    shutil.rmtree(exported)
    cfgfile = tmp_path / "config.json"
    cfgfile.write_text(json.dumps(cfg if replace else removal(tmp_path)))
    reviewed, repeat = tmp_path / "plan.json", tmp_path / "repeat.json"
    script = "replace_plant_equipment.py" if replace else "remove_unused_plants.py"
    for args in (
        ["--input", str(path), "--report", str(tmp_path / "inventory.json")],
        ["--input", str(path), "--config", str(cfgfile), "--report", str(reviewed)],
        ["--input", str(path), "--config", str(cfgfile), "--report", str(repeat)],
        ["--plan", str(reviewed), "--report", str(tmp_path / "apply.json")],
    ):
        run = subprocess.run(
            [exe, "execute_python_script", str(skill / "scripts" / script), *args],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(reviewed.read_text()) == json.loads(repeat.read_text())
    assert json.loads((tmp_path / "apply.json").read_text())["validation"]["ok"]


def test_metadata_cannot_be_reassigned_outside_replacement(sdk, tmp_path):
    path, _, _, cfg = fixture(sdk[0], tmp_path)
    report = preflight(path, cfg, True)

    def wrong(model, o, planned):
        result = plants.replace_source(model, o, planned)
        metadata = model.getAdditionalProperties(
            o.toUUID(planned["resolved_objects"]["metadata"]["handle"])
        ).get()
        metadata.setPointer(1, model.getPlantLoopByName("Keep Plant").get().handle())
        return result

    with pytest.raises(ValueError, match="validation"):
        apply(report, tmp_path, True, wrong)
    assert not Path(cfg["output_model_path"]).exists()


def test_inventory_role_matches_preflight(sdk, tmp_path):
    o = sdk[0]
    path, model, _, cfg = fixture(o, tmp_path)
    loop = model.getPlantLoopByName("Selected Plant").get()
    loop.sizingPlant().setLoopType("Condenser")
    assert model.save(str(path), True)
    item = next(
        x
        for x in plants.inventory(model)["plant_loops"]
        if x["handle"] == str(loop.handle())
    )
    assert not next(
        x for x in item["supply_equipment"] if x["type"] == "OS_Boiler_HotWater"
    )["replacement_supported"]
    assert not preflight(path, cfg, True)["ready"]


@pytest.mark.parametrize("missing", ["pump", "setpoint"])
def test_missing_plant_controls_warn_without_repair(sdk, tmp_path, missing):
    o = sdk[0]
    path, model, _, cfg = fixture(o, tmp_path)
    loop = model.getPlantLoopByName("Selected Plant").get()
    if missing == "pump":
        model.getPumpVariableSpeeds()[0].remove()
    else:
        for manager in loop.supplyOutletNode().setpointManagers():
            manager.remove()
    assert model.save(str(path), True)
    report = preflight(path, cfg, True)
    assert report["ready"] and not report["plan"]["simulation_ready"]
    assert "lacks" in str(report["warnings"])


@pytest.mark.parametrize("kind", ["NaturalGas", "AirCooled"])
@pytest.mark.parametrize("schedule_kind", ["temperature", "negative", "untyped"])
def test_incompatible_schedule_is_plan_error_before_preview(
    sdk, tmp_path, monkeypatch, kind, schedule_kind
):
    o = sdk[0]
    path, model, _, cfg = fixture(o, tmp_path, kind)
    schedule = o.model.ScheduleConstant(model)
    if schedule_kind != "untyped":
        limits = o.model.ScheduleTypeLimits(model)
        limits.setUnitType(
            "Temperature" if schedule_kind == "temperature" else "Dimensionless"
        )
        limits.setLowerLimitValue(-60 if schedule_kind == "temperature" else -1)
        limits.setUpperLimitValue(200 if schedule_kind == "temperature" else 1)
        assert schedule.setScheduleTypeLimits(limits)
    cfg["capacity_fraction_schedule"] = dict(handle=str(schedule.handle()))
    assert model.save(str(path), True)
    original = path.read_bytes()

    def forbidden(*args):
        pytest.fail("Invalid schedule reached model preview")

    monkeypatch.setattr(plants, "replace_source", forbidden)
    report = preflight(path, cfg, True)
    assert not report["ready"] and not report["plan"]["simulation_ready"]
    assert "type limits" in str(report["plan"]["errors"])
    assert path.read_bytes() == original and not Path(cfg["output_model_path"]).exists()


def test_invalid_schedule_cli_never_captures_failure(
    sdk, tmp_path, monkeypatch, capsys
):
    o = sdk[0]
    path, model, _, cfg = fixture(o, tmp_path)
    schedule = o.model.ScheduleConstant(model)
    limits = o.model.ScheduleTypeLimits(model)
    limits.setUnitType("Temperature")
    assert schedule.setScheduleTypeLimits(limits)
    cfg["capacity_fraction_schedule"] = dict(handle=str(schedule.handle()))
    assert model.save(str(path), True)
    config_path, report_path = tmp_path / "config.json", tmp_path / "plan.json"
    config_path.write_text(json.dumps(cfg))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "replace_plant_equipment.py",
            "--input",
            str(path),
            "--config",
            str(config_path),
            "--report",
            str(report_path),
        ],
    )

    def forbidden(*args, **kwargs):
        pytest.fail("Expected configuration result entered automatic failure reporting")

    monkeypatch.setattr(tx, "capture_exception", forbidden)
    assert (
        tx.cli(
            "replace_plant_equipment",
            plants.replacement_plan,
            plants.replace_source,
            plants.validate_replacement,
            plants.inventory,
        )
        == 2
    )
    report = json.loads(report_path.read_text())
    assert report["operation"] == "replace_plant_equipment" and not report["ready"]
    assert (
        "failure_receipt" not in report
        and "failure_receipt" not in capsys.readouterr().out
    )


@pytest.mark.parametrize("kind", ["NaturalGas", "AirCooled"])
def test_fraction_schedule_above_one_remains_compatible(sdk, tmp_path, kind):
    o = sdk[0]
    path, model, _, cfg = fixture(o, tmp_path, kind)
    schedule = o.model.ScheduleConstant(model)
    limits = o.model.ScheduleTypeLimits(model)
    limits.setUnitType("Dimensionless")
    limits.setLowerLimitValue(0)
    limits.setUpperLimitValue(2)
    assert schedule.setScheduleTypeLimits(limits)
    assert schedule.setValue(1.5)
    cfg["capacity_fraction_schedule"] = dict(handle=str(schedule.handle()))
    assert model.save(str(path), True)
    report = preflight(path, cfg, True)
    assert report["ready"], report
    assert apply(report, tmp_path, True)["ok"]


@pytest.mark.parametrize(
    "unsupported", ["evaporative", "heat_recovery", "missing_condenser"]
)
def test_chiller_inventory_scope_matches_rejection(sdk, tmp_path, unsupported):
    o = sdk[0]
    path, model, old, cfg = fixture(o, tmp_path, "AirCooled")
    if unsupported == "evaporative":
        assert old.setCondenserType("EvaporativelyCooled")
    elif unsupported == "heat_recovery":
        recovery = o.model.PlantLoop(model)
        assert recovery.addDemandBranchForComponent(old, True)
    else:
        index = next(
            i for i, (name, _) in raw_fields(old).items() if name == "Condenser Type"
        )
        assert old.setString(index, "WaterCooled")
    assert model.save(str(path), True)
    loop = next(
        x
        for x in plants.inventory(model)["plant_loops"]
        if x["name"] == "Selected Plant"
    )
    assert not next(
        x for x in loop["supply_equipment"] if x["handle"] == str(old.handle())
    )["replacement_supported"]
    report = preflight(path, cfg, True)
    assert not report["ready"] and report["plan"]["errors"]


@pytest.mark.parametrize("side", ["inlet", "outlet"])
def test_series_condenser_pipe_returns_unready(sdk, tmp_path, side):
    o = sdk[0]
    path, model, old, cfg = fixture(o, tmp_path, "WaterCooled")
    port = (
        old.demandInletModelObject()
        if side == "inlet"
        else old.demandOutletModelObject()
    )
    pipe = o.model.PipeAdiabatic(model)
    assert pipe.addToNode(port.get().to_Node().get())
    assert model.save(str(path), True)
    report = preflight(path, cfg, True)
    assert not report["ready"] and "single-chiller branch" in str(
        report["plan"]["errors"]
    )
    assert not Path(cfg["output_model_path"]).exists()


def test_operation_scheme_blocker_identifies_named_owner(sdk, tmp_path):
    o = sdk[0]
    path, model, old, _ = fixture(o, tmp_path)
    scheme = o.model.PlantEquipmentOperationHeatingLoad(model)
    scheme.setName("Office heating dispatch")
    assert scheme.addEquipment(old)
    assert (
        model.getPlantLoopByName("Selected Plant")
        .get()
        .setPlantEquipmentOperationHeatingLoad(scheme)
    )
    assert model.save(str(path), True)
    report = preflight(path, removal(tmp_path))
    assert not report["ready"]
    blockers = report["plan"]["impact"]["blocking_references"]
    owners = [x for blocker in blockers for x in blocker.get("referenced_by", [])]
    assert any(
        x["name"] == "Office heating dispatch"
        and x["type"] == "OS_PlantEquipmentOperation_HeatingLoad"
        for x in owners
    )
    assert "remove/reassign" in str(report["plan"]["errors"])


def test_empty_condenser_warns_about_unvalidated_idle_operation(sdk, tmp_path):
    path, _, _, cfg = fixture(sdk[0], tmp_path, "WaterCooled")
    report = preflight(path, cfg, True)
    assert report["ready"]
    assert report["plan"]["impact"]["condenser_remaining_demand_equipment_count"] == 0
    assert "idle energy" in str(report["warnings"]) and "not native-validated" in str(
        report["warnings"]
    )
