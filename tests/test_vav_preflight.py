from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

SCRIPTS = Path("skills/sdk_scripts").resolve()


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    from common.input_validation import validate
    from common.vav_plan import plan

    return validate, plan


@pytest.fixture
def catalog():
    return {
        "zones": [
            {
                "handle": "zone-1",
                "name": "Zone 1",
                "spaces": [{"name": "Space 1", "handle": "space-1"}],
                "is_plenum": False,
                "can_be_plenum": True,
                "plenum_air_loops": [],
                "has_thermostat": True,
                "has_dual_setpoint_schedules": True,
                "air_loops": [],
                "equipment": [],
            }
        ],
        "air_loops": [],
        "plant_loops": [
            {
                "handle": "heat-loop",
                "name": "HW",
                "loop_type": "Heating",
                "design_supply_temperature_c": 82.2,
                "design_delta_temperature_k": 11.1,
                "supply_equipment": [{"name": "Boiler"}],
                "supply_setpoint_managers": [{"name": "SPM"}],
                "supply_pumps": [{"name": "Pump"}],
            },
            {
                "handle": "cool-loop",
                "name": "CHW",
                "loop_type": "Cooling",
                "design_supply_temperature_c": 6.7,
                "design_delta_temperature_k": 5.6,
                "supply_equipment": [{"name": "Chiller"}],
                "supply_setpoint_managers": [{"name": "SPM"}],
                "supply_pumps": [{"name": "Pump"}],
            },
        ],
        "schedules": [
            {
                "handle": "operation",
                "name": "Operation",
                "type_limits": {"unit_type": "Availability", "lower": 0, "upper": 1},
            }
        ],
    }


@pytest.fixture
def config(tmp_path):
    return {
        "system_name": "New VAV",
        "output_model_path": str(tmp_path / "out.osm"),
        "target_zones": [{"name": "Zone 1"}],
        "defaults_profile": "prototype_vav_v1",
        "central_heating": {"type": "Electricity"},
        "central_cooling": {"type": "DXTwoSpeed", "dx_approved": True},
        "reheat": {"type": "Water", "plant_loop": {"name": "HW"}},
    }


def test_complete_plan_is_deterministic_and_preserves_arguments(
    modules, config, catalog, tmp_path
):
    _, plan = modules
    original = deepcopy(config)
    result = plan(config, catalog, tmp_path / "in.osm")
    assert result["ready"]
    assert result == plan(config, catalog, tmp_path / "in.osm")
    assert config == original

    assert result["resolved_objects"]["target_zones"] == [
        {"handle": "zone-1", "name": "Zone 1"}
    ]
    assert result["parameters"]["fan"]["pressure_rise_pa"] == pytest.approx(996.35564)
    assert result["parameters"]["design_temperatures_c"]["zone_heating"] == 40
    assert result["assumptions"]
    assert all(s.startswith("Object:New VAV.") for s in result["assumptions"])
    assert not (tmp_path / "out.osm").exists()


def test_recipe_specific_fan_fields_still_convert_pressure(
    modules, config, catalog, tmp_path
):
    from common.multizone_plan import PROFILE, plan

    profile = deepcopy(PROFILE)
    profile["fan"] = {"pressure_rise": 4.0, "pressure_units": "inH2O"}
    result = plan(config, catalog, tmp_path / "in.osm", profile=profile)
    assert result["ready"], result
    assert result["parameters"]["fan"]["pressure_rise_pa"] == pytest.approx(996.35564)


def test_no_profile_means_no_assumed_defaults(modules, catalog, tmp_path):
    _, plan = modules
    result = plan({}, catalog, tmp_path / "in.osm")
    assert not result["ready"]
    assert not result["assumptions"]
    assert "target_zones" in result["missing_inputs"]
    assert result["resolved_objects"]["target_zones"] == []


