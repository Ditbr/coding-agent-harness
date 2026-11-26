#!/usr/bin/env bash
# Manage a persistent local SSH tunnel (127.0.0.1:23750) to a remote Docker API.
# Configure connection details via environment variables or local `.env` (gitignored):
#   WIN_DOCKER_MODE=ecs|tailscale
#   WIN_DOCKER_HOST=<relay-or-remote-host>
#   WIN_DOCKER_USER=<ssh-user>
#   WIN_DOCKER_SSH_PORT=22
#   WIN_DOCKER_LOCAL_PORT=23750
#   WIN_DOCKER_REMOTE_PORT=23751
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${WIN_DOCKER_ENV_FILE:-${SCRIPT_DIR}/../.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

MODE="${WIN_DOCKER_MODE:-ecs}"
if [[ "$MODE" == "ecs" ]]; then
  WIN_USER="${WIN_DOCKER_USER:-root}"
  WIN_HOST="${WIN_DOCKER_HOST:-}"
  WIN_PORT="${WIN_DOCKER_SSH_PORT:-22}"
  REMOTE_PORT="${WIN_DOCKER_REMOTE_PORT:-23751}"
elif [[ "$MODE" == "tailscale" ]]; then
  WIN_USER="${WIN_DOCKER_USER:-harness}"
  WIN_HOST="${WIN_DOCKER_HOST:-}"
  WIN_PORT="${WIN_DOCKER_SSH_PORT:-22}"
  REMOTE_PORT="${WIN_DOCKER_REMOTE_PORT:-2375}"
else
  echo "Unknown WIN_DOCKER_MODE='$MODE' (use 'ecs' or 'tailscale')." >&2
  exit 1
fi

LOCAL_PORT="${WIN_DOCKER_LOCAL_PORT:-23750}"
CONTEXT_NAME="${WIN_DOCKER_CONTEXT:-win-docker}"
SSH_KEY="${WIN_DOCKER_SSH_KEY:-$HOME/.ssh/id_ed25519}"
PID_FILE="/tmp/win-docker-tunnel.pid"
LOG_FILE="/tmp/win-docker-tunnel.log"
DOCKER_BIN="$(command -v docker || echo /Applications/Docker.app/Contents/Resources/bin/docker)"

start_tunnel() {
  if [[ -z "$WIN_HOST" ]]; then
    echo "ERROR: WIN_DOCKER_HOST is not set. Export WIN_DOCKER_HOST or set it in .env." >&2
    return 1
  fi

  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Tunnel already running (PID $(cat "$PID_FILE")) on 127.0.0.1:${LOCAL_PORT}."
  else
    if [[ "$WIN_HOST" == 100.* ]] && [[ -x "/Applications/Tailscale.app/Contents/MacOS/Tailscale" ]]; then
      echo "Warming up Tailscale path to ${WIN_HOST}..."
      /Applications/Tailscale.app/Contents/MacOS/Tailscale ping -c 2 "${WIN_HOST}" || true
    fi
    local connected=0
    for attempt in 1 2 3; do
      echo "[mode=${MODE} attempt ${attempt}/3] Connecting SSH tunnel ${WIN_USER}@${WIN_HOST}:${WIN_PORT} (127.0.0.1:${LOCAL_PORT} -> 127.0.0.1:${REMOTE_PORT})..."
      if ssh -fNT \
        -i "$SSH_KEY" \
        -p "$WIN_PORT" \
        -o BatchMode=yes \
        -o ConnectTimeout=20 \
        -o ExitOnForwardFailure=yes \
        -o ServerAliveInterval=15 \
        -o ServerAliveCountMax=6 \
        -o TCPKeepAlive=yes \
        -o StrictHostKeyChecking=accept-new \
        -L "127.0.0.1:${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}" \
        "${WIN_USER}@${WIN_HOST}" \
        </dev/null >"$LOG_FILE" 2>&1; then
        connected=1
        break
      fi
      echo "  failed: $(cat "$LOG_FILE" 2>/dev/null || true)" >&2
      sleep 2
    done
    if [[ "$connected" -ne 1 ]]; then
      echo "ERROR: Could not establish SSH tunnel after 3 attempts." >&2
      return 1
    fi
    pgrep -n -f "127.0.0.1:${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}" > "$PID_FILE" || true
    echo "Started tunnel (PID $(cat "$PID_FILE" 2>/dev/null || echo '?')) -> 127.0.0.1:${LOCAL_PORT}"
  fi

  if ! "$DOCKER_BIN" context inspect "$CONTEXT_NAME" >/dev/null 2>&1; then
    "$DOCKER_BIN" context create "$CONTEXT_NAME" --docker "host=tcp://127.0.0.1:${LOCAL_PORT}"
  fi
  "$DOCKER_BIN" context use "$CONTEXT_NAME"

  NO_PROXY="127.0.0.1,localhost,${NO_PROXY:-}" \
  no_proxy="127.0.0.1,localhost,${no_proxy:-}" \
    "$DOCKER_BIN" version --format 'Context={{.Client.Context}} Server={{.Server.Version}} Arch={{.Server.Os}}/{{.Server.Arch}}'
}

stop_tunnel() {
  if [[ -f "$PID_FILE" ]]; then
    kill "$(cat "$PID_FILE")" 2>/dev/null || true
    rm -f "$PID_FILE"
    echo "Stopped tunnel."
  else
    pkill -f "127.0.0.1:${LOCAL_PORT}:127.0.0.1:" 2>/dev/null || true
    echo "No active tunnel PID file."
  fi
}

status_tunnel() {
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Tunnel UP (PID $(cat "$PID_FILE")) -> 127.0.0.1:${LOCAL_PORT}"
  else
    echo "Tunnel DOWN"
  fi
  echo "Active Docker context: $("$DOCKER_BIN" context show)"
}

case "${1:-status}" in
  start) start_tunnel ;;
  stop) stop_tunnel ;;
  status) status_tunnel ;;
  *)
    echo "Usage: $0 {start|stop|status}"
    exit 1
    ;;
esac
