#!/usr/bin/env bash
# Start the 工地看板 FastAPI backend (REST + SSE push channel).
# Usage: ./run_backend.sh [host] [port]
set -e
cd "$(dirname "$0")"
source myenv/bin/activate
HOST="${1:-0.0.0.0}"
PORT="${2:-8000}"
echo "Site Board API -> http://${HOST}:${PORT}  (docs: /docs)"
exec uvicorn src.backend.app:app --host "$HOST" --port "$PORT"
