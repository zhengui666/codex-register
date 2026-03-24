#!/usr/bin/env bash

set -euo pipefail

SERVER_HOST="${SERVER_HOST:-107.173.156.228}"
SERVER_USER="${SERVER_USER:-zzy}"
REMOTE_SRC_DIR="${REMOTE_SRC_DIR:-/home/zzy/codex-register-src}"
REMOTE_DEPLOY_DIR="${REMOTE_DEPLOY_DIR:-/home/zzy/codex-register-deploy}"
CONTAINER_NAME="${CONTAINER_NAME:-codex-register}"
IMAGE_NAME="${IMAGE_NAME:-ghcr.io/zhengui666/codex-register:latest}"
REPO_URL="${REPO_URL:-https://github.com/zhengui666/codex-register.git}"

ssh_target="${SERVER_USER}@${SERVER_HOST}"

ssh "$ssh_target" bash -s -- \
  "$REMOTE_SRC_DIR" \
  "$REMOTE_DEPLOY_DIR" \
  "$CONTAINER_NAME" \
  "$IMAGE_NAME" \
  "$REPO_URL" <<'EOF'
set -euo pipefail

REMOTE_SRC_DIR="$1"
REMOTE_DEPLOY_DIR="$2"
CONTAINER_NAME="$3"
IMAGE_NAME="$4"
REPO_URL="$5"

if [[ ! -f "${REMOTE_DEPLOY_DIR}/.env" ]]; then
  echo "缺少部署环境文件: ${REMOTE_DEPLOY_DIR}/.env" >&2
  exit 1
fi

if [[ -d "${REMOTE_SRC_DIR}/.git" ]]; then
  cd "${REMOTE_SRC_DIR}"
  git fetch origin master
  git reset --hard origin/master
else
  rm -rf "${REMOTE_SRC_DIR}"
  git clone --depth 1 "${REPO_URL}" "${REMOTE_SRC_DIR}"
  cd "${REMOTE_SRC_DIR}"
fi

mkdir -p "${REMOTE_DEPLOY_DIR}/data" "${REMOTE_DEPLOY_DIR}/logs"

warp_enabled="$(grep -E '^WARP_ENABLED=' "${REMOTE_DEPLOY_DIR}/.env" 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d '\r' || true)"
warp_proxy_url="$(grep -E '^WARP_PROXY_URL=' "${REMOTE_DEPLOY_DIR}/.env" 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d '\r' || true)"

warp_run_flags=()
case "${warp_enabled,,}" in
  1|true|yes|on)
    warp_run_flags+=(--cap-add=NET_ADMIN --device=/dev/net/tun)
    ;;
esac

if docker ps -a --format '{{.Names}}' | grep -Fxq "${CONTAINER_NAME}"; then
  docker cp "${CONTAINER_NAME}:/app/data/." "${REMOTE_DEPLOY_DIR}/data/" >/dev/null 2>&1 || true
  docker cp "${CONTAINER_NAME}:/app/logs/." "${REMOTE_DEPLOY_DIR}/logs/" >/dev/null 2>&1 || true
fi

docker build -t "${IMAGE_NAME}" .

docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true

docker run -d \
  --name "${CONTAINER_NAME}" \
  --restart unless-stopped \
  -p 8000:8000 \
  -v "${REMOTE_DEPLOY_DIR}/data:/app/data" \
  -v "${REMOTE_DEPLOY_DIR}/logs:/app/logs" \
  "${warp_run_flags[@]}" \
  --env-file "${REMOTE_DEPLOY_DIR}/.env" \
  "${IMAGE_NAME}"

echo "部署完成: ${CONTAINER_NAME}"
echo "镜像: ${IMAGE_NAME}"
EOF
