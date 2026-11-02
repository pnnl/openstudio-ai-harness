"""PR 47: permit companion EPW hydration without weakening preservation checks."""

import json
from pathlib import Path
import shutil

import pytest

import test_boiler_performance as boiler
import test_district_capacity as district
import test_terminal_edit as terminal
import test_terminal_replacement as replacement
import test_tower_performance as tower
from test_vav_preflight import sdk, model_file


@pytest.mark.slow
@pytest.mark.parametrize("workflow", [boiler, district, terminal, replacement, tower])
@pytest.mark.parametrize("case", ["empty", "populated", "changed_epw", "tampered_flag"])
def test_companion_weather_preservation(sdk, model_file, tmp_path, workflow, case):
    o = sdk[0]
    if workflow in (terminal, replacement):
        source = model_file
        model, _ = workflow.fixture(o, source, tmp_path)
    else:
        source, model, _ = workflow.fixture(o, tmp_path)
    weather = tmp_path / "weather.epw"
    shutil.copyfile(
        Path(__file__).parent / "fixtures/USA_FL_Tampa.Intl.AP.722110_TMY3.epw",
        weather,
    )
    if case == "populated":
        assert o.model.WeatherFile.setWeatherFile(
            model, o.EpwFile(str(weather))
        ).is_initialized()
    assert model.save(str(source), True)
    original = source.read_bytes()
    source.with_suffix(".osw").write_text(
        json.dumps(dict(weather_file=str(weather), steps=[]))
    )
    cfg = workflow.config(tmp_path)
    report = workflow.preflight(source, cfg)
    assert report["ready"], report
    assert report == workflow.preflight(source, cfg)
    assert report["plan"]["weather_was_empty"] is (case != "populated")
    assert report["plan"]["companions"]["weather_resource"]

    if case in ("changed_epw", "tampered_flag"):
        if case == "changed_epw":
            weather.write_bytes(weather.read_bytes().replace(b"Tampa", b"Other", 1))
        else:
            report["plan"]["weather_was_empty"] = False
        with pytest.raises(ValueError):
            workflow.apply(report, tmp_path)
        assert not Path(cfg["output_model_path"]).exists()
        assert not Path(cfg["output_model_path"]).with_suffix("").exists()
    else:
        result = workflow.apply(report, tmp_path)
        assert result["validation"]["ok"] and result["translation"]["ok"], result
        saved = (
            o.osversion.VersionTranslator().loadModel(result["output_model_path"]).get()
        )
        reference = o.model.Model()
        expected = o.model.WeatherFile.setWeatherFile(
            reference, o.EpwFile(str(weather))
        ).get()
        assert saved.getWeatherFile().city() == expected.city()
        editor = {
            boiler: boiler.boilers,
            district: district.district,
            terminal: terminal.terminals,
            replacement: replacement.terminals,
            tower: tower.towers,
        }[workflow]
        validator = editor.validate_model
        assert validator(saved, o, report["plan"], result["changes"])["ok"]
        # Hydration permits only metadata from the reviewed EPW, not arbitrary edits.
        saved.getWeatherFile().setCity("Unapproved weather metadata")
        assert not validator(saved, o, report["plan"], result["changes"])["ok"]
    assert source.read_bytes() == original
