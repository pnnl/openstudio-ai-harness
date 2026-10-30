# OpenStudio AI tests

## Publishing and full CI

Publishing runs the fast selection, including CLI/contract, manifest, privacy
and runtime unit checks and one paired Claude Code/Codex marketplace-export
smoke test. SDK modeling, native processes, simulations, browser execution,
repeated full exports, archive builds and large bundled-document parsing are
marked `slow` and run in the full pull-request/manual CI workflow. Publishing
does not install Chromium or repeat those checks. Distribution build, Twine
validation and the release-tag/version check remain in publishing.

From the repository root, with the development dependencies installed:

```bash
# Publishing selection; no browser installation needed.
python -m pytest -q tests -m "not slow" --strict-markers --durations=10

# Expensive checks separately.
python -m pytest -q tests -m slow --strict-markers --durations=25

# Full pull-request CI selection; neither marker is excluded.
python -m pytest -q tests --strict-markers --durations=25
```

Install Chromium with `python -m playwright install chromium` for browser
checks. Native checks retain their existing OpenStudio CLI requirements and
skips; the Python SDK remains pinned to 3.11.0. Standalone tests are separate:
`uv run --project standalone python -m pytest -q standalone/tests`.

The explicit selection policy is in [conftest.py](conftest.py). Whole integration
modules stay together; expensive tests in mixed modules are listed individually.
For a new expensive test, add `@pytest.mark.slow` or update that policy. New
unmarked tests run in the publishing selection. The policy regression tests in
[test_test_suites.py](test_test_suites.py) check its file/function references and
ensure publishing remains filtered while full CI remains unfiltered.

Full CI prints the 25 slowest durations and uploads `test-results/full.xml` as
`full-test-results-python-3.10`, including when tests fail. Use this report to
identify further slow checks rather than inferring cost from test names.

Local verification on October 14, 2026 (macOS, Python 3.13): 1,492 collected
tests partition into 271 fast and 1,221 slow tests, without overlap or omissions.
The fast selection passed in 21.15 seconds; six representative slow cases passed
in 24.76 seconds. Two expected SDK-document fallback warnings occurred in the
fast run. The full suite was not rerun for this selection change. These timings
exclude dependency installation, builds and publishing and do not predict GitHub
runner duration. Evidence is under `outputs/test-suite-split-20261014/` locally.

## Agent evaluation cases

`agent_eval_cases.json` contains conversation-style test cases for evaluating
the OpenStudio AI Model Workspace Agent.

The cases are intentionally simple and focused on realistic building energy
modeling questions. They are designed to evaluate:

- professionalism of the response;
- whether clarification is requested when inputs are missing;
- plan quality before tool execution;
- correct tool and skill routing;
- task completion;
- step efficiency and avoidance of unnecessary tools.

The file is data only. A future harness can read each case, send `query` to the
agent, and grade the response against `expected_output`, `expected_behavior`,
and `pass_criteria`.
