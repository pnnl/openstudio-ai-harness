# OpenStudio AI Task Planning Meeting

Meeting date: June 27, 2026

Purpose: align the next development tasks for making OpenStudio AI deployable
as a host-agent harness while reducing token cost through targeted SDK and
OpenStudio Standards knowledge.

## Meeting Outcomes

By the end of the meeting, agree on:

- which developer owns runtime distribution and MCP packaging;
- which developer owns SDK/knowledge/token optimization;
- milestone scope for the next 2-3 weeks;
- first acceptance tests for each workstream;
- decisions needed before implementation starts.

## Current Baseline

OpenStudio AI currently has:

- Claude Code plugin export;
- Codex plugin export;
- `openstudio_mcp` package name that avoids shadowing the external `mcp`
  package;
- exported skills, knowledge, instructions, blackboard schemas, and runtime
  learning schemas;
- generated HVAC child skills from one YAML spec per skill plus a shared Jinja
  template;
- manual developer learning pipeline that writes reviewable candidates;
- deterministic tests for adapter export, learning, SDK docs, and MCP smoke
  behavior.

The main deployment gap is that exported `.mcp.json` files still reference the
local source checkout and active Python environment. That is acceptable for
development, but not for a serious distribution package.

## Workstream 1: MCP Distribution And Runtime Packaging

Owner: Developer 1

Goal: make MCP the stable runtime kernel for OpenStudio AI, with Claude Code,
Codex, and future host adapters acting as thin clients.

### Ticket MCP-DIST-01: Define Runtime Package Boundary

Scope:

- define what ships in the installable OpenStudio AI runtime;
- include `openstudio_mcp`, approved measures, SDK index query assets, schemas,
  and future blackboard service;
- define what remains developer-only.

Deliverable:

- package boundary design doc;
- updated package manifest if needed.

Acceptance:

- team can point to one document that says what is runtime, host export,
  developer-only, and user-local state.

### Ticket MCP-DIST-02: Add Installed MCP Entrypoint

Scope:

- add a stable command such as `openstudio-ai-mcp`;
- launch the MCP server through the installed command instead of a repo path.

Target `.mcp.json` shape:

```json
{
  "mcpServers": {
    "openstudio_ai": {
      "command": "openstudio-ai-mcp",
      "args": ["--transport", "stdio"]
    }
  }
}
```

Acceptance:

- MCP starts through the installed entrypoint;
- smoke test verifies startup and at least one MCP tool call.

### Ticket MCP-DIST-03: Add Runtime Mode To Adapters

Scope:

- support `--runtime-mode local|installed`;
- use `installed` for distributable exports;
- preserve `local` for developer debugging.

Acceptance:

- Claude and Codex adapter tests prove `.mcp.json` changes correctly by mode;
- docs explain when to use each mode.

### Ticket MCP-DIST-04: Add Runtime Doctor Command

Command idea:

```bash
openstudio-ai doctor
```

Checks:

- MCP import/startup;
- OpenStudio Python availability;
- EnergyPlus/OpenStudio CLI availability when needed;
- SDK index availability;
- approved measures registry;
- writable runtime workspace;
- future blackboard state path.

Acceptance:

- command returns clear pass/fail output;
- JSON output exists for automation.

### Ticket MCP-DIST-05: Add Version Handshake

Scope:

- MCP exposes runtime version;
- exported plugin records expected runtime version;
- validation warns or fails on version mismatch.

Acceptance:

- adapter validation detects incompatible MCP runtime.

### Ticket MCP-DIST-06: Package SDK Index Runtime Assets

Scope:

- decide package data vs external artifact for SDK index;
- make MCP SDK lookup independent of repo checkout;
- surface clear errors through `doctor`.

Acceptance:

- SDK lookup works from the installed package path.

### Ticket MCP-DIST-07: Package Approved Measures

Scope:

- include `measures/approved`;
- add measure registry manifest;
- validate measure metadata and entrypoints.

Acceptance:

- MCP can list approved measures from packaged runtime;
- tests cover registry loading.

### Ticket MCP-DIST-08: Design Blackboard MCP Tools

Scope:

- design tool contracts before implementation;
- keep parent workflow skills as owners of workflow semantics.

