"""No-reheat class conversions retain branch service and unrelated raw fields."""

import json
import sys
from pathlib import Path

import pytest
from test_vav_preflight import sdk, model_file, SCRIPTS
from test_terminal_edit import fixture as vav_fixture

sys.path.insert(0, str(SCRIPTS))
from common import model_transaction as tx, terminal_replacement as terminals

OPERATION = "replace_terminal"


def fixture(o, source, folder, source_class="VAVNoReheat"):
    model, old = vav_fixture(o, source, folder, reheat=False)
    old.setZoneMinimumAirFlowInputMethod("Constant")
    old.setConstantMinimumAirFlowFraction(0.3)
    old.setMaximumAirFlowRate(0.5)
    if source_class == "ConstantVolumeNoReheat":
        loop = model.getAirLoopHVACs()[0]
        zone = model.getThermalZoneByName("Zone 1").get()
        assert loop.removeBranchForZone(zone)
        old = o.model.AirTerminalSingleDuctConstantVolumeNoReheat(
            model, model.alwaysOnDiscreteSchedule()
        )
        old.setMaximumAirFlowRate(0.5)
        old.setName("Selected Terminal")
        old.additionalProperties().setFeature("review_note", "retain")
        assert loop.addBranchForZone(zone, old)
    assert model.save(str(source), True)
    return model, old


def config(folder, target="ConstantVolumeNoReheat", maximum="Preserve"):
    result = dict(
        output_model_path=str(folder / "replaced.osm"),
        air_loop={"name": "Existing Air Loop"},
        zone={"name": "Zone 1"},
        terminal={"name": "Selected Terminal"},
        target_class=target,
        maximum_airflow_m3_s=maximum,
        availability_policy="Preserve",
        reheat_policy="None",
        zone_sizing_policy="Preserve",
        system_sizing_policy="Preserve",
        reference_policy="Reject",
    )
    if target == "VAVNoReheat":
        result["minimum_airflow_fraction"] = 0.2
    return result


def preflight(source, cfg):
    return tx.preflight(source, cfg, OPERATION, terminals.plan)


def apply(report, folder, creator=None):
    path = folder / "plan.json"
    path.write_text(json.dumps(report))
    return tx.apply(
        path,
        OPERATION,
        terminals.plan,
        creator or terminals.replace,
        terminals.validate_model,
    )


@pytest.mark.parametrize("target", ["ConstantVolumeNoReheat", "VAVNoReheat"])
@pytest.mark.parametrize("maximum", ["Preserve", "Autosize", 0.4])
def test_saved_class_service_identity_and_fields(
    sdk, model_file, tmp_path, target, maximum
):
    o = sdk[0]
    source_class = (
        "VAVNoReheat"
        if target == "ConstantVolumeNoReheat"
        else "ConstantVolumeNoReheat"
    )
    model, old = fixture(o, model_file, tmp_path, source_class)
    old_handle = str(old.handle())
    metadata = str(old.additionalProperties().handle())
    source = model_file.read_bytes()
    cfg = config(tmp_path, target, maximum)
    report = preflight(model_file, cfg)
    assert report["ready"], report
    assert report == preflight(model_file, cfg)
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and result["translation"]["ok"], result
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    terminal = terminals.typed(saved, o, result["changes"]["replacement_terminal"])
    assert str(terminal.handle()) != old_handle
    assert not saved.getModelObject(o.toUUID(old_handle)).is_initialized()
    assert str(terminal.additionalProperties().handle()) == metadata
    assert terminals.ports(terminal) == report["plan"]["resolved_objects"]["ports"]
    assert terminal.nameString() == "Selected Terminal"
    assert terminals.sized(terminal, "maximumAirFlowRate") == (
        0.5 if maximum == "Preserve" else maximum
    )
    assert model_file.read_bytes() == source


@pytest.mark.parametrize(
    "field",
    [
        "air_loop",
        "zone",
        "terminal",
        "target_class",
        "maximum_airflow_m3_s",
        "availability_policy",
        "reheat_policy",
        "zone_sizing_policy",
        "system_sizing_policy",
        "reference_policy",
        "minimum_airflow_fraction",
    ],
)
def test_missing_choices_never_infer_defaults(sdk, model_file, tmp_path, field):
    fixture(sdk[0], model_file, tmp_path, "ConstantVolumeNoReheat")
    cfg = config(tmp_path, "VAVNoReheat")
    del cfg[field]
    report = preflight(model_file, cfg)
    assert not report["ready"] and field in report["plan"]["missing_inputs"]
    assert not (tmp_path / "replaced.osm").exists()


