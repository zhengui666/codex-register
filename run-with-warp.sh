#!/usr/bin/env bash

set -euo pipefail

is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

wait_for_socket() {
  local path="$1"
  local retries="${2:-30}"
  local delay="${3:-1}"
  local i
  for ((i = 0; i < retries; i++)); do
    if [[ -S "$path" ]]; then
      return 0
    fi
    sleep "$delay"
  done
  return 1
}

wait_for_port() {
  local port="$1"
  local retries="${2:-30}"
  local delay="${3:-1}"
  local i
  for ((i = 0; i < retries; i++)); do
    if ss -lnt 2>/dev/null | awk '{print $4}' | grep -Eq "[:.]${port}\$"; then
      return 0
    fi
    sleep "$delay"
  done
  return 1
}

setup_warp() {
  export WARP_PROXY_URL="${WARP_PROXY_URL:-socks5h://127.0.0.1:40000}"

  if ! command -v warp-svc >/dev/null 2>&1 || ! command -v warp-cli >/dev/null 2>&1; then
    echo "[warp] warp-cli or warp-svc not installed, skipping WARP setup" >&2
    return 1
  fi

  if ! pgrep -x warp-svc >/dev/null 2>&1; then
    nohup warp-svc >/tmp/warp-svc.log 2>&1 &
  fi

  if ! wait_for_socket "/run/cloudflare-warp/warp_service" 30 1; then
    echo "[warp] warp_service socket not ready" >&2
    return 1
  fi

  if ! warp-cli --accept-tos registration show >/dev/null 2>&1; then
    rm -f /var/lib/cloudflare-warp/reg.json /var/lib/cloudflare-warp/conf.json
  fi

  if ! warp-cli --accept-tos status >/dev/null 2>&1; then
    true
  fi

  if warp-cli --accept-tos registration new >/tmp/warp-registration.log 2>&1; then
    :
  elif grep -q "Old registration is still around" /tmp/warp-registration.log 2>/dev/null; then
    warp-cli --accept-tos registration delete >/tmp/warp-registration-delete.log 2>&1 || true
    rm -f /var/lib/cloudflare-warp/reg.json /var/lib/cloudflare-warp/conf.json
    warp-cli --accept-tos registration new >/tmp/warp-registration.log 2>&1
  fi

  warp-cli --accept-tos mode proxy >/tmp/warp-mode.log 2>&1 || true
  warp-cli --accept-tos connect >/tmp/warp-connect.log 2>&1 || true

  if ! wait_for_port 40000 30 1; then
    echo "[warp] local proxy port 40000 did not come up" >&2
    return 1
  fi

  warp-cli --accept-tos status || true
  return 0
}

if is_true "${WARP_ENABLED:-0}"; then
  if ! setup_warp; then
    echo "[warp] setup failed, disabling WARP proxy for app runtime" >&2
    unset WARP_PROXY_URL
    export WARP_ENABLED=0
  fi
fi

exec python webui.py --host "${APP_HOST:-0.0.0.0}" --port "${APP_PORT:-8000}"
