# The published Python image has native linux/amd64 and linux/arm64 manifests.
# Do not add a --platform override: Docker should select the host-native image.
FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

# Install from PyPI rather than a Dev Container Feature on GHCR so a developer
# needs access only to the Python package index after the base image is pulled.
ARG UV_VERSION=0.12.5
RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}"