@pytest.mark.parametrize(
    "case",
    [
        "same_class",
        "reheat",
        "oa",
        "scheduled",
        "fixed_minimum",
        "turndown",
        "minimum_schedule",
        "wrong_zone",
        "invalid_fraction",
        "invalid_maximum",
        "cv_fraction",
    ],
)
def test_unsupported_controls_and_scope_are_unready(sdk, model_file, tmp_path, case):
    o = sdk[0]
    model, terminal = (
        vav_fixture(o, model_file, tmp_path, reheat=True)
        if case == "reheat"
        else fixture(o, model_file, tmp_path)
    )
    cfg = config(tmp_path)
    if case == "same_class":
        cfg.update(target_class="VAVNoReheat", minimum_airflow_fraction=0.2)
    elif case == "oa":
        terminal.setControlForOutdoorAir(True)
    elif case in ("scheduled", "fixed_minimum"):
        terminal.setZoneMinimumAirFlowInputMethod(
            "Scheduled" if case == "scheduled" else "FixedFlowRate"
        )
    elif case in ("turndown", "minimum_schedule"):
        schedule = o.model.ScheduleConstant(model)
        schedule.setValue(0.7)
        getattr(
            terminal,
            (
                "setMinimumAirFlowTurndownSchedule"
                if case == "turndown"
                else "setMinimumAirFlowFractionSchedule"
            ),
        )(schedule)
    elif case == "wrong_zone":
        cfg["zone"] = {"name": "Unserved zone"}
    elif case == "invalid_fraction":
        cfg.update(target_class="VAVNoReheat", minimum_airflow_fraction=1.1)
    elif case == "invalid_maximum":
        cfg["maximum_airflow_m3_s"] = -1
    elif case == "cv_fraction":
        cfg["minimum_airflow_fraction"] = 0.2
    model.save(str(model_file), True)
    if case.startswith("invalid"):
        with pytest.raises(ValueError, match="Invalid terminal replacement"):
            preflight(model_file, cfg)
    else:
        report = preflight(model_file, cfg)
        assert not report["ready"] and report["plan"]["errors"], report


@pytest.mark.parametrize(
    "kind", ["cost", "ems", "compatible_output", "incompatible_output"]
)
def test_reference_policies(sdk, model_file, tmp_path, kind):
    o = sdk[0]
    model, terminal = fixture(o, model_file, tmp_path)
    if kind == "cost":
        o.model.LifeCycleCost.createLifeCycleCost(
            "Maintenance", terminal, 100, "CostPerEach", "Maintenance", 1, 0
        ).get()
    elif kind == "ems":
        o.model.EnergyManagementSystemActuator(
            terminal, "AirTerminal:SingleDuct:VAV:NoReheat", "Mass Flow Rate"
        )
    else:
        output = o.model.OutputVariable(
            (
                "Zone Air Terminal Outdoor Air Volume Flow Rate"
                if kind == "compatible_output"
                else "Zone Air Terminal VAV Damper Position"
            ),
            model,
        )
        output.setKeyValue(terminal.nameString())
    model.save(str(model_file), True)
    report = preflight(model_file, config(tmp_path))
    if kind == "compatible_output":
        assert report["ready"], report
        assert report["plan"]["impact"]["retained_output_reference_count"] == 1
        assert apply(report, tmp_path)["validation"]["ok"]
    else:
        assert not report["ready"] and "Reference policy Reject" in " ".join(
            report["plan"]["errors"]
        )


