# No-reheat terminal class replacement

OpenStudio 3.11.0 / EnergyPlus 25.2; operation `replace_terminal`. Initial phase
11b supports one directly connected **VAVNoReheat ↔ ConstantVolumeNoReheat**
terminal. This is a selected-terminal conversion, not a whole-air-system recipe.

```json
{
  "output_model_path": "/work/converted.osm",
  "air_loop": {"name": "Existing Air Loop"},
  "zone": {"name": "Zone 1"},
  "terminal": {"name": "Selected Terminal"},
  "target_class": "ConstantVolumeNoReheat",
  "maximum_airflow_m3_s": "Preserve",
  "availability_policy": "Preserve",
  "reheat_policy": "None",
  "zone_sizing_policy": "Preserve",
  "system_sizing_policy": "Preserve",
  "reference_policy": "Reject"
}
```

Selectors accept a unique name or handle. Every shown field is an explicit choice;
only `output_model_path` is schema-required so preflight can list missing choices
without inventing them. For a VAV target choose `target_class: "VAVNoReheat"`
and add `minimum_airflow_fraction` between 0 and 1 inclusive. It is invalid for a
constant-volume target. Maximum flow accepts `"Preserve"` (retain existing fixed
or Autosize setting), `"Autosize"` (explicit reset) or a positive number in m³/s.
No implicit flow resets occur. Zone and system sizing inputs are preserved.

VAV source controls must use Constant minimum, no minimum/turndown schedule, and
`controlForOutdoorAir` false. A CV target cannot retain those other controls.
Explicit VAV minimum replaces the CV behavior on reverse conversion, with OA
control off and no minimum/turndown schedule. Target raw defaults and all active
flow settings are frozen in the reviewed plan and independently checked after save.

No coil exists before or after this operation. Reheat terminals are rejected;
no coil or plant is removed as a workaround. Terminals on other zones/loops,
air-loop supply equipment/fan, OA/DCV, schedules, loads and sizing stay unchanged.
Constant-volume requests maximum flow whenever available. VAV responds to zone
cooling demand down to its chosen Constant minimum; in heating it remains at its
minimum without local reheat. Both can overcool at part load. Flow also depends
on upstream availability/capacity and retained system controls. The minimum is a
supply-air fraction, not an OA fraction. See the pinned
[EnergyPlus engineering reference](https://bigladdersoftware.com/epx/docs/25-2/engineering-reference/air-system-distribution-terminals.html).

Impact reports old/new settings, service, boundary nodes, equipment slot, metadata,
multiplied nominal zone OA and retained compatible outputs. A fixed maximum below
total nominal zone OA marks simulation unready; autosized maximum warns that
sizing/ventilation remains unresolved. Multiple air-loop service warns. The
conversion alone does not certify comfort, energy savings or ventilation.

Impact also lists retained supply-fan names/classes and both system-sizing and
mechanical-ventilation OA methods. A VAV target with `OS_Fan_ConstantVolume` warns
that fan power is proportional to actual flow at fixed pressure/efficiency,
without a variable-volume part-load curve. A desired fan-class/curve change uses
`openstudio-supply-fan-replacer`; the terminal operation never changes it
implicitly. See the pinned [fan model equations](https://bigladdersoftware.com/epx/docs/25-2/engineering-reference/air-system-fans.html).
Discrete `OS_Fan_SystemModel` also warns for a VAV target. Impact records its
speed control, speed count and power-curve reference. Single-speed Discrete
control cycles on/off; multiple speeds use time-weighted speed-level power and
can have speed power fractions or a curve. The warning distinguishes those
cases rather than claiming every Discrete fan lacks a curve. Continuous control
does not get this warning. FanSystemModel edits/conversion need separate coverage;
the current fan replacer supports constant-/variable-volume fan classes only.
Model-specific warning strings remain in local plans/reports. Failure capture
reads explicit configuration, never plan warnings; public issue diagnostics must
not import warning text or model-object names.
When either OA method uses Ventilation Rate Procedure (including the mechanical
ventilation WithLimit variant), `system_oa_sizing_may_change` is true and preflight
warns that minimum-primary-flow changes can affect recalculated system OA despite
preserved sizing objects. Re-run sizing and check system OA. This is a dependency
warning, not a measured change in design OA; see the pinned
[VRP sizing guidance](https://bigladdersoftware.com/epx/docs/25-2/input-output-reference/group-design-objects.html#field-minimum-zone-ventilation-efficiency).

Direct references such as EMS actuators and LifeCycleCost block replacement. The
name remains, so name-keyed `Zone Air Terminal Outdoor Air Volume Flow Rate`
requests survive and are listed. Other name-keyed terminal outputs block rather
than silently becoming invalid. Wildcard requests remain; VAV-only variables
may disappear on CV. Existing schedules/output objects are never deleted.
Name-keyed EMS sensors remain blocked by reference policy, including sensors for
the compatible OA output. Their error explicitly distinguishes this policy from
output incompatibility; EMS control dependencies are not certified by this scope.

The old terminal and exactly two air connections are removed. A target terminal
and exactly two connections are added. The zone's equipment-list pointer and
metadata owner are retargeted; their handles, every other field, priorities,
sequential fractions and all other equipment slots remain. Both air boundary
node handles remain. The plan freezes the full connection graph, protected-object
snapshot, complete mutable-object fingerprints and every new raw field with
tokens for the three deliberately new identities. Saved validation independently
checks those fields plus translated terminal, ADU, zone sequencing and temperature
control. Raw checks fail before translation if the model is malformed.

The source and reviewed report hashes, exact fresh-plan equality, generated-object
counts and companion rules use the existing shared transaction unchanged. Output
is always a new OSM and companion directory. Store the apply report's `changes`
mapping in workflow state; later plans must use the replacement handle.

## Deferred coverage

Reheat addition/removal, reheat-terminal class changes, PIU/dual-duct/unitary/beam
terminals, reassignment, minimum-method conversion, automatic reference rewrites
and full VAV/CAV system conversion are outside this checkpoint. Same-class VAV
control edits retain identity through `openstudio-terminal-editor`. The existing
CAV recipe's pinned-engine reheat-cap issue documented in 11a remains a separate
follow-up; this no-reheat conversion does not change that recipe.