def test_explicit_schedule_is_not_merged_with_builtin(
    modules, config, catalog, tmp_path
):
    _, plan = modules
    config["availability_schedule"] = {"name": "Operation"}
    result = plan(config, catalog, tmp_path / "in.osm")
    assert result["ready"]
    assert result["parameters"]["availability_schedule"] == {"name": "Operation"}
    assert (
        result["resolved_objects"]["schedules"]["availability_schedule"]["handle"]
        == "operation"
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"fan": {"pressure_rise": 900}},
        {"fan": {"pressure_units": "Pa"}},
        {"central_cooling": {"type": "DXTwoSpeed"}},
        {"reheat": {"type": "Water"}},
        {"central_heating": {}},
    ],
)
def test_conditional_missing_inputs_block_ready(
    modules, config, catalog, tmp_path, patch
):
    _, plan = modules
    config.update(patch)
    result = plan(config, catalog, tmp_path / "in.osm")
    assert not result["ready"] and result["missing_inputs"]


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_name",
        "duplicate_selector",
        "existing_airloop",
        "equipment",
        "no_thermostat",
        "plenum",
        "no_spaces",
        "wrong_loop",
        "existing_system",
        "bad_schedule",
        "missing_zone",
    ],
)
def test_model_conflicts_block_ready(modules, config, catalog, tmp_path, change):
    _, plan = modules
    zone = catalog["zones"][0]
    if change == "duplicate_name":
        catalog["zones"].append({**zone, "handle": "zone-2"})
    elif change == "duplicate_selector":
        config["target_zones"].append({"handle": "zone-1"})
    elif change == "existing_airloop":
        zone["air_loops"] = [{"name": "Existing", "handle": "existing"}]
    elif change == "equipment":
        zone["equipment"] = [{"name": "Heater", "handle": "heater"}]
    elif change == "no_thermostat":
        zone["has_thermostat"] = False
    elif change == "plenum":
        zone["is_plenum"] = True
    elif change == "no_spaces":
        zone["spaces"] = []
    elif change == "wrong_loop":
        config["reheat"]["plant_loop"] = {"name": "CHW"}
    elif change == "existing_system":
        catalog["air_loops"] = [{"name": "New VAV", "handle": "existing"}]
    elif change == "bad_schedule":
        config["availability_schedule"] = {"name": "Operation"}
        catalog["schedules"][0]["type_limits"]["unit_type"] = "Temperature"
    elif change == "missing_zone":
        config["target_zones"] = [{"name": "Missing"}]
    result = plan(config, catalog, tmp_path / "in.osm")
    assert not result["ready"] and result["errors"]


def test_handle_resolves_duplicate_names(modules, config, catalog, tmp_path):
    _, plan = modules
    catalog["zones"].append({**catalog["zones"][0], "handle": "zone-2"})
    config["target_zones"] = [{"handle": "zone-1"}]
    assert plan(config, catalog, tmp_path / "in.osm")["ready"]


@pytest.mark.parametrize(
    "kind", ["input", "existing", "relative", "wrong_extension", "parent_file"]
)
def test_unsafe_output_is_rejected(modules, config, catalog, tmp_path, kind):
    _, plan = modules
    source = tmp_path / "in.osm"
    source.touch()
    if kind == "input":
        config["output_model_path"] = str(source)
    elif kind == "existing":
        Path(config["output_model_path"]).touch()
    elif kind == "relative":
        config["output_model_path"] = "out.osm"
    elif kind == "wrong_extension":
        config["output_model_path"] = str(tmp_path / "out.idf")
    elif kind == "parent_file":
        config["output_model_path"] = str(source / "out.osm")
    assert plan(config, catalog, source)["errors"]


