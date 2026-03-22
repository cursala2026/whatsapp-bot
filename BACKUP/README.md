# BACKUP Manual del Bot

Este directorio guarda copias manuales del estado del bot para volver a un punto estable.

## Objetivo

- Guardar respaldos con fecha y hora.
- Conservar codigo clave y metadata de despliegue.
- Poder restaurar rapidamente ante anomalias.

## Como crear un backup manual

Ejecutar desde la raiz del proyecto:

```powershell
powershell -ExecutionPolicy Bypass -File .\BACKUP\create_backup.ps1 -Label "antes-cambio-importante"
```

Notas:

- -Label es opcional y ayuda a identificar el motivo del respaldo.
- Se crea una carpeta con formato yyyy-MM-dd_HH-mm-ss_label.

## Que guarda cada backup

- main.py
- menu_config.json
- enviar.py
- requirements.txt
- README.md
- .gitignore
- metadata.txt (commit, rama, webhook, puertos, revision Cloud Run)
- restore_instructions.txt

## Restauracion rapida

1. Elegir la carpeta de backup a restaurar.
2. Copiar sus archivos a la raiz del repo.
3. Revisar estado con git status --short --branch.
4. Si corresponde, desplegar de nuevo en Cloud Run.

## Punto estable actual

- Webhook productivo: https://cursala-bot-42n6jtdjoq-rj.a.run.app/webhook
- Puerto local esperado: 8080
- Servicio Cloud Run: datosbotcursala en southamerica-east1
