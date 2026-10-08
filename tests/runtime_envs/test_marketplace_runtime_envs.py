"""Marketplace `uvx` launch contract across simulated user machines.

Each test names the environment it runs in (see docker/runtime-envs/Dockerfile).
Two plugin exports are baked into every image:

* ``as-is``       -- exactly what this checkout would publish today.
* ``release-sim`` -- the same source after a simulated release: the version is
  bumped and the matching wheel is reachable through ``UV_FIND_LINKS``.

Tests marked ``xfail(strict=True)`` encode a known gap in the current branch.
They are expected to fail now and will turn into hard failures (XPASS) once
the gap is fixed, prompting removal of the marker.
"""

from __future__ import annotations

import shlex
from typing import Any

import pytest

from runtime_env_harness import (
    COLD_START_LIMIT_S,
    STARTUP_BUDGET_S,
    RuntimeEnv,
    recommended_runtime_commands,
)

STATUS = ("runtime_openstudio_status", {})
COMPATIBILITY = ("runtime_plugin_compatibility", {})
PINNED_SDK_VERSION = "3.11.0"
HOME = "/home/modeler"

SDK_SAVE_SCRIPT = """\
import sys
import openstudio
model = openstudio.model.Model()
openstudio.model.Space(model).setName("Probe Space")
assert model.save(openstudio.toPath(sys.argv[1]), True)
print(openstudio.openStudioVersion())
"""

NATIVE_LOAD_RUBY = """\
vt = OpenStudio::OSVersion::VersionTranslator.new
model = vt.loadModel(OpenStudio::Path.new('{path}'))
if model.empty?
  puts 'LOAD_FAILED'
  vt.errors.each {{ |e| puts e.logMessage }}
else
  puts 'LOAD_OK'
end
"""


def runtime_env(profile: str) -> Any:
    return pytest.mark.runtime_env(profile)


def sdk_python(run_status: dict[str, Any]) -> dict[str, Any]:
    payload = run_status["runtime_openstudio_status"]
    assert payload.get("ok") is True, payload
    assert "sdk_python" in payload, payload
    return payload["sdk_python"]


def assert_pinned_sdk_python(info: dict[str, Any]) -> None:
    assert info["available"] is True, info
    assert "error" not in info, info
    assert info["openstudio_sdk_version"] == PINNED_SDK_VERSION, info
    assert info["python_version"].startswith("3.12."), info
    assert info["executable"].startswith(f"{HOME}/.cache/uv/"), info


def save_model_with_sdk(env: RuntimeEnv, executable: str, path: str) -> str:
    result = env.exec([executable, "-c", SDK_SAVE_SCRIPT, path])
    assert result.returncode == 0, result.describe()
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Export contract (inspected inside the clean box)
# ---------------------------------------------------------------------------


@runtime_env("uv-only")
@pytest.mark.parametrize("export", ["as-is", "release-sim"])
def test_claude_and_codex_exports_share_one_pinned_launch(env_pool, export) -> None:
    env = env_pool("uv-only")
    claude = env.mcp_server(export, "claude")
    codex = env.mcp_server(export, "codex")
    version = env.plugin_version(export)

    assert claude["command"] == codex["command"] == "uvx"
    assert claude["args"] == codex["args"]
    args = claude["args"]
    assert args[args.index("--python") + 1] == "3.12"
    assert args[args.index("--from") + 1] == f"openstudio-ai=={version}"
    assert args[args.index("--with") + 1] == f"openstudio=={PINNED_SDK_VERSION}"
    assert claude["env"]["OPENSTUDIO_AI_PLUGIN_VERSION"] == version
    for value in [*args, *claude["env"].values()]:
        assert not value.startswith(("/Users/", "/home/", "/opt/")), value


# ---------------------------------------------------------------------------
# uv-only: clean machine, uv installed, nothing else
# ---------------------------------------------------------------------------


@runtime_env("uv-only")
def test_cold_first_launch_starts_mcp_and_reports_sdk_python(env_pool, observe) -> None:
    env = env_pool("uv-only", shared_container=False)
    run = env.run_mcp([STATUS, COMPATIBILITY], timeout=COLD_START_LIMIT_S)

    observe("uv-only", cold_initialize_seconds=round(run.initialize_seconds, 1))
    assert run.server_name == "openstudio-ai-mcp"
    assert "runtime_openstudio_status" in run.tool_names
    assert_pinned_sdk_python(sdk_python(run.results))
    assert run.results["runtime_plugin_compatibility"]["ok"] is True


