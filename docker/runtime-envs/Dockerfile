# syntax=docker/dockerfile:1.7
#
# Runtime-environment matrix for the marketplace `uvx` launch contract.
#
# Each final stage is one "user machine". Host-side pytest
# (tests/runtime_envs/) builds a stage, keeps a container running, and launches
# the MCP server inside it with `docker exec -i` using the exact command from the
# exported plugin's `.mcp.json` -- the same way Claude Code or Codex would.
#
# Build one environment manually:
#   docker build -f docker/runtime-envs/Dockerfile --target uv-only \
#       -t openstudio-ai-runtime-env:uv-only .
#
# Do not add a --platform override: every base image used here publishes native
# linux/amd64 and linux/arm64 manifests, and `openstudio` publishes wheels for
# both architectures.

ARG UV_VERSION=0.12.5
ARG NATIVE_OPENSTUDIO_VERSION=3.11.0

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv-bin

# ---------------------------------------------------------------------------
# builder: produce the plugin exports and wheels every environment consumes.
#
#   /exports/as-is/        exports exactly as this checkout would publish them
#                          (pin = pyproject version, resolved from public PyPI)
#   /exports/release-sim/  exports after a simulated release: the version is
#                          bumped to SIM_VERSION and the matching wheel is
#                          provided through UV_FIND_LINKS=/opt/wheels
#   /wheels/               the simulated-release openstudio-ai wheel
#   /wheelhouse/           every wheel needed to run offline (air-gap profile)
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder
COPY --from=uv-bin /uv /uvx /usr/local/bin/
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /src
COPY . .

RUN uv sync --frozen --no-install-project --python /usr/local/bin/python3

# Writes the launch file for an export: `uvx` arguments without the final
# console-script name, so a stage can run other runtime commands with the same pin.
RUN cat > /usr/local/bin/export-plugins <<'EOF'
#!/bin/sh
set -eu
dest="$1"
uv run --frozen --no-sync python -m adapters.claude_code_adapter export-plugin \
    --output-dir "$dest/claude" --runtime-mode marketplace --force
uv run --frozen --no-sync python -m adapters.codex_adapter export-plugin \
    --output-dir "$dest/codex" --runtime-mode marketplace --force
uv run --frozen --no-sync python - "$dest" <<'PY'
import json, sys
from pathlib import Path
dest = Path(sys.argv[1])
config = json.loads((dest / "claude/openstudio-ai/.mcp.json").read_text())
server = next(iter(config["mcpServers"].values()))
args = server["args"]
command_index = args.index("openstudio-ai-mcp")
(dest / "uvx-spec-args").write_text(" ".join(args[:command_index]) + "\n")
(dest / "plugin-version").write_text(server["env"]["OPENSTUDIO_AI_PLUGIN_VERSION"] + "\n")
PY
EOF
RUN chmod +x /usr/local/bin/export-plugins && export-plugins /exports/as-is

ARG SIM_VERSION=0.4.1.dev0
RUN sed -i "0,/^version = \".*\"/s//version = \"${SIM_VERSION}\"/" pyproject.toml \
    && uv build --wheel --out-dir /wheels \
    && export-plugins /exports/release-sim \
    && test "$(cat /exports/release-sim/plugin-version)" = "${SIM_VERSION}"

