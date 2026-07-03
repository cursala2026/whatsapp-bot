# Proxy para el bot en VPS

## Objetivo
Exponer el bot en un subdominio propio, por ejemplo `webhook.cursala.com.ar`, sin interferir con la web principal.

## Configuración de Nginx
1. Copiar el archivo [nginx-bot.conf](nginx-bot.conf) a la carpeta de sitios de Nginx.
2. Activar el sitio.
3. Recargar Nginx.

Ejemplo en Ubuntu/Debian:
```bash
sudo cp nginx-bot.conf /etc/nginx/conf.d/webhook-cursala.conf
sudo nginx -t
sudo systemctl reload nginx
```

## Importante
- El bot sigue escuchando en `127.0.0.1:8081`.
- El proxy solo reenvía tráfico al bot.
- La web principal no se toca.
