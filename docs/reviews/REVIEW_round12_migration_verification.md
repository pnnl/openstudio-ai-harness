# Round 12: verification of J1–J4 (phase 6a plant migration)

Scope: working tree on top of `6a5c16d`. That covers `common/coil_migration.py`,
`tests/test_water_coil_migration.py` and the updated docs.

Verdict: all four findings are fixed, and I found no new issues.

**J1 (fixed): emptying the source plant is now reported.** The impact now shows
three things:

- `source_plant_remaining_coil_count`;
- `source_plant_remaining_demand_equipment_count`, which excludes pipes, pumps
  and connectors;
- `source_plant_will_be_unserved`.

When no coils remain, a warning says that the supply equipment, pumps and
autosizing stay in place. It also states accurately that the HVAC remover does
not delete plants yet, rather than pointing the user at a deletion it can't do.

Other demand equipment, such as a heat exchanger, is counted separately, so a
plant that is still in use is not called unserved. My updated probe P1 confirms
the count is 0 and the warning appears for the cooling-only CHW plant. The
saved output still keeps the plant.

**J2 (fixed): sizing parity is now proven with paired native runs.**
`test_native_matched_migration_retains_sizing` works like this:

- The destination's design supply and delta match the source exactly.
- The unrelated destination coil is removed before either run, so the two
  models differ only by the reviewed move.
- Both models are sized, and the test asserts that capacity, UA (or air flow)
  and water flow match within 1e-9 relative tolerance.
- CAV heating must be above 10 kW, which avoids relying on the near-zero VAV
  heating case.

The design is right. The tests skip here because there is no CLI, so I am relying
on your native run for the numbers. The before run also contains an unserved
plant without Severe errors, which supports the J1 default.

**J3 (fixed): the OpenStudio behaviour migration relies on is now a canary test.**
`test_pinned_sdk_branch_removal_and_attachment_controller_lifecycle`, for heating
and cooling, deliberately uses whichever `openstudio` is installed rather than
the 3.11-only fixture. It checks four things:

- branch removal clears the coil's controller and deletes it;
- the coil itself survives;
- attachment creates a new controller that points at the coil.

Each failure message names the installed OpenStudio version and the assumption
that changed. It ran and passed here on 3.11.0.

**J4 (fixed): fixed water values that don't match the destination are reported.**
These are the fixed cooling inlet-water value and the inlet/outlet water ratings
under heating `NominalCapacity`. The impact now lists
`retained_water_rating_mismatches`, with the retained and destination values.
The warning names `openstudio-water-coil-editor` as the explicit follow-up, and
the values themselves are left unchanged.

An autosized cooling inlet, or heating metadata under the UA method, correctly
produces no warning. The warning carries through to the apply report.

## Tests

I ran the doc's focused commands plus every earlier suite file in the Linux
sandbox (OpenStudio 3.11.0 wheel, no CLI): **467 passed and 50 skipped**. The
skips are native tests, including the new parity runs. `round11_probes_test.py`
has been updated: P1 now checks the J1 fix, and P2 (the canary) still passes.

## Housekeeping

- **Staging:** only `coil_migration.py` and the migration test file are staged.
  The `water_coil.py`, schema, manifest, skill and doc edits are still unstaged.
  Stage them together before committing.
