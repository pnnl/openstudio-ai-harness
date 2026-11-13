#!/usr/bin/env bash
# Launch the optional NLR openstudio-mcp server against a local, gitignored
# sandbox inside this repository. openstudio-mcp is expected as a sibling
# clone (../openstudio-mcp) with its own venv (`uv sync` there).
#
# Usage:
#   scripts/start_openstudio_mcp.sh --setup      # stage the sandbox (idempotent)
#   scripts/start_openstudio_mcp.sh --check      # verify binary + sandbox, then exit
#   scripts/start_openstudio_mcp.sh              # stdio (Claude Code .mcp.json)
#   scripts/start_openstudio_mcp.sh --http 10220 # streamable-http (manual use)
#
# Native (non-Docker) runs need two things the Docker image bakes in:
#   - OSCLI_GEMFILE / OSCLI_GEM_PATH: an empty Gemfile is enough; the
#     openstudio CLI falls back to its embedded openstudio-standards gem.
#   - COMMON_MEASURES_DIR: openstudio-common-measures-gem measures
#     (change_building_location and other common-measure tools).
# ComStock and gbXML measures are not staged; tools that need them fail.
#
# OPENSTUDIO_MCP_SANDBOX may point at a throwaway directory (the interop evals
# use one per run). The 150 MB common-measures download is kept once in
# OPENSTUDIO_MCP_CACHE and symlinked into each sandbox, which is staged
# automatically on start once `--setup` has populated the cache.
set -euo pipefail

HARNESS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NLR_ROOT="${OPENSTUDIO_MCP_ROOT:-$HARNESS_ROOT/../openstudio-mcp}"
SANDBOX="${OPENSTUDIO_MCP_SANDBOX:-$HARNESS_ROOT/.openstudio_mcp_sandbox}"
CACHE="${OPENSTUDIO_MCP_CACHE:-$HARNESS_ROOT/.openstudio_mcp_sandbox}"
COMMON_MEASURES_TAG="${COMMON_MEASURES_TAG:-v0.12.3}"

setup() {
  mkdir -p "$SANDBOX"/{inputs,runs,measures,oscli/gems}
  [ -f "$SANDBOX/oscli/Gemfile" ] || printf "source 'https://rubygems.org'\n" > "$SANDBOX/oscli/Gemfile"
  if [ ! -d "$CACHE/common-measures" ]; then
    local tmp
    tmp="$(mktemp -d)"
    curl -fsSL "https://github.com/NatLabRockies/openstudio-common-measures-gem/archive/refs/tags/${COMMON_MEASURES_TAG}.tar.gz" \
      | tar xz -C "$tmp"
    mkdir -p "$CACHE"
    mv "$tmp"/openstudio-common-measures-gem-*/lib/measures "$CACHE/common-measures"
    rm -rf "$tmp"
  fi
  if [ ! -e "$SANDBOX/common-measures" ]; then
    ln -s "$CACHE/common-measures" "$SANDBOX/common-measures"
  fi
  echo "Sandbox ready at $SANDBOX" >&2
}

case "${1:-}" in
  --setup) setup; exit 0 ;;
  --check) CHECK_ONLY=1 ;;
  --http)
    export MCP_TRANSPORT=http
    export MCP_AUTH="${MCP_AUTH:-none}"
    export MCP_HOST="${MCP_HOST:-127.0.0.1}"
    export MCP_PORT="${2:-${MCP_PORT:-10220}}"
    ;;
  "") ;;
  *) echo "unknown argument: $1" >&2; exit 2 ;;
esac

BIN="$NLR_ROOT/.venv/bin/openstudio-mcp"
if [ ! -x "$BIN" ]; then
  echo "openstudio-mcp not found at $BIN; clone it as a sibling and run 'uv sync' there." >&2
  exit 1
fi
if [ ! -d "$CACHE/common-measures" ]; then
  echo "common-measures not cached at $CACHE; run once: scripts/start_openstudio_mcp.sh --setup" >&2
  exit 1
fi
if [ -n "${CHECK_ONLY:-}" ]; then
  echo "ok: $BIN, cache $CACHE" >&2
  exit 0
fi
# Cheap and idempotent: (re)creates the per-run sandbox dirs and the symlink.
setup 2>/dev/null

export OPENSTUDIO_MCP_RUN_ROOT="$SANDBOX/runs"
export OPENSTUDIO_MCP_INPUT_ROOT="$SANDBOX/inputs"
export OPENSTUDIO_MCP_MEASURES_DIR="$SANDBOX/measures"
export OSCLI_GEMFILE="$SANDBOX/oscli/Gemfile"
export OSCLI_GEM_PATH="$SANDBOX/oscli/gems"
export COMMON_MEASURES_DIR="$SANDBOX/common-measures"
export OSMCP_SANDBOX="${OSMCP_SANDBOX:-off}"

cd "$HARNESS_ROOT"
exec "$BIN"
