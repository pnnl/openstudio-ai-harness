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
   `skill://pattern-based-calibration/...` resources. Verify and record the
   live skill version and resource digests when exposed. Do not substitute a
   local checkout or a separately installed copy when live discovery is
   unavailable. Record service version, content digest, and capability evidence
   only when the live MCP response exposes each value; otherwise record the
   absence.
   Stop if required project, bill-ingestion, meter gate, state, ledger, and
   report operations are not present.
3. Preflight the proposed OSM execution provider and record its connection,
   provider identifier, OpenStudio/EnergyPlus versions, model capability, and
   host/container workspace mapping. For NLR, follow every preflight and
   checkpoint in `delegated-nlr-modeling`.
4. Create the Calibration-MCP project with the provider's **host-visible**
   `runs_dir`, not a container-only path. Bind its returned
   `calibration_project_id` and `calibration_domain_service:
   "lbnl_bem_calibration"` to the PNNL `workflow_id` in the blackboard.
5. Validate bill units, weather identity, calendar/year, model identity, and
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
3. Save a new staged model, validate it, and record its model ID, host path,
   container path when applicable, hash, provider identity, and predecessor.
   Take a blackboard checkpoint before and after each critical mutation,
   simulation submission/completion, and provider transition.
4. Submit the candidate through the selected provider. Map the provider run ID
   and provider/container run path to the host-visible `runs_dir`; wait for
   canonical `<runs_dir>/<run_id>/run_record.json` and
   `<runs_dir>/<run_id>/run/eplusout.sql` evidence before asking
   Calibration-MCP to record the run.
5. Record the ledger outcome through Calibration-MCP, then store both its
   calibration ledger run ID and the provider run ID as separate fields. They
   may share a string today but are not interchangeable identifiers.
6. Use Calibration-MCP for state transitions, accepted-candidate decisions,
   budget accounting, and report finalization. PNNL records the returned
   project/report paths and hashes as artifacts; it does not recompute or
   silently override calibration arithmetic.

## Honest Completion

Only call a calibration result converged when Calibration-MCP's final report
and recorded evidence say so. If a budget, reach gate, provider capability,
unit/calendar check, SQL evidence requirement, or available-parameter list is
exhausted, finalize/record the available evidence and report a non-converged or
unavailable result. Do not call an unsupported Phase-3 diagnostic, an absent
external connector, or a missing final report a successful calibration.

Do not package or register LBNL's former filesystem calibration skill. Load
the authoritative methodology through Calibration-MCP's Skill-over-MCP
resources and use the actual tools exposed by that same configured service.

Use the attached `CALIBRATION_MCP_INTEGRATION.md` reference for the required
blackboard identity mapping and path/provenance fields.
