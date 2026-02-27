#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

cleanup_port() {
  local port="$1"
  local pids
  pids="$(lsof -ti:"$port" 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "[stop] kill port $port -> $pids"
    kill -9 $pids 2>/dev/null || true
  fi
}

echo "[stop] killing runtime processes..."
pkill -f 'openclaw_bridge_server.py' >/dev/null 2>&1 || true
pkill -f 'openvino_openai_provider/server.py' >/dev/null 2>&1 || true
pkill -f 'openai_mock_server.py' >/dev/null 2>&1 || true
pkill -f 'pnpm openclaw gateway' >/dev/null 2>&1 || true
pkill -f 'openclaw-gateway' >/dev/null 2>&1 || true
pkill -f 'scripts/start_openclaw_runtime.sh' >/dev/null 2>&1 || true
pkill -f 'scripts/test_openclaw_gateway_e2e.sh' >/dev/null 2>&1 || true

cleanup_port 8099
cleanup_port 18080
cleanup_port 18789

echo "[stop] remaining related processes:"
pgrep -af 'openclaw_bridge_server.py|openvino_openai_provider/server.py|openai_mock_server.py|pnpm openclaw gateway|openclaw-gateway' || true

echo "[stop] done"