def test_compatible_output_ems_sensor_is_explicitly_blocked_by_policy(
    sdk, model_file, tmp_path
):
    o = sdk[0]
    model, terminal = fixture(o, model_file, tmp_path)
    sensor = o.model.EnergyManagementSystemSensor(
        model, "Zone Air Terminal Outdoor Air Volume Flow Rate"
    )
    sensor.setKeyName(terminal.nameString())
    model.save(str(model_file), True)
    original = model_file.read_bytes()
    report = preflight(model_file, config(tmp_path))
    assert not report["ready"]
    errors = " ".join(report["plan"]["errors"])
    assert "EMS sensor blocked by policy, even for a compatible output" in errors
    assert "incompatible name-keyed" not in errors
    assert model_file.read_bytes() == original


@pytest.mark.parametrize("constant_fan", [True, False])
def test_vav_target_reports_retained_fan_class_and_power_warning(
    sdk, model_file, tmp_path, constant_fan
):
    o = sdk[0]
    model, _ = fixture(o, model_file, tmp_path, "ConstantVolumeNoReheat")
    loop = model.getAirLoopHVACs()[0]
    if constant_fan:
        from common import fan_class_replacement as fans

        cfg = dict(
            output_model_path=str(tmp_path / "fan-fixture.osm"),
            air_loop={"handle": str(loop.handle())},
            target_class="ConstantVolume",
            fan=dict(
                total_efficiency=0.7,
                motor_efficiency=0.9,
                pressure_rise=500,
                pressure_units="Pa",
            ),
            sizing="Autosize",
            terminal_policy="Preserve",
            system_sizing_policy="Preserve",
            reference_policy="Reject",
        )
        planned = fans.plan(model, o, cfg)
        assert planned["ready"], planned
        fans.replace(model, o, planned)
    model.save(str(model_file), True)
    report = preflight(model_file, config(tmp_path, "VAVNoReheat"))
    assert report["ready"], report
    impact = report["plan"]["impact"]
    kind = "OS_Fan_ConstantVolume" if constant_fan else "OS_Fan_VariableVolume"
    assert [x["type"] for x in impact["retained_supply_fans"]] == [kind]
    warning = " ".join(report["warnings"])
    assert ("openstudio-supply-fan-replacer" in warning) == constant_fan
    if constant_fan:
        assert (
            "proportionally" in warning
            and "without a variable-volume part-load curve" in warning
        )
        assert impact["retained_supply_fans"][0]["name"] in warning
    assert apply(report, tmp_path)["validation"]["ok"]


def system_fan_fixture(o, source, folder, mode="Discrete", multiple=False):
    model, _ = fixture(o, source, folder, "ConstantVolumeNoReheat")
    loop = model.getAirLoopHVACs()[0]
    loop.supplyFan().get().remove()
    fan = o.model.FanSystemModel(model)
    fan.setName("Acme Tower 123 Main Street engineering@acme.example")
    assert fan.setSpeedControlMethod(mode)
    if mode == "Continuous":
        curve = o.model.CurveCubic(model)
        curve.setCoefficient1Constant(0)
        curve.setCoefficient2x(0)
        curve.setCoefficient3xPOW2(0)
        curve.setCoefficient4xPOW3(1)
        assert fan.setElectricPowerFunctionofFlowFractionCurve(curve)
    elif multiple:
        assert fan.addSpeed(0.5, 0.125)
        assert fan.addSpeed(1, 1)
        assert fan.numberofSpeeds() == 2
    assert fan.addToNode(loop.supplyOutletNode())
    model.save(str(source), True)
    return model, fan


@pytest.mark.parametrize(
    "mode,multiple", [("Discrete", False), ("Discrete", True), ("Continuous", False)]
)
def test_system_model_fan_warning_matches_speed_control(
    sdk, model_file, tmp_path, mode, multiple
):
    o = sdk[0]
    _, fan = system_fan_fixture(o, model_file, tmp_path, mode, multiple)
    original = model_file.read_bytes()
    report = preflight(model_file, config(tmp_path, "VAVNoReheat"))
    assert report["ready"], report
    assert report == preflight(model_file, config(tmp_path, "VAVNoReheat"))
    observed = report["plan"]["impact"]["retained_supply_fans"][0]
    assert observed["type"] == "OS_Fan_SystemModel"
    assert observed["speed_control_method"] == mode
    assert observed["number_of_speeds"] == (2 if multiple else 1)
    assert (observed["power_curve"] is not None) == (mode == "Continuous")
    warning = " ".join(report["warnings"])
    assert ("OS_Fan_SystemModel with Discrete speed control" in warning) == (
        mode == "Discrete"
    )
    if mode == "Discrete":
        assert fan.nameString() in warning
        assert ("Multiple Discrete speeds" in warning) == multiple
        assert ("cycles on/off" in warning) != multiple
        assert "need separate coverage" in warning
    result = apply(report, tmp_path)
    assert result["validation"]["ok"] and result["translation"]["ok"]
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    assert terminals.fingerprint(
        saved.getFanSystemModel(fan.handle()).get()
    ) == terminals.fingerprint(fan)
    assert model_file.read_bytes() == original


