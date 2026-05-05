# 🚀 Pasos Siguientes - Admin App

## 1. Instalación de Dependencias

La app necesita Python y las librerías necesarias. Este paso es automático con los scripts proporcionados.

### Windows
```bash
install.bat
```
Esto hará:
- ✅ Crear entorno virtual (`venv/`)
- ✅ Instalar todas las dependencias
- ✅ Preparar la app para ejecutar

### macOS / Linux
```bash
chmod +x install.sh
./install.sh
```

---

## 2. Ejecutar la Aplicación

### Windows
```bash
run.bat
```

### macOS / Linux
```bash
./run.sh
```

**Primera vez:**
- Se abrirá el diálogo de **Configuración de Conexión**
- Ingresa la URL de tu bot (ej: `http://localhost:8000`)
- Ingresa la **Admin Key** (la misma que en el .env del bot)
- Haz clic en "Probar Conexión" para validar

---

## 3. Compilar a Ejecutable (.exe / binario)

Si quieres distribuir la app sin requerir que el usuario instale Python:

### Windows → .exe
```bash
build_exe.bat
```

Resultado: `dist/cursala-admin.exe` (~200MB)

### macOS / Linux → Binario
```bash
chmod +x build_exe.sh
./build_exe.sh
```

Resultado: `dist/cursala-admin` (~200MB)

---

## 4. Distribución

Opción A: **Compartir archivo único**
- Envía `dist/cursala-admin.exe` (Windows) o `dist/cursala-admin` (macOS/Linux)
- El usuario lo ejecuta directamente sin instalar nada

Opción B: **Crear instalador Windows**
(Requiere herramientas adicionales - tutoriales en DESARROLLO.md)

Opción C: **Compartir carpeta completa**
- Comprime toda la carpeta `admin_app/`
- Usuario ejecuta: 
  - Windows: `install.bat` luego `run.bat`
  - macOS/Linux: `./install.sh` luego `./run.sh`

---

## 5. Estructura de Archivos Finales

### Para Desarrollo
```
admin_app/
├── main.py
├── api_client.py
├── settings.py
├── requirements.txt
├── tabs/
│   ├── menu_editor.py
│   ├── contacts_manager.py
│   ├── vendors_manager.py
│   ├── test_messages.py
│   ├── backups_manager.py
│   └── settings_panel.py
└── [y documentación]
```

### Para Distribución (EXE)
```
cursala-admin.exe       ← El único archivo que necesita el usuario
```

### Para Distribución (Carpeta)
```
admin_app/
├── cursala-admin.exe   ← O el binario en macOS/Linux
└── ...
```

---

## 6. Variables de Entorno (Opcional)

En lugar de ingresar URL y Admin Key cada vez, puedes establecer:

### Windows
```bash
setx BOT_SERVER_URL "http://tu-servidor.com"
setx BOT_ADMIN_KEY "tu_clave_admin"
```

### macOS / Linux
```bash
export BOT_SERVER_URL="http://tu-servidor.com"
export BOT_ADMIN_KEY="tu_clave_admin"
```

La app las leerá automáticamente si existen.

---

## 7. Troubleshooting Rápido

| Problema | Solución |
|----------|----------|
| "ModuleNotFoundError: No module named 'PyQt6'" | Ejecuta `install.bat` o `./install.sh` |
| "No se pudo conectar al servidor" | Verifica que el bot está corriendo en la URL indicada |
| "Admin Key inválida" | Comprueba la clave en `.env` del bot |
| El ejecutable no inicia | Verifica que sea .exe (Windows) o tiene permisos (macOS/Linux) |
| Lento al cargar contactos | Normal, depende del tamaño de Firestore |

---

## 8. Características Ready-To-Use

✅ **MenuEditorTab**
- Edita saludo, opciones, respuestas
- Gestiona cursos y configuración general

✅ **ContactsManagerTab**
- Importa/exporta contactos
- Busca y filtra
- Eliminación masiva

✅ **VendorsManagerTab**
- CRUD completo de vendedores
- Asignación de cursos

✅ **TestMessagesTab**
- Envía mensajes de prueba
- Validación en tiempo real

✅ **BackupsManagerTab**
- Crea, restaura, elimina backups
- Historial de versiones

✅ **SettingsPanelTab**
- Configuración de la app
- Persistencia automática

---

## 9. Próximas Mejoras

Ver `CHECKLIST.md` para:
- Funcionalidades planeadas
- Optimizaciones pendientes
- Testing e integración

---

## 10. Soporte y Documentación

- `README.md` - Documentación completa
- `QUICKSTART.md` - Inicio rápido
- `ARCHITECTURE.md` - Detalles técnicos
- `CHECKLIST.md` - Estado del proyecto

---

**¿Listo para empezar?**

```bash
# Windows
install.bat
run.bat

# macOS/Linux
./install.sh
./run.sh
```

¡Disfruta administrando tu bot desde una interfaz gráfica! 🎉