# Offline wheelhouse for the simulated release on this architecture and Python.
RUN python -m pip download --only-binary=:all: --dest /wheelhouse \
        /wheels/openstudio_ai-*.whl "openstudio==3.11.0" \
    && cp /wheels/*.whl /wheelhouse/

# ---------------------------------------------------------------------------
# Shared layer for every user machine: exports, the simulated-release wheel, and
# a non-root modeler account. UV_FIND_LINKS stands in for "the matching
# openstudio-ai release has been published"; it does not shadow PyPI for the
# as-is pin because /opt/wheels contains only SIM_VERSION.
# ---------------------------------------------------------------------------
FROM scratch AS artifacts
COPY --from=builder /exports /opt/exports
COPY --from=builder /wheels /opt/wheels
COPY --from=builder /wheelhouse /opt/wheelhouse

# ---------------------------------------------------------------------------
# uv-only: a clean Linux box with only uv. No Python, no OpenStudio, cold cache.
# This is the minimum the marketplace contract claims to require.
# ---------------------------------------------------------------------------
FROM debian:bookworm-slim AS uv-only
COPY --from=uv-bin /uv /uvx /usr/local/bin/
COPY --from=artifacts /opt /opt
RUN useradd --create-home --shell /bin/sh modeler
ENV UV_FIND_LINKS=/opt/wheels OPENSTUDIO_AI_ENV_PROFILE=uv-only
USER modeler
WORKDIR /home/modeler/project
CMD ["sleep", "infinity"]

# uv-warm: uv-only after the setup skill's `install-runtime` step filled uv's
# cache. Used for startup-time and --network none checks.
FROM uv-only AS uv-warm
ENV OPENSTUDIO_AI_ENV_PROFILE=uv-warm
RUN uvx $(cat /opt/exports/release-sim/uvx-spec-args) openstudio-ai install-runtime

# ---------------------------------------------------------------------------
# system-py310: a machine with an older system Python and a project .venv that
# lacks `openstudio` -- the situation the old Python-discovery step guessed at.
# ---------------------------------------------------------------------------
FROM python:3.10-slim-bookworm AS system-py310
ARG UV_VERSION
RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}"
COPY --from=artifacts /opt /opt
RUN useradd --create-home --shell /bin/sh modeler
ENV UV_FIND_LINKS=/opt/wheels OPENSTUDIO_AI_ENV_PROFILE=system-py310
USER modeler
WORKDIR /home/modeler/project
RUN python -m venv .venv
CMD ["sleep", "infinity"]

# ---------------------------------------------------------------------------
# no-uv: Python and pipx, but no uv. The setup skill must bootstrap uv with
# `pipx install uv`; pipx's bin dir is deliberately NOT on PATH, as on a
# machine where `pipx ensurepath` was never run.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS no-uv
RUN python -m pip install --no-cache-dir pipx
COPY --from=artifacts /opt /opt
RUN useradd --create-home --shell /bin/sh modeler
ENV UV_FIND_LINKS=/opt/wheels OPENSTUDIO_AI_ENV_PROFILE=no-uv
USER modeler
WORKDIR /home/modeler/project
CMD ["sleep", "infinity"]

# ---------------------------------------------------------------------------
# legacy-pipx: a user who followed the pre-uvx instructions. An older
# openstudio-ai runtime is pipx-installed and on PATH, and uv is also present.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS legacy-pipx
ARG UV_VERSION
ARG LEGACY_RUNTIME_VERSION=0.3.1
RUN python -m pip install --no-cache-dir pipx "uv==${UV_VERSION}"
COPY --from=artifacts /opt /opt
RUN useradd --create-home --shell /bin/sh modeler
USER modeler
ENV PATH=/home/modeler/.local/bin:${PATH} \
    UV_FIND_LINKS=/opt/wheels \
    OPENSTUDIO_AI_ENV_PROFILE=legacy-pipx \
    LEGACY_RUNTIME_VERSION=${LEGACY_RUNTIME_VERSION}
RUN pipx install "openstudio-ai==${LEGACY_RUNTIME_VERSION}"
WORKDIR /home/modeler/project
CMD ["sleep", "infinity"]

# ---------------------------------------------------------------------------
# native-openstudio: uv plus a native OpenStudio CLI. Build with
# --build-arg NATIVE_OPENSTUDIO_VERSION=3.10.0 to model a user whose CLI is
# older than the pinned Python SDK (3.11.0).
# ---------------------------------------------------------------------------
FROM nrel/openstudio:${NATIVE_OPENSTUDIO_VERSION} AS native-openstudio
ARG NATIVE_OPENSTUDIO_VERSION
COPY --from=uv-bin /uv /uvx /usr/local/bin/
COPY --from=artifacts /opt /opt
RUN useradd --create-home --shell /bin/sh modeler
ENV UV_FIND_LINKS=/opt/wheels \
    OPENSTUDIO_AI_ENV_PROFILE=native-openstudio \
    NATIVE_OPENSTUDIO_VERSION=${NATIVE_OPENSTUDIO_VERSION}
USER modeler
WORKDIR /home/modeler/project
RUN uvx $(cat /opt/exports/release-sim/uvx-spec-args) openstudio-ai install-runtime
CMD ["sleep", "infinity"]

# ---------------------------------------------------------------------------
# airgap: an organization without public PyPI. Python 3.12 is provisioned by IT
# (`uv python install` at build time), packages come only from a local
# wheelhouse, and tests run the container with --network none.
# UV_OFFLINE is required: `uvx` still queries PyPI under UV_NO_INDEX=1 alone
# (pinned by test_uv_no_index_env_alone_still_contacts_pypi).
# ---------------------------------------------------------------------------
FROM debian:bookworm-slim AS airgap
COPY --from=uv-bin /uv /uvx /usr/local/bin/
COPY --from=artifacts /opt /opt
RUN useradd --create-home --shell /bin/sh modeler
USER modeler
RUN uv python install 3.12
ENV UV_OFFLINE=1 \
    UV_FIND_LINKS=/opt/wheelhouse \
    UV_PYTHON_DOWNLOADS=never \
    OPENSTUDIO_AI_ENV_PROFILE=airgap
WORKDIR /home/modeler/project
CMD ["sleep", "infinity"]
