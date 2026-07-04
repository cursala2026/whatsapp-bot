# Deploy desde GitHub Actions

## Secrets requeridos en GitHub

- `VPS_HOST`: IP o hostname del VPS
- `VPS_USER`: usuario SSH del VPS
- `VPS_SSH_KEY`: clave privada SSH en formato OpenSSH para conectarse al VPS
- `VPS_SSH_PASSPHRASE`: frase de paso de la clave privada, si la tienes (opcional)
- `VPS_PORT`: puerto SSH (opcional, por defecto 22)
- `VPS_DEPLOY_PATH`: ruta del proyecto en el VPS (opcional, por defecto `/opt/cursala/whatsapp-bot`)

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

En GitHub ve a Settings > Secrets and variables > Actions y agrega:

- `VPS_HOST`: IP o hostname del VPS
- `VPS_USER`: usuario SSH del VPS
- `VPS_PORT`: 22
- `VPS_SSH_KEY`: contenido completo del archivo privado generado, por ejemplo `~/.ssh/gh-actions-whatsapp-bot`
- `VPS_SSH_PASSPHRASE`: solo si la clave tiene frase de paso
- `VPS_DEPLOY_PATH`: ruta de despliegue en el VPS, por ejemplo `/opt/cursala/whatsapp-bot`

> Importante: la clave debe ser una privada OpenSSH. No uses una `.ppk` ni la clave pública.

## Qué hace el workflow
- se conecta al VPS por SSH,
- entra al directorio del proyecto,
- trae la rama correspondiente,
- y ejecuta `deploy-vps.sh`.

## Importante
- No subas `.env` ni credenciales de Firebase al repositorio.
- Asegúrate de que el VPS tenga esos archivos en la ruta correcta antes del primer deploy.
