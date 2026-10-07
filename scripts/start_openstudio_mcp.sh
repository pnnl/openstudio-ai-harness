#!/usr/bin/env bash
# Launch the optional NLR openstudio-mcp server against a local, gitignored
# sandbox inside this repository. openstudio-mcp is expected as a sibling
# clone (../openstudio-mcp) with its own venv (`uv sync` there).
#
# Usage:
#   scripts/start_openstudio_mcp.sh --setup      # one-time sandbox staging
#   scripts/start_openstudio_mcp.sh              # stdio (Claude Code .mcp.json)
#   scripts/start_openstudio_mcp.sh --http 10220 # streamable-http (evals)
#
# Native (non-Docker) runs need two things the Docker image bakes in:
#   - OSCLI_GEMFILE / OSCLI_GEM_PATH: an empty Gemfile is enough; the
#     openstudio CLI falls back to its embedded openstudio-standards gem.
#   - COMMON_MEASURES_DIR: openstudio-common-measures-gem measures
#     (change_building_location and other common-measure tools).
# ComStock and gbXML measures are not staged; tools that need them fail.
set -euo pipefail

HARNESS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NLR_ROOT="${OPENSTUDIO_MCP_ROOT:-$HARNESS_ROOT/../openstudio-mcp}"
SANDBOX="${OPENSTUDIO_MCP_SANDBOX:-$HARNESS_ROOT/.openstudio_mcp_sandbox}"
COMMON_MEASURES_TAG="${COMMON_MEASURES_TAG:-v0.12.3}"

setup() {
  mkdir -p "$SANDBOX"/{inputs,runs,measures,oscli/gems}
  [ -f "$SANDBOX/oscli/Gemfile" ] || printf "source 'https://rubygems.org'\n" > "$SANDBOX/oscli/Gemfile"
  if [ ! -d "$SANDBOX/common-measures" ]; then
    local tmp
    tmp="$(mktemp -d)"
    curl -fsSL "https://github.com/NatLabRockies/openstudio-common-measures-gem/archive/refs/tags/${COMMON_MEASURES_TAG}.tar.gz" \
      | tar xz -C "$tmp"
    mv "$tmp"/openstudio-common-measures-gem-*/lib/measures "$SANDBOX/common-measures"
    rm -rf "$tmp"
  fi
  echo "Sandbox ready at $SANDBOX" >&2
}

case "${1:-}" in
  --setup) setup; exit 0 ;;
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
if [ ! -f "$SANDBOX/oscli/Gemfile" ]; then
  echo "Sandbox not staged; run: scripts/start_openstudio_mcp.sh --setup" >&2
  exit 1
fi

export OPENSTUDIO_MCP_RUN_ROOT="$SANDBOX/runs"
export OPENSTUDIO_MCP_INPUT_ROOT="$SANDBOX/inputs"
export OPENSTUDIO_MCP_MEASURES_DIR="$SANDBOX/measures"
export OSCLI_GEMFILE="$SANDBOX/oscli/Gemfile"
export OSCLI_GEM_PATH="$SANDBOX/oscli/gems"
export COMMON_MEASURES_DIR="$SANDBOX/common-measures"
export OSMCP_SANDBOX="${OSMCP_SANDBOX:-off}"

cd "$HARNESS_ROOT"
exec "$BIN"