@runtime_env("uv-only")
@pytest.mark.xfail(
    strict=False,
    reason="A cold first launch downloads ~100 MB; setup's install-runtime prewarm "
    "exists because this can exceed the host's MCP startup timeout on slow links.",
)
def test_cold_first_launch_fits_host_startup_budget(env_pool, observe) -> None:
    env = env_pool("uv-only", shared_container=False)
    run = env.run_mcp([], timeout=COLD_START_LIMIT_S)
    observe("uv-only", cold_initialize_seconds=round(run.initialize_seconds, 1))
    assert run.initialize_seconds < STARTUP_BUDGET_S


@runtime_env("uv-only")
def test_reported_sdk_python_runs_openstudio_scripts(env_pool) -> None:
    env = env_pool("uv-only")
    info = sdk_python(env.run_mcp([STATUS]).results)
    version = save_model_with_sdk(env, info["executable"], f"{HOME}/project/probe.osm")
    assert version.startswith(PINNED_SDK_VERSION)


@runtime_env("uv-only")
def test_host_default_python_cannot_run_sdk_scripts(env_pool) -> None:
    """The bare box has no python at all: SDK scripts must use sdk_python."""
    env = env_pool("uv-only")
    result = env.sh("command -v python3 || command -v python")
    assert result.returncode != 0, result.describe()


@runtime_env("uv-only")
def test_doctor_after_setup_is_plugin_ready_without_native_cli(env_pool) -> None:
    env = env_pool("uv-only")
    install = env.exec(env.runtime_argv("openstudio-ai", "install-runtime"))
    assert install.returncode == 0, install.describe()

    doctor = env.doctor()
    payload = doctor.json()
    assert doctor.returncode == 1, doctor.describe()
    assert payload["plugin_ready"] is True
    assert payload["core_ready"] is False
    assert payload["python_openstudio"] == {"ok": True, "version": PINNED_SDK_VERSION}
    assert payload["openstudio"]["ok"] is False
    assert payload["commands"]["openstudio_ai_mcp"]["path"].startswith(
        f"{HOME}/.cache/uv/"
    )


@runtime_env("uv-only")
def test_fresh_machine_doctor_points_to_prepare_not_rebuild(env_pool) -> None:
    """A fresh machine must not look like a stale runtime to the setup skill."""
    env = env_pool("uv-only", shared_container=False)
    payload = env.doctor().json()
    codes = {d["code"]: d for d in payload["diagnostics"]}
    assert payload["plugin_compatibility"]["ok"] is True
    assert "plugin_runtime_incompatible" not in codes
    storage = codes["runtime_storage_not_ready"]["remediation"]
    assert "uvx " in storage and "install-runtime" in storage
    assert "--reinstall" not in storage


@runtime_env("uv-only")
def test_doctor_remediation_commands_are_runnable(env_pool, observe) -> None:
    env = env_pool("uv-only", shared_container=False)
    payload = env.doctor().json()
    commands = recommended_runtime_commands(payload)
    observe("uv-only", doctor_recommended_commands=sorted(commands))
    assert commands, "expected the fresh-machine doctor to recommend setup commands"
    unrunnable = []
    for command in commands:
        executable = shlex.split(command)[0]
        if env.sh(f"command -v {shlex.quote(executable)}").returncode != 0:
            unrunnable.append(command)
    assert not unrunnable, f"not runnable in marketplace mode: {unrunnable}"


@runtime_env("uv-only")
def test_reinstall_rebuilds_runtime_and_sdk_python_must_be_requeried(
    env_pool, observe
) -> None:
    env = env_pool("uv-only")
    before = sdk_python(env.run_mcp([STATUS]).results)["executable"]

    rebuild = env.exec(
        env.runtime_argv("openstudio-ai", "install-runtime", reinstall=True)
    )
    assert rebuild.returncode == 0, rebuild.describe()
    after = sdk_python(env.run_mcp([STATUS]).results)["executable"]

    old_still_runs = env.exec([before, "-c", "import openstudio"]).returncode == 0
    observe(
        "uv-only",
        sdk_python_changed_after_reinstall=before != after,
        previous_sdk_python_still_runs=old_still_runs,
    )
    save_model_with_sdk(env, after, f"{HOME}/project/after-reinstall.osm")


# ---------------------------------------------------------------------------
# as-is: what this branch would publish today
# ---------------------------------------------------------------------------


