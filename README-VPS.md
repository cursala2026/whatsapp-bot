# Despliegue seguro del bot en VPS

## Objetivo
Mantener el bot de WhatsApp aislado del sitio web principal para que no interfiera con los contenedores ya existentes.

## Recomendaciones
- No usar puertos 80/443 para este servicio.
- Exponer el bot solo en localhost del VPS o a través de un reverse proxy dedicado.
- Mantener el bot en su propia red Docker: `whatsapp-bot-net`.
- No ejecutar `docker compose down` sobre la pila completa de la web si solo se necesita reiniciar este servicio.

## Levantar solo el bot
```bash
cd /path/to/whatsapp-bot
docker compose up -d --build whatsapp-bot
```

## Verificar salud
```bash
curl http://127.0.0.1:8081/health
```

## Si luego se necesita exponer por subdominio
Configurar un proxy separado (Nginx/Caddy) que reenvíe a `http://127.0.0.1:8081`.
