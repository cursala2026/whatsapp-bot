#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

mkdir -p secrets

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Se creó .env desde .env.example. Edítalo con tus credenciales reales antes de continuar."
fi

if [ ! -f secrets/firebase_service_account.json ]; then
  echo "Advertencia: faltan secrets/firebase_service_account.json. Colócalo antes de arrancar el bot en producción."
fi

echo "[deploy] Commit actual del repositorio:" 
 git rev-parse --short HEAD || true

bash ./setup-network.sh
docker compose down --remove-orphans || true
docker compose up -d --build whatsapp-bot

for i in $(seq 1 12); do
  if docker inspect --format='{{.State.Health.Status}}' whatsapp-bot 2>/dev/null | grep -q 'healthy'; then
    echo "[deploy] Contenedor healthy"
    break
  fi
  echo "[deploy] Esperando que el contenedor esté healthy..."
  sleep 5
 done

echo "[deploy] Estado final del servicio:"
docker compose ps

echo "[deploy] Verificación HTTP:"
curl -fsS "http://127.0.0.1:${HOST_PORT:-8081}/health" || true
