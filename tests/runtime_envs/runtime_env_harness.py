"""Host-side helpers for the marketplace runtime-environment matrix.

Each profile is one stage of ``docker/runtime-envs/Dockerfile``. A test keeps a
container running, then launches the MCP server inside it over stdio with
``docker exec -i`` using the exact command and environment from the exported
plugin's ``.mcp.json`` -- the same launch Claude Code or Codex performs.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "docker" / "runtime-envs" / "Dockerfile"
IMAGE_REPO = os.getenv("OPENSTUDIO_AI_RUNTIME_ENV_IMAGE", "openstudio-ai-runtime-env")
ENABLE_VAR = "OPENSTUDIO_AI_RUNTIME_ENV_TESTS"
SKIP_BUILD_VAR = "OPENSTUDIO_AI_RUNTIME_ENV_SKIP_BUILD"
# Hosts give an MCP server a bounded time to start (Claude Code: MCP_TIMEOUT).
STARTUP_BUDGET_S = float(os.getenv("OPENSTUDIO_AI_MCP_STARTUP_BUDGET_S", "30"))
# A cold first launch downloads Python, openstudio, and dependencies.
COLD_START_LIMIT_S = float(os.getenv("OPENSTUDIO_AI_MCP_COLD_START_LIMIT_S", "900"))

EXPORT_ROOT = "/opt/exports"
MCP_CONFIG_PATHS = {
    "claude": "claude/openstudio-ai/.mcp.json",
    "codex": "codex/plugins/openstudio-ai/.mcp.json",
}
MCP_TAIL = ["openstudio-ai-mcp", "--transport", "stdio"]


@dataclass(frozen=True)
class Profile:
    """One simulated user machine."""

    name: str
    target: str
    build_args: tuple[tuple[str, str], ...] = ()
    network: str | None = None

    @property
    def tag(self) -> str:
        return f"{IMAGE_REPO}:{self.name}"


PROFILES: dict[str, Profile] = {
    profile.name: profile
    for profile in (
        Profile("uv-only", "uv-only"),
        Profile("uv-warm", "uv-warm"),
        Profile("system-py310", "system-py310"),
        Profile("no-uv", "no-uv"),
        Profile("legacy-pipx", "legacy-pipx"),
        Profile(
            "native-3.11",
            "native-openstudio",
            (("NATIVE_OPENSTUDIO_VERSION", "3.11.0"),),
        ),
        Profile(
            "native-3.10",
            "native-openstudio",
            (("NATIVE_OPENSTUDIO_VERSION", "3.10.0"),),
        ),
        Profile("airgap", "airgap", network="none"),
    )
}

_BUILT: set[str] = set()


def docker(
    *args: str, timeout: float = 600, check: bool = True
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["docker", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(
            f"docker {' '.join(args[:3])} failed ({completed.returncode}):\n"
            f"{completed.stderr[-4000:]}"
        )
    return completed


def build_image(profile: Profile) -> str:
    """Build a profile's image once per session (reuse with SKIP_BUILD_VAR=1)."""
    if profile.name in _BUILT:
        return profile.tag
    if os.getenv(SKIP_BUILD_VAR) == "1":
        exists = docker("image", "inspect", profile.tag, check=False)
        if exists.returncode == 0:
            _BUILT.add(profile.name)
            return profile.tag
    build_args: list[str] = []
    for key, value in profile.build_args:
        build_args += ["--build-arg", f"{key}={value}"]
    docker(
        "build",
        "--file",
        str(DOCKERFILE),
        "--target",
        profile.target,
        "--tag",
        profile.tag,
        *build_args,
        str(REPO_ROOT),
        timeout=3600,
    )
    _BUILT.add(profile.name)
    return profile.tag


@dataclass
class ExecResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    seconds: float

    def json(self) -> dict[str, Any]:
        """Parse the JSON document a command printed, ignoring surrounding text."""
        start = self.stdout.find("{")
        end = self.stdout.rfind("}")
        if start == -1 or end == -1:
            raise AssertionError(
                f"No JSON in output of {self.argv}:\n{self.describe()}"
            )
        return json.loads(self.stdout[start : end + 1])

    def describe(self) -> str:
        return (
            f"$ {shlex.join(self.argv)}\nexit={self.returncode} ({self.seconds:.1f}s)\n"
            f"--- stdout ---\n{self.stdout[-3000:]}\n--- stderr ---\n{self.stderr[-3000:]}"
        )


@dataclass
class McpRun:
    """Outcome of one stdio MCP session launched inside a container."""

    initialize_seconds: float
    server_name: str
    tool_names: set[str]
    results: dict[str, Any]
    stderr: str


