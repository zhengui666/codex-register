#!/usr/bin/env bash

set -euo pipefail

is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

if is_true "${WARP_ENABLED:-0}"; then
  export WARP_PROXY_URL="${WARP_PROXY_URL:-socks5h://127.0.0.1:40000}"

  if command -v warp-cli >/dev/null 2>&1; then
    warp-cli --accept-tos registration new >/tmp/warp-register.log 2>&1 || true
    warp-cli set-mode proxy >/tmp/warp-mode.log 2>&1 || warp-cli mode proxy >/tmp/warp-mode.log 2>&1 || true
    warp-cli connect >/tmp/warp-connect.log 2>&1 || true
  fi
fi

exec python webui.py