@runtime_env("uv-only")
@pytest.mark.xfail(
    strict=True,
    reason="Release step: pyproject is still 0.4.0 and openstudio-ai==0.4.0 is "
    "already on PyPI without sdk_python, so the as-is pin launches the pre-PR "
    "runtime until the version is bumped and published.",
)
def test_as_is_pin_launches_runtime_with_sdk_python(env_pool, observe) -> None:
    env = env_pool("uv-only")
    run = env.run_mcp([STATUS, COMPATIBILITY], export="as-is")
    observe(
        "uv-only",
        as_is_runtime=run.results["runtime_plugin_compatibility"],
        as_is_status_keys=sorted(run.results["runtime_openstudio_status"]),
    )
    sdk_python(run.results)


@runtime_env("uv-only")
def test_as_is_doctor_rejects_runtime_without_sdk_python(env_pool) -> None:
    env = env_pool("uv-only")
    run = env.run_mcp([STATUS], export="as-is")
    has_sdk_python = "sdk_python" in run.results["runtime_openstudio_status"]
    install = env.exec(
        env.runtime_argv("openstudio-ai", "install-runtime", export="as-is")
    )
    assert install.returncode == 0, install.describe()
    payload = env.doctor(export="as-is").json()
    assert has_sdk_python or payload["plugin_ready"] is False


# ---------------------------------------------------------------------------
# uv-warm: setup's install-runtime has already filled uv's cache
# ---------------------------------------------------------------------------


@runtime_env("uv-warm")
@pytest.mark.parametrize("host", ["claude", "codex"])
def test_warm_launch_fits_host_startup_budget(env_pool, observe, host) -> None:
    env = env_pool("uv-warm")
    run = env.run_mcp([STATUS], host=host, timeout=STARTUP_BUDGET_S * 4)
    observe(
        "uv-warm", host=host, warm_initialize_seconds=round(run.initialize_seconds, 1)
    )
    assert_pinned_sdk_python(sdk_python(run.results))
    assert run.initialize_seconds < STARTUP_BUDGET_S


@runtime_env("uv-warm")
def test_warm_cache_launches_offline_with_uv_offline(env_pool, observe) -> None:
    env = env_pool("uv-warm", network="none")
    run = env.run_mcp(
        [STATUS], extra_env={"UV_OFFLINE": "1"}, timeout=STARTUP_BUDGET_S * 4
    )
    observe(
        "uv-warm",
        network="none",
        offline_initialize_seconds=round(run.initialize_seconds, 1),
    )
    assert_pinned_sdk_python(sdk_python(run.results))
    assert run.initialize_seconds < STARTUP_BUDGET_S


@runtime_env("uv-warm")
@pytest.mark.xfail(
    strict=True,
    reason="uv caches PyPI index responses for ~10 minutes; after that every uvx "
    "launch revalidates against PyPI even with an exact pin and a warm cache, so the "
    "exported launch (no UV_OFFLINE) fails offline after ~30 s of retries.",
)
def test_warm_cache_launches_offline_after_index_cache_expires(
    env_pool, observe
) -> None:
    env = env_pool("uv-warm", network="none")
    # --refresh makes every cached index response stale, as it is ~10 minutes
    # after the last launch.
    argv = env.runtime_argv("openstudio-ai", "--version")
    result = env.exec([argv[0], "--refresh", *argv[1:]], timeout=STARTUP_BUDGET_S * 4)
    observe(
        "uv-warm",
        network="none",
        expired_index_exit=result.returncode,
        expired_index_seconds=round(result.seconds, 1),
    )
    assert result.returncode == 0, result.describe()


@runtime_env("uv-warm")
def test_cleared_cache_without_network_fails_instead_of_hanging(
    env_pool, observe
) -> None:
    env = env_pool("uv-warm", shared_container=False, network="none")
    clean = env.exec(["uv", "cache", "clean"])
    assert clean.returncode == 0, clean.describe()

    doctor = env.doctor(timeout=STARTUP_BUDGET_S * 4)
    observe(
        "uv-warm",
        network="none",
        cleared_cache_exit=doctor.returncode,
        cleared_cache_seconds=round(doctor.seconds, 1),
        exceeds_host_startup_budget=doctor.seconds >= STARTUP_BUDGET_S,
        cleared_cache_stderr_tail=doctor.stderr.strip().splitlines()[-3:],
    )
    assert doctor.returncode not in (0, 124), doctor.describe()
    assert "pypi.org" in doctor.stderr, "error should name the unreachable index"


