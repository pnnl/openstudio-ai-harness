"""Dual-MCP routing eval runner.

Drives the standalone automa-ai agent with both the harness MCP
(openstudio_ai_mcp, started in-process) and NLR openstudio-mcp (started
separately via ``scripts/start_openstudio_mcp.sh --http 10220``), then scores
the ordered tool calls from the agent's telemetry trace.

    uv run --project standalone python -m standalone.evals.run <run_name> \
        [--cases ID ...] [--deepeval] [--repeat N]

Outputs land in ``outputs/evals/<run_name>/<case_id>/`` (gitignored), or
``<case_id>/rep_<n>/`` with ``--repeat`` > 1.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import functools
import json
import os
import shutil
import socket
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

from standalone.agent import (
    NLR_MCP_HOST_ENV,
    NLR_MCP_PORT_ENV,
    NLR_MCP_SERVER_NAME,
    build_openstudio_ai_mcp_config,
    load_openstudio_agent_spec,
    repo_root,
)
from standalone.evals.checks import (
    deepeval_tool_correctness,
    extract_tool_calls,
    mcp_tool_name,
    score_case,
)

HARNESS_MCP_SERVER_NAME = "openstudio_ai_mcp"
CASES_PATH = Path(__file__).resolve().parent / "cases" / "nlr_routing.json"
FIXTURES_DIR = repo_root / "tests" / "fixtures"
NLR_INPUT_DIR = Path(
    os.getenv("OPENSTUDIO_MCP_SANDBOX", repo_root / ".openstudio_mcp_sandbox")
) / "inputs"
OUTPUT_ROOT = repo_root / "outputs" / "evals"


def nlr_endpoint() -> tuple[str, int]:
    return os.getenv(NLR_MCP_HOST_ENV, "127.0.0.1"), int(os.getenv(NLR_MCP_PORT_ENV, "10220"))


def nlr_reachable() -> bool:
    host, port = nlr_endpoint()
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def load_cases(ids: list[str] | None = None) -> list[dict[str, Any]]:
    cases = json.loads(CASES_PATH.read_text())
    return [c for c in cases if not ids or c["case_id"] in ids]


class _PrefixedToolSession(list):
    """Tools from several per-server MCP sessions, closed together."""

    def __init__(self) -> None:
        super().__init__()
        self._sessions: list[Any] = []

    async def aclose(self) -> None:
        for session in reversed(self._sessions):
            await session.aclose()
        self._sessions.clear()


@contextlib.contextmanager
def server_prefixed_mcp_tools():
    """Expose MCP tools as ``mcp__<server>__<tool>``, the way Claude Code does.

    automa-ai merges every server's tools under bare names, so the agent cannot
    tell which server a tool belongs to. The routing policy ("when NLR is
    configured as ``openstudio-mcp``...") depends on that, so without prefixes
    the eval would not reflect what Claude Code users see.
    """
    import automa_ai.agents.langgraph_chatagent as chatagent

    original = chatagent.load_mcp_tools

    async def load_prefixed(server_configs):
        combined = _PrefixedToolSession()
        try:
            for server, config in server_configs.items():
                session = await original({server: config})
                combined._sessions.append(session)
                for tool in session:
                    tool.name = mcp_tool_name(server, tool.name)
                    combined.append(tool)
        except BaseException:
            await combined.aclose()
            raise
        return combined

    chatagent.load_mcp_tools = load_prefixed
    try:
        yield
    finally:
        chatagent.load_mcp_tools = original


async def run_case(case: dict[str, Any], out_dir: Path, *, use_deepeval: bool) -> dict[str, Any]:
    from automa_ai.config.agent_spec import load_agent_factory_from_yaml
    from automa_ai.telemetry.trace_reader import read_jsonl

    out_dir.mkdir(parents=True, exist_ok=True)
    trace_path = out_dir / "trace.jsonl"
    trace_path.unlink(missing_ok=True)

    NLR_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name in case.get("inputs", []):
        shutil.copy2(FIXTURES_DIR / name, NLR_INPUT_DIR / name)
    prompt = case["prompt"].format(input_dir=NLR_INPUT_DIR)

    spec = load_openstudio_agent_spec(build_openstudio_ai_mcp_config())
    spec.telemetry = {**(spec.telemetry or {}), "path": str(trace_path)}
    spec.runtime.debug = False  # the UI spec streams every chunk to stdout
    mcp_configs = spec.to_factory_kwargs()["mcp_configs"]
    if NLR_MCP_SERVER_NAME not in mcp_configs:
        raise RuntimeError(f"{NLR_MCP_PORT_ENV} is not set; NLR server not configured.")

    providers = {NLR_MCP_SERVER_NAME: "nlr", HARNESS_MCP_SERVER_NAME: "harness"}

    agent = load_agent_factory_from_yaml(spec).get_agent()
    answer_parts: list[str] = []
    error = None
    try:
        with server_prefixed_mcp_tools():
            async for chunk in agent.stream(prompt, str(uuid.uuid4()), str(uuid.uuid4())):
                content = chunk.get("content") if isinstance(chunk, dict) else None
                if isinstance(content, str) and chunk.get("is_task_complete"):
                    answer_parts.append(content)
    except Exception as exc:  # record and still score whatever was traced
        error = f"{type(exc).__name__}: {exc}"
    finally:
        await agent.aclose()

    records, _issues = read_jsonl(trace_path) if trace_path.exists() else ([], [])
    calls = extract_tool_calls(records, providers=providers)
    answer = "\n".join(answer_parts)
    results = score_case(case, calls)
    if use_deepeval and case.get("expected_tools_ordered"):
        de = deepeval_tool_correctness(
            calls, case["expected_tools_ordered"], prompt=prompt, answer=answer
        )
        if de is None:
            print("deepeval not installed; install the standalone 'eval' extra.", file=sys.stderr)
        else:
            results.append(de)

    record = {
        "case_id": case["case_id"],
        "passed": error is None and all(r.passed for r in results),
        "error": error,
        "checks": [r.to_dict() for r in results],
        "tool_calls": [{"name": c.name, "provider": c.provider} for c in calls],
        "answer": answer,
    }
    (out_dir / "result.json").write_text(json.dumps(record, indent=2))
    return record


async def main_async(args: argparse.Namespace) -> int:
    from automa_ai.common.mcp_registry import MCPServerManager
    from openstudio_ai_mcp.server import serve

    if not nlr_reachable():
        host, port = nlr_endpoint()
        print(
            f"NLR openstudio-mcp is not reachable at {host}:{port}. Start it with "
            "`scripts/start_openstudio_mcp.sh --http 10220`.",
            file=sys.stderr,
        )
        return 2
    os.environ.setdefault(NLR_MCP_PORT_ENV, str(nlr_endpoint()[1]))

    scratch = Path(tempfile.mkdtemp(prefix="osai-eval-"))
    # Isolate harness learning/runtime state from the developer's workspace.
    os.environ["OPENSTUDIO_AI_DATA_DIR"] = str(scratch / "user_data")
    harness_config = build_openstudio_ai_mcp_config()
    harness_config.serve = functools.partial(serve, workspace_root=str(scratch / "workspace"))

    manager = MCPServerManager()
    manager.add_server(harness_config)
    started = await manager.start_all()
    if not all(started.values()):
        print("Harness MCP server failed to start.", file=sys.stderr)
        return 2

    run_dir = OUTPUT_ROOT / args.run_name
    records = []
    try:
        for case in load_cases(args.cases):
            for rep in range(1, args.repeat + 1):
                out_dir = run_dir / case["case_id"]
                label = case["case_id"]
                if args.repeat > 1:
                    out_dir = out_dir / f"rep_{rep}"
                    label = f"{label} [{rep}/{args.repeat}]"
                print(f"== {label}", flush=True)
                record = await run_case(case, out_dir, use_deepeval=args.deepeval)
                record["rep"] = rep
                records.append(record)
                for check in record["checks"]:
                    mark = "PASS" if check["passed"] else "FAIL"
                    print(f"  [{mark}] {check['check']}: {check['reason']}")
                timeline = " -> ".join(f"{c['name']}({c['provider']})" for c in record["tool_calls"])
                print(f"  tools: {timeline or '(none)'}")
                if record["error"]:
                    print(f"  error: {record['error']}")
    finally:
        await manager.stop_all()
        shutil.rmtree(scratch, ignore_errors=True)

    (run_dir / "summary.json").write_text(json.dumps(records, indent=2))
    if args.repeat > 1:
        for case_id in dict.fromkeys(r["case_id"] for r in records):
            reps = [r for r in records if r["case_id"] == case_id]
            print(f"{case_id}: {sum(r['passed'] for r in reps)}/{len(reps)} passed")
    passed = sum(r["passed"] for r in records)
    print(f"{passed}/{len(records)} runs passed. Results: {run_dir}")
    return 0 if passed == len(records) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_name")
    parser.add_argument("--cases", nargs="*", help="Case IDs to run (default: all)")
    parser.add_argument("--deepeval", action="store_true", help="Add DeepEval ToolCorrectness score")
    parser.add_argument(
        "--repeat", type=int, default=1, help="Run each case N times and report the pass rate"
    )
    args = parser.parse_args(argv)
    if args.repeat < 1:
        parser.error("--repeat must be >= 1")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
