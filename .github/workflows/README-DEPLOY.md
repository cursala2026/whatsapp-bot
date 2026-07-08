# Deploy desde GitHub Actions

## Secrets requeridos en GitHub
- **`VPS_HOST`**: IP o hostname del VPS.
- **`VPS_USER`**: Usuario SSH del VPS.
- **`VPS_SSH_KEY`**: Clave privada SSH en formato OpenSSH para conectarse al VPS.
- **`VPS_SSH_PASSPHRASE`**: Frase de paso de la clave privada, si la tienes (opcional).
- **`VPS_PORT`**: Puerto SSH (opcional, por defecto 22).
- **`VPS_DEPLOY_PATH`**: Ruta del proyecto en el VPS (opcional, por defecto `/opt/cursala/whatsapp-bot`).

## Crear la clave SSH

En tu máquina local, genera una clave nueva:

```bash
ssh-keygen -t ed25519 -C "github-actions-whatsapp-bot" -f ~/.ssh/gh-actions-whatsapp-bot
```

Luego copia la clave pública al VPS:

```bash
ssh-copy-id -i ~/.ssh/gh-actions-whatsapp-bot.pub <usuario>@<ip-del-vps>
```

## Configuración en GitHub

En GitHub, ve a `Settings > Secrets and variables > Actions` y agrega los `secrets` mencionados anteriormente.

> **Importante**: La clave SSH debe ser una clave privada en formato OpenSSH. No uses una `.ppk` ni la clave pública.

## Qué hace el workflow
- Se conecta al VPS por SSH.
- Entra al directorio del proyecto.
- trae la rama correspondiente,
- y ejecuta `deploy-vps.sh`.

## Importante
- No subas `.env` ni credenciales de Firebase al repositorio.
- Asegúrate de que el VPS tenga esos archivos en la ruta correcta antes del primer deploy.
- Asegúrate de que el VPS tenga esos archivos en la ruta correcta antes del primer deploy.