def test_model_named_plan_warnings_never_enter_failure_issue(
    sdk, model_file, tmp_path, monkeypatch
):
    from common import failure_reporting as reporting
    from test_failure_reporting import FakeGitHub
    from types import SimpleNamespace

    _, fan = system_fan_fixture(sdk[0], model_file, tmp_path)
    report = preflight(model_file, config(tmp_path, "VAVNoReheat"))
    assert report["ready"]
    assert fan.nameString() in " ".join(report["warnings"])
    plan = tmp_path / "reviewed.json"
    plan.write_text(json.dumps(report))
    state = tmp_path / "incidents"
    monkeypatch.setenv("OPENSTUDIO_AI_FAILURE_DIR", str(state))
    captured = reporting.capture_exception(
        RuntimeError("Saved validation failed"),
        OPERATION,
        "apply",
        args=SimpleNamespace(plan=plan),
        report=report,
    )
    receipt = Path(captured["failure_receipt"])
    private = reporting.read_json(receipt.with_name("private.json"))
    public = reporting.read_json(receipt)["public"]
    assert "warnings" not in private and "plan" not in private
    assert "warnings" not in public and "plan" not in public
    transport = FakeGitHub()
    assert reporting.submit(receipt, state, transport)["status"] == "submitted"
    for payload in [
        public,
        reporting.read_json(receipt.with_name("issue.json")),
        transport.posts,
    ]:
        text = json.dumps(payload)
        for token in [
            fan.nameString(),
            "Acme Tower",
            "123 Main Street",
            "engineering@acme.example",
        ]:
            assert token not in text


@pytest.mark.parametrize(
    "location", ["sizing", "mechanical", "mechanical_limit", "neither"]
)
def test_vrp_warning_covers_sizing_and_mechanical_ventilation(
    sdk, model_file, tmp_path, location
):
    o = sdk[0]
    model, _ = fixture(o, model_file, tmp_path)
    loop = model.getAirLoopHVACs()[0]
    method = "Standard62.1VentilationRateProcedure"
    if location == "sizing":
        assert loop.sizingSystem().setSystemOutdoorAirMethod(method)
    elif location.startswith("mechanical"):
        if location == "mechanical_limit":
            method += "WithLimit"
        mv = (
            loop.airLoopHVACOutdoorAirSystem()
            .get()
            .getControllerOutdoorAir()
            .controllerMechanicalVentilation()
        )
        assert mv.setSystemOutdoorAirMethod(method)
    model.save(str(model_file), True)
    report = preflight(model_file, config(tmp_path))
    assert report["ready"], report
    impact = report["plan"]["impact"]
    assert impact["system_oa_sizing_may_change"] == (location != "neither")
    assert (
        "Ventilation Rate Procedure is enabled" in " ".join(report["warnings"])
    ) == (location != "neither")
    assert report == preflight(model_file, config(tmp_path))
    assert apply(report, tmp_path)["validation"]["ok"]


def test_other_equipment_priority_and_schedules_retained(sdk, model_file, tmp_path):
    o = sdk[0]
    model, terminal = fixture(o, model_file, tmp_path)
    zone = model.getThermalZoneByName("Zone 1").get()
    heater = o.model.ZoneHVACBaseboardConvectiveElectric(model)
    heater.addToThermalZone(zone)
    zone.setHeatingPriority(heater, 1)
    zone.setHeatingPriority(terminal, 2)
    equipment = next(
        x
        for x in model.getZoneHVACEquipmentLists()
        if x.thermalZone().handle() == zone.handle()
    )
    schedule = o.model.ScheduleConstant(model)
    schedule.setValue(0.75)
    equipment.setSequentialHeatingFractionSchedule(terminal, schedule)
    model.save(str(model_file), True)
    before = terminals.signatures(model, terminal, [str(equipment.handle())])
    report = preflight(model_file, config(tmp_path))
    assert report["ready"], report
    result = apply(report, tmp_path)
    saved = o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
    new = terminals.typed(saved, o, result["changes"]["replacement_terminal"])
    assert terminals.signatures(saved, new, before) == before


