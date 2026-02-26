#!/usr/bin/env bash
set -euo pipefail

# 停止 OpenClaw 运行时所有相关服务

echo "Stopping OpenClaw runtime services..."

# 杀掉 bridge server
pkill -f "openclaw_bridge_server.py" && echo "✓ bridge server stopped" || true

# 杀掉 mock model server
pkill -f "openai_mock_server.py" && echo "✓ mock model server stopped" || true

# 杀掉 local provider server
pkill -f "providers/openvino_openai_provider/server.py" && echo "✓ local provider stopped" || true

# 杀掉 openclaw gateway
pkill -f "pnpm openclaw gateway" && echo "✓ gateway stopped" || true
pkill -f "openclaw-gateway" && echo "✓ gateway daemon stopped" || true

echo "All services stopped."