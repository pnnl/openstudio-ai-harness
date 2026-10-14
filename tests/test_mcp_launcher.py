"""Behavior of the inlined marketplace MCP launcher, run exactly as hosts run it."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from adapters.runtime_helpers import mcp_launcher_source

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="the fake uv is a POSIX shebang script"
)

SPEC = ["--python", ">=3.10,<3.14", "--from", "openstudio-ai==9.9.9"]

FAKE_UV = """#!{python}
import json, os, sys
args = sys.argv[1:]
is_probe = args[-3:] == ["python", "-c", ""]
# Both read stdin: a probe that inherited the host's stdin would consume the
# server's MCP messages and fail the stdin assertions below.
record = {{"argv": args, "probe": is_probe, "stdin": sys.stdin.read()}}
with open(os.environ["FAKE_UV_LOG"], "a") as log:
    log.write(json.dumps(record) + "\\n")
if is_probe:
    sys.exit(0 if os.environ.get("FAKE_UV_CACHED") == "1" else 1)
sys.exit(int(os.environ.get("FAKE_UV_EXIT", "0")))
"""


@pytest.fixture
def fake_uv(tmp_path: Path) -> Path:
    uv = tmp_path / "bin" / "uv"
    uv.parent.mkdir()
    uv.write_text(FAKE_UV.format(python=sys.executable), encoding="utf-8")
    uv.chmod(0o755)
    return uv


def launch(
    tmp_path: Path,
    launcher_args: list[str],
    *,
    env: dict[str, str],
    stdin: str = "",
    cwd: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[dict]]:
    log = tmp_path / "uv.log"
    result = subprocess.run(
        [sys.executable, "-I", "-c", mcp_launcher_source(), *launcher_args],
        input=stdin,
        capture_output=True,
        text=True,
        env={"PATH": os.environ.get("PATH", ""), "FAKE_UV_LOG": str(log), **env},
        cwd=cwd or tmp_path,
        timeout=60,
    )
    calls = (
        [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    )
    return result, calls


def test_cached_runtime_launches_offline(tmp_path: Path, fake_uv: Path) -> None:
    result, calls = launch(
        tmp_path,
        [*SPEC, "--", "openstudio-ai-mcp", "--transport", "stdio"],
        env={"UV": str(fake_uv), "FAKE_UV_CACHED": "1"},
        stdin='{"jsonrpc": "2.0"}\n',
    )
    assert result.returncode == 0, result.stderr
    probe, server = calls
    assert probe["argv"] == ["tool", "run", "--offline", *SPEC, "python", "-c", ""]
    assert server["argv"] == [
        "tool", "run", "--offline", *SPEC, "openstudio-ai-mcp", "--transport", "stdio",
    ]
    # The probe must not consume the host's MCP messages.
    assert probe["stdin"] == ""
    assert server["stdin"] == '{"jsonrpc": "2.0"}\n'
    assert result.stderr == ""


def test_cold_cache_falls_back_to_an_online_launch(tmp_path: Path, fake_uv: Path) -> None:
    result, calls = launch(
        tmp_path,
        [*SPEC, "--", "openstudio-ai-mcp"],
        env={"UV": str(fake_uv), "FAKE_UV_CACHED": "0"},
    )
    assert result.returncode == 0, result.stderr
    assert [call["probe"] for call in calls] == [True, False]
    assert calls[1]["argv"] == ["tool", "run", *SPEC, "openstudio-ai-mcp"]
    assert "not in uv's cache" in result.stderr


def test_server_exit_code_is_preserved(tmp_path: Path, fake_uv: Path) -> None:
    result, calls = launch(
        tmp_path,
        [*SPEC, "--", "openstudio-ai-mcp"],
        env={"UV": str(fake_uv), "FAKE_UV_CACHED": "1", "FAKE_UV_EXIT": "3"},
    )
    assert result.returncode == 3
    # A failing server is not relaunched online.
    assert len(calls) == 2


def test_uv_is_found_on_path_when_uv_env_is_unset(tmp_path: Path, fake_uv: Path) -> None:
    result, calls = launch(
        tmp_path,
        [*SPEC, "--", "openstudio-ai-mcp"],
        env={"PATH": str(fake_uv.parent), "FAKE_UV_CACHED": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert len(calls) == 2


def test_missing_uv_fails_clearly(tmp_path: Path) -> None:
    result, calls = launch(
        tmp_path, [*SPEC, "--", "openstudio-ai-mcp"], env={"PATH": str(tmp_path)}
    )
    assert result.returncode == 127
    assert "`uv` was not found" in result.stderr
    assert calls == []


@pytest.mark.parametrize("args", [[*SPEC], [*SPEC, "--"]])
def test_missing_command_fails_clearly(tmp_path: Path, fake_uv: Path, args) -> None:
    result, calls = launch(tmp_path, args, env={"UV": str(fake_uv)})
    assert result.returncode == 2
    assert "expected" in result.stderr
    assert calls == []


def test_project_modules_cannot_shadow_the_launcher_imports(
    tmp_path: Path, fake_uv: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "subprocess.py").write_text("raise SystemExit('shadowed')\n")
    result, calls = launch(
        tmp_path,
        [*SPEC, "--", "openstudio-ai-mcp"],
        env={"UV": str(fake_uv), "FAKE_UV_CACHED": "1"},
        cwd=project,
    )
    assert result.returncode == 0, result.stderr
    assert len(calls) == 2


def test_uv_env_pointing_at_a_missing_file_fails_clearly(tmp_path: Path) -> None:
    result, calls = launch(
        tmp_path,
        [*SPEC, "--", "openstudio-ai-mcp"],
        env={"UV": str(tmp_path / "missing-uv")},
    )
    assert result.returncode == 127
    assert "could not run uv" in result.stderr
    assert "Traceback" not in result.stderr
    assert calls == []


def test_options_without_from_spec_are_rejected(tmp_path: Path, fake_uv: Path) -> None:
    result, calls = launch(
        tmp_path,
        ["--python", ">=3.10,<3.14", "--", "openstudio-ai-mcp"],
        env={"UV": str(fake_uv)},
    )
    assert result.returncode == 2
    assert "--from" in result.stderr
    assert calls == []
