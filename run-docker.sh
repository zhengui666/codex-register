#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-$SCRIPT_DIR/data}"
LOGS_DIR="${LOGS_DIR:-$SCRIPT_DIR/logs}"
ENV_FILE="${ENV_FILE:-$SCRIPT_DIR/.env}"
CONTAINER_NAME="${CONTAINER_NAME:-codex-register}"
HOST_PORT="${APP_PORT:-8000}"
CONTAINER_PORT="${CONTAINER_PORT:-8000}"
IMAGE_REPO="${IMAGE_REPO:-}"
TAG="${IMAGE_TAG:-latest}"

detect_repo() {
  local remote_url repo_path
  if [[ -n "$IMAGE_REPO" ]]; then
    printf '%s' "$IMAGE_REPO"
    return 0
  fi

  remote_url="$(git -C "$SCRIPT_DIR" config --get remote.origin.url 2>/dev/null || true)"
  if [[ -n "$remote_url" ]]; then
    repo_path="$(printf '%s' "$remote_url" | sed -E 's#.*github.com[:/]+([^/]+/[^/]+?)(\.git)?$#\1#')"
    if [[ -n "$repo_path" && "$repo_path" != "$remote_url" ]]; then
      printf '%s' "$repo_path"
      return 0
    fi
  fi

  printf '%s' "$(basename "$SCRIPT_DIR")"
}

ensure_env_file() {
  if [[ -f "$ENV_FILE" ]]; then
    return 0
  fi

  cat > "$ENV_FILE" <<EOF
# OpenAI 自动注册系统 - 首次部署默认配置
# 按需修改后再次执行 run-docker.sh

APP_HOST=0.0.0.0
APP_PORT=${HOST_PORT}
APP_ACCESS_PASSWORD=admin123
APP_DATABASE_URL=data/database.db
EOF

  echo "已创建首次部署环境文件: $ENV_FILE"
  echo "已写入可直接运行的默认配置。建议尽快修改 APP_ACCESS_PASSWORD。"
}

ensure_dirs() {
  mkdir -p "$DATA_DIR" "$LOGS_DIR"
  if [[ ! -f "$DATA_DIR/.keep" ]]; then
    touch "$DATA_DIR/.keep" >/dev/null 2>&1 || true
  fi
}

login_if_needed() {
  if [[ -n "${GHCR_USERNAME:-}" && -n "${GHCR_TOKEN:-}" ]]; then
    printf '%s\n' "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USERNAME" --password-stdin
  fi
}

start_container() {
  local image
  image="${GHCR_IMAGE:-ghcr.io/$(detect_repo)}"

  docker pull "${image}:${TAG}"
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

  docker run -d \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    -p "${HOST_PORT}:${CONTAINER_PORT}" \
    -v "$DATA_DIR:/app/data" \
    -v "$LOGS_DIR:/app/logs" \
    -v "$ENV_FILE:/app/.env:ro" \
    -e APP_DATA_DIR=/app/data \
    -e APP_LOGS_DIR=/app/logs \
    --env-file "$ENV_FILE" \
    "${image}:${TAG}"

  echo "容器已启动: $CONTAINER_NAME"
  echo "镜像: ${image}:${TAG}"
  echo "端口: ${HOST_PORT}:${CONTAINER_PORT}"
  echo "数据目录: $DATA_DIR"
  echo "日志目录: $LOGS_DIR"
  echo "环境文件: $ENV_FILE"
}

ensure_dirs
ensure_env_file
login_if_needed
start_container
