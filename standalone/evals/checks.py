"""Deterministic scoring of agent tool-call traces for dual-MCP routing evals."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from fnmatch import fnmatch
from typing import Any, Iterable, Mapping


MCP_TOOL_PREFIX = "mcp__"


def mcp_tool_name(server: str, tool: str) -> str:
    """Claude Code-style server-qualified name, e.g. ``mcp__openstudio-mcp__run_simulation``."""
    return f"{MCP_TOOL_PREFIX}{server}__{tool}"


def split_mcp_tool_name(name: str) -> tuple[str | None, str]:
    """Inverse of :func:`mcp_tool_name`; unprefixed names return ``(None, name)``."""
    if name.startswith(MCP_TOOL_PREFIX):
        server, sep, tool = name[len(MCP_TOOL_PREFIX):].partition("__")
        if sep:
            return server, tool
    return None, name


@dataclass(frozen=True)
class ToolCall:
    name: str  # bare MCP tool name, server prefix stripped
    provider: str  # "nlr", "harness", or "agent" (built-ins like load_skill)
    arguments: Any = None


@dataclass(frozen=True)
class CheckResult:
    check: str
    passed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_tool_calls(
    records: Iterable[Mapping[str, Any]],
    *,
    providers: Mapping[str, str],
) -> list[ToolCall]:
    """Ordered tool calls from automa-ai telemetry, tagged by provider.

    Uses ``tool.call`` span starts, which are emitted once per executed call.
    MCP tools carry an ``mcp__<server>__`` prefix; ``providers`` maps each
    server name to a provider label. Unprefixed tools are agent built-ins.
    """
    calls: list[ToolCall] = []
    for record in records:
        if record.get("name") != "tool.call" or record.get("type") != "span_start":
            continue
        attrs = record.get("attributes") or {}
        name = attrs.get("tool.name")
        if not name:
            continue
        server, tool = split_mcp_tool_name(name)
        provider = providers.get(server, server) if server else "agent"
        calls.append(ToolCall(tool, provider, attrs.get("tool.arguments")))
    return calls


def check_required(calls: list[ToolCall], required: Iterable[Mapping[str, str]]) -> list[CheckResult]:
    """Each ``{"tool": name, "provider": p}`` must appear at least once."""
    results = []
    for spec in required:
        name, provider = spec["tool"], spec.get("provider")
        hits = [c for c in calls if c.name == name and (provider is None or c.provider == provider)]
        label = f"required:{name}" + (f"@{provider}" if provider else "")
        results.append(
            CheckResult(label, bool(hits), f"called {len(hits)} time(s)" if hits else "never called")
        )
    return results


def check_forbidden(calls: list[ToolCall], patterns: Iterable[str]) -> list[CheckResult]:
    """No call may match a forbidden glob (e.g. ``sim_*``)."""
    results = []
    for pattern in patterns:
        hits = sorted({c.name for c in calls if fnmatch(c.name, pattern)})
        results.append(
            CheckResult(
                f"forbidden:{pattern}",
                not hits,
                f"called {', '.join(hits)}" if hits else "not called",
            )
        )
    return results


def score_case(case: Mapping[str, Any], calls: list[ToolCall]) -> list[CheckResult]:
    return [
        *check_required(calls, case.get("required_tools", [])),
        *check_forbidden(calls, case.get("forbidden_tools", [])),
    ]


def deepeval_tool_correctness(
    calls: list[ToolCall], expected: Iterable[str], *, prompt: str, answer: str
) -> CheckResult | None:
    """Optional DeepEval ToolCorrectnessMetric (ordered, no LLM judge needed).

    Returns None when deepeval is not installed (``--extra eval``).
    """
    try:
        from deepeval.metrics import ToolCorrectnessMetric
        from deepeval.test_case import LLMTestCase
        from deepeval.test_case import ToolCall as DEToolCall
    except ImportError:
        return None
    metric = ToolCorrectnessMetric(should_consider_ordering=True, async_mode=False)
    test_case = LLMTestCase(
        input=prompt,
        actual_output=answer or "",
        tools_called=[DEToolCall(name=c.name) for c in calls],
        expected_tools=[DEToolCall(name=n) for n in expected],
    )
    score = metric.measure(test_case)
    return CheckResult("deepeval:ToolCorrectness", bool(metric.is_successful()), f"score={score:.2f}; {metric.reason}")
