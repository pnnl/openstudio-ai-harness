# NLR OpenStudio-MCP Production Integration Plan

## Product Decision

OpenStudio AI is the single user-facing plugin and mandatory workflow harness.
NLR OpenStudio-MCP is an optional, preferred execution provider when it is
installed locally and passes preflight. The plugin continues to work without
NLR by using OpenStudio AI's existing MCP tools and skills.

This is a provider integration, not a merger of repositories or a second
unfiltered tool catalog in Claude Code or Codex.

## Provider Selection Policy

| Condition | Modeling provider | OpenStudio AI responsibility |
| --- | --- | --- |
| NLR is configured, healthy, and version-compatible | NLR exclusively for model, measure, simulation, and results operations in that phase | Mandatory blackboard, artifact provenance, learning evidence, and user handoff |
| NLR is not configured, unavailable, or incompatible | OpenStudio AI only | Existing model, simulation, result, SDK, blackboard, and learning workflow |
| NLR cannot express a complex requested operation | Explicit OpenStudio AI SDK phase after recorded evidence and model handoff | SDK documentation, runtime verification, script provenance, validation, and subsequent provider handoff |

The selected provider is recorded before mutation. Two providers must never
modify the same unstaged model. A provider transition creates a new phase and
requires a saved model artifact, content hash, source/destination paths,
version information, and blackboard record.

## End-User Experience

The energy modeler uses the OpenStudio AI plugin normally. They do not need to
choose raw MCP tools or understand container paths. On each workflow, the
plugin determines whether NLR is available:

1. If available, the plugin loads `delegated-nlr-modeling`, initializes the
   blackboard, records the configured shared workspace, and performs NLR
   preflight.
2. If preflight succeeds, NLR performs the requested energy-modeling actions.
   OpenStudio AI records every material decision, NLR run ID, model/result
   artifact, warning, failure, and handoff.
3. If NLR is unavailable, the existing OpenStudio AI workflow proceeds without
   an NLR dependency.
4. If NLR cannot perform a requested complex operation, the plugin records the
   limitation, stages the model at a host-visible path, and uses the reviewed
   OpenStudio AI SDK route. It does not silently mix providers.

## Docker and File Boundary

NLR's Docker image contains its OpenStudio runtime. The OpenStudio AI plugin
does not need to install or execute that runtime for an NLR-owned phase.

NLR provider paths such as `/inputs`, `/runs`, and `/measures` are container
paths. The NLR connection must configure explicit local mounts, for example:

```text
<project>/nlr-workspace/inputs   -> /inputs
<project>/nlr-workspace/runs     -> /runs
<project>/nlr-workspace/measures -> /measures
```

The blackboard records both paths. NLR tools use the container path; host-side
SDK scripts use only the matching local path. A container path must never be
placed directly in a host shell command or script.

## NLR Skill Strategy

NLR has two distinct assets: implementation modules that register MCP tools,
and user-facing workflow guides retrieved through `list_skills` and
`get_skill`. The latter are not automatically installed as native Claude Code
or Codex skills.

### Near-term behavior

The delegated workflow retrieves only the task-relevant NLR guide after
preflight and records the guide name/version in the blackboard. OpenStudio AI
remains the parent workflow and does not bulk-copy NLR guide content into an
agent prompt.

### Migration program

1. Inventory NLR user-facing guides and classify each as:
   - provider-only operational guidance;
   - reusable modeling procedure suitable for a curated plugin skill;
   - reference knowledge that can be summarized with source attribution; or
   - unsafe/unbounded authoring guidance requiring a separate approval gate.
2. Map a curated guide to one OpenStudio AI native skill with a stable plugin
   name, explicit provider applicability, NLR source/version attribution, and
   acceptance tests. Do not migrate whole directories wholesale.
3. Keep provider-only details in NLR and retrieve them dynamically. Migrate
   only user-facing procedures that improve portability when NLR is absent.
4. For custom measures, require NLR `measure-authoring` guidance, live
   `search_api` evidence for non-trivial calls, a representative `test_measure`
   run, and model validation. Generated code remains untrusted candidate
   material until reviewed.
5. Re-evaluate every migrated skill against pinned NLR releases and the
   OpenStudio AI-only fallback workflow.

## Production Adapter Design

The dual-MCP configuration is a development compatibility mode. Production
should add a narrow NLR provider adapter inside OpenStudio AI rather than
registering NLR's entire tool catalog with every host.

Initial adapter operations:

```text
provider_nlr_preflight
provider_nlr_execute_phase
provider_nlr_get_status
provider_nlr_cancel
provider_nlr_import_artifacts
```

The adapter must persist a provider-run record with provider identity/image
digest, NLR/OpenStudio/EnergyPlus versions, NLR run ID, request/response
summary, content hashes, provider and host paths, artifact IDs, raw logs,
status, and timestamps. It should normalize outcomes as completed, failed,
cancelled, unavailable, incompatible, or validation-failed.

## Safety and Reliability Gates

Before remote or multi-user deployment:

- pin the NLR image by digest and maintain a supported-version matrix;
- use isolated execution with least-privilege mounts, no host secrets, resource
  limits, timeout/cancellation, and audited cleanup;
- restrict file access to per-workflow staging roots and validate paths after
  resolving symlinks;
- add authentication, authorization, tenant isolation, and TLS for any HTTP
  deployment;
- recover provider runs after OpenStudio AI restart instead of relying on
  in-memory task state;
- enforce blackboard/artifact checkpoints in the adapter, not only in prompts;
- add contract tests for successful work, NLR unavailability, incompatibility,
  custom-measure failure, timeout/cancellation, restart/recovery, SDK fallback,
  and artifact cleanup.

## Delivery Sequence

1. **Compatibility prototype:** use the delegated skill and dual-MCP local
   configuration; capture the first end-to-end artifact/provenance trace.
2. **Contract:** agree with NLR on version, transport, run-status, artifact,
   error, cancellation, security, and retention contracts.
3. **Adapter:** implement the narrow facade and persistent provider-run model
   behind a feature flag.
4. **Hardening:** add recovery, security, integration tests, pinned images, and
   operational documentation.
5. **Curated skill release:** migrate selected NLR guides with attribution,
   review, fallback behavior, and lifecycle ownership.

## Non-goals

- Replacing the OpenStudio AI plugin or blackboard with NLR.
- Reimplementing NLR tools in OpenStudio AI.
- Exposing raw NLR authoring/code-execution tools to all users by default.
- Assuming a shared in-memory model across processes or providers.
