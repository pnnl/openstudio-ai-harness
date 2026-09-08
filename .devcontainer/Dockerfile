# The published Python image has native linux/amd64 and linux/arm64 manifests.
# Do not add a --platform override: Docker should select the host-native image.
FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

# Chromium's Linux runtime libraries. The browser binary itself is downloaded by
# the post-create Playwright command after the project environment is installed.
RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get update \
    && apt-get install --no-install-recommends --yes \
        libasound2 \
        libatk-bridge2.0-0 \
        libatk1.0-0 \
        libatspi2.0-0 \
        libcairo2 \
        libcups2 \
        libdbus-1-3 \
        libgbm1 \
        libgtk-3-0 \
        libpango-1.0-0 \
        libx11-xcb1 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxkbcommon0 \
        libxrandr2 \
    && rm -rf /var/lib/apt/lists/*

# Install from PyPI rather than a Dev Container Feature on GHCR so a developer
# needs access only to the Python package index after the base image is pulled.
ARG UV_VERSION=0.12.5
RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}"
