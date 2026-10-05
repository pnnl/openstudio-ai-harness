---
name: calibration-mcp-orchestration
description: Coordinate measured-bill calibration through the optional LBNL Calibration-MCP while preserving OpenStudio AI workflow ownership and provider boundaries.
---

# Calibration-MCP Orchestration

Use this PNNL-owned routing skill for a measured-bill calibration request only
when the optional `bem-calibration` connector is available. It coordinates the
LBNL domain service with one selected model-execution provider; it does not
copy or register the former standalone LBNL calibration skill, or make the
Calibration-MCP service a model editor. The authoritative methodology is
discovered from the connected service through its Skill-over-MCP interface.

## Service And Provider Boundaries

- `bem-calibration` is the host connector name. `lbnl_bem_calibration` is the
  stable blackboard domain-service identity, never an `execution_provider`.
  Its executable is `bem-calibration-mcp`. It owns calibration arithmetic, pattern state,
  accepted candidates, the calibration ledger, and final reports.
- `openstudio-mcp` is the optional NLR host connection; `nlr_openstudio` is its
  stable execution-provider identifier. When compatible, load
  `delegated-nlr-modeling` and use it as the exclusive OSM mutation,
  simulation, and result provider for that phase.
- `openstudio_ai` is PNNL's local MCP. It retains blackboard, artifact,
  provenance, and parent-workflow ownership. Its existing OpenStudio route is
  the fallback only when the delegated-NLR policy permits it.
- Never ask Calibration-MCP to edit an OSM, submit a simulation, or substitute
  its results for provider evidence. Do not connect EnergyPlus-MCP in this
  workflow.

## Required Preflight

1. Initialize or read the PNNL blackboard workflow. Record the workflow ID,
   connector name, and all existing provider/model lineage before starting a
   calibration project.
2. Inspect the actual `bem-calibration` MCP session identity/version and tool
   inventory. Use its advertised `skills/list` and `skills/get` methods to
   discover `pattern-based-calibration`, then load its manifest-backed
   `skill://pattern-based-calibration/...` resources. Call `skills/list`
   directly: the service may not advertise the skills extension in its
   `initialize` capabilities. Verify and record the live skill version and
   resource digests when exposed. Do not substitute a local checkout or a
   separately installed copy when live discovery is unavailable. Record the
   session's `serverInfo.name` and `serverInfo.version` verbatim; the service
   may expose an empty version, which is recorded as absent, never inferred.
   Record content digest and capability evidence only when the live MCP
   response exposes each value.
   Stop if required project, bill-ingestion, meter gate, state, ledger, and
   report operations are not present.
3. Preflight the proposed OSM execution provider and record its connection,
   provider identifier, OpenStudio/EnergyPlus versions, model capability, and
   host/container workspace mapping. For NLR, follow every preflight and
   checkpoint in `delegated-nlr-modeling`. Take the provider version from its
   own version tool (NLR `get_versions.openstudio_mcp`, `openstudio`,
   `openstudio_cli`), not from `serverInfo.version`, which reports the MCP
   framework. When the provider reports no EnergyPlus version, read it from
   the first canonical `eplusout.sql`/`eplusout.err` and record it before any
   candidate is scored.
4. Create the Calibration-MCP project with `runs_dir` set to the **host**
   folder mounted at the provider's run root, not a container-only path and
   never a new empty folder. Read the returned `probe_file` through the
   provider's `read_file` and pass its code to `confirm_runs_dir` before any
   simulation. Then name every simulation `run_simulation(name="<run_tag>-...")`:
   the service counts only tagged runs toward the project's budget and
   ledger, so other chats' runs in the same run root stay out. Bind its
   returned `calibration_project_id` and `calibration_domain_service:
   "lbnl_bem_calibration"` to the PNNL `workflow_id` in the blackboard.
