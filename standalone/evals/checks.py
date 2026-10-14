"""Host-neutral, deterministic scoring of agent tool-call traces for interop evals."""
from __future__ import annotations

import re
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
    provider: str  # "harness", "agent" (host built-ins like Skill), or the MCP server name
    arguments: Any = None


@dataclass(frozen=True)
class CheckResult:
    check: str
    passed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


def _numbers(text: str) -> list[float]:
    return [float(m.replace(",", "")) for m in re.findall(r"-?\d[\d,]*\.?\d*", text)]


def check_expected(expected: Mapping[str, Any] | None, answer: str, files: Iterable[str] = ()) -> list[CheckResult]:
    """Outcome golden: ``{"metrics": [{"name", "value", "tolerance_pct", "unit_hint"?}], "artifacts": [...]}``.

    A metric passes when a number within ``tolerance_pct`` of ``value`` appears
    on the same line as ``name`` (case-insensitive) in the final answer.
    Artifacts are file-name globs that must match one of ``files``.
    """
    if not expected:
        return []
    results = []
    for metric in expected.get("metrics", []):
        name, target, tol = metric["name"], float(metric["value"]), float(metric.get("tolerance_pct", 5))
        found = [
            n for line in answer.splitlines() if name.lower() in line.lower() for n in _numbers(line)
        ]
        close = [n for n in found if abs(n - target) <= abs(target) * tol / 100]
        reason = (
            f"{close[0]} within {tol}% of {target}" if close
            else f"no value within {tol}% of {target} (saw {found[:5] or 'none'})"
        )
        results.append(CheckResult(f"expected:{name}", bool(close), reason))
    names = list(files)
    for pattern in expected.get("artifacts", []):
        hits = [f for f in names if fnmatch(f, pattern)]
        results.append(CheckResult(f"artifact:{pattern}", bool(hits), f"{len(hits)} match(es)"))
    return results


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
