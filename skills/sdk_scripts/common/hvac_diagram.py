"""Deterministic Mermaid artifacts. Object labels never become diagram syntax."""

import hashlib
from collections import defaultdict, deque
import json
import re


def label(value):
    # Mermaid supports decimal entity codes. Never insert raw model syntax.
    return "".join(
        c if c.isalnum() or c in " _-.,:/" else f"#{ord(c)};"
        for c in str(value).replace("\n", " ").replace("\r", " ")
    )


def markdown(value):
    return "".join(
        c if c.isalnum() or c in " _-.,:/" else f"&#{ord(c)};"
        for c in str(value).replace("\n", " ").replace("\r", " ")
    )


def vertex(handle, channel="object"):
    return "n" + hashlib.sha256((handle + ":" + channel).encode()).hexdigest()[:32]


def channel(node, field, port, medium):
    kind, name = node["type"], field.lower()
    if kind == "OS_ThermalZone":
        return "zone"
    if (
        kind in {"OS_Node", "OS_PortList"}
        or routing_connector(kind)
        or kind.endswith(
            (
                "_Mixer",
                "_Splitter",
                "_ZoneMixer",
                "_ZoneSplitter",
                "_ReturnPlenum",
                "_SupplyPlenum",
            )
        )
    ):
        return medium
    if kind == "OS_AirLoopHVAC_OutdoorAirSystem":
        return "OA mixing and relief"
    if kind in {"OS_AirLoopHVAC", "OS_PlantLoop"}:
        if (
            "demand side inlet" in name
            or "supply side outlet" in name
            or "plant side outlet" in name
        ):
            return "supply to demand B" if name.endswith(" b") else "supply to demand"
        if (
            "demand side outlet" in name
            or "supply side inlet" in name
            or "plant side inlet" in name
        ):
            return "demand to supply"
    for phrase in (
        "supply air",
        "exhaust air",
        "primary air",
        "secondary air",
        "chilled water",
        "condenser",
        "source side",
        "load side",
        "use side",
        "supply side",
        "demand side",
        "water",
        "air",
    ):
        if phrase in name:
            return phrase
    if kind.startswith(("OS_Pipe_", "OS_Pump_", "OS_HeaderedPumps_")):
        return "water"
    if kind == "OS_WaterUse_Connections":
        return "water"
    # Opaque equipment keeps separate ports. Joining them invents topology.
    return "unexpanded port " + str(port)


LEGEND = (
    "Green: thermal zones. Blue: air system (secondary loop). Orange: water system "
    "(primary loop). Solid arrows connect equipment through hidden routing nodes "
    "and recorded zone boundaries. Dashed arrows show containment or service/VRF "
    "membership, not a verified internal flow order. Controls and SDK routing "
    "objects are hidden. Coil air/water and recovery supply/exhaust views stay "
    "separate. Exact handles, ports and warnings remain in graph.json; condensed "
    "connection evidence is in equipment_graph.json. No sizing/operation validation."
    " The overview and VRF diagrams fold contained equipment without external "
    "flow into the parent label; exact components remain in JSON. One connected "
    "air view reads from supply "
    "on the left through zones to return/exhaust on the right. OA intake/mixed "
    "and return/relief boxes are port views of the same assembly. Heat recovery "
    "appears on both streams. Open arrows mark verified outdoor boundaries. "
    "Routing-only water bypass paths are omitted from the drawing and retained "
    "with evidence in equipment_graph.json. Fan roles come from connected paths. "
    "Equipment order follows the model, including fans upstream of coils."
)

STYLES = [
    "  classDef zone fill:#dcfce7,stroke:#15803d,color:#17202a,stroke-width:2px",
    "  classDef air fill:#dbeafe,stroke:#2563eb,color:#17202a,stroke-width:2px",
    "  classDef water fill:#ffedd5,stroke:#c2410c,color:#17202a,stroke-width:2px",
    "  classDef boundary fill:transparent,stroke:transparent,color:#17202a",
]


def routing_connector(kind):
    return kind.startswith(("OS_AirLoopHVAC_", "OS_Connector_")) and kind.endswith(
        ("Mixer", "Splitter")
    )


