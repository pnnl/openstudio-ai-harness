# In-place minimum outdoor-air and ZoneSum DCV editing

`edit_ventilation.py` inventories, preflights explicit partial settings and applies
an unchanged reviewed plan through the common copy transaction. The release
contract is `../compatibility.json`; change/retest the package and bundles together.

```json
{
  "output_model_path": "/absolute/outputs/ventilation.osm",
  "air_loop": {"name": "Main Air Loop"},
  "ventilation": {"dcv": true, "minimum_flow_m3_s": 0}
}
```

This example explicitly chooses both DCV and a zero controller floor; it is not a
code/template recommendation. A DCV-only patch retains the old floor and warns
when it can mask occupancy modulation. Missing selections, no-op edits, unsupported
DCV methods and unsafe schedule assignments return unready plans. The strict
[schema](ventilation.schema.json) rejects extra keys, invalid types, negative flows
and nonfinite values. Selectors use exactly a name or handle.

The preview also inspects the translated EnergyPlus minimum when DCV is enabled.
On pinned OpenStudio 3.11.0, a retained OSM `Autosize` minimum translates to `0`
with DCV; the plan explicitly reports this behavior. Native VAV/CAV comparisons
confirm that DCV-only edits can then reduce actual OA. The OSM field stays Autosize;
the script applies no implicit minimum-flow setter.

`impact.dcv_floor` records declared/translated minimums, the scheduled lower bound,
nominal design OA and minimum-limit type. A verified `FixedMinimum` floor at or
above nominal ZoneSum design OA sets `impact.dcv_effective: false` and says plainly
that DCV will have no effect on OA reductions. It names an explicit
`minimum_flow_m3_s` change (for example 0) to allow reductions; fraction floors and
other overrides can still prevent them. A floor partway between zero and design
keeps the “can mask DCV” warning. A varying/unverified minimum-flow schedule or
ProportionalMinimum does not establish a persistent blocking floor. Effectiveness
is also false when DCV is disabled; otherwise it is null, meaning a benefit is
not established. No case automatically promises savings. Missing/unresolved
translated fields fail clearly, and saved validation rechecks the translated floor.
This diagnostic adds no new readiness gate or inferred model change.

| Field | Explicit meaning |
| --- | --- |
| `minimum_flow_m3_s`, `maximum_flow_m3_s` | Nonnegative flow in m³/s or `Autosize` |
| `minimum_limit_type` | `FixedMinimum` or `ProportionalMinimum` |
| `minimum_flow_schedule` | Existing schedule multiplying controller minimum flow; null resets reference |
| `minimum_fraction_schedule` | Existing schedule setting a floor as a fraction of supply flow; null resets reference |
| `maximum_fraction_schedule` | Existing schedule capping OA as a fraction of supply flow; null resets reference |
| `dcv` | Explicit boolean; existing uniquely owned `ZoneSum` MV only |

Selected schedules must be Constant/Ruleset, already have compatible dimensionless
type limits and have every default/rule/explicit design-day/holiday/custom-day
value in [0,1]. OpenStudio assigns type limits when an untyped schedule is attached;
preflight refuses that implicit change. A cloned preview also verifies requested
settings and raw protected state before becoming ready. No schedule is constructed,
modified or deleted. Retained unsupported schedule types produce warnings when
their ranges cannot be verified; no annual schedule enumeration enters the summary.

The local standards reference at commit
`8bad404ef113019661fc0c14274a3554234219f7` is:

- `standards/Standards.AirLoopHVAC.rb:2430–2467`: DCV helper explicitly resets
  controller minimum flow to zero and enables the MV controller. This partial
  editor exposes those as two separate choices.
- `standards/Standards.AirLoopHVAC.rb:1940–1960`: multizone optimization changes
  the ventilation method; that template policy is outside this ZoneSum operation.
- `standards/Standards.AirLoopHVAC.rb:2830–2910`: occupancy-based minimum-flow
  damper scheduling is distinct from the fraction schedule used by prototype CAV.
- `thermal_zone/thermal_zone.rb:633–697`: per-space people, area, fixed and ACH
  terms combined with `Sum`/`Maximum`; the report follows that nominal calculation.

See the [EnergyPlus 25.2 controller reference](https://bigladdersoftware.com/epx/docs/25-2/input-output-reference/group-controllers.html)
for the controller minimum floor, MV request, fraction limits and other overrides.
ZoneSum DCV uses occupancy for per-person OA. Area/fixed/ACH requirements remain;
maximum caps, exhaust, humidity, economizer and EMS may affect actual OA. MV
availability and the controller minimum-flow schedule are distinct controls.

The report records inherited SpaceType OA/People, occupancy schedule ranges,
per-space terms, zone multipliers once, nominal design OA, controller/MV settings,
actual sizing values/all-OA flags and translated mixed-air temperature control.
The console preview caps zone rows at six; full details are in the report. Geometry
aggregates use 12 significant digits to avoid last-bit SDK summation differences
between fresh preflights; requested values and protected raw fields are not rounded.
The nominal sum excludes schedule coincidence, distribution effectiveness and
exhaust. It is review evidence, not a ventilation or sizing certificate.

Warnings mark simulation unready for conflicting/zero OA caps, a fixed maximum OA
or supply flow below nominal zone OA, a fixed controller floor above fixed sizing
design OA, 100% fraction OA with incompatible sizing flags, missing DCV OA/People
inputs, unverifiable/out-of-range relevant schedules, and missing active-economizer
mixed-air setpoint control. Nonzero/autosized floors, fractional caps, constant
occupancy, MV availability and proportional minimums have specific review warnings.
Sizing is preserved; this editor neither resizes systems nor creates CO2 controls.
Flow/schedule edits preserve other MV methods; toggling DCV on those methods is
unready instead of inferring a method conversion.

Apply verifies source/resource hashes and the exact fresh plan, then saves/reloads
and independently checks seven groups: requested values, reported values and
identities, controller/MV identity, protected model fingerprints, ownership,
supply order and retained context. Numeric comparisons use `rel_tol=1e-9` and
`abs_tol=1e-9`; enums/nulls and protected raw fields remain exact. Translation errors
prevent publication. Report files are the canonical interface; original bytes and
all unspecified inputs stay protected. Companion paths follow the common portable
copy contract. A successful edit/translation does not establish annual savings.
