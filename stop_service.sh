#!/usr/bin/env bash
# 工地看板系統 — 停止（前端看板 + 後端 API）
# 依 run/*.pid 優雅關閉（SIGTERM → 等待 → SIGKILL）；PID 檔遺失時以 pattern 收尾。
set -eo pipefail
cd "$(dirname "$0")"
RUN_DIR="$(pwd)/run"

stop_pid() {
  local name="$1" pidfile="$2" pid
  if [[ -f "$pidfile" ]] && pid="$(cat "$pidfile" 2>/dev/null)" && \
     [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "▶ 停止 ${name} (PID ${pid}) …"
    kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
    if kill -0 "$pid" 2>/dev/null; then
      echo "  仍未結束 → SIGKILL"; kill -KILL "$pid" 2>/dev/null || true
    fi
    echo "  ✓ ${name} 已停止"
  else
    echo "· ${name} 無有效 PID（未執行或 PID 檔遺失）"
  fi
  rm -f "$pidfile"
}

# 先停前端再停後端（與啟動相反順序）
stop_pid "前端看板" "$RUN_DIR/frontend.pid"
stop_pid "後端 API" "$RUN_DIR/backend.pid"

# fallback：清掉可能殘留的孤兒程序（精確 pattern，不會誤殺本腳本）
for pat in "uvicorn src.backend.app:app" "python -m src.frontend.main"; do
  if pgrep -f "$pat" >/dev/null 2>&1; then
    echo "▶ 清理殘留：$pat"
    pkill -TERM -f "$pat" 2>/dev/null || true
    sleep 1
    pkill -KILL -f "$pat" 2>/dev/null || true
  fi
done

echo "✅ 工地看板系統已停止。"
