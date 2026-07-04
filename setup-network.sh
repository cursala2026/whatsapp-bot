#!/usr/bin/env bash
set -euo pipefail

NETWORK_NAME="${SHARED_PROXY_NETWORK:-nginx-proxy}"

if ! docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then
  echo "[network] Creando red compartida: $NETWORK_NAME"
  docker network create "$NETWORK_NAME"
else
  echo "[network] Reutilizando red compartida: $NETWORK_NAME"
fi

if docker ps --format '{{.Names}}' | grep -qx 'nginx-proxy'; then
  if ! docker network inspect "$NETWORK_NAME" | grep -q '"Name": "nginx-proxy"'; then
    docker network connect "$NETWORK_NAME" nginx-proxy >/dev/null 2>&1 || true
  fi
fi

if docker ps --format '{{.Names}}' | grep -qx 'whatsapp-bot'; then
  if ! docker inspect whatsapp-bot --format '{{json .NetworkSettings.Networks}}' | grep -q "$NETWORK_NAME"; then
    docker network connect "$NETWORK_NAME" whatsapp-bot >/dev/null 2>&1 || true
  fi
fi

echo "[network] Red lista: $NETWORK_NAME"
docker network inspect "$NETWORK_NAME" --format 'Nombre: {{.Name}}\nContenedores: {{range .Containers}}{{.Name}} {{end}}'