def test_preview_cannot_change_another_equipment_pointer(
    sdk, model_file, tmp_path, monkeypatch
):
    o = sdk[0]
    model, _ = fixture(o, model_file, tmp_path)
    zone = model.getThermalZoneByName("Zone 1").get()
    first = o.model.ZoneHVACBaseboardConvectiveElectric(model)
    second = o.model.ZoneHVACBaseboardConvectiveElectric(model)
    first.addToThermalZone(zone)
    second.addToThermalZone(zone)
    model.save(str(model_file), True)
    real_replace = terminals.replace

    def changed(preview, sdk, planned):
        result = real_replace(preview, sdk, planned)
        equipment = preview.getModelObject(
            sdk.toUUID(planned["resolved_objects"]["equipment_list"]["handle"])
        ).get()
        index = next(
            i
            for i, (name, value) in terminals.raw_fields(equipment).items()
            if name == "Zone Equipment" and value == str(first.handle())
        )
        assert equipment.setPointer(index, second.handle())
        return result

    monkeypatch.setattr(terminals, "replace", changed)
    with pytest.raises(
        ValueError, match="unrelated boundary, metadata or equipment-list"
    ):
        preflight(model_file, config(tmp_path))
    assert not (tmp_path / "replaced.osm").exists()


@pytest.mark.parametrize("multiplier", [1, 10])
def test_total_oa_and_terminal_minimum_are_reported(
    sdk, model_file, tmp_path, multiplier
):
    o = sdk[0]
    model, _ = fixture(o, model_file, tmp_path, "ConstantVolumeNoReheat")
    zone = model.getThermalZoneByName("Zone 1").get()
    zone.setMultiplier(multiplier)
    oa = o.model.DesignSpecificationOutdoorAir(model)
    oa.setOutdoorAirFlowRate(0.02)
    zone.spaces()[0].setDesignSpecificationOutdoorAir(oa)
    model.save(str(model_file), True)
    report = preflight(model_file, config(tmp_path, "VAVNoReheat", 0.05))
    assert report["ready"], report
    impact = report["plan"]["impact"]
    assert impact["zone_nominal_oa_m3_s"] == pytest.approx(0.02 * multiplier)
    assert impact["nominal_minimum_supply_flow_m3_s"] == pytest.approx(0.01)
    assert (report["plan"].get("simulation_ready") is False) == (multiplier == 10)
    assert "Supply fraction is not OA fraction" in " ".join(report["warnings"])


@pytest.mark.parametrize(
    "mutation",
    [
        "name",
        "maximum",
        "availability",
        "minimum",
        "metadata",
        "priority",
        "node_name",
        "other_equipment",
        "new_object",
        "graph",
    ],
)
def test_mutations_fail_before_publication(sdk, model_file, tmp_path, mutation):
    o = sdk[0]
    fixture(o, model_file, tmp_path, "ConstantVolumeNoReheat")
    report = preflight(model_file, config(tmp_path, "VAVNoReheat"))
    assert report["ready"], report

    def changed(model, sdk, planned):
        result = terminals.replace(model, sdk, planned)
        terminal = terminals.typed(model, sdk, result["replacement_terminal"])
        if mutation == "name":
            terminal.setName("Wrong name")
        elif mutation == "maximum":
            terminal.setMaximumAirFlowRate(9)
        elif mutation == "availability":
            terminal.setAvailabilitySchedule(model.alwaysOffDiscreteSchedule())
        elif mutation == "minimum":
            terminal.setConstantMinimumAirFlowFraction(0.9)
        elif mutation == "metadata":
            terminal.additionalProperties().setFeature("review_note", "changed")
        elif mutation == "priority":
            equipment = model.getModelObject(
                sdk.toUUID(planned["resolved_objects"]["equipment_list"]["handle"])
            ).get()
            assert equipment.setInt(
                planned["resolved_objects"]["equipment_slot"] + 1, 9
            )
        elif mutation == "node_name":
            terminal.inletModelObject().get().setName("Changed node")
        elif mutation == "other_equipment":
            model.getFanVariableVolumes()[0].setPressureRise(99)
        elif mutation == "new_object":
            o.model.FanVariableVolume(model)
        elif mutation == "graph":
            model.disconnect(terminal, terminal.inletPort())
        return result

    with pytest.raises(ValueError):
        apply(report, tmp_path, changed)
    assert not (tmp_path / "replaced.osm").exists()


