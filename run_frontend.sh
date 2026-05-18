#!/usr/bin/env bash
# Start the 工地看板 PyQt5 standalone board.
# Usage: ./run_frontend.sh [--fullscreen]
# Env:   CARDASH_API   API base URL (default http://127.0.0.1:8000)
set -e
cd "$(dirname "$0")"
source myenv/bin/activate
export CARDASH_API="${CARDASH_API:-http://127.0.0.1:8000}"
echo "Board UI -> API ${CARDASH_API}"
exec python -m src.frontend.main "$@"
