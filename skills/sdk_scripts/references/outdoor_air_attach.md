# Direct outdoor-air intake attachment

`attach_outdoor_air.py` adds one uniquely owned OA system at the main supply inlet
of a served unsplit air loop without one, immediately upstream of a direct fan or
coil. Existing fan/coil, loop, terminals, node handles, loads and sizing remain
protected. Only the inlet/downstream connection fields change; the preview
freezes the entire new graph and all created fields. Unitary/complex inlet
arrangements, shared/dedicated OA and replacing an existing intake require
separate coverage.

Require explicit choices, using the schema:

- `air_loop`: exact name/handle; `name`: unused object-name prefix.
- `ventilation`: every flow/schedule/DCV field is required. Minimum is nonnegative
  fixed flow or Autosize; maximum must be positive fixed flow or Autosize and at
  least minimum if both fixed. Each of the three schedule references is an exact
  existing typed Constant/Ruleset [0,1] schedule or explicit null. Minimum-flow
  schedule multiplies the floor; fraction schedules act on current supply flow.
- `ventilation_method: ZoneSum`, existing `mechanical_availability_schedule` and
  explicit `dcv` boolean. Enabling DCV never implicitly zeroes the minimum.
- `economizer_control: NoEconomizer`: explicit initial control. ModulateFlow and
  NoLockout are the documented inactive initial action/lockout. SDK-provided
  economizer cutoff fields remain inactive; use the economizer editor afterward
  to choose limits and verify mixed-air temperature control before enabling it.
- `bypass_control`: explicit `BypassWhenWithinEconomizerLimits` or
  `BypassWhenOAFlowGreaterThanMinimum`, recorded even before recovery exists.

One OA system, one OA controller, one ZoneSum MV controller, three nodes and five
new connections are created; the original inlet/downstream connection is removed.
All created objects have deterministic names and are fingerprinted after saving.
Hash binding, preservation checks, companion handling, report files and
EnergyPlus translation use the common transaction. The source is unchanged and
publication is exclusive to a new OSM plus `<stem>/` companion.

The plan uses the ventilation editor's occupancy, schedule, floor, cap and sizing
review, including its verified translated DCV floor. Warnings can mark simulation
unready while leaving a bounded edit ready. Adding outdoor air changes mixing and
coil loads; no automatic sizing, exhaust redesign, code policy or compliance is
implied. Zone OA definitions and People stay as supplied. Resolve those and
schedule contents separately. Attach heat recovery in a subsequent independent
operation if requested. Each step produces a reviewable copied output.
