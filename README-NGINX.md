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

## Red compartida
Para que el proxy pueda llegar al bot por Docker, el contenedor del bot debe estar unido a la misma red que el proxy. El despliegue actual usa el script [setup-network.sh](setup-network.sh) para crear o reutilizar la red compartida y conectar ambos contenedores.

## Rollback rápido
Si el sitio principal `cursala.com.ar` empieza a fallar por esta configuración, ejecuta:

```bash
bash /path/to/restore-main-site.sh
```

Ese script elimina la regla del subdominio del proxy, quita las variables de enrutamiento del contenedor del bot y recarga Nginx para volver al estado anterior.
