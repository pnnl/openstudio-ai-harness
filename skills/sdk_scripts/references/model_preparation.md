# Stable working-copy preparation

All bundled planners use the pinned OpenStudio 3.11.0 loader before planning.
Older OSMs return `requires_preparation` with source/target versions and the next
operation, without candidates or a ready plan. Newer OSMs are rejected. Current
OSMs are loaded twice by default; all model-object handles must match exactly.
The guard costs about one extra model load; absolute overhead scales with model
size. The internal `check_stability=False` option is for explicit preparation and
measurement, not an agent workaround. No classes or handles are ignored.

Run `scripts/prepare_model.py --input <absolute-original.osm> --output
<absolute-new.osm> --report <absolute-new.json>` through the doctor-verified CLI.
Preparation alone may translate an older OSM. It resolves companions against the
original model/workflow location, stages them with the existing packager, saves
current format, and verifies all handles and raw object fields after independent
reloads. Original and companion hashes are checked again before exclusive
publication. It never overwrites a source, model output, companion directory or
report. Invalid current air- or plant-loop assignment-list references fail clearly;
preparation cannot repair arbitrary damaged models.

A successful report has `status: prepared`, source/target versions, input/output
paths and SHA-256 hashes, bounded translator warning/error counts and messages,
`object_changes` counts by type, validation results, companion paths, and
`lineage.source` / `lineage.prepared` records. Generated/removed inventory counts
compare stored handles with translated model-object handles; historical metadata
such as OS:Version may leave that inventory. `refactored_by_type` counts translator
repair/refactoring events, which may include several events for one object.
These counts describe translation, not semantic equivalence. Type lists are
capped at 24 categories plus an `other_types` total; translator messages at 8 per
severity and 240 characters each.

Apply `state_patch` through workflow state's merge operation. Its
`model_preparation` map is keyed by output SHA-256 and retains original → prepared
lineage without replacing past entries. Keep the model and same-stem companion
folder together. Honor `requires_companion_workflow` for external CSV files;
`companion_readiness` only describes packaged resources, not runnable physics.

Re-inventory and re-preflight the returned `output_model_path`. Require the
owning operation's fresh ready plan and review its assumptions as usual. Never
reuse a blocked plan or write an ad hoc normalizer. If input is already current
and handle-stable, status is `already_current`: it returns the input path/hash
and writes no new model or companions (only the requested JSON report).
Preparation makes no byte-level or semantic no-op claim.

Apply retains exact source hashes, complete reviewed/fresh report equality,
cascade and snapshot checks. A mismatch reports at most 12 differing JSON paths
(up to 180 characters each), categorized as stale source, handle churn, changed
value/type/structure/length. It prints no differing values or full snapshots.
