# Interop evals: openstudio-ai plugin + your MCP server, in real Claude Code

These evals run the exported **openstudio-ai Claude plugin** (agent, skills and
MCP server) in `claude -p` next to **a second OpenStudio MCP server that you are
developing**, and score what the agent does. The first target is NLR
`openstudio-mcp`, but the runner only knows a plain MCP config entry, so any
stdio server works.

Arms, per case:

| Arm | Servers connected | What it checks |
| --- | --- | --- |
| `harness-only` | openstudio-ai | baseline: the case is solvable without your server |
| `sut-only` | your server (plugin agent and skills still loaded) | your server works under our agent |
| `both` | both | routing: the agent sends the work to your server (`required_tools` / `forbidden_tools`) |

Every arm also checks that each server connected and that the session ended
cleanly. A case's optional `expected` block (for example site EUI within a
tolerance) is checked on every arm.

## Quick start (openstudio-mcp developer)

Goal: be able to run this from the root of `openstudio-ai-harness`:

```bash
uv run python -m evals.interop \
    --sut-config evals/sut/openstudio-mcp.json \
    --run-name my_test_results_dir
```

- `evals.interop` is the Python module that runs the evaluation.
- `--sut-config` selects the system under test (SUT).
- `--run-name` names the results folder under `outputs/evals/`.

Prerequisites: Claude Code (`claude` on PATH, logged in or with your gateway env
set), `uv`, and OpenStudio on `PATH`.

1. **Check out your `openstudio-mcp` branch and build its environment.**

   ```bash
   cd /path/to/openstudio-mcp && git checkout my-branch && uv sync
   ```

   This creates `.venv/bin/openstudio-mcp`, which the launcher script runs. The
   eval uses whatever branch is checked out here.

2. **Clone this repo** (check out a tag if you want a specific version) and set up
   the environment that runs the evaluations.

   ```bash
   git clone git@github.com:pnnl/openstudio-ai-harness.git && cd openstudio-ai-harness
   git checkout <tag>
   uv sync
   ```

3. **Stage the shared measures cache once** (about 150 MB download), from the root
   of this repo, pointing at your `openstudio-mcp` checkout.

   ```bash
   OPENSTUDIO_MCP_ROOT=/path/to/openstudio-mcp scripts/start_openstudio_mcp.sh --setup
   ```

4. **Configure the server entry.** This file tells the harness how to start
   `openstudio-mcp`. Copy `evals/sut/openstudio-mcp.example.json` to
   `evals/sut/openstudio-mcp.json` and replace the two placeholders:
   - `/ABS/PATH/TO/openstudio-ai-harness/...` becomes where you cloned this repo in step 2.
   - `/ABS/PATH/TO/openstudio-mcp` becomes your `openstudio-mcp` checkout from step 1.

   Leave `{sandbox}` alone and keep the key `openstudio-mcp` (details below).

5. **Run it** with the command at the top of this section.

6. **Read the result.** The exit code is 0 only if every session passed. Details
   are in `outputs/evals/<run-name>/`: `summary.json`, `provenance.json`, and
   `result.json` and `timeline.json` per session (see Results).

**Model (optional environment variable).** Setting `ANTHROPIC_MODEL`, the same
variable Claude Code reads, is optional. Put it in your shell or in the repo-root
`.env` (a value already in your shell wins over `.env`), or pass `--model <id>` to
choose the model for a single run. `--model` takes precedence. The runner needs one
of the two: if neither is set it exits with an error. Use the exact model ID your
Anthropic API access or gateway accepts. `provenance.json` records the model and
whether it came from `--model` or `ANTHROPIC_MODEL`. For results that compare
across people, agree on one model.

### The server entry

The file you created in step 4 (`openstudio-mcp.json`) is a standard `mcpServers`
file with exactly one entry. With the paths filled in it looks like:

```json
{
  "mcpServers": {
    "openstudio-mcp": {
      "command": "bash",
      "args": ["/abs/path/openstudio-ai-harness/scripts/start_openstudio_mcp.sh"],
      "env": {
        "OPENSTUDIO_MCP_ROOT": "/abs/path/openstudio-mcp",
        "OPENSTUDIO_MCP_SANDBOX": "{sandbox}"
      }
    }
  }
}
```

- The **key** is the server name. Tools reach the agent as
  `mcp__<key>__<tool>`, and the policy in `prompts/openstudio_agent.md` refers to
  NLR as `openstudio-mcp`, so keep that name for NLR.
- `{sandbox}` in any string is replaced with a fresh temp directory per session.
  Test inputs are copied to `{sandbox}/inputs`. Claude starts the server over
  stdio for each session, so there is no port or separate terminal.
- `start_openstudio_mcp.sh` is just the native launcher for NLR. It symlinks the
  cached measures into the sandbox. `scripts/start_openstudio_mcp.sh --check`
  verifies the binary and cache. Any other server just needs its own `command`.
- Native runs have no ComStock or gbXML measures (the Docker image installs
  them), so tools that need them return errors. This is accepted.

## Options

| Flag | Meaning |
| --- | --- |
| `--arms a,b` | subset of `harness-only,sut-only,both` (default all) |
| `--cases ID ...` | only these case ids |
| `--cases-dir DIR` | extra `*.json` case files, for example from your own repo. A duplicate `case_id` is an error |
| `--repeat N` | repeat each session N times (agent routing varies between runs) |
| `--runtime-mode` | how the plugin launches the openstudio-ai server: `local` (default, this checkout), `installed`, `marketplace` (need `openstudio-ai-mcp` on PATH) |
| `--timeout S` | seconds per Claude session (default 900) |
| `--deepeval` | add DeepEval ToolCorrectness on the `both` arm (`uv sync --extra eval`) |
| `--model ID` | model id for every session (default `$ANTHROPIC_MODEL`) |
| `--run-name NAME` | name of the results folder under `outputs/evals/` (default `interop`) |

