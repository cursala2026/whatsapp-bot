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

echo "[deploy] Deteniendo y eliminando contenedor anterior del bot..."
docker compose stop whatsapp-bot || true
docker compose rm -f whatsapp-bot || true

echo "[deploy] Eliminando imagen de Docker anterior para forzar reconstrucción..."
docker image rm whatsapp-bot-whatsapp-bot || true

echo "[deploy] Construyendo imagen sin cache..."
docker compose build --no-cache whatsapp-bot

echo "[deploy] Iniciando contenedor del bot..."
docker compose up -d --force-recreate whatsapp-bot

if ! docker ps --format '{{.Names}}' | grep -q 'whatsapp-bot'; then
    echo "[deploy] ❌ ERROR: El contenedor 'whatsapp-bot' no se pudo iniciar."
    echo "[deploy] Mostrando logs para diagnóstico:"
    docker logs whatsapp-bot --tail 100 || echo "No se encontraron logs para whatsapp-bot."
    exit 1
fi

for i in $(seq 1 12); do
  STATE=$(docker inspect --format='{{.State.Status}}' whatsapp-bot 2>/dev/null || echo "unknown")
  if [ "$STATE" != "running" ]; then
    echo "[deploy] ❌ ERROR: El contenedor no está en estado 'running'. Estado actual: $STATE."
    echo "[deploy] Mostrando los últimos logs para diagnóstico:"
    docker logs whatsapp-bot --tail 50
    exit 1
  fi

  STATUS=$(docker inspect --format='{{.State.Health.Status}}' whatsapp-bot 2>/dev/null || echo "unknown")
  echo "[deploy] Verificando estado... (Intento $i/12). Status: $STATE, Health: $STATUS"
  if [ "$STATUS" == "healthy" ]; then
    echo "[deploy] ✅ Contenedor 'healthy'."
    break
  fi
  sleep 5
done

if [ "$(docker inspect --format='{{.State.Health.Status}}' whatsapp-bot 2>/dev/null)" != "healthy" ]; then
    echo "[deploy] ⚠️ ADVERTENCIA: El contenedor está corriendo pero no alcanzó el estado 'healthy'."
    echo "[deploy] Revisa los logs para asegurar que todo funciona como se espera:"
    echo "  docker logs whatsapp-bot --tail 100"
fi

echo "[deploy] Estado final del servicio:"
docker compose ps

echo "[deploy] Verificación HTTP:"
HOST_PORT_EFFECTIVE="${HOST_PORT:-8081}"
HEALTH_URL="http://127.0.0.1:${HOST_PORT_EFFECTIVE}/health"
echo "[deploy] Probando conexión a ${HEALTH_URL}"
curl -fsS "${HEALTH_URL}" || echo "[deploy] ⚠️ No se pudo verificar el endpoint de salud. Revisa el proxy y los puertos."

echo "[deploy] Limpiando imágenes de Docker antiguas..."
docker image prune -f --filter "dangling=true"
