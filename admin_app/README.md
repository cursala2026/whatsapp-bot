# Admin App - Bot WhatsApp Cursala

Aplicación de escritorio para gestionar toda la configuración del bot WhatsApp de Cursala.

## Características

- **Editor de Menús**: Edita el saludo, opciones, respuestas y cursos directamente
- **Gestor de Contactos**: Importa/Exporta contactos, búsqueda, filtrado
- **Gestor de Vendedores**: Administra la lista de vendedores y asignaciones
- **Mensajes de Prueba**: Envía mensajes de prueba a números específicos
- **Gestor de Backups**: Crea y restaura backups de configuración
- **Configuración**: Ajusta parámetros de la aplicación

## Requisitos

- Python 3.8+
- Windows, macOS o Linux
- Conexión a Internet (para comunicarse con el bot)

## Instalación

### 1. Clonar/Descargar el Proyecto

```bash
cd admin_app
```

### 2. Crear Entorno Virtual

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Instalar Dependencias

```bash
pip install -r requirements.txt
```

### 4. Ejecutar la Aplicación

```bash
python main.py
```

## Primera Vez

1. Al ejecutar la app, se te pedirá:
   - **URL del Servidor**: La dirección del bot (ej: `http://localhost:8000` o `https://tu-dominio.com`)
   - **Admin Key**: La clave de administrador configurada en el bot

2. Haz clic en "Probar Conexión" para verificar que todo esté correctamente configurado

3. Una vez conectado, ¡puedes comenzar a administrar!

## Estructura de Archivos

```
admin_app/
├── main.py                 # Ventana principal
├── settings.py            # Configuración de la app
├── api_client.py          # Cliente HTTP para comunicarse con el bot
├── requirements.txt       # Dependencias de Python
├── tabs/
│   ├── __init__.py
│   ├── menu_editor.py     # Editor de menús y configuración
│   ├── contacts_manager.py # Gestor de contactos
│   ├── vendors_manager.py  # Gestor de vendedores
│   ├── test_messages.py    # Envío de mensajes de prueba
│   ├── settings_panel.py   # Panel de configuración
│   └── backups_manager.py  # Gestor de backups
└── backups/               # Carpeta de backups (se crea automáticamente)
```

## Uso

### Editor de Menús
- Edita el mensaje de bienvenida
- Personaliza las 4 opciones principales del menú
- Define respuestas para cada opción
- Administra la lista de cursos disponibles
- Configura email de notificación y reglas de Gemini

### Gestor de Contactos
- **Recargar**: Obtiene los últimos contactos del servidor
- **Buscar**: Filtra por teléfono, nombre, etc.
- **Exportar**: Descarga contactos en formato Excel
- **Importar**: Carga contactos desde archivo Excel
- **Eliminar**: Borra contactos individuales

### Gestor de Vendedores
- **Agregar**: Crea nuevos vendedores
- **Editar**: Modifica información existente
- **Eliminar**: Borra vendedores
- **Asignar Cursos**: Especifica qué cursos atiende cada vendedor

### Mensajes de Prueba
- Envía mensajes de prueba a cualquier número
- Presets predefinidos para agilizar
- Verifica que el bot responda correctamente

### Gestor de Backups
- Crea backups automáticos o manuales
- Restaura configuración anterior
- Historial de versiones
- Elimina backups antiguos

## Configuración Avanzada

### Archivo de Configuración

El archivo `.admin_config.json` se crea automáticamente. Contiene:

```json
{
  "server_url": "http://localhost:8000",
  "admin_key": "tu_clave_admin",
  "theme": "light",
  "window_width": 1200,
  "window_height": 800,
  "auto_save_menu_config": true,
  "auto_backup_enabled": true
}
```

### Variables de Entorno

Opcionalmente, puedes establecer:

```bash
export BOT_SERVER_URL=http://tu-servidor.com
export BOT_ADMIN_KEY=tu_clave_admin
```

## Troubleshooting

### "No se pudo conectar al servidor"
1. Verifica que la URL es correcta
2. Asegúrate que el bot está corriendo
3. Comprueba la Admin Key es válida
4. Si usas HTTPS, verifica el certificado

### "ModuleNotFoundError: No module named 'PyQt6'"
1. Asegúrate haber ejecutado `pip install -r requirements.txt`
2. Verifica que usas el entorno virtual correcto

### Las pestañas están vacías
1. Reinicia la aplicación
2. Verifica la conexión nuevamente
3. Revisa los logs de la consola

## Desarrollo

Para agregar nuevas funcionalidades:

1. Las pestañas se encuentran en `tabs/`
2. Usa `api_client.py` para comunicarte con el bot
3. Sigue las convenciones de naming de PyQt6

## Licencia

Privado - Cursala
