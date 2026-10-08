"""Fixtures for the Docker-backed marketplace runtime-environment matrix.

These tests are opt-in because they build images and download packages:

    OPENSTUDIO_AI_RUNTIME_ENV_TESTS=1 uv run --extra dev pytest tests/runtime_envs -v

Select environments with ``-m`` / ``-k`` (for example ``-k native``). Set
``OPENSTUDIO_AI_RUNTIME_ENV_SKIP_BUILD=1`` to reuse already-built images.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from llm_setup_agent import load_llm_settings
from runtime_env_harness import ENABLE_VAR, PROFILES, REPO_ROOT, RuntimeEnv

REPORT_PATH = Path(
    os.getenv(
        "OPENSTUDIO_AI_RUNTIME_ENV_REPORT",
        REPO_ROOT / "outputs" / "runtime_envs" / "report.json",
    )
)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "runtime_env(profile): Docker-backed marketplace runtime environment test",
    )
    config.addinivalue_line(
        "markers",
        "runtime_env_agent: a real model follows the setup skill (needs LLM_API_KEY)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    reason = None
    if os.getenv(ENABLE_VAR) != "1":
        reason = f"set {ENABLE_VAR}=1 to run Docker runtime-environment tests"
    elif shutil.which("docker") is None:
        reason = "docker is not available"
    agent_reason = reason or _agent_skip_reason()
    for item in items:
        if reason and item.get_closest_marker("runtime_env"):
            item.add_marker(pytest.mark.skip(reason=reason))
        elif agent_reason and item.get_closest_marker("runtime_env_agent"):
            item.add_marker(pytest.mark.skip(reason=agent_reason))


def _agent_skip_reason() -> str | None:
    if load_llm_settings() is None:
        return (
            "set LLM_API_KEY (tests/runtime_envs/.env) to run model-driven setup tests"
        )
    try:
        import openai  # noqa: F401
    except ImportError:
        return "install openai (uv run --with openai==2.6.1 ...) for model-driven tests"
    return None


@pytest.fixture(scope="session")
def llm_settings() -> dict[str, str]:
    settings = load_llm_settings()
    assert settings is not None
    return settings


@pytest.fixture(scope="session")
def observations() -> Iterator[list[dict[str, Any]]]:
    """Facts measured in each environment, written to a JSON report at session end."""
    records: list[dict[str, Any]] = []
    yield records
    if records:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(records, indent=2, default=str) + "\n")


@pytest.fixture
def observe(
    request: pytest.FixtureRequest, observations: list[dict[str, Any]]
) -> Callable[..., None]:
    def record(profile: str, **facts: Any) -> None:
        observations.append({"test": request.node.nodeid, "profile": profile, **facts})
        for key, value in facts.items():
            request.node.user_properties.append((key, value))

    return record


@pytest.fixture(scope="session")
def env_pool() -> Iterator[Callable[..., RuntimeEnv]]:
    """Start profile containers on demand.

    ``shared=True`` (default) reuses one container per profile for the session.
    ``shared=False`` gives a pristine container -- a cold uv cache -- that is
    removed at session end.
    """
    shared: dict[tuple[str, str | None], RuntimeEnv] = {}
    private: list[RuntimeEnv] = []

    def get(
        name: str, *, shared_container: bool = True, network: str | None = None
    ) -> RuntimeEnv:
        profile = PROFILES[name]
        key = (name, network)
        if shared_container and key in shared:
            return shared[key]
        env = RuntimeEnv.start(profile, network=network)
        if shared_container:
            shared[key] = env
        else:
            private.append(env)
        return env

    yield get
    for env in [*shared.values(), *private]:
        env.stop()