@pytest.mark.parametrize(
    "patch",
    [
        {"typo": 1},
        {"fan": {"total_efficiency": True}},
        {"fan": {"pressure_rise": 0}},
        {"fan": {"total_efficiency": 1.1}},
        {"fan": {"pressure_rise": float("nan")}},
        {"fan": {"pressure_rise": 10**1000}},
        {"fan": {"pressure_units": "psi"}},
        {"target_zones": [{"name": "a", "handle": "b"}]},
        {"target_zones": [{}]},
        {"target_zones": []},
        {"target_zones": [{"name": " "}]},
        {"central_heating": {"type": "Steam"}},
        {"defaults_profile": "ASHRAE-2019"},
        {"economizer": "unsupported"},
        {"design_temperatures_c": {"zone_heating": 101}},
        {"central_heating": {"type": "Water", "plant_loop": {"name": "HW", "typo": 1}}},
    ],
)
def test_schema_rejects_invalid_config(modules, config, patch):
    validate, _ = modules
    schema = json.loads((SCRIPTS / "references/vav_input.schema.json").read_text())
    config.update(patch)
    assert validate(config, schema)


def test_partial_inputs_and_explicit_config_pass_schema(modules, config):
    validate, _ = modules
    schema = json.loads((SCRIPTS / "references/vav_input.schema.json").read_text())
    assert validate({}, schema) == []
    assert validate(config, schema) == []


@pytest.fixture
def sdk(monkeypatch):
    openstudio = pytest.importorskip("openstudio")
    if openstudio.openStudioVersion() != "3.11.0":
        pytest.skip("Requires exactly OpenStudio 3.11.0")
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "vav_preflight_script", SCRIPTS / "vav_preflight.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return openstudio, module


@pytest.fixture
def model_file(sdk, tmp_path):
    os, _ = sdk
    model = os.model.Model()
    zone = os.model.ThermalZone(model)
    zone.setName("Zone 1")
    space = os.model.Space(model)
    space.setThermalZone(zone)
    thermostat = os.model.ThermostatSetpointDualSetpoint(model)
    heat = os.model.ScheduleConstant(model)
    heat.setValue(20.0)
    cool = os.model.ScheduleConstant(model)
    cool.setValue(24.0)
    assert thermostat.setHeatingSetpointTemperatureSchedule(heat)
    assert thermostat.setCoolingSetpointTemperatureSchedule(cool)
    zone.setThermostatSetpointDualSetpoint(thermostat)
    loop = os.model.PlantLoop(model)
    loop.setName("HW")
    loop.sizingPlant().setLoopType("Heating")
    prepare_existing_plant(os, model, loop, True)
    path = tmp_path / "in.osm"
    assert model.save(str(path), True)
    return path


def test_native_preflight_preserves_model_and_is_repeatable(
    sdk, model_file, config, tmp_path
):
    _, module = sdk
    configuration = tmp_path / "config.json"
    configuration.write_text(json.dumps(config))
    before = model_file.read_bytes()
    result = module.preflight(model_file, configuration)
    assert result["ok"] and result["ready"], result
    assert result == module.preflight(model_file, configuration)
    assert result["input_sha256"] == hashlib.sha256(before).hexdigest()
    assert model_file.read_bytes() == before
    assert not Path(config["output_model_path"]).exists()


def test_assumption_review_does_not_approve_or_create(
    sdk, model_file, config, tmp_path
):
    _, module = sdk
    from common.vav_plan import PROFILE, CONTROLS
    from report import emit

    config.pop("defaults_profile")
    config["fan"] = {"pressure_rise": 750, "pressure_units": "Pa"}
    original = deepcopy(config)
    configuration = tmp_path / "review-config.json"
    configuration.write_text(json.dumps(config))
    before = model_file.read_bytes()
    result = module.preflight(model_file, configuration)
    assert not result["ready"] and "defaults_profile" in result["missing_inputs"]
    review = result["assumption_review"]
    assert review["status"] == "needs_review"
    rows = {row["field"]: row for row in review["inputs"]}
    assert rows["fan.pressure_rise"]["value"] == 750
    assert rows["fan.pressure_rise"]["source"] == "user_input"
    assert rows["fan.total_efficiency"]["value"] == PROFILE["fan"]["total_efficiency"]
    assert rows["fan.total_efficiency"]["source"] == "proposed_default"
    assert {row["field"]: row["value"] for row in review["fixed_controls"]} == CONTROLS
    assert all(not row["editable"] for row in review["fixed_controls"])
    review["fixed_controls"][0]["value"] = "changed proposal"
    assert result["plan"]["controls"] == {}  # Review cannot authorize construction.
    assert config == original and model_file.read_bytes() == before
    assert not Path(config["output_model_path"]).exists()
    report_path = tmp_path / "review.json"
    summary = emit(result, report_path)
    assert summary["assumption_review"]["status"] == "needs_review"
    assert "fixed_controls" not in summary["assumption_review"]
    assert json.loads(report_path.read_text())["assumption_review"] == review