def physical(node):
    """Hide SDK routing/control objects, not unknown equipment classes."""
    kind = node["type"]
    return (
        kind
        not in {
            "OS_Node",
            "OS_PortList",
            "OS_Connection",
            "OS_AirLoopHVAC",
            "OS_PlantLoop",
            "OS_Pipe_Adiabatic",
            "OS_AirLoopHVAC_ZoneSplitter",
            "OS_AirLoopHVAC_ZoneMixer",
        }
        and not routing_connector(kind)
        and not kind.startswith(
            (
                "OS_Controller_",
                "OS_SetpointManager_",
                "OS_Connector_",
                "OS_AvailabilityManager_",
            )
        )
    )


def equipment_name(node, stream):
    kinds = {
        "OS_AirLoopHVAC_OutdoorAirSystem": "Outdoor-air box",
        "OS_AirConditioner_VariableRefrigerantFlow": "VRF outdoor unit",
        "OS_ZoneHVAC_TerminalUnit_VariableRefrigerantFlow": "VRF indoor unit",
        "OS_AirTerminal_SingleDuct_VAV_Reheat": "VAV reheat terminal",
        "OS_AirTerminal_SingleDuct_VAV_NoReheat": "VAV terminal",
        "OS_HeatExchanger_AirToAir_SensibleAndLatent": "Heat recovery",
    }
    if node["type"] == "OS_ThermalZone":
        return node["name"] or "Thermal zone"
    type_name = node["type"].removeprefix("OS_")
    readable = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", type_name.replace("_", " "))
    readable = re.sub(r"([A-Z])([A-Z][a-z])", r"\1 \2", readable)
    kind = kinds.get(node["type"], readable)

    def normalized(text):
        return re.sub(r"[\s_]", "", text.casefold())

    default = re.fullmatch(
        re.escape(normalized(type_name)) + r"(\d*)", normalized(node["name"])
    )
    if default:
        text = kind + (" " + default[1] if default[1] else "")
    else:
        text = kind + (" / " + node["name"] if node["name"] else "")
    if stream not in {"object", "air", "water", "OA mixing and relief"}:
        text += " / " + (
            "internal path unexpanded" if stream.startswith("unexpanded") else stream
        )
    return text


def shared_zone_labels(graph, group):
    systems = {
        g["root"]: g["name"]
        for g in graph["groups"]
        if g["kind"] in {"air_loop", "vrf_system"}
    }
    current = (
        group["root"] if group and group["kind"] in {"air_loop", "vrf_system"} else None
    )
    labels = {}
    for zone in graph["zones"]:
        served = set(zone["air_loops"]) | set(zone["vrf_systems"])
        if len(served) < 2:
            continue
        others = sorted(
            served - {current}, key=lambda key: (systems.get(key, key), key)
        )
        prefix = "also: " if current in served else "served by: "
        labels[zone["handle"]] = prefix + ", ".join(
            systems.get(key, key) for key in others
        )
    return labels


