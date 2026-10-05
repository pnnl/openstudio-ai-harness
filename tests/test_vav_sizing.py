"""Native design-day verification; simulation is outside the skill edit scripts."""

from __future__ import annotations
import json
import os
from pathlib import Path
import sqlite3
import shutil
import subprocess
import pytest
from test_vav_apply import sdk, apply_module, reviewed_plan
from vav_fixture import prepare_vav_fixture


@pytest.mark.parametrize(
    "hydronic,use_schedule_file", [(True, False), (False, False), (True, True)]
)
def test_native_vav_design_day_sizing(
    sdk, apply_module, tmp_path, hydronic, use_schedule_file
):
    exe = Path(
        os.environ.get(
            "OPENSTUDIO_SKILL_TEST_EXE",
            "/Applications/OpenStudio-3.11.0/bin/openstudio",
        )
    )
    if not exe.is_file():
        pytest.skip("Native 3.11.0 CLI unavailable")
    source_path, config, fixture, original = prepare_vav_fixture(
        sdk[0], tmp_path, hydronic
    )
    schedule_source = None
    if use_schedule_file:
        o = sdk[0]
        model = o.osversion.VersionTranslator().loadModel(str(source_path)).get()
        source_workflow = (
            source_path.with_name(source_path.stem + "_files") / "workflow.osw"
        )
        model.workflowJSON().setOswPath(str(source_workflow))
        schedule_source = source_workflow.parent / "files/schedule.csv"
        schedule_source.parent.mkdir()
        schedule_source.write_text("value\n" + "0.5\n" * 8760)
        external = o.model.ExternalFile.getExternalFile(
            model, str(schedule_source)
        ).get()
        schedule = o.model.ScheduleFile(external)
        schedule.setRowstoSkipatTop(1)
        assert model.getLightss()[0].setSchedule(schedule)
        assert model.save(str(source_path), True)
    plan_file = reviewed_plan(sdk, source_path, config, tmp_path)
    report = apply_module.apply(plan_file)
    assert report["validation"]["ok"]
    workflow = Path(report["workflow_path"])
    if use_schedule_file:
        moved = tmp_path / "moved"
        moved.mkdir()
        shutil.move(report["output_model_path"], moved / "vav.osm")
        shutil.move(report["companion_directory"], moved / "vav")
        workflow = moved / "vav/workflow.osw"
        schedule_source.unlink()  # The simulation must use the copied resource.
    run_dir = workflow.parent / "run"
    assert not Path(json.loads(workflow.read_text())["weather_file"]).is_absolute()
    completed = subprocess.run(
        [str(exe), "run", "-w", str(workflow)],
        cwd=workflow.parent,
        capture_output=True,
        text=True,
        timeout=120,
    )
    (tmp_path / "cli.log").write_text(completed.stdout + completed.stderr)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    error_file = run_dir / "eplusout.err"
    errors = error_file.read_text()
    assert "** Severe **" not in errors and "**  Fatal  **" not in errors, errors
    assert "EnergyPlus Completed Successfully" in errors, errors
    sql = run_dir / "eplusout.sql"
    with sqlite3.connect(sql) as connection:
        sizing = connection.execute(
            "SELECT CompType, CompName, Description, Value, Units FROM ComponentSizes WHERE upper(CompName) LIKE '%SIZING VAV%' OR upper(CompName) LIKE '%VAV TERMINAL%' OR upper(CompName) LIKE '%REHEAT COIL%'"
        ).fetchall()
    (tmp_path / "sizing_evidence.json").write_text(
        json.dumps(
            {
                "hydronic": hydronic,
                "validation": report["validation"],
                "component_sizes": sizing,
            },
            indent=2,
        )
    )
    fan_flows = [
        row[3]
        for row in sizing
        if row[0] == "Fan:VariableVolume" and "Maximum Flow Rate" in row[2]
    ]
    terminal_flows = [
        row[3]
        for row in sizing
        if "AirTerminal:SingleDuct:VAV:Reheat" == row[0]
        and "Maximum Air Flow Rate" in row[2]
    ]
    assert len(fan_flows) == 1 and fan_flows[0] > 0, sizing
    assert len(terminal_flows) == 5 and all(x > 0 for x in terminal_flows), sizing
    reheat_capacities = [
        row[3]
        for row in sizing
        if row[1].endswith("REHEAT COIL")
        and row[2] in ("Design Size Rated Capacity", "Design Size Nominal Capacity")
    ]
    cooling_capacities = [
        row[3]
        for row in sizing
        if row[1] == "SIZING VAV COOLING COIL"
        and row[2]
        in (
            "Design Size Design Coil Load",
            "Design Size High Speed Gross Rated Total Cooling Capacity",
        )
    ]
    assert len(reheat_capacities) == 5 and all(x > 0 for x in reheat_capacities), sizing
    assert len(cooling_capacities) == 1 and cooling_capacities[0] > 0, sizing
    assert 'PlantLoop="MAIN SERVICE WATER LOOP"' not in errors
    assert "No node connection errors were found." in errors
    assert fixture.read_bytes() == original
