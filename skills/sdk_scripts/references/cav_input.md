# Prototype CAV input contract

The script derives validation from the shared VAV input vocabulary and applies
the restrictions below. This avoids duplicating the full schema. Unknown fields
block. Use absolute input/output/report paths and new output/report destinations.
The output path is required for configured preflight, including assumption review.

- `system_name`, `target_zones`: nonempty name and exact zone name/handle selectors.
- `defaults_profile`: `prototype_cav_v1`, only after explicit human acceptance.
- `central_heating`, `reheat`: `type: Water` and explicit compatible HW
  `plant_loop` selector. They may select separate heating plants.
- `central_cooling`: `Water` plus CHW selector, or `DXTwoSpeed` plus explicit
  `dx_approved: true`. Coil/plant/fuel choices are not filled automatically.
- Editable inputs: `fan` efficiency/motor efficiency/pressure with Pa or inH2O;
  `availability_schedule`, `outdoor_air_schedule`; `economizer` (NoEconomizer,
  FixedDryBulb, DifferentialDryBulb); `minimum_terminal_airflow_fraction` [0,1];
  `sizing_option` (Coincident/NonCoincident); six `design_temperatures_c` values
  (preheat, precool, central_heating, central_cooling, zone_heating, zone_cooling).
  Availability/OA schedules use exact name/handle or `builtin: AlwaysOnDiscrete`.
  An explicit OA choice is required even with an accepted profile. `null` means
  ZoneSum minimum ventilation with no additional fraction floor. Builtin
  AlwaysOnDiscrete means **100% outdoor air whenever running**, enables both
  all-outdoor-air sizing flags and makes economizer selection ineffective.
  Named/handle constant 1 schedules have the same meaning. Other positive or
  variable/unclassified fraction schedules enable conservative 100% OA heating/
  cooling sizing; this can oversize coils. Constant 0 keeps minimum-ventilation
  sizing. The plan/review and compact summary expose the OA policy; missing OA
  choice leaves preflight unready. Re-preflight previously approved CAV plans.
- `minimum_system_airflow_ratio`: fixed 1.0 in this bounded recipe. It sets the
  heating sizing ratio, not every terminal's operating flow.
- `return_plenum`: null only in this initial recipe.

Generic defaults: fan efficiencies 0.62/0.9 and pressure 4 inH2O; system heating
airflow sizing ratio 1.0; terminal minimum fraction 0.3; coincident sizing;
NoEconomizer; heating design 62 F central/122 F zone; other design temperatures
from the shared generic profile. OA schedule drives minimum **fraction**, unlike
the VAV minimum-flow schedule field. Fixed controls include CycleOnAny/3600 seconds,
scheduled cooling SAT, ZoneSum ventilation, ReverseWithLimits water reheat, maximum
reheat airflow fraction 0.5 and flow per area 0.0. These generic damper settings
do not include ASHRAE/building-specific callbacks or final ventilation corrections.

The saved plan is authoritative for all resolved settings, units, controls and
assumptions. Partial plans have `ready: false` and cannot apply. A nonzero preflight
exit with missing inputs is a review checkpoint, not cancellation of the task.