The exit code is 0 only if every session passes.

## Results

`outputs/evals/<run-name>/` (gitignored):

- `provenance.json`: openstudio-ai version and git SHA, your server's git SHA (taken
  from the first existing directory in the entry's `env`), `claude --version`, model,
  runtime mode, arms, and a hash of the cases that ran
- `summary.json`: every session's checks and tool calls
- `metrics` (in each session's `result.json`, and printed per session): `turns`,
  `tool_calls`, `output_tokens`, `cost_usd`, `duration_s`, `api_duration_s` and the
  cache token counts, read from Claude's final `result` event. Compare `turns`,
  `tool_calls` and `output_tokens` for agent effort; cost and cache tokens are
  dominated by the fixed size of the system prompt and tool schemas. Turn counts
  vary between runs, so use `--repeat` before comparing arms.
- `report.md`: the same results as readable tables (pass/fail per case and arm, effort,
  failed checks, tool sequences). Written at the end of every run; regenerate it for
  any existing run, or all runs, with
  `uv run python -m evals.report [RUN_DIR ...]`.
  With `--repeat`, effort numbers are medians.
- `<arm>/<case_id>[/rep_N]/`: `result.json` (checks, tool calls, final answer),
  `timeline.json` (each call with its result and error flag) and `raw.stream.jsonl`
  (the Claude stream-json)

When `both` fails, read the `tools:` line printed by the runner or `timeline.json`.
Typical failures are the agent using the openstudio-ai `sim_*` tools, or never loading
the `delegated-nlr-modeling` skill.

## Cases

Cases are JSON lists in `evals/cases/` (or `--cases-dir`):

```json
{
  "case_id": "openstudio_mcp_simulation_001",
  "description": "...",
  "prompt": "Run ... {input_dir}/sample.osm ...",
  "inputs": ["sample.osm", "USA_FL_Tampa.Intl.AP.722110_TMY3.epw"],
  "arms": ["harness-only", "sut-only", "both"],
  "required_tools": [{"tool": "run_simulation", "provider": "openstudio-mcp"}],
  "forbidden_tools": ["sim_*"],
  "expected_tools_ordered": ["run_simulation"],
  "expected": {
    "metrics": [{"name": "Site EUI", "value": 34.14, "tolerance_pct": 5}],
    "artifacts": ["*.sql"]
  }
}
```

- `inputs` are file names from `tests/fixtures/`, copied into `{input_dir}`.
- A tool's `provider` is `harness` for openstudio-ai, or the server name (the key
  in your `--sut-config`, e.g. `openstudio-mcp`) for the server under test.
- `required_tools`, `forbidden_tools` (globs) and `expected_tools_ordered` apply to
  the `both` arm only. `arms` is optional (default all three).
- `required_skills` / `forbidden_skills` (globs) check skills loaded through the
  host `Skill` tool, by exported name without the plugin prefix (for example
  `delegated-nlr-modeling`). Like the tool keys they apply to `both`.
- `arm_routing` sets routing keys for a single arm, replacing the top-level ones
  for that arm, e.g.
  `{"harness-only": {"required_skills": ["openstudio-sdk-model-editor"]}}`. Use it
  to check which route the isolated arms took, not just their outcome.
- `expected.metrics`: passes when a number within `tolerance_pct` of `value`
  appears on a line of the final answer containing `name`. `expected.artifacts`
  are file-name globs that must exist in the session sandbox. Metrics read the
  agent's prose, so prefer `expected.model` or artifacts wherever the outcome is
  in a file.
- `expected.model` inspects the `.osm` the agent produced: the newest `.osm` in the
  session sandbox that is not byte-identical to a staged input (each server saves
  to its own workspace). The file is kept as `output.osm` next to `result.json`.
  The check fails if no new model was saved. It parses the OSM text, so it needs
  no OpenStudio install. Keys, all optional:

  ```json
  "model": {
    "version_min": "3.0.0",
    "counts": {"OS:ThermalZone": 10},
    "min_counts": {"OS:AirLoopHVAC": 1},
    "fields": [
      {"type": "OS:SizingPeriod:DesignDay", "field": "Name", "contains": "International", "match": "all"},
      {"type": "OS:RunPeriod", "field": "End Month", "equals": "1"}
    ]
  }
  ```

  `field` is the `!- Label` comment of the OSM field (case-insensitive, `{unit}`
  dropped). `match` is `any` (default) or `all` objects of that type. A prompt that
  needs this must ask the agent to save the model, so say so in the prompt.

## Known limitations

- **The plugin's `settings.json` agent is not applied in `claude -p`.** The plugin
  ships `{"agent": "openstudio-modeler"}` so that the modeler agent (which holds
  the routing policy) runs as the main thread. In headless mode this does not
  happen, even for a normally installed plugin: without `--agent` the policy is
  absent. The runner passes `--agent openstudio-ai:openstudio-modeler` explicitly,
  so these evals test the policy itself, **not** whether users get it
  automatically. Interactive behavior is unverified. This is a possible product
  gap, tracked outside these evals.
- Tool names depend on how the plugin is loaded: `--plugin-dir` gives
  `mcp__openstudio_ai__*`, a real install gives
  `mcp__plugin_openstudio-ai_openstudio_ai__*`. The scorer accepts both.
- LLM routing is not deterministic. Use `--repeat` to measure a pass rate.
- Claude Code only for now; a Codex driver is planned.
