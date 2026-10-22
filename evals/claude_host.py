"""Claude Code host driver: run ``claude -p`` and read tool calls from stream-json."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from evals.checks import ToolCall, split_mcp_tool_name

PLUGIN_AGENT = "openstudio-ai:openstudio-modeler"


@dataclass
class ClaudeRun:
    events: list[dict[str, Any]]
    raw: str
    returncode: int
    stderr: str = ""
    timed_out: bool = False

    @property
    def init(self) -> dict[str, Any]:
        return next(
            (e for e in self.events if e.get("type") == "system" and e.get("subtype") == "init"), {}
        )

    @property
    def result(self) -> dict[str, Any]:
        return next((e for e in reversed(self.events) if e.get("type") == "result"), {})

    @property
    def final_text(self) -> str:
        return str(self.result.get("result") or "")

    @property
    def is_error(self) -> bool:
        return self.timed_out or self.returncode != 0 or bool(self.result.get("is_error", not self.result))


def parse_stream_json(raw: str) -> list[dict[str, Any]]:
    events = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _content_blocks(event: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    content = (event.get("message") or {}).get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def provider_for(server: str | None, providers: Mapping[str, str]) -> str:
    """Provider label for an MCP server name.

    Plugin-installed servers are named ``plugin_<plugin>_<server>`` (``--plugin-dir``
    loads them as plain ``<server>``), so also match on that suffix.
    """
    if server is None:
        return "agent"
    if server in providers:
        return providers[server]
    for name, label in providers.items():
        if server.startswith("plugin_") and server.endswith(f"_{name}"):
            return label
    return server


def extract_tool_calls(
    events: Iterable[Mapping[str, Any]], *, providers: Mapping[str, str]
) -> list[ToolCall]:
    """Ordered tool calls from ``tool_use`` blocks, tagged by provider.

    ``providers`` maps an MCP server name to a provider label (``harness`` for
    openstudio-ai); servers not in the map keep their own name as provider.
    Built-ins such as ``Skill`` or ``ToolSearch`` get provider ``agent``.
    """
    calls: list[ToolCall] = []
    for event in events:
        if event.get("type") != "assistant":
            continue
        for block in _content_blocks(event):
            if block.get("type") != "tool_use" or not block.get("name"):
                continue
            server, tool = split_mcp_tool_name(block["name"])
            provider = provider_for(server, providers)
            calls.append(ToolCall(tool, provider, block.get("input")))
    return calls


def tool_timeline(events: Iterable[Mapping[str, Any]], *, providers: Mapping[str, str]) -> list[dict[str, Any]]:
    """Tool calls with their result status, for the result bundle."""
    timeline: dict[str, dict[str, Any]] = {}
    for event in events:
        for block in _content_blocks(event):
            if event.get("type") == "assistant" and block.get("type") == "tool_use":
                server, tool = split_mcp_tool_name(block.get("name", ""))
                timeline[block["id"]] = {
                    "name": tool,
                    "provider": provider_for(server, providers),
                    "arguments": block.get("input"),
                    "is_error": None,
                    "result": None,
                }
            elif event.get("type") == "user" and block.get("type") == "tool_result":
                entry = timeline.get(block.get("tool_use_id", ""))
                if entry is not None:
                    entry["is_error"] = bool(block.get("is_error"))
                    entry["result"] = _result_text(block.get("content"))
    return list(timeline.values())


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text", "")) for b in content if isinstance(b, dict))
    return ""


def run_claude(
    prompt: str,
    *,
    mcp_config: Path,
    model: str,
    plugin_dir: Path | None = None,
    agent: str | None = PLUGIN_AGENT,
    cwd: Path | None = None,
    timeout: float = 900,
    claude_bin: str = "claude",
) -> ClaudeRun:
    """One non-interactive Claude Code session.

    ``--strict-mcp-config`` means only the servers in ``mcp_config`` are used;
    that also suppresses the plugin's own ``.mcp.json``. ``--agent`` is passed
    explicitly because ``--plugin-dir`` does not apply the plugin's
    ``settings.json`` ``agent`` key.
    """
    cmd = [
        claude_bin, "-p", prompt,
        "--output-format", "stream-json", "--verbose",
        "--no-session-persistence",
        "--permission-mode", "bypassPermissions",
        "--strict-mcp-config", "--mcp-config", str(mcp_config),
        "--model", model,
    ]
    if plugin_dir is not None:
        cmd += ["--plugin-dir", str(plugin_dir)]
    if agent:
        cmd += ["--agent", agent]
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, env=os.environ.copy(), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raw = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return ClaudeRun(parse_stream_json(raw), raw, -1, "timeout", timed_out=True)
    return ClaudeRun(parse_stream_json(proc.stdout), proc.stdout, proc.returncode, proc.stderr)


def run_metrics(run: ClaudeRun) -> dict[str, Any]:
    """Effort metrics from the final ``result`` event (``None`` where Claude did not report them).

    ``cache_creation_tokens`` / ``cache_read_tokens`` mostly reflect the fixed size of
    the system prompt and tool schemas, not the work done; compare ``turns``,
    ``tool_calls`` and ``output_tokens`` for effort.
    """
    result, usage = run.result, run.result.get("usage") or {}
    tool_calls = sum(
        1 for e in run.events if e.get("type") == "assistant"
        for b in _content_blocks(e) if b.get("type") == "tool_use"
    )
    return {
        "turns": result.get("num_turns"),
        "tool_calls": tool_calls,
        "output_tokens": usage.get("output_tokens"),
        "input_tokens": usage.get("input_tokens"),
        "cache_creation_tokens": usage.get("cache_creation_input_tokens"),
        "cache_read_tokens": usage.get("cache_read_input_tokens"),
        "cost_usd": result.get("total_cost_usd"),
        "duration_s": round(result["duration_ms"] / 1000, 1) if result.get("duration_ms") is not None else None,
        "api_duration_s": round(result["duration_api_ms"] / 1000, 1) if result.get("duration_api_ms") is not None else None,
    }


def connected_servers(run: ClaudeRun) -> dict[str, str]:
    """MCP server name -> status from the init event."""
    return {s["name"]: s.get("status", "") for s in run.init.get("mcp_servers", [])}