def equipment_topology(graph, group=None):
    """Contract routing paths; never traverse an intervening physical component.

    Keep one verified path for each condensed endpoint pair/medium. The raw graph
    retains all parallel routing paths and exact original connection records.
    """
    nodes = {n["handle"]: n for n in graph["nodes"]}
    edges = [e for e in graph["edges"] if group is None or group["id"] in e["groups"]]
    members = set(nodes) if group is None else set(group["members"])
    adjacency = defaultdict(list)
    views, displayed, omitted = {}, defaultdict(set), set()
    shared_zones = shared_zone_labels(graph, group)

    def endpoint(edge, side):
        key = edge[side]
        stream = "zone" if nodes[key]["type"] == "OS_ThermalZone" else "air"
        if edge["kind"] == "flow":
            stream = channel(
                nodes[key],
                edge[side + "_field"],
                edge[side + "_field_index"],
                edge["medium"],
            )
            if stream.startswith("unexpanded"):
                omitted.add(key)
        return key, stream

    def add(point, medium=None):
        key, stream = point
        if nodes[key]["type"] == "OS_ThermalZone":
            stream = "zone"
        identifier = vertex(key, stream)
        category = (
            "zone"
            if stream == "zone"
            else (
                "water"
                if medium == "water"
                or stream == "water"
                or any(
                    word in stream
                    for word in (
                        "chilled water",
                        "condenser",
                        "source side",
                        "load side",
                        "use side",
                    )
                )
                else "air"
            )
        )
        if stream == "object":
            in_water_group = group and group["kind"] == "plant_loop"
            water_equipment = nodes[key]["type"].startswith(
                (
                    "OS_Pump_",
                    "OS_HeaderedPumps_",
                    "OS_Boiler_",
                    "OS_Chiller_",
                    "OS_WaterHeater_",
                    "OS_WaterUse_",
                    "OS_CoolingTower_",
                    "OS_DistrictHeating",
                    "OS_DistrictCooling",
                )
            )
            category = "water" if in_water_group or water_equipment else "air"
        text = equipment_name(nodes[key], stream)
        if stream == "zone" and key in shared_zones:
            text += " / " + shared_zones[key]
        views[identifier] = dict(
            id=identifier,
            handle=key,
            type=nodes[key]["type"],
            channel=stream,
            category=category,
            label=text,
        )
        displayed[key].add(stream)
        return identifier

    for edge in edges:
        if edge["kind"] not in {"flow", "zone_boundary"}:
            continue
        source, target = endpoint(edge, "source"), endpoint(edge, "target")
        medium = edge.get("medium", "air")
        adjacency[source].append((target, medium, edge["id"]))
        for point in (source, target):
            if physical(nodes[point[0]]):
                add(point, medium)

    condensed, boundaries = {}, {}
    for source in sorted(adjacency):
        if not physical(nodes[source[0]]):
            continue
        queue = deque(
            (target, medium, [evidence])
            for target, medium, evidence in sorted(adjacency[source])
        )
        visited = set()
        while queue:
            target, medium, evidence = queue.popleft()
            if physical(nodes[target[0]]):
                a, b = add(source, medium), add(target, medium)
                condensed.setdefault(
                    (a, b, "flow", medium),
                    dict(
                        source=a,
                        target=b,
                        kind="flow",
                        medium=medium,
                        evidence=evidence,
                    ),
                )
                continue
            if (target, medium) in visited:
                continue
            visited.add((target, medium))
            if (
                medium == "air"
                and nodes[target[0]]["type"] == "OS_Node"
                and not adjacency[target]
                and len(nodes[target[0]]["ports"]) == 1
                and nodes[target[0]]["ports"][0]["direction"] == "in"
            ):
                identifier = add(source, medium)
                boundaries.setdefault(
                    (identifier, "out"),
                    dict(
                        anchor=identifier,
                        direction="out",
                        handle=target[0],
                        evidence=evidence,
                    ),
                )
            for following, next_medium, next_evidence in sorted(adjacency[target]):
                if next_medium == medium:
                    queue.append((following, medium, evidence + [next_evidence]))

    # A one-ended intake node can only be reached by starting at that boundary.
    # Keep it as a marker with evidence, never as physical equipment.
    for source in sorted(adjacency):
        node = nodes[source[0]]
        if (
            node["type"] != "OS_Node"
            or len(node["ports"]) != 1
            or node["ports"][0]["direction"] != "out"
        ):
            continue
        queue = deque(
            (target, medium, [key])
            for target, medium, key in adjacency[source]
            if medium == "air"
        )
        visited = set()
        while queue:
            target, medium, evidence = queue.popleft()
            if physical(nodes[target[0]]):
                identifier = add(target, medium)
                boundaries.setdefault(
                    (identifier, "in"),
                    dict(
                        anchor=identifier,
                        direction="in",
                        handle=source[0],
                        evidence=evidence,
                    ),
                )
                continue
            if target in visited:
                continue
            visited.add(target)
            queue.extend(
                (following, medium, evidence + [key])
                for following, m, key in adjacency[target]
                if m == medium
            )

    for key in sorted(members):
        if physical(nodes[key]) and key not in displayed:
            add((key, "zone" if nodes[key]["type"] == "OS_ThermalZone" else "object"))

    for edge in edges:
        if edge["kind"] not in {
            "contains",
            "vrf_membership",
            "serves_zone",
            "plenum_zone",
        }:
            continue
        if not all(physical(nodes[edge[side]]) for side in ("source", "target")):
            continue
        ends = []
        for side in ("source", "target"):
            key = edge[side]
            # Relations do not join two circuit views into a physical flow path.
            streams = sorted(displayed[key])
            preferred = "water" if group and group["kind"] == "plant_loop" else "air"
            stream = preferred if preferred in streams else streams[0]
            ends.append(vertex(key, stream))
        a, b = ends
        # Avoid duplicating a proven terminal-to-zone air connection with a
        # generic equipment membership edge. Zone-only membership remains.
        if edge["kind"] == "serves_zone" and (a, b, "flow", "air") in condensed:
            continue
        condensed.setdefault(
            (a, b, edge["kind"], ""),
            dict(source=a, target=b, kind=edge["kind"], evidence=[edge["id"]]),
        )
    topology = dict(
        nodes=sorted(views.values(), key=lambda n: n["id"]),
        edges=sorted(
            condensed.values(),
            key=lambda e: (e["source"], e["target"], e["kind"], e.get("medium", "")),
        ),
        boundaries=sorted(
            boundaries.values(), key=lambda b: (b["anchor"], b["direction"])
        ),
    )
    classify_air_paths(topology, graph)
    originals = {e["id"]: e for e in graph["edges"]}
    for edge in topology["edges"]:
        if edge["kind"] == "flow" and edge["medium"] == "water":
            path = [originals[key] for key in edge["evidence"]]
            edge["routing_bypass"] = routing_bypass(path, nodes)
            edge["plant_return"] = any(
                nodes[e["target"]]["type"] == "OS_PlantLoop"
                and "demand side outlet" in e["target_field"].lower()
                for e in path
            )
    exterior = []
    for boundary in topology["boundaries"]:
        anchor = views[boundary["anchor"]]
        # Zone air nodes are state points. A one-ended zone node does not prove
        # an outdoor outlet, even when the zone has exhaust equipment.
        if anchor["type"] == "OS_ThermalZone":
            continue
        paths = anchor["air_paths"]
        evidence = [originals[key] for key in boundary["evidence"]]
        # An OA box has multiple roles: its explicit port disambiguates them.
        if anchor["type"] == "OS_AirLoopHVAC_OutdoorAirSystem":
            side = "target" if boundary["direction"] == "in" else "source"
            field = evidence[-1 if side == "target" else 0][side + "_field"].lower()
            paths = (
                ["outdoor"]
                if "outdoor air" in field
                else ["exhaust"] if "relief air" in field else []
            )
        role = "outdoor" if boundary["direction"] == "in" else "exhaust"
        if role in paths:
            exterior.append(
                dict(**boundary, role=role, id=vertex(boundary["handle"], role))
            )
    topology["boundaries"] = exterior
    return topology, sorted(omitted)