Candidate tools:

- `blackboard_initialize_workflow`
- `blackboard_get_workflow`
- `blackboard_update_state_patch`
- `blackboard_get_phase_state`
- `blackboard_mark_step_complete`
- `blackboard_snapshot`

Acceptance:

- tool contract doc exists;
- JSON request/response examples exist;
- storage and concurrency assumptions are explicit.

### Ticket MCP-DIST-09: Add Export Validation Command

Command idea:

```bash
openstudio-ai validate-export /path/to/exported/plugin
```

Checks:

- plugin manifest;
- `.mcp.json`;
- MCP startup;
- skill folder layout;
- learning schemas;
- absence of developer-only files;
- SDK index reachability;
- approved measure reachability.

Acceptance:

- command validates both Claude and Codex exports.

### Ticket MCP-DIST-10: Define Release Bundle

Scope:

- define installable package or wheel;
- document optional offline bundle;
- include plugin export process;
- include doctor and validation steps.

Acceptance:

- release checklist exists;
- team can reproduce a clean install on another machine.

## Workstream 2: SDK, Standards Knowledge, And Token Optimization

Owner: Developer 2

Goal: reduce token consumption by replacing broad source/document loading with
targeted MCP queries and compact, reviewed knowledge generated from
OpenStudio Standards.

Primary source:

```text
/Users/xuwe123/github/openstudio-standards/lib/openstudio-standards/prototypes/common/objects/Prototype.hvac_systems.rb
```

### Ticket SDK-KB-01: Build HVAC System Inventory

Scope:

- extract supported `model_add_hvac_system` system types;
- capture source line references;
- include aliases and dispatcher behavior where obvious.

Initial systems:

- `PTAC`
- `PTHP`
- `PSZ-AC`
- `PSZ-HP`
- `PSZ-VAV`
- `VRF`
- `Fan Coil`
- `Radiant Slab`
- `Baseboards`
- `Unit Heaters`
- `High Temp Radiant`
- `Window AC`
- `Residential AC`
- `Forced Air Furnace`
- `Residential Forced Air Furnace`
- `Residential Forced Air Furnace with AC`
- `Residential Air Source Heat Pump`
- `Residential Minisplit Heat Pumps`
- `VAV Reheat`
- `VAV No Reheat`
- `VAV Gas Reheat`
- `PVAV Reheat`
- `PVAV PFP Boxes`
- `VAV PFP Boxes`
- `Water Source Heat Pumps`
- `Ground Source Heat Pumps`
- `DOAS Cold Supply`
- `DOAS`
- `DOAS with DCV`
- `DOAS with Economizing`
- `ERVs`
- `Residential ERVs`
- `Residential Ventilators`
- `Evaporative Cooler`
- `Ideal Air Loads`

Acceptance:

- compact JSON inventory exists under `sdk_index/index/`;
- inventory includes system name, source function, branch location, and called
  lower-level function where available.

### Ticket SDK-KB-02: Build Standards Function Trace Graph

Scope:

- map each system type to helper calls;
- include plant loop helpers and lower-level HVAC builders;
- preserve source references.

Acceptance:

- graph exists under `sdk_index/graph/`;
- VAV, PSZ, DOAS, fan coil, and water-source heat pump traces are covered.

### Ticket SDK-KB-03: Create Token-Light HVAC Knowledge Cards

Each card should include:

- system type;
- when used;
- required inputs;
- fuel compatibility;
- created OpenStudio objects;
- lower-level functions;
- common failure modes;
- validation checks;
- source references.

Acceptance:

- cards exist under `knowledge/openstudio_standards_hvac/`;
- cards are concise and retrieve one system at a time.

### Ticket SDK-KB-04: Add MCP Queries For Standards HVAC Knowledge

Candidate tools:

- `standards_hvac_list_systems`
- `standards_hvac_get_system`
- `standards_hvac_trace_system`
- `standards_hvac_find_by_component`

Acceptance:

- host agents can retrieve one targeted system card without loading the full
  Standards source file.

### Ticket SDK-KB-05: Build SDK Method Micro-Index

Scope:

- class;
- method;
- signature;
- return type;
- units;
- common traps;
- examples;
- source URL or file reference.

Priority lessons:

- surface azimuth values are radians, not degrees;
- optional values require `is_initialized`;
- object conversion patterns such as `to_X` and `get`;
- model load/save patterns through `VersionTranslator`.

Acceptance:

- compact method index exists;
- MCP can answer method-specific questions without broad context loading.

### Ticket SDK-KB-06: Add Retrieval Policy To Harness Instructions

Policy:

1. Query HVAC system inventory first.
2. Retrieve one system card.
3. Retrieve only needed SDK methods.
4. Load only the child skill for the current phase.
5. Load broad docs only after targeted lookup fails.

Acceptance:

- host instructions include the retrieval policy;
- tests confirm exported instructions include it.

### Ticket SDK-KB-07: Add Standards Knowledge Generation Script

Scope:

- parse `model_add_hvac_system`;
- extract system branches and helper calls;
- write candidate inventory/cards;
- do not auto-promote generated content.

Acceptance:

- script writes candidate assets for review;
- generated assets include source references.

### Ticket SDK-KB-08: Produce VAV Golden Card

Scope:

- cover `VAV Reheat`, `VAV No Reheat`, and `VAV Gas Reheat`;
- link to `model_add_vav_reheat`;
- connect to existing parent/child VAV skills.

Acceptance:

- reviewed VAV card exists;
- eval confirms agent retrieves VAV card instead of loading broad source.

### Ticket SDK-KB-09: Produce PSZ And DOAS Cards

Scope:

- `PSZ-AC`
- `PSZ-HP`
- `PSZ-VAV`
- `DOAS`
- `DOAS with DCV`
- `DOAS with Economizing`

Acceptance:

- reviewed cards exist;
- MCP retrieval tests cover each system family.

### Ticket SDK-KB-10: Add Token Budget Evaluation

Eval cases:

- add VAV reheat system;
- add PSZ-AC;
- add DOAS with DCV;
- explain fan coil system creation.

Metrics:

- number of loaded context files;
- estimated token count;
- targeted card retrieval success;
- broad source loading avoided.

Acceptance:

- eval report shows token savings against baseline broad-context behavior.

## Milestone Proposal

### Milestone 1: Foundation

Runtime:

- `MCP-DIST-01`
- `MCP-DIST-02`
- `MCP-DIST-03`

Knowledge:

- `SDK-KB-01`
- `SDK-KB-02`
- `SDK-KB-08`

### Milestone 2: Validation And Retrieval

Runtime:

- `MCP-DIST-04`
- `MCP-DIST-06`
- `MCP-DIST-09`

Knowledge:

- `SDK-KB-04`
- `SDK-KB-05`
- `SDK-KB-06`

### Milestone 3: Release And Expansion

Runtime:

- `MCP-DIST-05`
- `MCP-DIST-07`
- `MCP-DIST-08`
- `MCP-DIST-10`

Knowledge:

- `SDK-KB-03`
- `SDK-KB-07`
- `SDK-KB-09`
- `SDK-KB-10`

## Decisions Needed In Meeting

1. Should the first runtime package be an installable Python package, a vendored
   plugin bundle, or both?
2. Should SDK index ship as package data or as a separate artifact?
3. What OpenStudio installation assumptions are acceptable for users?
4. Should blackboard MCP tools be designed now but implemented after packaging?
5. Which HVAC systems are highest priority after VAV, PSZ, and DOAS?
6. What token budget target should the SDK/knowledge retrieval eval enforce?

## Recommended Immediate Assignments

Developer 1:

- start with `MCP-DIST-01`, `MCP-DIST-02`, and `MCP-DIST-03`;
- produce a packaged-entrypoint proof by the next checkpoint.

Developer 2:

- start with `SDK-KB-01`, `SDK-KB-02`, and `SDK-KB-08`;
- produce the first HVAC inventory, trace graph, and reviewed VAV card by the
  next checkpoint.

## Success Criteria

The next phase is successful when:

- Claude Code and Codex exports can point to a stable MCP runtime command;
- MCP can validate its local runtime environment;
- host agents can retrieve targeted HVAC and SDK knowledge through MCP;
- VAV workflow context loading is measurably smaller than broad source loading;
- generated knowledge stays review-gated before becoming trusted runtime
  content.