# ---------------------------------------------------------------------------
# system-py310: older system Python and a project .venv without openstudio
# ---------------------------------------------------------------------------


@runtime_env("system-py310")
def test_uvx_ignores_system_python_and_project_venv(env_pool) -> None:
    env = env_pool("system-py310")
    info = sdk_python(env.run_mcp([STATUS]).results)

    assert_pinned_sdk_python(info)
    assert not info["executable"].startswith(f"{HOME}/project/.venv")
    for candidate in ("python3", f"{HOME}/project/.venv/bin/python"):
        result = env.exec([candidate, "-c", "import openstudio"])
        assert result.returncode != 0, f"{candidate} unexpectedly imports openstudio"
    save_model_with_sdk(env, info["executable"], f"{HOME}/project/probe.osm")


# ---------------------------------------------------------------------------
# no-uv: the setup skill has to bootstrap uv with pipx
# ---------------------------------------------------------------------------


@runtime_env("no-uv")
def test_setup_bootstraps_uv_with_pipx_and_needs_path_fix(env_pool, observe) -> None:
    env = env_pool("no-uv", shared_container=False)
    doctor_argv = env.runtime_argv("openstudio-ai", "doctor")

    missing = env.sh(shlex.join(doctor_argv))
    assert missing.returncode == 127, missing.describe()

    install = env.exec(["pipx", "install", "uv"])
    assert install.returncode == 0, install.describe()

    on_default_path = env.sh("command -v uvx").returncode == 0
    observe("no-uv", pipx_uvx_on_default_path=on_default_path)
    assert not on_default_path, "pipx bin dir unexpectedly on the default PATH"
    assert env.exec(["test", "-x", f"{HOME}/.local/bin/uvx"]).returncode == 0

    fixed_path = f"{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin"
    server = env.mcp_server()
    run = env.run_mcp([STATUS], extra_env={"PATH": fixed_path})
    assert server["command"] == "uvx"
    assert_pinned_sdk_python(sdk_python(run.results))


# ---------------------------------------------------------------------------
# legacy-pipx: pre-uvx runtime still installed and on PATH
# ---------------------------------------------------------------------------


@runtime_env("legacy-pipx")
def test_uvx_launch_is_isolated_from_legacy_runtime(env_pool) -> None:
    env = env_pool("legacy-pipx")
    run = env.run_mcp([STATUS, COMPATIBILITY])
    info = sdk_python(run.results)

    assert_pinned_sdk_python(info)
    assert "pipx" not in info["executable"]
    compatibility = run.results["runtime_plugin_compatibility"]
    assert compatibility["ok"] is True, compatibility


@runtime_env("legacy-pipx")
def test_uvx_doctor_probes_its_own_mcp_command(env_pool) -> None:
    env = env_pool("legacy-pipx")
    env.exec(env.runtime_argv("openstudio-ai", "install-runtime"))
    payload = env.doctor().json()
    mcp_path = payload["commands"]["openstudio_ai_mcp"]["path"]
    assert mcp_path.startswith(f"{HOME}/.cache/uv/"), mcp_path
    assert payload["version"] == env.plugin_version()


@runtime_env("legacy-pipx")
def test_bare_openstudio_ai_still_resolves_to_legacy_install(env_pool, observe) -> None:
    """Documents the migration hazard: terminal `openstudio-ai` != plugin runtime."""
    env = env_pool("legacy-pipx")
    bare = env.sh("openstudio-ai --version || openstudio-ai doctor --json")
    where = env.sh("command -v openstudio-ai")
    observe(
        "legacy-pipx",
        bare_openstudio_ai_path=where.stdout.strip(),
        bare_output_head=(bare.stdout or bare.stderr).strip().splitlines()[:2],
    )
    assert where.returncode == 0 and "/.local/bin/" in where.stdout
    assert env.plugin_version() not in bare.stdout


# ---------------------------------------------------------------------------
# native-openstudio: uv plus a native OpenStudio CLI
# ---------------------------------------------------------------------------


def _configure_native_cli(env: RuntimeEnv) -> str:
    located = env.sh("command -v openstudio")
    assert located.returncode == 0, located.describe()
    executable = located.stdout.strip()
    configure = env.exec(
        env.runtime_argv("openstudio-ai", "configure-openstudio", "--path", executable)
    )
    assert configure.returncode == 0, configure.describe()
    return executable