def routing_bypass(path, nodes):
    """Recognize a splitter-to-mixer branch containing routing nodes/pipes only."""
    for i, edge in enumerate(path):
        if nodes[edge["source"]]["type"] != "OS_Connector_Splitter":
            continue
        for following in path[i:]:
            kind = nodes[following["target"]]["type"]
            if kind == "OS_Connector_Mixer":
                return True
            if kind not in {"OS_Node", "OS_Pipe_Adiabatic"}:
                break
    return False


def classify_air_paths(topology, graph):
    """Label directed paths from recorded OA/loop boundaries, never from names.

    The OA box and zones terminate a walk: crossing either would merge supply
    and return. These tags only affect views; evidence and endpoints stay exact.
    """
    originals = {e["id"]: e for e in graph["edges"]}
    raw_nodes = {n["handle"]: n for n in graph["nodes"]}
    nodes = {n["id"]: n for n in topology["nodes"]}
    forward, backward = defaultdict(list), defaultdict(list)
    flows = []
    for edge in topology["edges"]:
        if edge["kind"] == "flow" and edge["medium"] == "air":
            flows.append(edge)
            forward[edge["source"]].append(edge)
            backward[edge["target"]].append(edge)

    def boundary(key):
        return raw_nodes[nodes[key]["handle"]]["type"] in {
            "OS_ThermalZone",
            "OS_AirLoopHVAC_OutdoorAirSystem",
        }

    def walk(edge, section, reverse=False):
        queue, visited = deque([edge]), set()
        while queue:
            current = queue.popleft()
            key = (current["source"], current["target"])
            if key in visited:
                continue
            visited.add(key)
            current.setdefault("air_paths", set()).add(section)
            following = current["source" if reverse else "target"]
            if not boundary(following):
                queue.extend((backward if reverse else forward)[following])

    oa_loops = {
        group_id
        for node in graph["nodes"]
        if node["type"] == "OS_AirLoopHVAC_OutdoorAirSystem"
        for group_id in node["groups"]
    }
    for edge in flows:
        path = [originals[key] for key in edge["evidence"]]
        for side, sections in (
            (
                "source",
                (("mixed air", "supply", False), ("relief air", "exhaust", False)),
            ),
            (
                "target",
                (("outdoor air", "outdoor", True), ("return air", "return", True)),
            ),
        ):
            original = path[0 if side == "source" else -1]
            if raw_nodes[original[side]]["type"] == "OS_AirLoopHVAC_OutdoorAirSystem":
                field = original[side + "_field"].lower()
                for phrase, section, reverse in sections:
                    if phrase in field:
                        walk(edge, section, reverse)
        # With no OA box, the supply inlet marks the return/supply boundary.
        # A condensed closure can run from a zone to the first supply component.
        for original in path:
            if (
                original["kind"] == "flow"
                and raw_nodes[original["source"]]["type"] == "OS_AirLoopHVAC"
                and "supply side inlet" in original["source_field"].lower()
                and not set(original["groups"]) & oa_loops
            ):
                walk(edge, "return", True)
                for following in forward[edge["target"]]:
                    walk(following, "supply")
        # A zone's exhaust port list also feeds recirculating zone equipment
        # (VRF/PTAC). It is not proof of outdoor exhaust. Seed only the actual
        # exhaust fan; OA relief paths are seeded separately above.
        if raw_nodes[nodes[edge["target"]]["handle"]]["type"] == "OS_Fan_ZoneExhaust":
            walk(edge, "exhaust")

    for edge in flows:
        edge["air_paths"] = sorted(edge.get("air_paths", ()))
        for key in (edge["source"], edge["target"]):
            nodes[key].setdefault("air_paths", set()).update(edge["air_paths"])
    fan_roles = {
        "supply": "Supply fan",
        "return": "Return fan",
        "outdoor": "Outdoor-air fan",
        "exhaust": "Relief/exhaust fan",
    }
    for node in topology["nodes"]:
        node["air_paths"] = sorted(node.get("air_paths", ()))
        if raw_nodes[node["handle"]]["type"].startswith("OS_Fan_"):
            # The outgoing path determines role, notably for a supply fan at
            # the first component of a loop with no outdoor-air system.
            connected = forward[node["id"]] or backward[node["id"]]
            roles = sorted({role for e in connected for role in e["air_paths"]})
            node["fan_roles"] = roles
            if roles:
                node["label"] = (
                    "/".join(fan_roles[r] for r in roles) + " / " + node["label"]
                )


