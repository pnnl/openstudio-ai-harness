# In-place economizer editing

`edit_economizer.py` inventories air loops, preflights explicit partial settings,
and applies an unchanged reviewed plan through the shared copy transaction.
The version contract is `../compatibility.json`; update/retest the package and
exported bundles together when changing the supported OpenStudio release.

```json
{
  "output_model_path": "/absolute/outputs/economizer.osm",
  "air_loop": {"name": "Main Air Loop"},
  "economizer": {
    "control_type": "FixedDryBulb",
    "maximum_dry_bulb_c": 24.0
  }
}
```

This is an illustrative explicit edit, not a climate or code recommendation.
Selectors accept exactly a name or handle. Inputs are strict: unsupported keys,
wrong types, nonfinite numbers and out-of-bounds values fail. Missing selections
or an empty edit return an unready plan. No-op edits and invalid effective controls
are unready. See [the schema](economizer.schema.json).

| Field | Meaning |
| --- | --- |
| `control_type` | NoEconomizer, FixedDryBulb, FixedEnthalpy, DifferentialDryBulb, DifferentialEnthalpy, FixedDewPointAndDryBulb, ElectronicEnthalpy, DifferentialDryBulbAndEnthalpy |
| `lockout_type` | NoLockout, LockoutWithHeating or LockoutWithCompressor |
| `maximum_dry_bulb_c`, `minimum_dry_bulb_c` | Explicit dry-bulb cutoff in °C, or null to reset |
| `maximum_dewpoint_c` | Explicit dewpoint cutoff in °C, or null to reset |
| `maximum_enthalpy_j_kg` | Explicit enthalpy cutoff in J/kg, or null to reset |

Temperature inputs are bounded to −100–100 °C and enthalpy to 0–300000 J/kg.
These broad guards do not certify suitability. FixedDryBulb requires a nonblank
maximum dry-bulb limit; FixedEnthalpy requires maximum enthalpy;
FixedDewPointAndDryBulb requires dry-bulb and dewpoint limits. Active minimum
dry-bulb must be below maximum. ElectronicEnthalpy requires an existing quadratic
or cubic limit curve; no curve is inferred or replaced. NoEconomizer retains
inactive limits and lockout. Disable an existing economizer with an explicit
`{"control_type": "NoEconomizer"}` patch.

Every omitted field is retained. Nonblank dry-bulb, enthalpy, dewpoint, minimum
dry-bulb and electronic-curve restrictions can act together. Changing type does
not clear the old cutoffs. The plan exposes effective before/after values and
retained ventilation controls so the user can explicitly remove unwanted limits.

The standards reference is `Standards.AirLoopHVAC.rb:1030–1099` and `1151–1183`:
its climate/template policy resets limits before selecting new ones; this partial
editor deliberately requires explicit resets. The hydronic LockoutWithCompressor
warning follows the standards' integrated/nonintegrated distinction and does not
infer a supply-air-temperature cutoff. VAV/CAV parent construction shares these
field setters while retaining its approved recipe defaults and one transaction.

The [EnergyPlus 25.2 Controller:OutdoorAir reference](https://bigladdersoftware.com/epx/docs/25-2/input-output-reference/group-controllers.html)
describes the additive cutoffs and OA overrides. Minimum-flow/fraction schedules
and mechanical ventilation are independent from economizer selection. Maximum
fraction can override minimum ventilation. A positive time-of-day economizer
schedule forces maximum OA; it is not an availability schedule. MinimumFlowWithBypass
controls heat recovery while holding minimum OA. Existing high-humidity controls,
EMS, staging and equipment availability can further affect operation.

The impact reports retained flow values, schedule references/constant values, MV
method/DCV, action, staging, curve, heat-recovery bypass and sizing flags. A retained
constant 100% OA floor warns that economizer selection cannot lower it; unmatched
all-OA sizing flags or conflicting/zero flow/fraction caps also set
`simulation_ready: false` without blocking this independent edit. Nonconstant
schedule values require time-based review; no schedule enumeration is printed.
No compliance, correct sizing or annual savings is inferred.

Enabled economizers also inspect the proposed translated OA controller's mixed-air
node. `retained_context.mixed_air_control` and the impact record the node, its
translated temperature managers and whether a single-temperature setpoint source
is verified. Generated MixedAir managers and direct managers are recognized by
target fields, including NodeList expansion; a reference-node match does not count.
Humidity-only managers and Scheduled:DualSetpoint (which writes high/low bounds)
do not supply the single temperature setpoint read by this economizer.

When no source is verified, the scoped edit stays ready, but a specific warning
sets plan, companion and published `simulation_ready: false`. No manager, setpoint
value or supply-outlet control is created implicitly. Verify custom/EMS setpoint
control separately; manager presence alone does not certify reference chains or
runtime EMS execution. NoEconomizer skips this requirement. The saved model's
translated control context must match the approved preview.

The [EnergyPlus 25.2 MixedAir source](https://github.com/NatLabRockies/EnergyPlus/blob/v25.2.0/src/EnergyPlus/MixedAir.cc#L2389-L2419)
checks `TempSetPoint` and reports “Missing temperature setpoint for economizer
controller”; it also allows EMS-managed node temperature setpoints. This bundle
conservatively flags sources it cannot verify instead of inferring EMS behavior.

Apply preserves the original bytes, selected controller handle/name, every other
model object and raw field except explicitly requested controller fields, all
connections/order and incoming references. Saved getters are checked against the
approved effective values with `rel_tol=1e-9` and `abs_tol=1e-9` for numbers
(nulls/enums remain exact), then protected-state fingerprints, retained context
and ownership are independently checked. Translation errors prevent publication.
Use report files as the canonical machine interface. Carry the published companion
folder with the model; missing simulation resources remain warnings where safe.