@dataclass
class RuntimeEnv:
    profile: Profile
    container_id: str
    network: str | None = None
    _servers: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def start(cls, profile: Profile, *, network: str | None = None) -> "RuntimeEnv":
        tag = build_image(profile)
        network = network if network is not None else profile.network
        name = f"osai-env-{profile.name.replace('.', '')}-{uuid.uuid4().hex[:8]}"
        args = ["run", "--detach", "--rm", "--name", name]
        if network:
            args += ["--network", network]
        args.append(tag)
        container_id = docker(*args).stdout.strip()
        return cls(profile=profile, container_id=container_id, network=network)

    def stop(self) -> None:
        docker("rm", "--force", self.container_id, check=False, timeout=120)

    # -- commands -------------------------------------------------------------
    def exec(
        self,
        argv: list[str],
        *,
        env: dict[str, str] | None = None,
        timeout: float = 900,
    ) -> ExecResult:
        env_flags: list[str] = []
        for key, value in (env or {}).items():
            env_flags += ["--env", f"{key}={value}"]
        started = time.monotonic()
        try:
            completed = docker(
                "exec",
                *env_flags,
                self.container_id,
                *argv,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return ExecResult(
                argv, 124, str(exc.stdout or ""), f"timed out after {timeout}s", timeout
            )
        return ExecResult(
            argv,
            completed.returncode,
            completed.stdout,
            completed.stderr,
            time.monotonic() - started,
        )

    def sh(self, script: str, **kwargs: Any) -> ExecResult:
        """Run a non-login shell so PATH is exactly what the image defines."""
        return self.exec(["sh", "-c", script], **kwargs)

    def read_text(self, path: str) -> str:
        result = self.exec(["cat", path])
        assert result.returncode == 0, result.describe()
        return result.stdout

    # -- plugin exports -------------------------------------------------------
    def mcp_server(
        self, export: str = "release-sim", host: str = "claude"
    ) -> dict[str, Any]:
        key = (export, host)
        if key not in self._servers:
            config = json.loads(
                self.read_text(f"{EXPORT_ROOT}/{export}/{MCP_CONFIG_PATHS[host]}")
            )
            servers = config["mcpServers"]
            assert len(servers) == 1, servers
            self._servers[key] = next(iter(servers.values()))
        return self._servers[key]

    def plugin_version(self, export: str = "release-sim") -> str:
        return self.read_text(f"{EXPORT_ROOT}/{export}/plugin-version").strip()

    def runtime_argv(
        self,
        command: str,
        *args: str,
        export: str = "release-sim",
        reinstall: bool = False,
    ) -> list[str]:
        """Run another runtime console script with the export's exact uvx pin."""
        server = self.mcp_server(export)
        launch = list(server["args"])
        assert server["command"] == "uvx", server
        assert launch[-3:] == MCP_TAIL, launch
        options = ["--reinstall"] if reinstall else []
        return ["uvx", *options, *launch[:-3], command, *args]

    def doctor(self, export: str = "release-sim", **kwargs: Any) -> ExecResult:
        server = self.mcp_server(export)
        return self.exec(
            self.runtime_argv(
                "openstudio-ai",
                "doctor",
                "--json",
                "--plugin-version",
                server["env"]["OPENSTUDIO_AI_PLUGIN_VERSION"],
                "--plugin-contract-version",
                server["env"]["OPENSTUDIO_AI_PLUGIN_CONTRACT_VERSION"],
                export=export,
            ),
            **kwargs,
        )

    # -- MCP ------------------------------------------------------------------
    def run_mcp(
        self,
        calls: list[tuple[str, dict[str, Any]]],
        *,
        export: str = "release-sim",
        host: str = "claude",
        extra_env: dict[str, str] | None = None,
        timeout: float = COLD_START_LIMIT_S,
    ) -> McpRun:
        server = self.mcp_server(export, host)
        env = {**server.get("env", {}), **(extra_env or {})}
        env_flags: list[str] = []
        for key, value in env.items():
            env_flags += ["--env", f"{key}={value}"]
        argv = [
            "exec",
            "-i",
            *env_flags,
            self.container_id,
            server["command"],
            *server["args"],
        ]
        return asyncio.run(_mcp_session(argv, calls, timeout))


async def _mcp_session(
    docker_args: list[str], calls: list[tuple[str, dict[str, Any]]], timeout: float
) -> McpRun:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(command="docker", args=docker_args)
    with tempfile.TemporaryFile(mode="w+") as errlog:

        async def session_body() -> McpRun:
            started = time.monotonic()
            async with stdio_client(params, errlog=errlog) as (
                read_stream,
                write_stream,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    init = await session.initialize()
                    init_seconds = time.monotonic() - started
                    tools = await session.list_tools()
                    results: dict[str, Any] = {}
                    for name, arguments in calls:
                        result = await session.call_tool(name=name, arguments=arguments)
                        results[name] = result.structured_content
            return McpRun(
                initialize_seconds=init_seconds,
                server_name=init.server_info.name,
                tool_names={tool.name for tool in tools.tools},
                results=results,
                stderr="",
            )

        try:
            run = await asyncio.wait_for(session_body(), timeout=timeout)
        except BaseException as exc:
            errlog.seek(0)
            raise AssertionError(
                f"MCP session failed: {exc!r}\n--- server stderr ---\n{errlog.read()[-4000:]}"
            ) from exc
        errlog.seek(0)
        run.stderr = errlog.read()
        return run


BACKTICK_COMMAND = re.compile(r"`((?:uvx|openstudio-ai(?:-mcp)?)\b[^`]*)`")


def recommended_runtime_commands(payload: Any) -> set[str]:
    """Collect every backticked runtime command (`uvx ...` or `openstudio-ai ...`)."""
    found: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, str):
            found.update(match.group(1) for match in BACKTICK_COMMAND.finditer(value))
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return found