def drawing_endpoint(node, paths=()):
    """Unfold only the OA assembly; never duplicate zones to break the air cycle."""
    if node["type"] == "OS_AirLoopHVAC_OutdoorAirSystem":
        return node["id"] + (
            "_return" if set(paths) & {"return", "exhaust"} else "_supply"
        )
    return node["id"]


def presentation_notes(topology):
    count = sum(e.get("routing_bypass", False) for e in topology["edges"])
    if count:
        return f"{count} condensed paths through routing-only water bypass branches are omitted from this equipment view; their exact paths remain in equipment_graph.json. They are not mains or district-water inlets."
    return ""


def render(topology, omitted_zones=(), folded_equipment=()):
    hidden = set(omitted_zones) | set(folded_equipment)
    nodes = {n["id"]: n for n in topology["nodes"] if n["handle"] not in hidden}
    definitions, links, shown = {}, [], set()

    def point(key, paths=()):
        node = nodes[key]
        identifier = drawing_endpoint(node, paths)
        text = node["label"]
        if node["type"] == "OS_AirLoopHVAC_OutdoorAirSystem":
            text += " / " + (
                "return and relief"
                if identifier.endswith("_return")
                else "intake and mixed air"
            )
        definitions[identifier] = (
            f'  {identifier}["{label(text)}"]:::{node["category"]}'
        )
        shown.add(key)
        return identifier

    names = {
        "contains": "contains",
        "vrf_membership": "VRF membership",
        "serves_zone": "serves zone",
        "plenum_zone": "plenum zone",
    }
    for edge in topology["edges"]:
        if (
            edge["source"] not in nodes
            or edge["target"] not in nodes
            or edge.get("routing_bypass")
        ):
            continue
        a, b = (
            point(edge[side], edge.get("air_paths", ()))
            for side in ("source", "target")
        )
        arrow = "-->" if edge["kind"] == "flow" else "-.->"
        text = edge["medium"] if edge["kind"] == "flow" else names[edge["kind"]]
        if edge.get("plant_return"):
            # Rank the pump upstream, but preserve the true arrow toward it.
            links.append(f"  {b} <---|Water return| {a}")
        else:
            links.append(f'  {a} {arrow}|"{label(text)}"| {b}')
    for boundary in topology.get("boundaries", ()):
        if boundary["anchor"] not in nodes:
            continue
        anchor = point(boundary["anchor"], [boundary["role"]])
        identifier = boundary["id"]
        definitions[identifier] = f'  {identifier}[" "]:::boundary'
        a, b = (
            (identifier, anchor)
            if boundary["direction"] == "in"
            else (anchor, identifier)
        )
        text = "Outdoor air" if boundary["direction"] == "in" else "Exhaust to outdoors"
        links.append(f'  {a} -->|"{text}"| {b}')
    for key in sorted(nodes.keys() - shown):
        point(key)
    if omitted_zones:
        definitions["more_zones"] = (
            f'  more_zones["{len(omitted_zones)} additional zones: see index.md and per-zone diagrams"]:::zone'
        )
    notes = presentation_notes(topology)
    return "\n".join(
        [
            "flowchart LR",
            *[definitions[k] for k in sorted(definitions)],
            *sorted(links),
            *STYLES,
            "  %% " + notes,
            "",
        ]
    )


