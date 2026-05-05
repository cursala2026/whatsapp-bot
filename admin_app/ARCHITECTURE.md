# Estructura del Proyecto - Admin App

```
admin_app/
│
├── 📋 ARCHIVOS PRINCIPALES
│   ├── main.py                    # Ventana principal (entry point)
│   ├── settings.py                # Sistema de configuración
│   ├── api_client.py              # Cliente HTTP para el bot
│   └── requirements.txt           # Dependencias básicas
│
├── 📂 CARPETA: tabs/              # Módulos de interfaz gráfica
│   ├── __init__.py
│   ├── menu_editor.py             # Edición de menús y configuración
│   ├── contacts_manager.py        # Gestión de contactos
│   ├── vendors_manager.py         # Gestión de vendedores
│   ├── test_messages.py           # Envío de mensajes de prueba
│   ├── settings_panel.py          # Panel de configuración general
│   └── backups_manager.py         # Gestión de backups
│
├── 📂 CARPETA: backups/           # Almacenamiento local de backups (auto-creada)
│
├── 📚 DOCUMENTACIÓN
│   ├── README.md                  # Documentación completa
│   ├── QUICKSTART.md              # Guía rápida de inicio
│   └── ARCHITECTURE.md            # Este archivo
│
├── 🔧 SCRIPTS DE INSTALACIÓN
│   ├── install.bat                # Instalación para Windows
│   ├── install.sh                 # Instalación para macOS/Linux
│   ├── run.bat                    # Ejecutar en Windows
│   ├── run.sh                     # Ejecutar en macOS/Linux
│   ├── build_exe.bat              # Generar .exe (Windows)
│   └── build_exe.sh               # Generar ejecutable (macOS/Linux)
│
├── 📦 CONFIGURACIÓN
│   ├── requirements.txt           # Dependencias runtime
│   ├── requirements-dev.txt       # Dependencias desarrollo (incluye PyInstaller)
│   └── .admin_config.json.example # Ejemplo de configuración
│
└── 📁 CARPETAS GENERADAS (después de primera ejecución)
    ├── venv/                      # Entorno virtual Python
    └── backups/                   # Carpeta de backups automáticos
```

## Flujo de Datos

```
┌─────────────────────────────────────────────────────────═
│                                                         │
│  main.py (QMainWindow)                                 │
│  ├─ SettingsDialog (conexión inicial)                 │
│  └─ AdminAppWindow                                     │
│     └─ QTabWidget con 6 pestañas                       │
│
│  Cada pestaña hereda de QWidget y se comunica via:    │
│   api_client.BotApiClient (HTTP requests)             │
│                                                         │
│  Configuración persistida en:                          │
│   ~/.admin_config.json (settings.py)                   │
│                                                         │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│     BOT BACKEND (FastAPI)                               │
│     Endpoints:                                          │
│     - GET  /version                                    │
│     - GET  /admin/firestore/users                      │
│     - POST /admin/firestore/contacts/import            │
│     - POST /admin/send-test-message                    │
│     - GET  /admin/download-contacts-template           │
│     - ... (más endpoints según necesidad)              │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│     FIRESTORE (Database)                                │
│     - Contactos                                         │
│     - Cursos                                            │
│     - Vendedores                                        │
└─────────────────────────────────────────────────────────┘
```

## Clases Clave

### main.py
- `SettingsDialog`: Diálogo de configuración de conexión
- `AdminAppWindow`: Ventana principal con 6 pestañas

### settings.py
- `CONFIG`: Diccionario global de configuración
- `DEFAULT_CONFIG`: Valores por defecto
- Funciones: `load_config()`, `save_config()`

### api_client.py
- `BotApiClient`: Cliente HTTP para comunicarse con el bot
- Métodos: `get_version()`, `get_all_contacts()`, `send_test_message()`, etc.

### tabs/*.py
- `MenuEditorTab`: Panel para editar menús
- `ContactsManagerTab`: Tabla de contactos con I/O
- `VendorsManagerTab`: CRUD de vendedores
- `TestMessagesTab`: Formulario para enviar mensajes
- `BackupsManagerTab`: Navegador de backups
- `SettingsPanelTab`: Configuración de la app

## Dependencias Principales

| Paquete | Versión | Propósito |
|---------|---------|-----------|
| PyQt6 | 6.7.0 | Framework GUI |
| requests | 2.31.0 | Cliente HTTP |
| openpyxl | 3.1.1 | Leer/escribir Excel |
| pandas | 2.1.3 | Procesamiento de datos |
| pyinstaller | 6.1.0 | Generar ejecutables |

## Instalación de Entorno

```
1. Python 3.8+ instalado → venv creado → pip actualizado
2. requirements.txt instalado en venv
3. Carpeta backups/ creada
4. .admin_config.json cargado/creado
```

## Ciclo de Vida de la Aplicación

```
1. main.py inicia → se carga CONFIG desde settings.py
2. AdminAppWindow.__init__() → intenta conectar con bot
3. Si no hay admin_key → muestra SettingsDialog
4. Usuario ingresa URL + admin_key → test_connection()
5. Si la conexión es válida → carga las 6 pestañas
6. Usuario interactúa con tabs → usan api_client para comunicarse con bot
7. Cambios se guardan en CONFIG → se persisten en .admin_config.json
8. Al cerrar → closeEvent() guarda window dimensions
```

## Convenciones de Código

- **Nomenclatura**: snake_case para funciones/variables, PascalCase para clases
- **Imports**: Estándar → PyQt6 → proyecto
- **Errores**: Usar QMessageBox para UI, logging para consola
- **Async**: Usar QThread para operaciones largas (carga de contacts, etc.)
- **I18n**: Comentarios españoles en código, interfaz multiidioma planeada

## Extensibilidad

Para agregar una nueva pestaña:

1. Crear `tabs/new_feature.py` con clase `NewFeatureTab(QWidget)`
2. Importar en `main.py`
3. Agregar a AdminAppWindow en `__init__()`

```python
from tabs.new_feature import NewFeatureTab

# En AdminAppWindow.__init__():
self.new_feature_tab = NewFeatureTab()
self.tabs.addTab(self.new_feature_tab, "Nueva Pestaña")
```

## Generación de Ejecutables

### Usando build_exe.bat (Windows):
```
build_exe.bat
→ Genera dist/cursala-admin.exe (~200MB)
```

### Usando build_exe.sh (macOS/Linux):
```
./build_exe.sh
→ Genera dist/cursala-admin (~200MB)
```

El ejecutable incluye Python + PyQt6 + todas las dependencias, permitiendo distribuir la app sin requerir instalación de Python en la máquina del usuario.
