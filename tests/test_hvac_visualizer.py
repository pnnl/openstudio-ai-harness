"""Native graph provenance, independent circuits and portable read-only exports."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest
from test_vav_preflight import sdk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/sdk_scripts"))
from common.hvac_graph import extract, handle, raw, state
from common.hvac_diagram import (
    artifacts,
    channel,
    diagram,
    equipment_topology,
    equipment_name,
    fold_contained,
    overview,
    physical,
    vertex,
)
from visualize_hvac import visualize


@pytest.fixture
def topology(sdk, tmp_path):
    native = sdk[0]
    model = native.model.Model()
    air = native.model.AirLoopHVAC(model)
    air.setName('Office "AHU" <script> %% end [A] | B')
    oa = native.model.AirLoopHVACOutdoorAirSystem(
        model, native.model.ControllerOutdoorAir(model)
    )
    assert oa.addToNode(air.supplyInletNode())
    hx = native.model.HeatExchangerAirToAirSensibleAndLatent(model)
    assert hx.addToNode(oa.outboardOANode().get())
    fan = native.model.FanVariableVolume(model)
    fan.setName("Z first fan")
    assert fan.addToNode(air.supplyOutletNode())
    cold = native.model.CoilCoolingWater(model)
    cold.setName("A second cooling coil")
    assert cold.addToNode(air.supplyOutletNode())
    hot = native.model.CoilHeatingWater(model)
    assert hot.addToNode(air.supplyOutletNode())
    hw, chw = native.model.PlantLoop(model), native.model.PlantLoop(model)
    assert hw.addDemandBranchForComponent(hot)
    assert chw.addDemandBranchForComponent(cold)
    zones, terminals = [], []
    for index in range(2):
        zone = native.model.ThermalZone(model)
        zone.setName("Duplicate zone")  # Explicitly force duplicate stored names below.
        reheat = native.model.CoilHeatingWater(model)
        assert hw.addDemandBranchForComponent(reheat)
        terminal = native.model.AirTerminalSingleDuctVAVReheat(
            model, model.alwaysOnDiscreteSchedule(), reheat
        )
        assert air.addBranchForZone(zone, terminal)
        zones.append(zone)
        terminals.append(terminal)
    plenum = native.model.ThermalZone(model)
    plenum.setName("Return plenum zone")
    assert zones[0].setReturnPlenum(plenum)
    vrf = native.model.AirConditionerVariableRefrigerantFlow(model)
    indoor = native.model.ZoneHVACTerminalUnitVariableRefrigerantFlow(model)
    assert indoor.addToThermalZone(zones[0])
    assert vrf.addTerminal(indoor)
    zone_only = native.model.ThermalZone(model)
    baseboard = native.model.ZoneHVACBaseboardConvectiveElectric(model)
    assert baseboard.addToThermalZone(zone_only)
    unserved = native.model.ThermalZone(model)
    unitary = native.model.AirLoopHVACUnitarySystem(model)
    unitary.setSupplyFan(native.model.FanConstantVolume(model))
    manager = native.model.SetpointManagerScheduled(
        model, native.model.ScheduleConstant(model)
    )
    assert manager.addToNode(air.supplyOutletNode())
    source = tmp_path / "topology.osm"
    assert model.save(str(source), True)
    return dict(
        native=native,
        model=model,
        source=source,
        air=air,
        oa=oa,
        hx=hx,
        fan=fan,
        hot=hot,
        cold=cold,
        hw=hw,
        chw=chw,
        zones=zones,
        terminals=terminals,
        plenum=plenum,
        vrf=vrf,
        indoor=indoor,
        zone_only=zone_only,
        baseboard=baseboard,
        unserved=unserved,
        unitary=unitary,
        manager=manager,
    )


def test_graph_records_every_native_connection_with_exact_ports(topology):
    graph = extract(topology["model"], topology["native"])
    connections = {
        handle(obj): raw(obj)
        for obj in topology["model"].modelObjects()
        if obj.iddObjectType().valueName() == "OS_Connection"
    }
    flows = [e for e in graph["edges"] if e["kind"] == "flow"]
    assert len(flows) == len(connections) > 30
    objects = {handle(obj): obj for obj in topology["model"].modelObjects()}
    for edge in flows:
        original = connections[edge["id"]]
        assert (
            edge["source"],
            edge["source_port"],
            edge["target"],
            edge["target_port"],
        ) == (
            original["Source Object"],
            int(original["Outlet Port"]),
            original["Target Object"],
            int(original["Inlet Port"]),
        )
        assert edge["provenance"] == "OS_Connection"
        for side in ("source", "target"):
            obj = objects[edge[side]]
            assert (
                handle(obj.getTarget(edge[side + "_field_index"]).get()) == edge["id"]
            )
    assert not any(
        w["code"].startswith("invalid_connection") for w in graph["warnings"]
    )


def test_graph_keeps_same_water_coil_identity_in_both_circuits(topology):
    graph = extract(topology["model"], topology["native"])
    for coil in (topology["hot"], topology["cold"]):
        key = handle(coil)
        assert len([n for n in graph["nodes"] if n["handle"] == key]) == 1
        connected = [
            e
            for e in graph["edges"]
            if e["kind"] == "flow" and key in (e["source"], e["target"])
        ]
        assert len(connected) == 4
        assert {e["medium"] for e in connected} == {"air", "water"}
        for edge in connected:
            kind = "air_loop" if edge["medium"] == "air" else "plant_loop"
            assert all(
                next(g for g in graph["groups"] if g["id"] == i)["kind"] == kind
                for i in edge["groups"]
            )


def test_stale_numeric_ports_retain_evidence_and_use_explicit_fields(topology):
    model, native = topology["model"], topology["native"]
    hx = topology["hx"]
    index = hx.primaryAirInletPort()
    connection = model.getModelObject(hx.getTarget(index).get().handle()).get()
    values = raw(connection)
    field = "Inlet Port" if values["Target Object"] == handle(hx) else "Outlet Port"
    field_index = next(
        i
        for i in range(connection.numFields())
        if connection.iddObject().getField(i).get().name() == field
    )
    assert connection.setInt(field_index, index + 4)
    before = state(model)
    graph = extract(model, native)
    edge = next(e for e in graph["edges"] if e["id"] == handle(connection))
    side = "target" if field == "Inlet Port" else "source"
    assert edge[side + "_port"] == index + 4
    assert edge[side + "_field_index"] == index
    assert edge[side + "_field"] == "Supply Air Inlet Node"
    assert (
        channel(
            next(n for n in graph["nodes"] if n["handle"] == handle(hx)),
            edge[side + "_field"],
            index,
            "air",
        )
        == "supply air"
    )
    assert any(
        w["code"] == "connection_port_discrepancy" and w["handle"] == edge["id"]
        for w in graph["warnings"]
    )
    assert state(model) == before


def test_branches_recovery_and_plenum_connections_remain_explicit(topology):
    graph = extract(topology["model"], topology["native"])
    for obj, count in ((topology["hx"], 4), (topology["oa"], 4)):
        connected = [
            e
            for e in graph["edges"]
            if e["kind"] == "flow" and handle(obj) in (e["source"], e["target"])
        ]
        assert len(connected) == count
    assert len([n for n in graph["nodes"] if "Splitter" in n["type"]]) >= 3
    assert any(
        e["kind"] == "plenum_zone" and e["target"] == handle(topology["plenum"])
        for e in graph["edges"]
    )
    assert not any(
        e["kind"] == "flow"
        and e["source"] == handle(topology["terminals"][0])
        and e["target"] == handle(topology["terminals"][1])
        for e in graph["edges"]
    )


def test_vrf_oa_zone_equipment_and_unserved_membership_are_separate(topology):
    graph = extract(topology["model"], topology["native"])
    zones = {z["handle"]: z for z in graph["zones"]}
    mixed = zones[handle(topology["zones"][0])]
    assert mixed["air_loops"] == [handle(topology["air"])]
    assert mixed["vrf_systems"] == [handle(topology["vrf"])]
    assert handle(topology["indoor"]) in mixed["equipment"]
    assert zones[handle(topology["zone_only"])]["equipment"] == [
        handle(topology["baseboard"])
    ]
    assert zones[handle(topology["unserved"])]["unserved"]
    assert not zones[handle(topology["plenum"])]["unserved"]
    vrf_edges = [e for e in graph["edges"] if e["source"] == handle(topology["vrf"])]
    assert any(e["kind"] == "vrf_membership" for e in vrf_edges)
    assert not any(e["kind"] == "flow" and e.get("medium") == "air" for e in vrf_edges)


def test_embedded_equipment_is_visible_without_invented_internal_flow(topology):
    graph = extract(topology["model"], topology["native"])
    for parent in (topology["unitary"], topology["indoor"], topology["terminals"][0]):
        assert any(
            e["kind"] == "contains" and e["source"] == handle(parent)
            for e in graph["edges"]
        )
        assert any(
            w["code"] == "embedded_air_path_unexpanded"
            and w["handle"] == handle(parent)
            for w in graph["warnings"]
        )
    controls = [e for e in graph["edges"] if e["kind"] == "control"]
    assert any(e["source"] == handle(topology["manager"]) for e in controls)
    assert graph["coverage"]["sizing_or_operation_validated"] is False


def test_extraction_is_stable_and_does_not_mutate_model(topology):
    before = state(topology["model"])
    original = topology["source"].read_bytes()
    first = extract(topology["model"], topology["native"])
    assert first == extract(topology["model"], topology["native"])
    assert before == state(topology["model"])
    loaded = (
        topology["native"]
        .osversion.VersionTranslator()
        .loadModel(str(topology["source"]))
        .get()
    )
    assert first == extract(loaded, topology["native"])
    assert topology["source"].read_bytes() == original


def test_oa_and_ventilation_controllers_belong_to_air_loop(topology):
    graph = extract(topology["model"], topology["native"])
    group = next(g for g in graph["groups"] if g["root"] == handle(topology["air"]))
    controllers = [
        n
        for n in graph["nodes"]
        if n["type"]
        in {"OS_Controller_OutdoorAir", "OS_Controller_MechanicalVentilation"}
    ]
    assert len(controllers) == 2
    for controller in controllers:
        assert controller["handle"] in group["members"]
        assert group["id"] in controller["groups"]
        assert "unassigned" not in controller["groups"]


def test_hidden_only_group_retained_in_json_but_not_published(sdk):
    native = sdk[0]
    model = native.model.Model()
    native.model.ControllerMechanicalVentilation(model)
    before = state(model)
    graph = extract(model, native)
    assert any(g["id"] == "unassigned" for g in graph["groups"])
    output, _ = artifacts(graph)
    assert "unassigned.mmd" not in output
    assert "unassigned.md" not in output
    assert "Unassigned connected" not in output["index.md"]
    assert state(model) == before


def test_prepared_legacy_multiloop_has_no_orphan_controllers(sdk, tmp_path):
    from common.model_preparation import prepare

    source = ROOT / "tests/fixtures/openstudio-legacy-multiloop.osm"
    prepared = tmp_path / "prepared.osm"
    assert prepare(source, prepared)["ok"]
    report = visualize(prepared, tmp_path / "diagrams")
    graph = json.loads(Path(report["graph_path"]).read_text())
    air_groups = [g for g in graph["groups"] if g["kind"] == "air_loop"]
    controllers = [n for n in graph["nodes"] if n["type"].startswith("OS_Controller_")]
    assert len(air_groups) == 10 and len(controllers) == 20
    assert all(
        any(n["handle"] in g["members"] for g in air_groups) for n in controllers
    )
    assert not any(g["kind"] == "unassigned" for g in graph["groups"])
    assert len(report["diagram_paths"]) == 20
    assert not (tmp_path / "diagrams/unassigned.mmd").exists()


def test_mermaid_separates_coil_circuits_and_heat_recovery_streams(topology):
    graph = extract(topology["model"], topology["native"])
    air = next(g for g in graph["groups"] if g["root"] == handle(topology["air"]))
    plant = next(g for g in graph["groups"] if g["root"] == handle(topology["hw"]))
    air_text, _ = diagram(graph, air)
    water_text, _ = diagram(graph, plant)
    coil, hx = handle(topology["hot"]), handle(topology["hx"])
    assert vertex(coil, "air") in air_text
    assert vertex(coil, "water") not in air_text
    assert vertex(coil, "water") in water_text
    assert vertex(coil, "air") not in water_text
    supply, exhaust = vertex(hx, "supply air"), vertex(hx, "exhaust air")
    assert supply in air_text and exhaust in air_text
    assert not any(
        supply in line and exhaust in line
        for line in air_text.splitlines()
        if "-->" in line
    )
    # A fan's downstream connection really reaches the cooling coil, regardless
    # of their intentionally reversed alphabetical names.
    outgoing = {}
    for edge in graph["edges"]:
        if edge["kind"] == "flow":
            outgoing.setdefault(edge["source"], set()).add(edge["target"])
    next_node = outgoing[handle(topology["fan"])].pop()
    assert outgoing[next_node] == {handle(topology["cold"])}
    assert ' -->|"air"' in air_text
    assert vertex(handle(topology["manager"]), "object") not in air_text
    assert "stored control reference" not in air_text


def test_equipment_views_hide_sdk_objects_and_color_three_categories(topology):
    graph = extract(topology["model"], topology["native"])
    before = json.dumps(graph, sort_keys=True)
    projected, _ = equipment_topology(graph)
    raw_nodes = {n["handle"]: n for n in graph["nodes"]}
    assert {n["category"] for n in projected["nodes"]} == {"zone", "air", "water"}
    assert all(physical(raw_nodes[n["handle"]]) for n in projected["nodes"])
    kept = {n["handle"] for n in projected["nodes"]}
    for name in ("oa", "fan", "cold", "hot", "hx", "indoor", "vrf", "baseboard"):
        assert handle(topology[name]) in kept
    for name in ("air", "hw", "chw", "manager"):
        assert handle(topology[name]) not in kept
    assert {handle(t) for t in topology["terminals"]} <= kept
    output, _ = artifacts(graph)
    for name, text in output.items():
        if not name.endswith(".mmd"):
            continue
        assert "OS_Node" not in text and "OS_PortList" not in text
        assert "SetpointManager" not in text and "Controller_" not in text
        assert "p16 to" not in text and "current fields" not in text
        assert "classDef zone fill:#dcfce7" in text
        assert "classDef air fill:#dbeafe" in text
        assert "classDef water fill:#ffedd5" in text
    assert json.loads(output["equipment_graph.json"])["nodes"] == projected["nodes"]
    assert json.dumps(graph, sort_keys=True) == before


def test_each_condensed_flow_has_a_contiguous_verified_path(topology):
    graph = extract(topology["model"], topology["native"])
    raw_nodes = {n["handle"]: n for n in graph["nodes"]}
    originals = {e["id"]: e for e in graph["edges"]}
    for group in [None, *graph["groups"]]:
        projected, _ = equipment_topology(graph, group)
        nodes = {n["id"]: n for n in projected["nodes"]}
        for edge in projected["edges"]:
            if edge["kind"] != "flow":
                assert all(originals[k]["kind"] != "control" for k in edge["evidence"])
                continue
            path = [originals[k] for k in edge["evidence"]]
            assert path[0]["source"] == nodes[edge["source"]]["handle"]
            assert path[-1]["target"] == nodes[edge["target"]]["handle"]
            assert all(p["kind"] in {"flow", "zone_boundary"} for p in path)
            assert all(p.get("medium", "air") == edge["medium"] for p in path)
            if group:
                assert all(group["id"] in p["groups"] for p in path)
            for left, right in zip(path, path[1:]):
                assert left["target"] == right["source"]
                assert not physical(raw_nodes[left["target"]])


def test_condensing_nodes_preserves_serial_order_and_parallel_zone_branches(topology):
    graph = extract(topology["model"], topology["native"])
    air = next(g for g in graph["groups"] if g["root"] == handle(topology["air"]))
    projected, _ = equipment_topology(graph, air)
    nodes = {n["id"]: n for n in projected["nodes"]}
    pairs = {
        (nodes[e["source"]]["handle"], nodes[e["target"]]["handle"])
        for e in projected["edges"]
        if e["kind"] == "flow"
    }
    assert (handle(topology["fan"]), handle(topology["cold"])) in pairs
    assert (handle(topology["cold"]), handle(topology["hot"])) in pairs
    for terminal, zone in zip(topology["terminals"], topology["zones"]):
        assert (handle(topology["hot"]), handle(terminal)) in pairs
        assert (handle(terminal), handle(zone)) in pairs
    assert not any(
        (handle(a), handle(b)) in pairs
        for a in topology["terminals"]
        for b in topology["terminals"]
    )


def diagram_connections(text):
    """A single connected drawing uses one zone box and two OA port views."""
    assert text.startswith("flowchart LR\n")
    assert "subgraph" not in text
    nodes, edges = set(), []
    for line in text.splitlines():
        if "-->" in line or "-.->" in line or "<--" in line:
            a, b = line.split()[0], line.split()[-1]
            assert a in nodes and b in nodes
            if "<--" in line:
                a, b = b, a
            edges.append((a, b))
        elif '["' in line:
            nodes.add(line.strip().split("[")[0])
    return nodes, edges


def test_supply_return_and_relief_paths_match_native_roles(topology):
    native, air, oa = topology["native"], topology["air"], topology["oa"]
    return_fan = native.model.FanConstantVolume(topology["model"])
    assert return_fan.addToNode(air.supplyInletNode())
    relief_fan = native.model.FanConstantVolume(topology["model"])
    assert relief_fan.addToNode(oa.outboardReliefNode().get())
    assert handle(air.supplyFan().get()) == handle(topology["fan"])
    assert handle(air.returnFan().get()) == handle(return_fan)
    assert handle(air.reliefFan().get()) == handle(relief_fan)
    graph = extract(topology["model"], native)
    before = json.dumps(graph, sort_keys=True)
    group = next(g for g in graph["groups"] if g["root"] == handle(air))
    projected, _ = equipment_topology(graph, group)
    nodes = {n["handle"]: n for n in projected["nodes"] if "fan_roles" in n}
    for fan, role, title in (
        (topology["fan"], "supply", "Supply fan"),
        (return_fan, "return", "Return fan"),
        (relief_fan, "exhaust", "Relief/exhaust fan"),
    ):
        assert nodes[handle(fan)]["fan_roles"] == [role]
        assert nodes[handle(fan)]["label"].startswith(title)
    text, _ = diagram(graph, group)
    displayed, links = diagram_connections(text)
    assert (
        vertex(handle(topology["fan"]), "air"),
        vertex(handle(topology["cold"]), "air"),
    ) in links  # Preserve the real blow-through order.
    for terminal, zone in zip(topology["terminals"], topology["zones"]):
        assert (
            vertex(handle(terminal), "air"),
            vertex(handle(zone), "zone"),
        ) in links
        assert text.count(vertex(handle(zone), "zone") + '["') == 1
    by_id = {n["id"]: n for n in projected["nodes"]}
    returns = [
        e
        for e in projected["edges"]
        if e["kind"] == "flow" and e["air_paths"] == ["return"]
    ]
    assert any(by_id[e["target"]]["handle"] == handle(return_fan) for e in returns)
    assert any(by_id[e["source"]]["handle"] == handle(return_fan) for e in returns)
    oa_key = vertex(handle(oa), "OA mixing and relief")
    assert oa_key + "_supply" in displayed and oa_key + "_return" in displayed
    assert (vertex(handle(return_fan), "air"), oa_key + "_return") in links
    assert "Exhaust to outdoors" in text
    assert json.dumps(graph, sort_keys=True) == before


def test_loop_without_oa_keeps_supply_and_return_distinct(sdk):
    native = sdk[0]
    model = native.model.Model()
    air = native.model.AirLoopHVAC(model)
    fan = native.model.FanConstantVolume(model)
    coil = native.model.CoilHeatingElectric(model)
    assert fan.addToNode(air.supplyOutletNode())
    assert coil.addToNode(air.supplyOutletNode())
    zone = native.model.ThermalZone(model)
    terminal = native.model.AirTerminalSingleDuctUncontrolled(
        model, model.alwaysOnDiscreteSchedule()
    )
    assert air.addBranchForZone(zone, terminal)
    graph = extract(model, native)
    group = next(g for g in graph["groups"] if g["root"] == handle(air))
    projected, _ = equipment_topology(graph, group)
    fan_node = next(n for n in projected["nodes"] if n["handle"] == handle(fan))
    assert fan_node["fan_roles"] == ["supply"]
    _, links = diagram_connections(diagram(graph, group)[0])
    assert (
        vertex(handle(fan), "air"),
        vertex(handle(coil), "air"),
    ) in links
    assert (
        vertex(handle(zone), "zone"),
        vertex(handle(fan), "air"),
    ) in links


def test_zone_exhaust_fan_is_not_a_supply_fan(topology):
    fan = topology["native"].model.FanZoneExhaust(topology["model"])
    assert fan.addToThermalZone(topology["zone_only"])
    graph = extract(topology["model"], topology["native"])
    projected, _ = equipment_topology(graph)
    views = [n for n in projected["nodes"] if n["handle"] == handle(fan)]
    assert views and all(n["fan_roles"] == ["exhaust"] for n in views)
    by_id = {n["id"]: n for n in projected["nodes"]}
    assert all(
        by_id[b["anchor"]]["type"] != "OS_ThermalZone" for b in projected["boundaries"]
    )
    shown, _ = diagram_connections(overview(graph))
    assert vertex(handle(topology["zone_only"]), "zone") in shown
    assert "Exhaust to outdoors" in overview(graph)


def test_outdoor_boundaries_keep_contiguous_native_evidence(topology):
    graph = extract(topology["model"], topology["native"])
    projected, _ = equipment_topology(graph)
    originals = {e["id"]: e for e in graph["edges"]}
    views = {n["id"]: n for n in projected["nodes"]}
    raw_nodes = {n["handle"]: n for n in graph["nodes"]}
    boundaries = projected["boundaries"]
    assert (
        len(boundaries) == 2
    )  # VRF recirculation and zone air nodes are not outdoor outlets.
    assert {b["role"] for b in boundaries} == {"outdoor", "exhaust"}
    for boundary in boundaries:
        path = [originals[key] for key in boundary["evidence"]]
        anchor = views[boundary["anchor"]]
        if boundary["direction"] == "in":
            assert path[0]["source"] == boundary["handle"]
            assert path[-1]["target"] == anchor["handle"]
        else:
            assert path[0]["source"] == anchor["handle"]
            assert path[-1]["target"] == boundary["handle"]
        assert raw_nodes[boundary["handle"]]["type"] == "OS_Node"
        assert len(raw_nodes[boundary["handle"]]["ports"]) == 1
        for left, right in zip(path, path[1:]):
            assert left["target"] == right["source"]
            assert not physical(raw_nodes[left["target"]])
    hx = handle(topology["hx"])
    assert {
        views[b["anchor"]]["channel"]
        for b in boundaries
        if views[b["anchor"]]["handle"] == hx
    } == {"supply air", "exhaust air"}


def test_oa_without_recovery_still_has_outdoor_and_exhaust_markers(sdk):
    native = sdk[0]
    model = native.model.Model()
    air = native.model.AirLoopHVAC(model)
    oa = native.model.AirLoopHVACOutdoorAirSystem(
        model, native.model.ControllerOutdoorAir(model)
    )
    assert oa.addToNode(air.supplyInletNode())
    fan = native.model.FanConstantVolume(model)
    assert fan.addToNode(air.supplyOutletNode())
    zone = native.model.ThermalZone(model)
    terminal = native.model.AirTerminalSingleDuctUncontrolled(
        model, model.alwaysOnDiscreteSchedule()
    )
    assert air.addBranchForZone(zone, terminal)
    graph = extract(model, native)
    group = next(g for g in graph["groups"] if g["root"] == handle(air))
    projected, _ = equipment_topology(graph, group)
    assert {b["role"] for b in projected["boundaries"]} == {"outdoor", "exhaust"}
    text = diagram(graph, group)[0]
    assert "Outdoor air" in text and "Exhaust to outdoors" in text
    assert "Heat recovery" not in text  # Never fabricate a recovery or bypass branch.
    diagram_connections(text)


def test_water_bypasses_remain_in_evidence_without_floating_loops(sdk):
    from common.hvac_diagram import presentation_notes

    native = sdk[0]
    model = native.model.Model()
    plant = native.model.PlantLoop(model)
    pump = native.model.PumpVariableSpeed(model)
    assert pump.addToNode(plant.supplyInletNode())
    heater = native.model.WaterHeaterMixed(model)
    use = native.model.WaterUseConnections(model)
    assert plant.addSupplyBranchForComponent(heater)
    assert plant.addDemandBranchForComponent(use)
    assert plant.addSupplyBranchForComponent(native.model.PipeAdiabatic(model))
    assert plant.addDemandBranchForComponent(native.model.PipeAdiabatic(model))
    graph = extract(model, native)
    before = state(model)
    group = next(g for g in graph["groups"] if g["root"] == handle(plant))
    projected, _ = equipment_topology(graph, group)
    views = {n["id"]: n for n in projected["nodes"]}
    uses = [n for n in projected["nodes"] if n["handle"] == handle(use)]
    assert len(uses) == 1 and uses[0]["channel"] == "water"
    bypasses = [e for e in projected["edges"] if e.get("routing_bypass")]
    assert len(bypasses) >= 3
    assert all(e["evidence"] for e in bypasses)
    assert any(e["source"] == e["target"] for e in bypasses)
    text = diagram(graph, group)[0]
    _, links = diagram_connections(text)
    assert len(links) == 3
    assert not any(a == b for a, b in links)
    assert {(views[a]["handle"], views[b]["handle"]) for a, b in links} == {
        (handle(pump), handle(heater)),
        (handle(heater), handle(use)),
        (handle(use), handle(pump)),
    }
    assert (
        " <---|Water return| " in text
    )  # Mermaid needs three dashes for a start arrow.
    assert "not mains or district-water inlets" in presentation_notes(projected)
    assert "District" not in text
    assert state(model) == before


def test_condensed_flow_cannot_join_separate_coil_or_recovery_circuits(topology):
    graph = extract(topology["model"], topology["native"])
    projected, _ = equipment_topology(graph)
    nodes = {n["id"]: n for n in projected["nodes"]}
    for coil in (topology["hot"], topology["cold"]):
        assert nodes[vertex(handle(coil), "air")]["category"] == "air"
        assert nodes[vertex(handle(coil), "water")]["category"] == "water"
    for edge in projected["edges"]:
        if edge["kind"] != "flow":
            continue
        a, b = nodes[edge["source"]], nodes[edge["target"]]
        assert not (a["handle"] == b["handle"] and a["channel"] != b["channel"])
        assert {a["category"], b["category"]} != {"air", "water"}


def test_primary_loop_keeps_chiller_boiler_and_pumps_orange(topology):
    native, model = topology["native"], topology["model"]
    boiler = native.model.BoilerHotWater(model)
    chiller = native.model.ChillerElectricEIR(model)
    assert topology["hw"].addSupplyBranchForComponent(boiler)
    assert topology["chw"].addSupplyBranchForComponent(chiller)
    pumps = []
    for loop in (topology["hw"], topology["chw"]):
        pump = native.model.PumpVariableSpeed(model)
        assert pump.addToNode(loop.supplyInletNode())
        pumps.append(pump)
    graph = extract(model, native)
    projected, _ = equipment_topology(graph)
    for equipment in (boiler, chiller, *pumps):
        views = [n for n in projected["nodes"] if n["handle"] == handle(equipment)]
        assert views and all(n["category"] == "water" for n in views)


def test_overview_folds_embedded_components_but_detail_retains_them(topology):
    graph = extract(topology["model"], topology["native"])
    child = next(
        e["target"]
        for e in graph["edges"]
        if e["kind"] == "contains" and e["source"] == handle(topology["unitary"])
    )
    assert vertex(child) not in overview(graph)
    group = next(
        g for g in graph["groups"] if handle(topology["unitary"]) in g["members"]
    )
    detailed, _ = diagram(graph, group)
    assert vertex(child) in detailed


@pytest.mark.parametrize("terminal_count", [9, 40])
def test_vrf_diagrams_fold_indoor_components_and_keep_full_json(sdk, terminal_count):
    native = sdk[0]
    model = native.model.Model()
    vrf = native.model.AirConditionerVariableRefrigerantFlow(model)
    for _ in range(terminal_count):
        indoor = native.model.ZoneHVACTerminalUnitVariableRefrigerantFlow(model)
        assert indoor.addToThermalZone(native.model.ThermalZone(model))
        assert vrf.addTerminal(indoor)
    graph = extract(model, native)
    group = next(g for g in graph["groups"] if g["root"] == handle(vrf))
    output, _ = artifacts(graph)
    text = output[group["id"] + ".mmd"]
    definitions, links = diagram_connections(text)
    assert len(definitions) == 1 + 2 * terminal_count
    assert text.count("contains: cooling coil, fan, heating coil") == terminal_count
    children = {e["target"] for e in graph["edges"] if e["kind"] == "contains"}
    detailed = json.loads(output["equipment_graph.json"])
    assert children <= {n["handle"] for n in detailed["nodes"]}
    assert all(vertex(child) not in text for child in children)
    assert (
        len([e for e in detailed["edges"] if e["kind"] == "contains"])
        == 3 * terminal_count
    )
    assert len(links) == 2 * terminal_count


def test_folding_keeps_child_with_flow_in_any_circuit_view():
    parent = dict(
        id="p",
        handle="parent",
        type="OS_ZoneHVAC_TerminalUnit_VariableRefrigerantFlow",
        label="Indoor",
    )
    child = dict(id="c", handle="child", type="OS_Coil_Heating_Water", label="Coil")
    water_view = dict(child, id="cw")
    topology = dict(
        nodes=[parent, child, water_view],
        edges=[
            dict(source="p", target="c", kind="contains"),
            dict(source="cw", target="p", kind="flow"),
        ],
    )
    presented, folded = fold_contained(topology, vrf_only=True)
    assert not folded
    assert presented == topology
    assert parent["label"] == "Indoor"


@pytest.mark.parametrize(
    "kind,name,expected",
    [
        (
            "OS_AirTerminal_SingleDuct_VAV_NoReheat",
            "Air Terminal Single Duct VAV No Reheat 25",
            "VAV terminal 25",
        ),
        ("OS_Fan_VariableVolume", "Fan Variable Volume 5", "Fan Variable Volume 5"),
        (
            "OS_Fan_VariableVolume",
            "Fan Variable Volume West AHU",
            "Fan Variable Volume / Fan Variable Volume West AHU",
        ),
        (
            "OS_AirTerminal_SingleDuct_VAV_NoReheat",
            "Office terminal",
            "VAV terminal / Office terminal",
        ),
        (
            "OS_Fan_VariableVolume",
            "<Fan Variable Volume>",
            "Fan Variable Volume / <Fan Variable Volume>",
        ),
    ],
)
def test_default_type_names_are_not_repeated(kind, name, expected):
    assert equipment_name(dict(type=kind, name=name), "object") == expected


def test_shared_zone_names_other_system_in_each_view(topology):
    graph = extract(topology["model"], topology["native"])
    mixed = handle(topology["zones"][0])
    for current, other in (
        (topology["air"], topology["vrf"]),
        (topology["vrf"], topology["air"]),
    ):
        group = next(g for g in graph["groups"] if g["root"] == handle(current))
        projected, _ = equipment_topology(graph, group)
        zone = next(n for n in projected["nodes"] if n["handle"] == mixed)
        assert zone["label"].endswith("also: " + other.nameString())
        text, _ = diagram(graph, group)
        assert "also:" in text and "<script>" not in text
    projected, _ = equipment_topology(graph)
    shared = next(n for n in projected["nodes"] if n["handle"] == mixed)
    assert "served by:" in shared["label"]
    single = next(
        n for n in projected["nodes"] if n["handle"] == handle(topology["zones"][1])
    )
    assert "also:" not in single["label"] and "served by:" not in single["label"]


def test_labels_duplicate_names_and_large_overview_are_safe(topology):
    graph = extract(topology["model"], topology["native"])
    for zone in graph["zones"]:
        zone["name"] = 'Duplicate "zone" ``` <script>\n%% injected --> target'
    output, _ = artifacts(graph)
    for name, text in output.items():
        if name.endswith(".mmd"):
            assert "<script>" not in text and "%% injected" not in text
            assert '"zone"' not in text and "```" not in text
    for zone in graph["zones"]:
        assert (
            vertex(zone["handle"], "zone")
            in output[
                next(
                    g["id"] + ".mmd"
                    for g in graph["groups"]
                    if g["root"] == zone["handle"]
                )
            ]
        )
    text = overview(graph, zone_limit=1)
    assert "additional zones" in text
    for zone in graph["zones"]:
        assert zone["handle"] in output["index.md"]


def test_visualize_publishes_stable_artifacts_and_preserves_source(topology, tmp_path):
    source = topology["source"]
    original = source.read_bytes()
    first = visualize(source, tmp_path / "diagrams-a")
    second = visualize(source, tmp_path / "diagrams-b")
    assert first["ok"] and first["mode"] == "inspect_only" and not first["ready"]
    assert Path(first["equipment_graph_path"]).is_file()
    for name in Path(first["output_directory"]).iterdir():
        assert (
            name.read_bytes()
            == (Path(second["output_directory"]) / name.name).read_bytes()
        )
    assert source.read_bytes() == original
    assert not list(Path(first["output_directory"]).glob("*.osm"))
    with pytest.raises(ValueError, match="new directory"):
        visualize(source, tmp_path / "diagrams-a")
    assert source.read_bytes() == original


def test_selected_diagrams_do_not_discard_full_graph(topology, tmp_path):
    selected = handle(topology["hw"])
    report = visualize(topology["source"], tmp_path / "selected", [selected])
    assert len(report["diagram_paths"]) == 1
    graph = json.loads(Path(report["graph_path"]).read_text())
    assert len(graph["groups"]) > 1 and len(graph["zones"]) == 5
    with pytest.raises(ValueError, match="Unknown system"):
        visualize(topology["source"], tmp_path / "invalid", ["not-an-object"])
    assert not (tmp_path / "invalid").exists()


@pytest.mark.parametrize("version", ["old", "new"])
def test_visualizer_honors_version_gates(sdk, tmp_path, version):
    from common.version_guard import CompatibilityError, PreparationRequired

    if version == "old":
        source = ROOT / "tests/fixtures/openstudio-legacy-multiloop.osm"
        # Use the checked-in genuinely old fixture, never a rewritten header.
        error = PreparationRequired
    else:
        source = tmp_path / "newer.osm"
        source.write_text("OS:Version, {11111111-1111-1111-1111-111111111111}, 9.0.0;")
        error = CompatibilityError
    with pytest.raises(error):
        visualize(source, tmp_path / "not-written")
    assert not (tmp_path / "not-written").exists()


def test_missing_weather_and_csv_do_not_gate_read_only_inspection(
    topology, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)  # ExternalFile copies resources under cwd/files.
    native, model = topology["native"], topology["model"]
    weather = native.model.WeatherFile.setWeatherFile(
        model,
        native.EpwFile(
            str(ROOT / "tests/fixtures/USA_FL_Tampa.Intl.AP.722110_TMY3.epw")
        ),
    ).get()
    url = next(
        i
        for i in range(weather.numFields())
        if weather.iddObject().getField(i).get().name().lower() == "url"
    )
    weather.setString(url, "/missing/weather.epw")
    csv = tmp_path / "values.csv"
    csv.write_text("1\n" * 8760)
    external = native.model.ExternalFile.getExternalFile(model, str(csv)).get()
    schedule = native.model.ScheduleFile(external, 1, 0)
    schedule.setName("Missing schedule resource")
    source = tmp_path / "missing-files.osm"
    model.save(str(source), True)
    csv.unlink()
    result = visualize(source, tmp_path / "inspection")
    assert result["ok"] and Path(result["graph_path"]).is_file()


def test_graph_matches_output_schema(topology, tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    result = visualize(topology["source"], tmp_path / "schema")
    jsonschema.validate(
        json.loads(Path(result["graph_path"]).read_text()),
        json.loads(
            (ROOT / "skills/sdk_scripts/schemas/hvac_graph.schema.json").read_text()
        ),
    )


@pytest.mark.parametrize("loop_kind", ["AirLoopHVAC", "PlantLoop"])
def test_missing_assignment_list_is_bounded_before_extraction(sdk, tmp_path, loop_kind):
    from common.diagnostics import failure_report

    model = sdk[0].model.Model()
    getattr(sdk[0].model, loop_kind)(model)
    source = tmp_path / "missing-list.osm"
    model.save(str(source), True)
    text, count = re.subn(
        r"(?ms)^OS:AvailabilityManagerAssignmentList\s*,.*?;", "", source.read_text()
    )
    assert count == 1
    source.write_text(text)
    with pytest.raises(ValueError) as error:
        visualize(source, tmp_path / "not-published")
    report = failure_report(error.value)
    assert report["status"] == "invalid_model"
    assert report["invalid_references"][0]["type"] == "OS_" + loop_kind
    assert len(json.dumps(report)) < 1200
    assert not (tmp_path / "not-published").exists()


def test_source_change_during_extraction_rejects_publication(
    topology, tmp_path, monkeypatch
):
    import visualize_hvac

    original = visualize_hvac.extract

    def changed(*args):
        graph = original(*args)
        with topology["source"].open("a") as stream:
            stream.write("\n! concurrent edit\n")
        return graph

    monkeypatch.setattr(visualize_hvac, "extract", changed)
    with pytest.raises(ValueError, match="Input changed"):
        visualize(topology["source"], tmp_path / "not-published")
    assert not (tmp_path / "not-published").exists()


def test_extraction_rejects_in_memory_mutation(topology, monkeypatch):
    import common.hvac_graph as graph_module

    original = graph_module.state
    calls = []

    def changed(model):
        calls.append(True)
        if len(calls) == 2:
            topology["native"].model.ThermalZone(model)
        return original(model)

    monkeypatch.setattr(graph_module, "state", changed)
    with pytest.raises(RuntimeError, match="changed in-memory"):
        extract(topology["model"], topology["native"])


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_relocated_public_native_visualizer(topology, tmp_path, host):
    cli = Path(
        os.environ.get(
            "OPENSTUDIO_SKILL_TEST_EXE",
            "/Applications/OpenStudio-3.11.0/bin/openstudio",
        )
    )
    if not cli.is_file():
        pytest.skip("Native 3.11.0 CLI unavailable")
    from adapters.claude_code_adapter import ClaudeCodeAdapter
    from adapters.codex_adapter import CodexAdapter
    from adapters.contracts import HostAdapterConfig

    adapter = (ClaudeCodeAdapter if host == "claude" else CodexAdapter)(
        HostAdapterConfig(
            host_name=host, workspace_root=ROOT, runtime_mode="marketplace"
        )
    )
    export = tmp_path / "original export"
    plugin = adapter.export_plugin(export, dry_run=False).plugin_dir
    moved = tmp_path / "relocated plugin"
    shutil.move(str(plugin), moved)
    shutil.rmtree(export)
    script = moved / "skills/openstudio-hvac-visualizer/scripts/visualize_hvac.py"
    original = topology["source"].read_bytes()
    outputs = []
    for index in range(2):
        report_path = tmp_path / f"native-{index}.json"
        output = tmp_path / f"native-{index}"
        run = subprocess.run(
            [
                str(cli),
                "execute_python_script",
                str(script),
                "--input",
                str(topology["source"]),
                "--output-dir",
                str(output),
                "--report",
                str(report_path),
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert run.returncode == 0, run.stdout + run.stderr
        report = json.loads(report_path.read_text())
        assert report["ok"] and report["mode"] == "inspect_only" and not report["ready"]
        assert len(run.stdout) < 6000
        assert "Z first fan" not in run.stdout
        graph = json.loads((output / "graph.json").read_text())
        assert (
            graph["coverage"]["represented_connection_count"]
            == graph["coverage"]["native_connection_count"]
        )
        outputs.append({p.name: p.read_bytes() for p in output.iterdir()})
    assert outputs[0] == outputs[1]
    assert topology["source"].read_bytes() == original
    report_path = tmp_path / "old.json"
    run = subprocess.run(
        [
            str(cli),
            "execute_python_script",
            str(script),
            "--input",
            str(ROOT / "tests/fixtures/openstudio-legacy-multiloop.osm"),
            "--output-dir",
            str(tmp_path / "old"),
            "--report",
            str(report_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert run.returncode == 2
    assert json.loads(report_path.read_text())["status"] == "requires_preparation"
    assert not (tmp_path / "old").exists()