5. Stage the incoming model through the selected provider before the baseline
   (for NLR, load it and save a copy under the provider's run root). Record
   that provider-serialized copy as the staged seed with its host path,
   container path, host hash, and the user's file as its parent. Run the
   service's `check_model_meters` and `check_measure_reach` gates against the
   staged seed, not the user's original file: the service binds those gates
   to the baseline model hash and refuses to initialize state from a mismatch.
6. Validate bill units, weather identity, calendar/year, model identity, and
   the provider's ability to produce canonical monthly facility electricity and
   gas SQL evidence. Do not continue from a unit, calendar, version, or path
   mismatch.

## Loop And Checkpoints

1. Let Calibration-MCP create/inspect domain state and return the next
   calibration decision or recipe. Record that decision and its source in the
   PNNL blackboard before a mutation.
2. Select exactly one mutating provider for the staged model. The domain
   service is never that provider. Do not let NLR and `openstudio_ai` mutate
   the same unstaged model.
3. A Calibration-MCP recipe names an audited measure and its arguments; it
   never delivers code. Stage the measure library once per deployment
   (`stage_measures`) into the host directory the provider mounts as
   `/inputs/measures`, resolve the directory through the provider (NLR
   `find_measure` → `selected_measure.measure_dir`), and confirm with
   `list_measure_arguments` that every recipe argument exists. Request the
   recipe with `project_id`: for `HE`, `COP`, `FAN`, `HEAT-STP`, and
   `COOL-STP` it carries the project's pass-1 soft limits as `min_val` and
   `max_val`; pass them verbatim and never choose limits. If a measure
   default would change something the recipe does not name (for example a
   fuel type), read the model's current value through the provider, pin it,
   and record that as a blackboard assumption. Apply every rung to the same
   sweep seed, never cumulatively. At the start of each sweep, read
   `calibration_state.current_best_model_path` and
   `current_best_model_sha256`; freeze that committed model as this sweep's
   seed in the blackboard. After `commit_sweep`, refresh both fields before
   selecting or preparing another parameter. The initial provider-staged
   baseline is the seed only until a candidate is committed. Reload the
   frozen sweep seed through the
   provider immediately before each `apply_measure` (NLR `load_osm_model`
   then `apply_measure`, which acts on the provider's in-memory model), and
   record the candidate hash and its seed hash on the host. Before submitting
   each candidate, verify its saved
   seed hash equals the frozen sweep seed hash and the service's current-best
   hash. Stop on a mismatch; never submit or record it as a valid candidate.
   When the provider exposes a seed guard (some NLR builds
   accept `apply_measure(model_path=<sweep seed>,
   expected_model_sha256=<its host hash>)`), pass the sweep seed's host
   hash; the hash of a user-authored file will not match the provider's
   re-serialized bytes. Save each result as a new staged model and record its
   model ID, host path, container path when applicable, hash, provider
   identity, measure/arguments, and predecessor. Take a blackboard checkpoint
   before and after each critical mutation, simulation submission/completion,
   and provider transition.
4. Submit the candidate through the selected provider, or the whole prepared
   ladder at once (see Ladder Batching And Concurrency). Map the provider run ID
   and provider/container run path to the host-visible `runs_dir`; wait for
   canonical `<runs_dir>/<run_id>/run_record.json` and
   `<runs_dir>/<run_id>/run/eplusout.sql` evidence before asking
   Calibration-MCP to record the run. Wait with Calibration-MCP
   `wait_for_runs`, which reads those records on the host. NLR
   `get_run_status` remains a single-run diagnostic (it returns the record under `run`).
   Verify on the host that the record's `run_id` equals its directory name,
   its status is the provider's success value
   (NLR `success`; EnergyPlus-MCP `completed`), and
   the SQL holds twelve monthly values for both facility meters. Provider
   measure-application directories carry no `run_record.json` and are not
   physical simulations.
5. Record the ledger outcome through Calibration-MCP, then store both its
   calibration ledger run ID and the provider run ID as separate fields. They
   may share a string today but are not interchangeable identifiers. A
   candidate record currently requires the placeholder `decision="rejected"`;
   `commit_sweep` is the only action that marks a winner `selected`. Check
   that the returned ledger entry's `kind` equals the requested kind: `ok:
   true` alone is not acceptance. A failed or mis-kinded record stops the
   loop and is recorded as a failure; never re-simulate a rung to retry a
   ledger write, because every physical run consumes the service budget.
6. Use Calibration-MCP for state transitions, accepted-candidate decisions,
   budget accounting, and report finalization. PNNL records the returned
   project/report paths and hashes as artifacts; it does not recompute or
   silently override calibration arithmetic.

## Ladder Batching And Concurrency

Rungs of one sweep are independent work: every candidate starts from the same
frozen sweep seed, Calibration-MCP records each run separately, and `commit_sweep`
only needs the complete set. Execute a ladder as a **batch**, not as N
sequential submit-wait-record cycles. In the 2026-09-15/16 synthetic-retail
project each EnergyPlus run took ~10 s but rungs were spaced 60-90 s apart and
none of 128 runs overlapped: more than 85 % of wall time was orchestration
waiting, and the provider's `max_concurrency` of 2 was never used.

1. Ask `sweep_progress` for this selection's `expected_values` and
   `bound_evidence` before touching the model. For SHW, the service may
   exclude increasing percentage rungs after every water heater reaches its
   pinned `max_eff=1.0` cap. Preserve the returned seed hash, starting
   efficiencies, and excluded values in the blackboard; do not simulate
   excluded rungs or treat a repeated result as a new candidate. If the
   service returns `at_bound: true` with no feasible rung, stop and report
   that selection as blocked; do not fabricate a complete sweep. Budget the
   returned feasible ladder:
   `calibration_progress(needed=<rung count>)` must return
   `can_start_batch: true`. Never start a partial sweep.
2. Read the provider's concurrency (NLR `get_server_status.max_concurrency`)
   and record it. If it is 1, tell the user that raising
   `OSMCP_MAX_CONCURRENCY` (NLR docker env; Claude Desktop config requires a
   restart and a new chat) will shorten sweeps, and let the user change it;
   never edit host MCP configuration yourself. Batching still helps at 1,
   because the provider queue removes the per-rung waiting gap.
3. Prepare phase (serial; this is the only provider constraint): for each
   rung, reload the frozen sweep seed, `apply_measure`, save the candidate to its
   own distinct path, hash it on the host, and record its lineage. Then
   call Calibration-MCP `validate_candidate` on the saved model; never submit
   a candidate whose validation returns `simulate: false`. Wait for each
   validation result before that rung's submission: never send
   `validate_candidate` and `run_simulation` in the same parallel batch. Validate the first
   rung before preparing the rest: a `failure_kind: "no_op"` there means the
   measure cannot reach this model, so close the parameter with
   `mark_unresolvable` instead of simulating the ladder. An `at_soft_limit`
   or `beyond_soft_limit_stop` result ends the ladder at that rung: do not
   prepare or simulate later rungs; record the earlier ones and commit. The
   provider's single in-memory model is why *preparation* is serial; it is
   not a reason to serialize the simulations. One blackboard checkpoint
   before the first apply and one after the last save satisfy the
   critical-mutation checkpoint rule for the ladder.
4. Submit phase: call `run_simulation(osm_path=<candidate>,
   name="<run_tag>-<parameter>-<value>")` for every
   prepared candidate without waiting between calls; the provider queues runs
   beyond `max_concurrency`. Record every provider run ID in one blackboard
   patch as `active_ladder` (a list of `{parameter, value, model_path,
   sha256, provider_run_id, status}`), not as a single `active_candidate`.
5. Wait phase: wait for the *set* of runs, not one run to completion at a
   time. Call Calibration-MCP `wait_for_runs(project_id, run_ids=<every
   provider run ID in active_ladder>)` once. It returns when every run has
   finished, or after `max_wait_s` with `pending_run_ids`; call it again with
   those. Do not sleep a fixed interval or poll `get_run_status` per run: the
   provider's once-per-minute guidance governs polling the provider and does
   not apply to this host-side wait. Treat `possibly_stuck` as a prompt to
   read the provider's run logs, not as permission to cancel or rerun.
6. Verify and record phase: apply the step-4 evidence checks to each completed
   run, then `record_run` each one (any order) and check `kind` on every
   response. One failed run neither blocks recording the others nor is
   re-simulated; record it as a failure and let the service's sweep rules
   decide. Then `commit_sweep`, with one checkpoint after the last record and
   one after the commit.
7. Do not run two *sweeps* concurrently: the next parameter's seed is the
   current committed best model after the previous sweep (the winner if one
   was adopted, or the unchanged incoming model otherwise). Read and verify
   the new seed path and hash from Calibration-MCP state before preparing any
   new rung. Do not interleave rungs of two
   projects on one provider session; its loaded model is shared state.

## Honest Completion

Only call a calibration result converged when Calibration-MCP's final report
and recorded evidence say so. `finalize_report` refuses while the service's
termination basis is still the pattern loop: a committed sweep winner without
a terminal basis is progress, not completion. Record the committed
current-best run and model and report the calibration as in progress. If a
budget, reach gate, provider capability, unit/calendar check, SQL evidence
requirement, or available-parameter list is exhausted, finalize/record the
available evidence and report a non-converged or unavailable result. Do not call an unsupported Phase-3 diagnostic, an absent
external connector, or a missing final report a successful calibration.

Do not package or register LBNL's former filesystem calibration skill. Load
the authoritative methodology through Calibration-MCP's Skill-over-MCP
resources and use the actual tools exposed by that same configured service.

Use the attached `CALIBRATION_MCP_INTEGRATION.md` reference for the required
blackboard identity mapping and path/provenance fields.
