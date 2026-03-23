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

  if command -v warp-svc >/dev/null 2>&1; then
    if ! pgrep -x warp-svc >/dev/null 2>&1; then
      nohup warp-svc >/tmp/warp-svc.log 2>&1 &
    fi
    for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
      if ss -xlp 2>/dev/null | grep -q "/run/cloudflare-warp/warp_service"; then
        break
      fi
      sleep 1
    done
  fi

  if command -v warp-cli >/dev/null 2>&1; then
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      if warp-cli status >/tmp/warp-status.log 2>&1; then
        break
      fi
      sleep 1
    done

    if grep -qi "old registration\|registration delete required" /tmp/warp-status.log 2>/dev/null; then
      rm -f /var/lib/cloudflare-warp/reg.json
      rm -f /var/lib/cloudflare-warp/conf.json
      warp-cli --accept-tos registration new >/tmp/warp-register.log 2>&1 || true
    fi

    warp-cli set-mode proxy >/tmp/warp-mode.log 2>&1 || warp-cli mode proxy >/tmp/warp-mode.log 2>&1 || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      warp-cli connect >/tmp/warp-connect.log 2>&1 || true
      if warp-cli status >/tmp/warp-status.log 2>&1 && ! grep -qi "error\|inactive\|registration delete required" /tmp/warp-status.log 2>/dev/null; then
        break
      fi
      sleep 1
    done
  fi
fi

exec python webui.py
