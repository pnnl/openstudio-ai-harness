import sys, json
import pytest
from test_vav_preflight import sdk, model_file, SCRIPTS
from test_ventilation import fixture

sys.path.insert(0, str(SCRIPTS))
from common import outdoor_air_attach as oa, model_transaction as tx


def config(tmp_path, model):
    return dict(
        output_model_path=str(tmp_path / "intake.osm"),
        air_loop={"name": "Existing Air Loop"},
        name="New Intake",
        ventilation_method="ZoneSum",
        mechanical_availability_schedule={
            "handle": str(model.alwaysOnDiscreteSchedule().handle())
        },
        economizer_control="NoEconomizer",
        bypass_control="BypassWhenWithinEconomizerLimits",
        ventilation=dict(
            minimum_flow_m3_s="Autosize",
            maximum_flow_m3_s="Autosize",
            minimum_limit_type="FixedMinimum",
            minimum_flow_schedule=None,
            minimum_fraction_schedule=None,
            maximum_fraction_schedule=None,
            dcv=False,
        ),
    )


def preflight(source, cfg):
    return tx.preflight(source, cfg, "attach_outdoor_air", oa.plan)


def apply(report, tmp_path, creator=None):
    path = tmp_path / "oa-plan.json"
    path.write_text(json.dumps(report))
    return tx.apply(
        path, "attach_outdoor_air", oa.plan, creator or oa.execute, oa.validate_model
    )


@pytest.mark.parametrize("kind", ["VariableVolume", "ConstantVolume"])
def test_attach_preserves_served_system_and_sizes(sdk, model_file, tmp_path, kind):
    o = sdk[0]
    m, c = fixture(o, model_file, tmp_path, kind)
    m.getAirLoopHVACs()[0].airLoopHVACOutdoorAirSystem().get().remove()
    m.save(str(model_file), True)
    before = model_file.read_bytes()
    cfg = config(tmp_path, m)
    r = preflight(model_file, cfg)
    assert r["ready"], r
    assert r == preflight(model_file, cfg)
    result = apply(r, tmp_path)
    assert result["validation"]["ok"] and result["translation"]["ok"]
    assert model_file.read_bytes() == before
    saved = o.model.Model.load(result["output_model_path"]).get()
    assert len(saved.getAirLoopHVACOutdoorAirSystems()) == 1
    assert (
        saved.getControllerOutdoorAirs()[0].minimumOutdoorAirFlowRate().is_initialized()
        is False
    )


@pytest.mark.parametrize(
    "fault",
    ["existing", "missing_flow", "contradictory_flow", "unserved", "bad_schedule"],
)
def test_connector_rejects_unsupported_or_incomplete_inputs(
    sdk, model_file, tmp_path, fault
):
    o = sdk[0]
    m, c = fixture(o, model_file, tmp_path)
    cfg = config(tmp_path, m)
    if fault != "existing":
        m.getAirLoopHVACs()[0].airLoopHVACOutdoorAirSystem().get().remove()
    if fault == "missing_flow":
        del cfg["ventilation"]["minimum_flow_m3_s"]
    elif fault == "contradictory_flow":
        cfg["ventilation"].update(minimum_flow_m3_s=2, maximum_flow_m3_s=1)
    elif fault == "unserved":
        for zone in list(m.getThermalZones()):
            m.getAirLoopHVACs()[0].removeBranchForZone(zone)
    elif fault == "bad_schedule":
        cfg["mechanical_availability_schedule"] = {"name": "Missing"}
    m.save(str(model_file), True)
    assert not preflight(model_file, cfg)["ready"]


@pytest.mark.parametrize("fault", ["extra_object", "controller", "sizing", "zone"])
def test_connector_rejects_unrequested_saved_changes(sdk, model_file, tmp_path, fault):
    o = sdk[0]
    m, c = fixture(o, model_file, tmp_path)
    m.getAirLoopHVACs()[0].airLoopHVACOutdoorAirSystem().get().remove()
    m.save(str(model_file), True)
    r = preflight(model_file, config(tmp_path, m))

    def bad(model, native, planned):
        result = oa.execute(model, native, planned)
        if fault == "extra_object":
            native.model.FanConstantVolume(model)
        elif fault == "controller":
            model.getControllerOutdoorAirs()[0].setEconomizerControlType("FixedDryBulb")
        elif fault == "sizing":
            model.getAirLoopHVACs()[0].sizingSystem().setAllOutdoorAirinHeating(True)
        else:
            model.getThermalZones()[0].setMultiplier(2)
        return result

    with pytest.raises(ValueError, match="validation"):
        apply(r, tmp_path, bad)
    assert not (tmp_path / "intake.osm").exists()
