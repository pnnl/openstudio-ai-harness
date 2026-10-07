# Dual-MCP routing evals (optional)

These evals run the standalone automa-ai agent with two MCP servers connected at once:

- the harness MCP (`openstudio_ai_mcp`)
- NLR openstudio-mcp (`openstudio-mcp`)

The agent's telemetry trace gives the ordered tool calls. Each eval checks which
server handled the work. The policy under test is the NLR Provider Gate in
`prompts/openstudio_agent.md`: when NLR is available, it must do the model,
simulation and results work.

The openstudio-mcp team can use this to check that their changes still route correctly.
Core harness installs and unit tests do not need any of this.

## Prerequisites

1. **NLR openstudio-mcp** cloned as a sibling (`../openstudio-mcp`) with its own
   venv (`uv sync`). You also need OpenStudio 3.11.0 on `PATH`. See the top-level
   README.
2. **Sandbox staged** once:
   ```bash
   scripts/start_openstudio_mcp.sh --setup
   ```
3. **Standalone env with the `eval` extra.** This installs deepeval, which is only
   needed for `--deepeval`:
   ```bash
   uv sync --project standalone --extra eval
   ```
4. **LLM API key** in `.env`: `OSSTD_LLM_API`. The model name and base URL come
   from `standalone/openstudio_agent.yaml`, the same spec the standalone UI uses.

## Running

Start NLR over HTTP in one terminal:

```bash
scripts/start_openstudio_mcp.sh --http 10220
```

Run the suite from the repo root in another:

```bash
uv run --project standalone python -m standalone.evals.run smoke                # deterministic checks only
uv run --project standalone python -m standalone.evals.run smoke --deepeval     # + DeepEval ToolCorrectness (ordered)
uv run --project standalone python -m standalone.evals.run smoke --cases nlr_simulation_provider_001
uv run --project standalone python -m standalone.evals.run smoke --repeat 5     # pass rate over 5 runs per case
```

The first argument (`smoke` above) is a run name. It only picks the output
folder; every run starts from a fresh agent and harness workspace.

Skill routing is an LLM decision, so it can vary between runs of the same case.
Use `--repeat` to measure a pass rate instead of relying on one run.

How the runner works:

- It starts the harness MCP in-process. The harness workspace and learning DB go in
  a temp dir, so your local state is not touched.
- It connects to NLR at `NLR_OPENSTUDIO_MCP_HOST:NLR_OPENSTUDIO_MCP_PORT`
  (default `127.0.0.1:10220`). If NLR is not reachable, it exits with code 2.
- It copies the case fixtures into `.openstudio_mcp_sandbox/inputs/`.
- It renames MCP tools to `mcp__<server>__<tool>` for the run, the way Claude
  Code presents them, so the agent can tell which server owns each tool.

## What the agent sees

`standalone/agent.py` builds the agent spec. It differs from the YAML in two ways
that matter for routing:

- **NLR server.** It is added only when `NLR_OPENSTUDIO_MCP_PORT` is set. The
  runner sets it for you.
- **Skill catalog.** automa-ai's `load_skill` does not list skills to the model,
  while Claude Code and Codex show every skill's name and description. To match
  them, `agent.py` appends an "Available Skills" list, built from each skill's
  front matter (`name:` and `description:`), to the system prompt. It also
  registers each front-matter name as a `load_skill` alias, since automa-ai
  resolves skills by file name only (e.g. `delegated-nlr-modeling` loads
  `skills/delegated_nlr_modeling.md`).

## Outputs

For each case, the runner writes to `outputs/evals/<run_name>/<case_id>/`, or to
`<case_id>/rep_<n>/` when `--repeat` is greater than 1:

- `trace.jsonl`: automa-ai telemetry
- `result.json`: checks, the ordered tool timeline with a provider tag on each call,
  and the final answer

It also writes `summary.json` for the whole run. With `--repeat`, it prints a
per-case pass rate such as `nlr_simulation_provider_001: 4/5 passed`. The exit code
is 0 only if every run passes.

When a run fails, check the first `load_skill` call in its timeline. A failing run
typically loads a harness-only skill such as `simulate` or `hvac_sizing_assistant`
instead of `delegated-nlr-modeling`.

## Cases

Cases live in `cases/nlr_routing.json`:

| field | meaning |
|---|---|
| `prompt` | Agent prompt; `{input_dir}` expands to the NLR inputs dir |
| `inputs` | Files copied from `tests/fixtures/` into the inputs dir |
| `required_tools` | `{"tool", "provider"}` entries; each must be called at least once. `provider` is `nlr`, `harness`, or `agent` |
| `forbidden_tools` | Globs that must never be called, e.g. `sim_*` |
| `expected_tools_ordered` | Expected sequence for DeepEval ToolCorrectness (only with `--deepeval`) |

Tool names in cases are bare (`run_simulation`, not
`mcp__openstudio-mcp__run_simulation`). Scoring strips the server prefix from
each traced call and tags it by server: `openstudio-mcp` is `nlr`,
`openstudio_ai_mcp` is `harness`, and unprefixed built-ins such as `load_skill`
and `run_python` are `agent`.

The starter case `nlr_simulation_provider_001` asks for an annual simulation and the
site EUI. It passes when NLR `run_simulation` is called and no harness `sim_*` tool is.

## Tests

None of these tests need an LLM or NLR:

```bash
uv run --project standalone pytest standalone/tests/test_nlr_routing_checks.py  # eval scoring
uv run --project standalone pytest standalone/tests/test_automa_ai.py           # skill aliases and catalog
```