def diagram(graph, group):
    topology, omitted = equipment_topology(graph, group)
    return system_drawing(topology, group), omitted


def fold_contained(topology, vrf_only=False):
    """Presentation only: never fold a component with any external flow view."""
    nodes = {n["id"]: n for n in topology["nodes"]}
    flow_ends = {
        e[side]
        for e in topology["edges"]
        if e["kind"] == "flow"
        for side in ("source", "target")
    }
    contains = [
        e
        for e in topology["edges"]
        if e["kind"] == "contains"
        and e["target"] not in flow_ends
        and (
            not vrf_only
            or nodes[e["source"]]["type"]
            == "OS_ZoneHVAC_TerminalUnit_VariableRefrigerantFlow"
        )
    ]
    folded_ids = {e["target"] for e in contains}
    flow_handles = {n["handle"] for n in topology["nodes"] if n["id"] in flow_ends}
    folded = [
        n["handle"]
        for n in topology["nodes"]
        if n["id"] in folded_ids and n["handle"] not in flow_handles
    ]
    descriptions = defaultdict(set)
    for edge in contains:
        child = nodes[edge["target"]]
        if child["handle"] not in folded:
            continue
        kind = child["type"]
        description = next(
            (
                text
                for prefix, text in (
                    ("OS_Coil_Cooling", "cooling coil"),
                    ("OS_Coil_Heating", "heating coil"),
                    ("OS_Fan_", "fan"),
                    ("OS_HeatExchanger_", "heat exchanger"),
                )
                if kind.startswith(prefix)
            ),
            child["label"],
        )
        descriptions[edge["source"]].add(description)
    presented = dict(
        topology,
        nodes=[
            dict(
                n,
                label=n["label"]
                + (
                    " / contains: " + ", ".join(sorted(descriptions[n["id"]]))
                    if n["id"] in descriptions
                    else ""
                ),
            )
            for n in topology["nodes"]
        ],
    )
    return presented, folded