@runtime_env("native-3.11")
def test_matching_native_cli_is_core_ready(env_pool) -> None:
    env = env_pool("native-3.11")
    _configure_native_cli(env)
    doctor = env.doctor()
    payload = doctor.json()
    assert doctor.returncode == 0, doctor.describe()
    assert payload["core_ready"] is True
    assert payload["openstudio"]["source"] == "runtime configuration"
    assert payload["openstudio"]["version_probe"]["openstudio_version"].startswith(
        "3.11"
    )

    status = env.run_mcp([STATUS]).results["runtime_openstudio_status"]
    assert status["available"] is True, status
    assert_pinned_sdk_python(status["sdk_python"])


@runtime_env("native-3.11")
@pytest.mark.parametrize(
    "profile", ["native-3.11", "native-3.10"], ids=["cli-3.11", "cli-3.10"]
)
def test_sdk_saved_model_loads_in_native_cli(env_pool, observe, profile) -> None:
    env = env_pool(profile)
    executable = _configure_native_cli(env)
    info = sdk_python(env.run_mcp([STATUS]).results)
    model_path = f"{HOME}/project/sdk-{profile}.osm"
    save_model_with_sdk(env, info["executable"], model_path)

    load = env.exec([executable, "-e", NATIVE_LOAD_RUBY.format(path=model_path)])
    loaded = "LOAD_OK" in load.stdout
    observe(
        profile,
        native_cli=env.sh("openstudio --version").stdout.strip(),
        sdk_version=info["openstudio_sdk_version"],
        native_loads_sdk_model=loaded,
        native_load_output=load.stdout.strip().splitlines()[-3:],
    )
    assert loaded, load.describe()


@runtime_env("native-3.10")
def test_doctor_warns_when_sdk_is_newer_than_native_cli(env_pool) -> None:
    """CLI 3.10 loads SDK 3.11 models only with a 'use with caution' warning."""
    env = env_pool("native-3.10")
    _configure_native_cli(env)
    doctor = env.doctor()
    payload = doctor.json()
    codes = {d["code"]: d for d in payload["diagnostics"]}
    mismatch = codes["openstudio_sdk_cli_version_mismatch"]
    assert mismatch["severity"] == "warning"
    assert "uvx " in mismatch["remediation"]
    assert payload["core_ready"] is True, "a newer SDK warns but does not block"
    assert doctor.returncode == 0, doctor.describe()


# ---------------------------------------------------------------------------
# airgap: no public network; local wheelhouse and IT-provisioned Python 3.12
# ---------------------------------------------------------------------------


@runtime_env("airgap")
def test_airgap_wheelhouse_launch(env_pool, observe) -> None:
    env = env_pool("airgap")
    assert env.network == "none"
    run = env.run_mcp([STATUS, COMPATIBILITY])
    observe("airgap", initialize_seconds=round(run.initialize_seconds, 1))
    assert_pinned_sdk_python(sdk_python(run.results))
    assert run.results["runtime_plugin_compatibility"]["ok"] is True


@runtime_env("airgap")
def test_airgap_without_provisioned_python_fails_clearly(env_pool) -> None:
    env = env_pool("airgap", shared_container=False)
    result = env.exec(
        env.runtime_argv("openstudio-ai", "--help"),
        env={"UV_PYTHON_INSTALL_DIR": "/tmp/no-python-here"},
        timeout=STARTUP_BUDGET_S * 4,
    )
    assert result.returncode != 0, result.describe()
    assert "3.12" in result.stderr, result.describe()


@runtime_env("airgap")
@pytest.mark.parametrize(
    "settings, expect_offline",
    [
        ("UV_NO_INDEX=1", False),
        ("UV_OFFLINE=1", True),
        ("UV_DEFAULT_INDEX=file:///opt/wheelhouse", True),
    ],
    ids=["no-index-env", "offline", "default-index"],
)
def test_uv_settings_that_keep_uvx_off_pypi(
    env_pool, observe, settings, expect_offline
) -> None:
    """Which uv knobs an organization can rely on; UV_NO_INDEX alone is not one."""
    env = env_pool("airgap", shared_container=False)
    launch = shlex.join(env.runtime_argv("openstudio-ai", "--help"))
    result = env.sh(
        f"env -u UV_OFFLINE {settings} {launch}", timeout=STARTUP_BUDGET_S * 4
    )
    contacted_pypi = "pypi.org" in result.stderr or "dns error" in result.stderr
    observe(
        "airgap",
        uv_settings=settings,
        exit_code=result.returncode,
        contacted_pypi=contacted_pypi,
    )
    assert (result.returncode == 0) is expect_offline, result.describe()
