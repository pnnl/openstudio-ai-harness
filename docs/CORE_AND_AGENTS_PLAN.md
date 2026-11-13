# OpenStudio SI core and agents migration plan

OpenStudio SI will provide a shared engineering runtime. Labs will be able to publish and update specialist agents against a supported core interface on their own release schedules. Codex and Claude Code will consume host-specific packages generated from the same contribution source.

## Starting point

- The harness checkout on `main` contains an in-progress rename. Its package and CLI now use `openstudio-si`, its Python MCP module is `openstudio_si_mcp`, and exported host configs use the `openstudio_si` MCP server key. The rename also reaches repository URLs, plugin identifiers, runtime configuration, and local workspace paths.
- The local marketplace checkout on `rename-openstudio-si` still contains generated OpenStudio AI exports from the previous release. The renamed harness workflow targets `pnnl/openstudio-si-plugins` and removes the legacy Claude export during sync. The checkout alone does not establish which renamed URLs or packages are live.
- The previous marketplace release shows `0.4.1`, MCP contract `6.0`, and OpenStudio SDK `3.11.0`. The previous release is the comparison baseline. The first OpenStudio SI release targets `0.4.2` with contract `6.0` and SDK `3.11.0`.
- The harness already owns engineering sessions, model lineage, durable jobs, artifacts, workflow state, and approvals. The diagnostic-specific `sim_diagnose` and `results_plausibility` tools are listed as future work.

Sources are the [release guide](RELEASE.md), [harness handoff](../HANDOFF.md), [marketplace publisher](../.github/workflows/publish-plugins.yml), and [host exporter](../adapters/runtime_helpers.py).

## 1. Complete and verify the OpenStudio SI rename

1. Inventory the current rename diff and record each old and new public identifier. Cover PyPI, executable names, Python imports, MCP server keys, plugin and marketplace IDs, repository links, environment variables, local storage paths, and generated install commands. Mark deliberate legacy references explicitly.
2. Document OpenStudio SI as a fresh installation. Tell users with OpenStudio AI to disable the old plugin or MCP entry before enabling OpenStudio SI. Explain that existing workspaces, saved sessions, and project instructions do not migrate automatically. Leave old files in place.
3. Build the renamed wheel and generate both marketplace exports from the same harness revision. Verify the package and contract versions, installer and doctor output, plugin metadata, and MCP connection. Test a clean installation in both hosts and open a new engineering session with job artifacts.
4. Coordinate the repository rename and marketplace publishing permissions. The maintainer confirmed the PyPI name is available and the publishing credential is ready. Publish the harness release, merge the generated marketplace export, and verify the installation links before posting the announcement on the GitLab page for the marketplace.

**Exit check.** A fresh install works on both hosts, the harness and marketplace advertise matching versions, and the GitLab announcement links to working installation instructions.

## 2. Define the smallest core contract the pilot needs

1. Trace an existing session and failed job through current MCP operations. Identify how a consumer can resolve job status, read retained simulation logs, and record a structured finding against the session. Verify tool behavior and evidence references before adding MCP methods.
2. Publish a narrowly scoped contract for those operations. Define required inputs, expected outputs, artifact references, error cases, and version compatibility. Keep model-change approvals, execution-provider choice, and authoritative session writes with the core. Apply the existing NLR selection rules for workflows that invoke an execution provider.
3. Verify a fixture through the declared interface in CI. Cover an accessible log, a missing or expired artifact, and an unsupported core version. Exercise the core’s read and finding-write behavior directly so host behavior can be tested separately.

**Exit check:** A consumer using the documented interface can read the failed-run evidence and persist a finding without reading SQLite directly or depending on provider-local file paths. [Session tools](../openstudio_si_mcp/tools/session.py) · [NLR integration](NLR_INTEGRATION_PLAN.md)

## 3. Package the first lab-owned agent

1. Create one pilot contribution outside the harness source tree. Use a canonical `AGENTS.md`, an `agent.yaml` manifest, and a fixture with expected findings. Start the manifest with a namespaced ID, owning lab or maintainer, agent version, supported core interface versions, declared MCP tools, and entry point.
2. Use a shared validator and exporter to generate the supported Codex and Claude Code entry points from the canonical profile. Treat the tool list as a requirement for compatibility. Verify which capabilities each host can enforce and keep operation-level authorization in the core. Start the pilot with the existing MCP operations.
3. Make the package independently releasable. Have the core team maintain the contribution template, compatibility checks, and curated catalog. Have the lab maintain its profile, fixtures, domain claims, and release tags. Catalog entries should point to a reviewed, pinned agent version.

**Exit check:** Build and validate the same agent source for both hosts. Install it alongside an existing core, then publish or simulate a second agent version without rebuilding or releasing that core. [Scientific Agents contribution pattern](https://github.com/K-Dense-AI/scientific-agents/blob/main/CONTRIBUTING.md#file-layout) · [Existing OpenStudio SI exporter](../harness/asset_manifest.py)

## 4. Run the simulation diagnostics pilot

1. Use one failed EnergyPlus run. Give the agent the session ID and job ID. Ask it to locate `eplusout.err` and record the relevant evidence, a diagnosis or bounded hypothesis, its uncertainty, and the next check or proposed repair. Keep the pilot workflow read-only on models.
2. Evaluate the same fixture through both host packages. Check that the finding cites the correct job and log evidence, distinguishes observed errors from inferred causes, and can be reopened from the engineering session. Check that a missing log yields an explicit evidence gap.
3. Ask a lab maintainer to change the profile, run the validator, release the new version, and submit it to the catalog. Record any step that needs a harness code change or core maintainer intervention.

**Exit check:** Both hosts produce a qualifying finding on the same fixture, and the lab can update the agent independently. Use the pilot results to decide whether to add warning-heavy and implausible-results cases and which interfaces are ready for a second lab.

## Decisions needed before implementation

- **Rename cutover.** Confirm the repository rename timing, marketplace publishing permissions, and the exact GitLab page for the announcement.
- **Pilot ownership.** Identify the lab that will maintain the diagnostic agent and the core maintainer who will sign off on the interface.
- **First distribution.** For the pilot, use a lab-owned package and a core-curated catalog entry. Decide whether the catalog and build tooling warrant a separate repository after the first independent release.
