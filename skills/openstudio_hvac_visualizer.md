---
name: openstudio-hvac-visualizer
description: Draw a local OSM model's HVAC topology as JSON, Mermaid and Markdown, including air/plant loops, zone equipment, served zones and VRF membership. Use for topology inspection before or after an HVAC edit; does not validate sizing or simulate.
---

# HVAC Visualizer

Prefer configured compatible NLR through `delegated-nlr-modeling` when it supplies
the required topology. If it cannot, record that provider transition and use this
local bundle against the recorded host model path. NLR-owned unstaged models are
not accessible through this script.

Run `scripts/doctor.py` with project-first host Python 3.10+ and use its verified
OpenStudio 3.11.0 executable. These scripts are fixed launchers into the complete
plugin's shared `sdk/` library; restore the whole plugin on `plugin_incomplete`.
No modeling-runtime connection or diagramming service is required.

```text
<verified-cli> execute_python_script <skill>/scripts/visualize_hvac.py --input <absolute/model.osm> --output-dir <absolute/new-diagram-directory> --report <absolute/new-report.json>
```

The source and companions are read only. Weather, simulation success and an
assumptions approval are not prerequisites. Use new output/report paths; no
existing output is replaced. `ok: true, status: visualized` is success; `ready`
stays false because this is inspection, not an approved mutation plan.

If the command returns `requires_preparation`, follow
[model preparation](references/model_preparation.md) using this skill's
`scripts/prepare_model.py`, then rerun visualization against the prepared path.
Store original → prepared lineage and `state_patch` in the workflow blackboard.
Never write an ad hoc normalizer or bypass the version/stability gate. A missing
current-version loop assignment list is an invalid-model diagnostic, not a repair
request the visualizer can satisfy.

Present `index.md` and the selected per-system Markdown views, or the Mermaid
content when supported by the host. Link the local artifacts; do not paste the
full JSON graph into the conversation. The index lists all system/zone handles.
For a focused second view, repeat `--system <exact-handle>` for air loops, plants,
VRF systems or zones. This selects per-system diagrams; the JSON graph and
overview remain complete. On large models the overview collapses zones after 40;
every zone remains identifiable in the index and full graph.

Diagrams show equipment and rectangular thermal-zone boxes. Green denotes zones,
blue the air system (secondary loop), and orange the water system (primary loop).
Hide SDK nodes, port lists, loop boundary objects, virtual splitters/mixers,
adiabatic routing pipes and controls. Solid arrows connect consecutive equipment
through verified directed routing paths and recorded zone boundaries. Keep
branches parallel and coil air/water and recovery supply/exhaust views separate.
Use one connected air diagram: supply/intake on the left, zones in the middle,
and return/relief/exhaust on the right. Show each zone once. The OA intake/mixed
and return/relief boxes are port views of the same assembly; heat recovery retains
separate supply/exhaust views. Open arrows show verified outdoor intake/exhaust
boundaries. Label fans by their connected paths. Preserve actual equipment order,
including blow-through fans before coils, and every physical arrow's direction.
Routing-only water bypass paths remain in the equipment JSON and are omitted from
the drawing with a note. Do not label them as mains/district connections. Water-use
connections retain one inlet/outlet water view; plant return arrows stay explicit.
Dashed edges are containment, service or VRF membership, never invented internal
flow. VRF diagrams and the overview fold contained coils/fans without external
flow into their parent label; full components stay in JSON. Other per-system
views retain those components with their internal air order unexpanded. Keep any
component with an external flow connection visible. Default equipment names show
the type once; custom names remain. Shared-zone labels name the other air-loop or
VRF systems serving that zone. Hidden-only groups produce no diagram files;
their controls remain in JSON, with OA/MV controllers assigned to their air loop.

`equipment_graph.json` records a verified path's original edge IDs for each
condensed connection; `graph.json` keeps every original handle, port, stored
controller reference and warning. Port discrepancies stay in that detailed graph;
do not repair or ignore them. Diagrams omit port numbers and handle suffixes from
equipment labels. Unknown equipment retains separate unexpanded port views and
coverage warnings; never describe a partial diagram as complete validation.
Translator-generated controls, sizing and operational correctness are not verified.
Read [the graph contract](references/hvac_graph.schema.json) only for machine
consumption, topology debugging or an unfamiliar omission.

Generated artifacts contain original model labels and handles and stay local.
Unexpected execution failures route to `report-openstudio-failure` before safe
recovery, using `failure_receipt` when returned. Do not attach the graph, diagrams,
model or companions to automatic public issues. Expected input/version/preparation
questions do not submit. Store diagram/report paths and the input hash in workflow
state so later modeling phases can identify which copy was inspected.