@pytest.mark.parametrize(
    "contents",
    ['{"system_name":"a","system_name":"b"}', '{"fan":{"pressure_rise":NaN}}'],
)
def test_strict_json_input(sdk, model_file, tmp_path, contents):
    _, module = sdk
    config = tmp_path / "bad.json"
    config.write_text(contents)
    with pytest.raises(ValueError):
        module.preflight(model_file, config)


def test_wrong_sdk_blocks_before_input_read(sdk, monkeypatch, tmp_path):
    os, module = sdk
    monkeypatch.setattr(os, "openStudioVersion", lambda: "3.10.0")
    with pytest.raises(RuntimeError, match="executing SDK"):
        module.preflight(tmp_path / "nonexistent.osm")


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_native_exported_preflight_runs_from_unrelated_directory(
    sdk, model_file, config, tmp_path, host, monkeypatch
):
    import os
    from adapters.claude_code_adapter import ClaudeCodeAdapter
    from adapters.codex_adapter import CodexAdapter
    from adapters.contracts import HostAdapterConfig

    executable = Path(
        os.environ.get(
            "OPENSTUDIO_SKILL_TEST_EXE",
            "/Applications/OpenStudio-3.11.0/bin/openstudio",
        )
    )
    if not executable.is_file():
        pytest.skip("Native OpenStudio CLI unavailable; set OPENSTUDIO_SKILL_TEST_EXE")
    adapter_type = ClaudeCodeAdapter if host == "claude" else CodexAdapter
    result = adapter_type(
        HostAdapterConfig(
            host_name="claude_code" if host == "claude" else host,
            workspace_root=Path.cwd(),
            runtime_mode="marketplace",
        )
    ).export_plugin(tmp_path / "export", dry_run=False)
    skill = result.plugin_dir / "skills/openstudio-vav-reheat-system-creator"
    configuration = tmp_path / "config.json"
    configuration.write_text(json.dumps(config))
    foreign = tmp_path / "foreign" / "common"
    foreign.mkdir(parents=True)
    (foreign / "__init__.py").write_text("raise RuntimeError('foreign helper loaded')")
    monkeypatch.setenv("PYTHONPATH", str(foreign.parent))
    before = model_file.read_bytes()
    completed = subprocess.run(
        [
            str(executable),
            "execute_python_script",
            str(skill / "scripts/vav_preflight.py"),
            "--input",
            str(model_file),
            "--config",
            str(configuration),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=45,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    report = json.loads(completed.stdout.splitlines()[-1])
    assert report["ready"] and report["ok"], report
    assert report["input_sha256"] == hashlib.sha256(before).hexdigest()
    assert model_file.read_bytes() == before
    assert not Path(config["output_model_path"]).exists()


def test_conversion_overflow_blocks_plan(modules, config, catalog, tmp_path):
    _, plan = modules
    config["fan"] = {"pressure_rise": 1e308, "pressure_units": "inH2O"}
    result = plan(config, catalog, tmp_path / "in.osm")
    assert not result["ready"]
    assert result["errors"]
    json.dumps(result, allow_nan=False)


def test_explicit_pascal_pressure_and_distinct_plenum(
    modules, config, catalog, tmp_path
):
    _, plan = modules
    config["fan"] = {"pressure_rise": 900, "pressure_units": "Pa"}
    catalog["zones"].append(
        {
            **catalog["zones"][0],
            "handle": "plenum",
            "name": "Plenum",
            "is_plenum": False,
            "can_be_plenum": True,
            "plenum_air_loops": [],
            "has_thermostat": False,
        }
    )
    config["return_plenum"] = {"handle": "plenum"}
    result = plan(config, catalog, tmp_path / "in.osm")
    assert result["ready"]
    assert result["parameters"]["fan"]["pressure_rise_pa"] == 900
    assert result["resolved_objects"]["return_plenum"]["handle"] == "plenum"
    assert result["conversions"] == []


def test_older_model_translation_is_repeatable_and_read_only(sdk):
    _, module = sdk
    source = Path("tests/fixtures/sample.osm").resolve()
    before = source.read_bytes()
    first = module.preflight(source)
    second = module.preflight(source)
    assert first == second
    assert first["ok"] and not first["ready"]
    assert source.read_bytes() == before


def test_dangling_output_symlink_blocks_ready(modules, config, catalog, tmp_path):
    _, plan = modules
    output = Path(config["output_model_path"])
    output.symlink_to(tmp_path / "missing.osm")
    assert plan(config, catalog, tmp_path / "in.osm")["errors"]


def test_sat_temperature_obeys_prototype_type_limits(
    modules, config, catalog, tmp_path
):
    _, plan = modules
    config["design_temperatures_c"] = {"central_cooling": -1.0}
    assert plan(config, catalog, tmp_path / "in.osm")["errors"]


def prepare_existing_plant(os, model, loop, heating):
    supply = 82.222222 if heating else 6.666667
    loop.sizingPlant().setDesignLoopExitTemperature(supply)
    loop.sizingPlant().setLoopDesignTemperatureDifference(
        11.111111 if heating else 5.611111
    )
    source = (
        os.model.DistrictHeatingWater(model)
        if heating
        else os.model.DistrictCooling(model)
    )
    assert loop.addSupplyBranchForComponent(source)
    pump = os.model.PumpVariableSpeed(model)
    assert pump.addToNode(loop.supplyInletNode())
    schedule = os.model.ScheduleConstant(model)
    schedule.setValue(supply)
    manager = os.model.SetpointManagerScheduled(model, schedule)
    assert manager.addToNode(loop.supplyOutletNode())


@pytest.mark.parametrize(
    "value,expected",
    [
        ({"head": 4, "units": "ft"}, ["$.head: violates maximum 3"]),
        ({"head": 3, "units": "ft"}, []),
        ({"head": 4, "units": "Pa"}, []),
        ({"head": 1001, "units": "Pa"}, ["$.head: violates maximum 1000"]),
        ({"head": 4}, []),
        ({}, []),
    ],
)
def test_bounded_schema_conditional_limits_respect_required_inputs(
    modules, value, expected
):
    validate, _ = modules
    schema = {
        "type": "object",
        "if": {"required": ["units"], "properties": {"units": {"enum": ["ft"]}}},
        "then": {"properties": {"head": {"maximum": 3}}},
        "else": {"properties": {"head": {"maximum": 1000}}},
    }
    assert validate(value, schema) == expected


@pytest.mark.parametrize(
    "count,expected",
    [
        (0, ["$.curve: requires at least 4 items"]),
        (3, ["$.curve: requires at least 4 items"]),
        (4, []),
        (5, ["$.curve: requires at most 4 items"]),
    ],
)
def test_bounded_schema_array_length_reports_nested_path(modules, count, expected):
    validate, _ = modules
    schema = {
        "type": "object",
        "properties": {
            "curve": {
                "type": "array",
                "minItems": 4,
                "maxItems": 4,
                "items": {"type": "number"},
            }
        },
    }
    assert validate({"curve": [1] * count}, schema) == expected