@pytest.mark.parametrize("mode", ["tampered", "stale"])
def test_exact_review_and_source_hash_still_enforced(sdk, model_file, tmp_path, mode):
    fixture(sdk[0], model_file, tmp_path)
    report = preflight(model_file, config(tmp_path))
    assert report["ready"]
    if mode == "tampered":
        report["plan"]["parameters"]["maximum_airflow_m3_s"] = 9
    else:
        model_file.write_bytes(
            model_file.read_bytes() + b"\n! Changed after approval\n"
        )
    with pytest.raises(ValueError):
        apply(report, tmp_path)
    assert not (tmp_path / "replaced.osm").exists()


@pytest.mark.parametrize("tamper", [False, True])
def test_csv_companion_move_and_hash(sdk, model_file, tmp_path, monkeypatch, tamper):
    import shutil
    from common.companions import external_file_status

    o = sdk[0]
    model, _ = fixture(o, model_file, tmp_path)
    monkeypatch.chdir(tmp_path)
    csv = tmp_path / "loads.csv"
    csv.write_text("value\n" + "0.5\n" * 8760)
    external = o.model.ExternalFile.getExternalFile(model, str(csv)).get()
    schedule = o.model.ScheduleFile(external)
    schedule.setRowstoSkipatTop(1)
    lights = o.model.Lights(o.model.LightsDefinition(model))
    lights.setSpace(model.getThermalZoneByName("Zone 1").get().spaces()[0])
    lights.setSchedule(schedule)
    model.save(str(model_file), True)
    original = model_file.read_bytes()
    report = preflight(model_file, config(tmp_path))
    assert report["ready"], report
    bound = Path(
        next(
            x["source"]
            for x in report["plan"]["companions"]["resources"]
            if x["target"].endswith("loads.csv")
        )
    )
    if tamper:
        bound.write_text(bound.read_text() + "0.1\n")
        with pytest.raises(ValueError):
            apply(report, tmp_path)
        assert not (tmp_path / "replaced.osm").exists()
        return
    result = apply(report, tmp_path)
    moved = tmp_path / "moved"
    moved.mkdir()
    shutil.move(result["output_model_path"], moved / "replaced.osm")
    shutil.move(result["companion_directory"], moved / "replaced")
    for path in {csv, bound}:
        path.unlink()
    model = o.osversion.VersionTranslator().loadModel(str(moved / "replaced.osm")).get()
    assert result["requires_companion_workflow"]
    model.workflowJSON().setOswPath(str(moved / "replaced/workflow.osw"))
    assert external_file_status(model)["ok"]
    assert model_file.read_bytes() == original


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_native_relocated_complete_exports(sdk, model_file, tmp_path, host):
    import shutil
    import subprocess
    from adapters.claude_code_adapter import ClaudeCodeAdapter
    from adapters.codex_adapter import CodexAdapter
    from adapters.contracts import HostAdapterConfig
    from plugin_fixture import copy_plugin_for_skill
    from test_supply_fan_performance import native_cli

    exe = str(native_cli())
    target = "ConstantVolumeNoReheat" if host == "claude" else "VAVNoReheat"
    fixture(
        sdk[0],
        model_file,
        tmp_path,
        "VAVNoReheat" if host == "claude" else "ConstantVolumeNoReheat",
    )
    original = model_file.read_bytes()
    setup = HostAdapterConfig(
        host_name=host, workspace_root=Path.cwd(), runtime_mode="marketplace"
    )
    adapter = ClaudeCodeAdapter(setup) if host == "claude" else CodexAdapter(setup)
    exported = tmp_path / "export"
    adapter.export_plugin(exported, dry_run=False)
    skill = next(exported.rglob("openstudio-terminal-replacer/SKILL.md")).parent
    for relative in (
        "scripts/doctor.py",
        "scripts/sdk_probe.py",
        "scripts/prepare_model.py",
        "references/model_preparation.md",
        "references/terminal_replacement.md",
        "references/terminal_replacement.schema.json",
    ):
        assert (skill / relative).is_file(), relative
    skill = copy_plugin_for_skill(skill, tmp_path / "relocated")
    shutil.rmtree(exported)
    cfg = tmp_path / "request.json"
    cfg.write_text(json.dumps(config(tmp_path, target)))
    script = skill / "scripts/replace_terminal.py"
    reviewed = tmp_path / "reviewed.json"
    repeated = tmp_path / "repeated.json"
    for args in (
        ["--input", str(model_file), "--report", str(tmp_path / "inventory.json")],
        ["--input", str(model_file), "--config", str(cfg), "--report", str(reviewed)],
        ["--input", str(model_file), "--config", str(cfg), "--report", str(repeated)],
        ["--plan", str(reviewed), "--report", str(tmp_path / "applied.json")],
    ):
        run = subprocess.run(
            [exe, "execute_python_script", str(script), *args],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert run.returncode == 0, run.stdout + run.stderr
    result = json.loads((tmp_path / "applied.json").read_text())
    assert result["validation"]["ok"] and result["translation"]["ok"]
    assert json.loads(reviewed.read_text()) == json.loads(repeated.read_text())
    assert model_file.read_bytes() == original
    assert json.loads((tmp_path / "inventory.json").read_text())["candidates"][
        "terminals"
    ][0]["supported"]


def native_run(o, source, folder, terminal_ref):
    import sqlite3
    import subprocess
    from test_supply_fan_performance import native_cli

    folder.mkdir()
    model = o.osversion.VersionTranslator().loadModel(str(source)).get()
    terminal = terminals.typed(model, o, terminal_ref)
    node = terminal.outletModelObject().get()
    zone = model.getThermalZoneByName("Core_ZN ZN").get()
    variables = {
        "System Node Standard Density Volume Flow Rate": node.nameString(),
        "System Node Temperature": node.nameString(),
        "Zone Mean Air Temperature": zone.nameString(),
        "Zone Air Terminal Outdoor Air Volume Flow Rate": terminal.nameString(),
    }
    for variable, key in variables.items():
        output = o.model.OutputVariable(variable, model)
        output.setKeyValue(key)
        output.setReportingFrequency("Hourly")
    weather = Path(str(model.getWeatherFile().path().get()))
    if not weather.is_absolute():
        weather = source.parent / weather
    assert o.model.WeatherFile.setWeatherFile(
        model, o.EpwFile(str(weather.resolve()))
    ).is_initialized()
    instrumented = folder / "instrumented.osm"
    assert model.save(str(instrumented), True)
    workflow = folder / "workflow.osw"
    workflow.write_text(json.dumps({"seed_file": str(instrumented), "steps": []}))
    run = subprocess.run(
        [str(native_cli()), "run", "-w", str(workflow)],
        cwd=folder,
        capture_output=True,
        text=True,
        timeout=120,
    )
    (folder / "cli.log").write_text(run.stdout + run.stderr)
    assert run.returncode == 0, run.stdout + run.stderr
    err = (folder / "run/eplusout.err").read_text()
    assert (
        "EnergyPlus Completed Successfully" in err
        and "** Severe **" not in err
        and "**  Fatal  **" not in err
    ), err
    with sqlite3.connect(folder / "run/eplusout.sql") as sql:
        data = {}
        for variable, key in variables.items():
            rows = sql.execute(
                "SELECT t.EnvironmentPeriodIndex,t.SimulationDays,t.Hour,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE d.Name=? AND lower(d.KeyValue)=lower(?) AND t.WarmupFlag=0 ORDER BY t.TimeIndex",
                (variable, key),
            ).fetchall()
            assert rows, (variable, key)
            data[variable] = rows
        sizes = sql.execute(
            "SELECT CompType,Description,Value FROM ComponentSizes WHERE lower(CompName)=lower(?)",
            (terminal.nameString(),),
        ).fetchall()
    flow = [
        row[3]
        for row in data["System Node Standard Density Volume Flow Rate"]
        if row[3] > 1e-6
    ]
    assert flow
    observed = dict(
        terminal=terminal_ref,
        hours=len(data["System Node Temperature"]),
        active_hours=len(flow),
        active_flow_range_m3_s=[min(flow), max(flow)],
        discharge_range_c=[
            min(x[3] for x in data["System Node Temperature"]),
            max(x[3] for x in data["System Node Temperature"]),
        ],
        zone_temperature_range_c=[
            min(x[3] for x in data["Zone Mean Air Temperature"]),
            max(x[3] for x in data["Zone Mean Air Temperature"]),
        ],
        component_sizes=sizes,
        warnings=err,
    )
    (folder / "observed.json").write_text(json.dumps(observed, indent=2))
    (folder / "hourly.json").write_text(json.dumps(data, indent=2))
    return observed


@pytest.mark.parametrize("target", ["ConstantVolumeNoReheat", "VAVNoReheat"])
def test_native_bidirectional_operating_flow(sdk, tmp_path, target):
    import hashlib
    from test_supply_fan_performance import native_cli
    from vav_fixture import prepare_vav_fixture
    from common.hvac_inventory import inventory as hvac_inventory
    from common.vav_plan import plan as vav_plan
    from common.vav_create import create as create_vav

    native_cli()
    o = sdk[0]
    unserved, cfg, original_fixture, original_bytes = prepare_vav_fixture(
        o, tmp_path, False
    )
    model = o.osversion.VersionTranslator().loadModel(str(unserved)).get()
    planned = vav_plan(cfg, hvac_inventory(model), None)
    assert planned["ready"], planned
    create_vav(model, o, planned)
    loop = model.getAirLoopHVACByName("Sizing VAV").get()
    zone = model.getThermalZoneByName("Core_ZN ZN").get()
    assert loop.removeBranchForZone(zone)
    source_class = (
        "VAVNoReheat"
        if target == "ConstantVolumeNoReheat"
        else "ConstantVolumeNoReheat"
    )
    terminal = getattr(o.model, terminals.CLASSES[source_class])(
        model, model.alwaysOnDiscreteSchedule()
    )
    terminal.setName("Selected Terminal")
    terminal.autosizeMaximumAirFlowRate()
    if source_class == "VAVNoReheat":
        terminal.setZoneMinimumAirFlowInputMethod("Constant")
        terminal.setConstantMinimumAirFlowFraction(0.3)
        terminal.setControlForOutdoorAir(False)
    terminal.additionalProperties().setFeature("review_note", "retain")
    assert loop.addBranchForZone(zone, terminal)
    source = tmp_path / "before.osm"
    assert model.save(str(source), True)
    before_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    request = config(tmp_path, target, "Preserve")
    request["air_loop"] = {"name": "Sizing VAV"}
    request["zone"] = {"name": "Core_ZN ZN"}
    report = preflight(source, request)
    assert report["ready"], report
    assert report == preflight(source, request)
    result = apply(report, tmp_path)
    before = native_run(o, source, tmp_path / "before_run", terminals.ref(terminal))
    after = native_run(
        o,
        Path(result["output_model_path"]),
        tmp_path / "after_run",
        result["changes"]["replacement_terminal"],
    )
    cv, vav = (after, before) if target == "ConstantVolumeNoReheat" else (before, after)
    assert cv["hours"] == vav["hours"] == 72
    assert cv["active_flow_range_m3_s"][0] == pytest.approx(
        cv["active_flow_range_m3_s"][1], rel=1e-5
    )
    assert vav["active_flow_range_m3_s"][0] < 0.8 * cv["active_flow_range_m3_s"][0]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before_hash
    assert original_fixture.read_bytes() == original_bytes
    (tmp_path / "native_evidence.json").write_text(
        json.dumps(
            dict(
                target=target,
                before=before,
                after=after,
                source_sha256=before_hash,
                source_unchanged=True,
                validation=result["validation"],
                translation=result["translation"],
            ),
            indent=2,
        )
    )
