#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CLIENT_SCRIPT="$SCRIPT_DIR/ui.py"
LOG_DIR="$REPO_ROOT/logs"
STREAMLIT_PORT="${STREAMLIT_SERVER_PORT:-8504}"
mkdir -p "$LOG_DIR"

uv run --project "$SCRIPT_DIR" streamlit run "$CLIENT_SCRIPT" \
  --server.address 0.0.0.0 \
  --server.port "$STREAMLIT_PORT" \
  --server.headless true > "$LOG_DIR/client.log" 2>&1 &
CLIENT_PID=$!

echo "Client PID: $CLIENT_PID"

cleanup() {
  kill $CLIENT_PID 2>/dev/null || true
}

trap cleanup SIGINT SIGTERM EXIT
while kill -0 "$CLIENT_PID" 2>/dev/null; do
  sleep 1
done
