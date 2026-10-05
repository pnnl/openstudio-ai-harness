"""Disposable five-zone VAV sizing inputs for native tests and local evaluation."""

from pathlib import Path


def prepare_vav_fixture(o, tmp_path, hydronic):
    fixture = Path(__file__).resolve().parent / "fixtures/sample.osm"
    original = fixture.read_bytes()
    model = o.osversion.VersionTranslator().loadModel(str(fixture)).get()
    # Remove HVAC only from the disposable copy to make explicit unserved targets.
    for loop in list(model.getAirLoopHVACs()):
        loop.remove()
    # Exclude the seed's unrelated service-water warnings from VAV evidence.
    for plant in list(model.getPlantLoops()):
        plant.remove()
    for equipment in list(model.getWaterUseEquipments()):
        equipment.remove()
    targets = ["Core_ZN ZN"] + [f"Perimeter_ZN_{i} ZN" for i in range(1, 5)]
    for name in targets:
        zone = model.getThermalZoneByName(name).get()
        assert not zone.airLoopHVACs() and not zone.equipment()
    config = {
        "system_name": "Sizing VAV",
        "output_model_path": str(tmp_path / "vav.osm"),
        "target_zones": [{"name": x} for x in targets],
        "defaults_profile": "prototype_vav_v1",
        "central_heating": {"type": "Electricity"},
        "central_cooling": {"type": "DXTwoSpeed", "dx_approved": True},
        "reheat": {"type": "Electricity"},
    }
    if hydronic:
        for name, loop_type, supply, delta in (
            ("Fixture HW", "Heating", 82.222222, 11.111111),
            ("Fixture CHW", "Cooling", 6.666667, 5.611111),
        ):
            plant = o.model.PlantLoop(model)
            plant.setName(name)
            plant.sizingPlant().setLoopType(loop_type)
            plant.sizingPlant().setDesignLoopExitTemperature(supply)
            plant.sizingPlant().setLoopDesignTemperatureDifference(delta)
            pump = o.model.PumpVariableSpeed(model)
            assert pump.addToNode(plant.supplyInletNode())
            source = (
                o.model.DistrictHeatingWater(model)
                if loop_type == "Heating"
                else o.model.DistrictCooling(model)
            )
            assert plant.addSupplyBranchForComponent(source)
            for side in ("Supply", "Demand"):
                assert getattr(plant, f"add{side}BranchForComponent")(
                    o.model.PipeAdiabatic(model)
                )
            schedule = o.model.ScheduleConstant(model)
            schedule.setValue(supply)
            manager = o.model.SetpointManagerScheduled(model, schedule)
            assert manager.addToNode(plant.supplyOutletNode())
        config.update(
            central_heating={"type": "Water", "plant_loop": {"name": "Fixture HW"}},
            central_cooling={"type": "Water", "plant_loop": {"name": "Fixture CHW"}},
            reheat={"type": "Water", "plant_loop": {"name": "Fixture HW"}},
        )
    control = model.getSimulationControl()
    control.setDoZoneSizingCalculation(True)
    control.setDoSystemSizingCalculation(True)
    control.setDoPlantSizingCalculation(hydronic)
    control.setRunSimulationforSizingPeriods(True)
    control.setRunSimulationforWeatherFileRunPeriods(False)
    source_path = tmp_path / "unserved.osm"
    assert model.save(str(source_path), True)
    return source_path, config, fixture, original
