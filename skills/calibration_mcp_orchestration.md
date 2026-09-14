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
4. Create the Calibration-MCP project with the provider's **host-visible**
   `runs_dir`, not a container-only path. Use a dedicated, initially empty
   host directory per project: the service counts every
   `<runs_dir>/*/run_record.json` toward its physical-run budget and ledger,
   so a shared provider workspace with earlier runs corrupts both. Bind its
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
   `list_measure_arguments` that every recipe argument exists. If a measure
   default would change something the recipe does not name (for example a
   fuel type), read the model's current value through the provider, pin it,
   and record that as a blackboard assumption. Apply every rung to the same
   staged seed with the provider's seed guard (NLR
   `apply_measure(model_path=<staged seed>, expected_model_sha256=<its host
   hash>)`); the hash of a user-authored file will not match the provider's
   re-serialized bytes. Save each result as a new staged model and record its
   model ID, host path, container path when applicable, hash, provider
   identity, measure/arguments, and predecessor. Take a blackboard checkpoint
   before and after each critical mutation, simulation submission/completion,
   and provider transition.
4. Submit the candidate through the selected provider. Map the provider run ID
   and provider/container run path to the host-visible `runs_dir`; wait for
   canonical `<runs_dir>/<run_id>/run_record.json` and
   `<runs_dir>/<run_id>/run/eplusout.sql` evidence before asking
   Calibration-MCP to record the run. Poll the provider's own status (NLR
   `get_run_status` returns the record under `run`) and verify on the host
   that the record's `run_id` equals its directory name, its status is the
   provider's success value (NLR `success`; EnergyPlus-MCP `completed`), and
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
