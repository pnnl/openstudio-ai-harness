# Marketplace runtime-environment tests

These tests check the marketplace `uvx` launch contract on simulated user
machines. Each environment is one stage of
[docker/runtime-envs/Dockerfile](../../docker/runtime-envs/Dockerfile). Tests
run on the host and start the MCP server inside a container with
`docker exec -i`, using the exact command and environment from the exported
plugin's `.mcp.json`. This is the same launch Claude Code or Codex performs.

Every image contains two exports:

- `as-is`: what this checkout would publish today. The pin is the `pyproject`
  version, resolved from public PyPI.
- `release-sim`: the same source after a simulated release. The version is
  bumped to `0.4.1.dev0` and its wheel is served through `UV_FIND_LINKS`.

| Environment | Machine it simulates |
| --- | --- |
| `uv-only` | Clean Linux with only uv: no Python, no OpenStudio, cold cache |
| `uv-warm` | `uv-only` after setup's `install-runtime` (startup time, `--network none`) |
| `system-py310` | System Python 3.10 plus a project `.venv` without `openstudio` |
| `no-uv` | Python and pipx without uv; pipx's bin dir is not on `PATH` |
| `legacy-pipx` | Pre-uvx `openstudio-ai==0.3.1` installed with pipx and on `PATH`, plus uv |
| `native-3.11` / `native-3.10` | uv plus the NREL native OpenStudio CLI at that version |
| `airgap` | No network; Python provided ahead of time; packages come from a local wheelhouse |

## Running

```bash
# Deterministic matrix (builds images on first run; about 2-3 GB for the native images)
OPENSTUDIO_AI_RUNTIME_ENV_TESTS=1 uv run --extra dev pytest tests/runtime_envs -v -rxX

# Reuse images that are already built, and pick environments
OPENSTUDIO_AI_RUNTIME_ENV_TESTS=1 OPENSTUDIO_AI_RUNTIME_ENV_SKIP_BUILD=1 \
    uv run --extra dev pytest tests/runtime_envs -k "native or airgap" -v
```

The tests are skipped unless `OPENSTUDIO_AI_RUNTIME_ENV_TESTS=1` is set, so the
normal test suite does not need Docker.

Measured facts, such as startup seconds, whether the native CLI loads a model
saved by the SDK, and agent transcripts, are written to
`outputs/runtime_envs/report.json`. Set `OPENSTUDIO_AI_RUNTIME_ENV_REPORT` to
write them somewhere else.

Tuning:

- `OPENSTUDIO_AI_MCP_STARTUP_BUDGET_S` (default `30`): the host's MCP startup
  timeout.
- `OPENSTUDIO_AI_MCP_COLD_START_LIMIT_S` (default `900`): the hard limit for a
  cold first launch.

## Model-driven setup tests

[test_agent_setup_runtime_envs.py](test_agent_setup_runtime_envs.py) gives a
real model the exported `setup-openstudio-ai` skill and a shell tool that runs
inside the container. The user is simulated: every approval is granted and
logged. The assertions cover:

- the readiness state the agent actually reaches;
- the skill's approval gates, such as asking before `pipx install uv`;
- whether the agent's readiness claim matches a doctor run the harness performs
  itself.

Any OpenAI-compatible endpoint works. The defaults target the PNNL AI Incubator
Depot:

```bash
cp tests/runtime_envs/.env.example tests/runtime_envs/.env   # or use the repo-root .env
# set LLM_API_KEY, and LLM_MODEL to a model your team can access

OPENSTUDIO_AI_RUNTIME_ENV_TESTS=1 \
    uv run --extra dev --with openai==2.6.1 pytest tests/runtime_envs -m runtime_env_agent -v
```

Leave `LLM_TEMPERATURE` unset for Claude models on the Depot, because they
reject `temperature=0`.

## Expected failures

Tests marked `xfail(strict=True)` encode gaps in the current branch, and each
reason names the gap. When a gap is fixed, its test reports XPASS, which fails
the run; remove the marker at that point.
