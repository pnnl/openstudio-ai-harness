# LBNL Calibration-MCP Integration Contract

OpenStudio AI can optionally configure LBNL Calibration-MCP as the
`bem-calibration` host connector, launched by the separately distributed
`bem-calibration-mcp` command. This integration does not package, register, or
export the former standalone LBNL filesystem skill. Instead, the connected
service remains the authoritative source: the workflow discovers its
`pattern-based-calibration` methodology through `skills/list`, `skills/get`,
and the advertised `skill://pattern-based-calibration/...` resources. The
integration does not proxy the service's tools through `openstudio_ai` or
install its runtime with the OpenStudio AI package.

Calibration-MCP is a domain service: it owns calibration arithmetic, pattern
state, accepted candidates, ledger records, and final reports. OpenStudio AI
remains the parent workflow, blackboard, provenance, and artifact owner.
NLR OpenStudio-MCP (`openstudio-mcp` connection, `nlr_openstudio` provider) is
the preferred compatible OSM mutation/simulation provider under the existing
exclusive-provider policy. The `openstudio_ai` provider route is only its
existing permitted fallback. EnergyPlus-MCP is not part of this integration.

## Connector And Readiness

Calibration-MCP is separately configured by a user or deployment as the
`bem-calibration` host connection. It is intentionally not added to generated
Claude or Codex `.mcp.json` files: these adapters cannot isolate a missing
external stdio server from plugin startup. This keeps the generated plugin
core usable when the prototype service is absent and avoids publishing an
unlicensed or local-checkout runtime dependency. Its tools are never merged
into PNNL's `openstudio_ai` MCP server.

`openstudio-ai doctor` reports separately configured Calibration-MCP and the
optional `bem-calibration-mcp` command as an optional capability. Its absence
never makes `core_ready` true or false: core readiness describes the PNNL
runtime and local OpenStudio requirements only. Install Calibration-MCP using
its own supported distribution and configure the host connection before
relying on its tools. Command discovery is not a version/capability preflight;
the parent workflow records the actual MCP session identity and exposed tool
inventory. Record a service version or content digest only when that live MCP
response exposes it; do not infer one from a filesystem skill or local checkout.

After connecting, the workflow must discover the live Skill-over-MCP catalog
and verify the published resource digests before following the methodology.
If the host cannot expose the advertised skill methods/resources, report the
calibration capability as unavailable rather than silently falling back to a
stale copied skill. This is still Calibration-MCP integration: the small PNNL
routing skill only establishes workflow and provider boundaries; it does not
contain LBNL's calibration methodology.

## Blackboard Identity And Evidence Mapping

Workflow state and artifact `metadata` are extensible, so this contract does
not require a schema migration. Keep the fields structured and preserve the
following distinct identities rather than collapsing them into one `run_id`.

| Record area | Required metadata | Notes |
| --- | --- | --- |
| Workflow | `workflow_id`, `calibration_project_id`, `calibration_connector: "bem-calibration"`, `calibration_domain_service: "lbnl_bem_calibration"`, live-exposed `calibration_service_version`, `calibration_service_digest`, `calibration_tool_inventory` | PNNL workflow ID and LBNL project ID are different lifecycle identifiers. Record service metadata only when the live MCP exposes it. The domain service is never an execution provider. |
| Provider | `execution_provider` (`nlr_openstudio` or documented fallback), `provider_connector` (`openstudio-mcp` or `openstudio_ai`), provider image/endpoint/version | Connection names and provider IDs are deliberately distinct. |
| Model lineage | `model_id`, `model_format`, `host_path`, `container_path` when applicable, `sha256`, `parent_model_id`, `created_by` | A container path such as `/runs/...` is never a host shell path. |
| Run evidence | `provider_run_id`, `calibration_ledger_run_id`, `host_runs_dir`, `provider_runs_dir`, `run_record_path`, `eplusout_sql_path`, SQL/hash evidence | IDs may initially match but must be stored separately. Calibration-MCP consumes the host-visible evidence layout. |
| Compatibility | `openstudio_version`, `energyplus_version`, `weather_path`, `weather_sha256`, `calendar_year`, `bill_electricity_unit`, `bill_gas_unit`, unit-provenance source | Record qualification evidence before a state-changing decision. |
| Calibration report | `calibration_report_path`, `calibration_report_sha256`, `calibration_status`, `termination_basis`, warnings | A final report/hash belongs in PNNL artifacts; Calibration-MCP remains the source of its contents. |

The selected model-execution provider writes physical simulation evidence under
the same host-visible `runs_dir` used to create the Calibration-MCP project.
For an NLR container, record the explicit host-to-container mapping; the
provider may use `/runs`, but Calibration-MCP and PNNL host tools use the host
path. Require canonical `run_record.json` and `run/eplusout.sql` before the
domain service records a candidate.

## Routing And Completion

Before calibration, preflight Calibration-MCP's actual session
identity/version/tool inventory, the chosen provider's capability/version, the
model, meter/evidence availability, bill units, weather, calendar, and the
host/container path mapping. Between critical mutations, simulations,
provider transitions, and report handoff, write a PNNL blackboard checkpoint.
Calibration-MCP never becomes a mutating provider; only one selected execution
provider may mutate an unstaged model phase.

PNNL records decision and provenance patches, while Calibration-MCP records
the calibration project state and ledger. The parent workflow must report an
honest non-converged or unavailable result if capabilities, evidence,
parameters, budget, or the final report do not support convergence.
