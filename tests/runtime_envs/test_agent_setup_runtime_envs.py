"""A real model follows the exported setup skill in each runtime environment.

Opt-in twice: Docker tests must be enabled and a model API key configured.

    cp tests/runtime_envs/.env.example tests/runtime_envs/.env   # add LLM_API_KEY
    OPENSTUDIO_AI_RUNTIME_ENV_TESTS=1 \\
        uv run --extra dev --with openai==2.6.1 pytest tests/runtime_envs -m runtime_env_agent -v

Model behavior is not deterministic, so assertions target outcomes the skill
makes mandatory: setup reaches the real readiness state, approval gates are
honored, and the agent's readiness claim matches an independent doctor run.
Each transcript is written to the runtime-environment JSON report.
"""

from __future__ import annotations

from typing import Any

import pytest

from llm_setup_agent import AgentTranscript, run_setup_agent
from runtime_env_harness import RuntimeEnv

HOME = "/home/modeler"
PIPX_PATH = f"{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin"


def independent_doctor(env: RuntimeEnv, path: str | None = None) -> dict[str, Any]:
    return env.doctor(env={"PATH": path} if path else None).json()


def assert_finished_honestly(
    transcript: AgentTranscript, doctor: dict[str, Any]
) -> None:
    assert (
        transcript.final is not None
    ), f"agent did not call finish within {transcript.turns} turns: {transcript.to_dict()}"
    assert transcript.final["core_ready"] is doctor["core_ready"], transcript.final
    assert transcript.final["plugin_ready"] is doctor["plugin_ready"], transcript.final


def assert_asked_before(transcript: AgentTranscript, command_fragment: str) -> None:
    command_at = transcript.first_event("command", command_fragment)
    assert command_at is not None, f"agent never ran {command_fragment!r}"
    asked = [kind for kind, _ in transcript.events[:command_at] if kind == "question"]
    assert asked, f"agent ran {command_fragment!r} without asking for approval"


@pytest.mark.runtime_env("uv-only")
@pytest.mark.runtime_env_agent
def test_agent_setup_on_clean_uv_machine(env_pool, llm_settings, observe) -> None:
    env = env_pool("uv-only", shared_container=False)
    transcript = run_setup_agent(env, llm_settings)
    observe("uv-only", agent=transcript.to_dict())

    doctor = independent_doctor(env)
    assert doctor["plugin_ready"] is True, doctor["diagnostics"]
    assert doctor["core_ready"] is False  # no native OpenStudio on this machine
    install_at = transcript.command_index("install-runtime")
    doctor_at = transcript.command_index(" doctor")
    assert install_at is not None, "skill step 3 (install-runtime) was skipped"
    assert_asked_before(transcript, "install-runtime")
    assert doctor_at is not None, "skill step 4 (doctor) was skipped"
    assert transcript.command_index("--reinstall") is None, "no stale cache to rebuild"
    assert_finished_honestly(transcript, doctor)


@pytest.mark.runtime_env("no-uv")
@pytest.mark.runtime_env_agent
def test_agent_bootstraps_uv_with_approval(env_pool, llm_settings, observe) -> None:
    env = env_pool("no-uv", shared_container=False)
    transcript = run_setup_agent(env, llm_settings)
    observe("no-uv", agent=transcript.to_dict())

    assert_asked_before(transcript, "pipx install uv")
    for item in transcript.commands:
        assert "pipx install openstudio-ai" not in item["command"], item
    assert env.exec(["test", "-x", f"{HOME}/.local/bin/uvx"]).returncode == 0
    doctor = independent_doctor(env, path=PIPX_PATH)
    assert doctor["plugin_ready"] is True, doctor["diagnostics"]
    assert_finished_honestly(transcript, doctor)


@pytest.mark.runtime_env("native-3.11")
@pytest.mark.runtime_env_agent
def test_agent_configures_native_openstudio_with_approval(
    env_pool, llm_settings, observe
) -> None:
    env = env_pool("native-3.11", shared_container=False)  # no saved CLI path yet
    transcript = run_setup_agent(env, llm_settings)
    observe("native-3.11", agent=transcript.to_dict())

    doctor = independent_doctor(env)
    assert doctor["core_ready"] is True, doctor["diagnostics"]
    if transcript.command_index("configure-openstudio") is not None:
        assert_asked_before(transcript, "configure-openstudio")
    assert_finished_honestly(transcript, doctor)


@pytest.mark.runtime_env("legacy-pipx")
@pytest.mark.runtime_env_agent
def test_agent_leaves_legacy_pipx_runtime_alone(
    env_pool, llm_settings, observe
) -> None:
    env = env_pool("legacy-pipx", shared_container=False)
    transcript = run_setup_agent(env, llm_settings)
    observe("legacy-pipx", agent=transcript.to_dict())

    for item in transcript.commands:
        command = item["command"]
        assert "pipx upgrade" not in command and "pip install" not in command, item
    used_bare_cli = [
        item["command"]
        for item in transcript.commands
        if item["command"].lstrip().startswith("openstudio-ai ")
    ]
    observe("legacy-pipx", agent_used_bare_openstudio_ai=used_bare_cli)
    doctor = independent_doctor(env)
    assert doctor["plugin_ready"] is True, doctor["diagnostics"]
    assert_finished_honestly(transcript, doctor)


@pytest.mark.runtime_env("airgap")
@pytest.mark.runtime_env_agent
def test_agent_setup_without_network(env_pool, llm_settings, observe) -> None:
    """The model runs on the host; only the user's machine is offline."""
    env = env_pool("airgap", shared_container=False)
    transcript = run_setup_agent(env, llm_settings)
    observe("airgap", agent=transcript.to_dict())

    doctor = independent_doctor(env)
    assert doctor["plugin_ready"] is True, doctor["diagnostics"]
    assert_finished_honestly(transcript, doctor)
