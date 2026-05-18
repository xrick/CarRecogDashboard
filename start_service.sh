#!/usr/bin/env bash
# 工地看板系統 — 一鍵啟動（後端 FastAPI + 前端 PyQt 看板，背景執行）
#
# Usage:  ./start_service.sh [host] [port] [-- <frontend args>]
#   host/port  後端綁定位址（預設 0.0.0.0 8000）
#   -- ...     之後的參數原樣傳給前端，例如:  ./start_service.sh -- --fullscreen
#
# Env passthrough:  CARDASH_API CARDASH_DB CARDASH_CONFIG（沿用既有設定）
# PID:  run/backend.pid  run/frontend.pid     Log:  logs/backend.log  logs/frontend.log
# 停止:  ./stop_service.sh
set -eo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
RUN_DIR="$ROOT/run"
LOG_DIR="$ROOT/logs"
mkdir -p "$RUN_DIR" "$LOG_DIR"

HOST="0.0.0.0"; PORT="8000"; FE_ARGS=()
# parse: [host] [port] [-- fe args...]
while [[ $# -gt 0 ]]; do
  case "$1" in
    --) shift; FE_ARGS=("$@"); break ;;
    *)  if [[ "$HOST" == "0.0.0.0" && "$1" != "0.0.0.0" && -z "${_HSET:-}" ]]; then
          HOST="$1"; _HSET=1
        else PORT="$1"; fi
        shift ;;
  esac
done

is_alive() { [[ -f "$1" ]] && kill -0 "$(cat "$1" 2>/dev/null)" 2>/dev/null; }

if is_alive "$RUN_DIR/backend.pid" || is_alive "$RUN_DIR/frontend.pid"; then
  echo "⚠ 服務似乎已在執行中（PID 檔仍有效）。請先 ./stop_service.sh 再啟動。"
  exit 1
fi

# shellcheck disable=SC1091
source myenv/bin/activate

# ---- backend ----------------------------------------------------------
echo "▶ 啟動後端  uvicorn  http://${HOST}:${PORT}  (docs: /docs)"
nohup uvicorn src.backend.app:app --host "$HOST" --port "$PORT" \
      > "$LOG_DIR/backend.log" 2>&1 &
echo $! > "$RUN_DIR/backend.pid"

# 前端打 API 用 loopback（HOST 可能是 0.0.0.0）
export CARDASH_API="${CARDASH_API:-http://127.0.0.1:${PORT}}"

# ---- wait for backend health (最多 ~25s；逾時仍續，前端可容忍 API 未就緒) --
printf "  等待後端就緒"
for i in $(seq 1 50); do
  if curl -fsS -o /dev/null "http://127.0.0.1:${PORT}/" 2>/dev/null; then
    echo "  ✓ 後端已就緒"; break
  fi
  is_alive "$RUN_DIR/backend.pid" || { echo;
    echo "✗ 後端啟動失敗，請看 logs/backend.log"; tail -n 20 "$LOG_DIR/backend.log";
    rm -f "$RUN_DIR/backend.pid"; exit 1; }
  printf "."; sleep 0.5
  [[ $i -eq 50 ]] && echo "  (逾時，仍繼續；前端會自動重試)"
done

# ---- frontend (PyQt 看板) --------------------------------------------
[[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" && "${QT_QPA_PLATFORM:-}" != "offscreen" ]] && \
  echo "⚠ 未偵測到 \$DISPLAY，PyQt 看板可能無法顯示（如為純伺服器，設 QT_QPA_PLATFORM=offscreen 或改用遠端桌面）。"
echo "▶ 啟動前端看板  (API ${CARDASH_API})  args: ${FE_ARGS[*]:-<none>}"
nohup python -m src.frontend.main "${FE_ARGS[@]}" \
      > "$LOG_DIR/frontend.log" 2>&1 &
echo $! > "$RUN_DIR/frontend.pid"
sleep 1
is_alive "$RUN_DIR/frontend.pid" || { echo "✗ 前端啟動失敗，請看 logs/frontend.log";
  tail -n 20 "$LOG_DIR/frontend.log"; }

echo
echo "✅ 已於背景啟動："
echo "   後端 PID $(cat "$RUN_DIR/backend.pid")  · log: logs/backend.log"
echo "   前端 PID $(cat "$RUN_DIR/frontend.pid") · log: logs/frontend.log"
echo "   API: ${CARDASH_API}/docs    停止: ./stop_service.sh"
