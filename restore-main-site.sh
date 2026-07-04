#!/usr/bin/env bash
set -euo pipefail

if ! docker ps --format '{{.Names}}' | grep -qx 'nginx-proxy'; then
  echo "[rollback] No se encontró el contenedor nginx-proxy. No hay nada que revertir."
  exit 0
fi

echo "[rollback] Eliminando la regla de reenvío del subdominio webhook.cursala.com.ar..."
if docker ps --format '{{.Names}}' | grep -qx 'whatsapp-bot'; then
  docker update --env-rm VIRTUAL_HOST --env-rm VIRTUAL_PORT --env-rm VIRTUAL_PROTO whatsapp-bot >/dev/null 2>&1 || true
fi

docker exec nginx-proxy sh -c '
  set -e
  rm -f /etc/nginx/vhost.d/webhook.cursala.com.ar \
        /etc/nginx/vhost.d/webhook.cursala.com.ar.conf \
        /etc/nginx/conf.d/webhook-cursala.conf \
        /etc/nginx/conf.d/webhook-cursala.conf
  if command -v nginx >/dev/null 2>&1; then
    nginx -t
    nginx -s reload
  fi
'

echo "[rollback] Verificando si aún queda alguna configuración del subdominio..."
docker exec nginx-proxy sh -c 'nginx -T 2>/dev/null | grep -n "webhook.cursala.com.ar" || true'

echo "[rollback] Reintento de verificación HTTP contra la web principal..."
curl -I -L --max-time 10 https://cursala.com.ar 2>/dev/null | head -n 10 || true

echo "[rollback] Si el sitio principal sigue fallando, revisa el estado de nginx-proxy con:"
echo "  docker logs nginx-proxy --tail 100"