def system_drawing(topology, group):
    if group["kind"] == "vrf_system":
        presented, folded = fold_contained(topology, vrf_only=True)
        return render(presented, folded_equipment=folded)
    return render(topology)


def overview(graph, zone_limit=40):
    topology, _ = equipment_topology(graph)
    zones = sorted(z["handle"] for z in graph["zones"])
    presented, folded = fold_contained(topology)
    return render(presented, zones[zone_limit:], folded)


def artifacts(graph, selected=()):
    groups = graph["groups"]
    if selected:
        missing = set(selected) - {g["root"] for g in groups}
        if missing:
            raise ValueError(
                "Unknown system/zone handle; choose an exact root handle from graph.json"
            )
        groups = [g for g in groups if g["root"] in selected]
    equipment, _ = equipment_topology(graph)
    output = {
        "overview.mmd": overview(graph),
        "equipment_graph.json": json.dumps(
            dict(schema_version=1, source_graph="graph.json", **equipment),
            sort_keys=True,
            indent=2,
        )
        + "\n",
    }
    index = [
        "# HVAC topology",
        "",
        LEGEND,
        "",
        "```mermaid",
        output["overview.mmd"].rstrip(),
        "```",
        "",
        "## Diagrams",
        "",
        "| System | Kind | Model handle | Diagram |",
        "| --- | --- | --- | --- |",
    ]
    nodes = {node["handle"]: node for node in graph["nodes"]}
    unknown = {
        edge[side]
        for edge in graph["edges"]
        if edge["kind"] == "flow"
        for side in ("source", "target")
        if channel(
            nodes[edge[side]],
            edge[side + "_field"],
            edge[side + "_field_index"],
            edge["medium"],
        ).startswith("unexpanded")
    }
    for group in groups:
        stem = group["id"]
        projected, omitted = equipment_topology(graph, group)
        unknown.update(omitted)
        if not projected["nodes"]:
            continue  # Retain controls in JSON without publishing an empty diagram.
        text = system_drawing(projected, group)
        output[stem + ".mmd"] = text
        output[stem + ".md"] = (
            f'# {markdown(group["name"])}\n\n{LEGEND}\n\n{presentation_notes(projected)}\n\n```mermaid\n{text}```\n'
        )
        index.append(
            f'| {markdown(group["name"])} | {group["kind"]} | {group["root"] or "none"} | [view]({stem}.md) / [Mermaid]({stem}.mmd) |'
        )
    index += [
        "",
        "## Zone index",
        "",
        "All zones remain identifiable here, including zones collapsed in the overview.",
        "",
        "| Zone | Model handle | Air loops | VRF systems | Equipment | Status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for zone in graph["zones"]:
        status = (
            "unserved"
            if zone["unserved"]
            else (
                "plenum"
                if zone["plenum"]
                else "ideal loads" if zone["ideal_loads"] else "served"
            )
        )
        index.append(
            f'| {markdown(zone["name"])} | {zone["handle"]} | {", ".join(zone["air_loops"])} | {", ".join(zone["vrf_systems"])} | {", ".join(zone["equipment"])} | {status} |'
        )
    index += [
        "",
        "## Coverage",
        "",
        "See graph.json for exact connections, source provenance and per-object warnings.",
        "",
    ]
    if unknown:
        index += [
            f"Opaque port views: {len(unknown)} objects retain separate ports; internal through-flow is not inferred.",
            "",
        ]
    output["index.md"] = "\n".join(index)
    return output, sorted(unknown)
