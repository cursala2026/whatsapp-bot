# ⚡ Quick Commands - Admin App

Copiar y pegar estos comandos según tu SO:

## 🪟 Windows

```bash
# Instalación (primera vez, ~3 minutos)
install.bat

# Ejecutar la app (después de instalar)
run.bat

# Compilar a .exe (opcional, ~5 minutos)
build_exe.bat
# Resultado: dist/cursala-admin.exe
```

## 🍎 macOS / 🐧 Linux

```bash
# Dar permisos de ejecución (solo primera vez)
chmod +x install.sh
chmod +x run.sh
chmod +x build_exe.sh

# Instalación (primera vez, ~3 minutos)
./install.sh

# Ejecutar la app (después de instalar)
./run.sh

# Compilar a binario (opcional, ~5 minutos)
./build_exe.sh
# Resultado: dist/cursala-admin
```

---

## 📖 Documentación Rápida

| Archivo | Contenido |
|---------|----------|
| `QUICKSTART.md` | Instalación en 2 minutos |
| `README.md` | Documentación completa y exhaustiva |
| `ARCHITECTURE.md` | Detalles técnicos y estructura |
| `CHECKLIST.md` | Estado del proyecto y TO-DO |
| `GETTING_STARTED.md` | Pasos siguientes después de instalar |
| `QUICK_COMMANDS.md` | ← Este archivo |

---

## 🔧 Troubleshooting Inmediato

### Python no encontrado
**Windows**: Descarga de https://www.python.org (marca "Add to PATH")
**macOS**: `brew install python3`
**Linux**: `sudo apt-get install python3`

### "Permission denied" en .sh
```bash
chmod +x install.sh run.sh build_exe.sh
```

### PyQt6 no encontrado
```bash
# Windows
install.bat

# macOS/Linux
./install.sh
```

### Conexión al servidor falla
- Verifica URL: `http://localhost:8000` o tu servidor
- Verifica Admin Key: debe ser igual a `ADMIN_KEY` en `.env` del bot
- Verifica que el bot esté corriendo: `python main.py` en la carpeta del bot

---

## 📦 Archivos Generados Automáticamente

Después de ejecutar `install.bat` o `./install.sh`, se crearán:

```
admin_app/
├── venv/                    (entorno virtual Python)
└── backups/                 (backups de configuración)
└── .admin_config.json       (tu configuración guardada)
```

---

## 🎯 Flujo Básico

```
1. install.bat/./install.sh    → Prepara entorno
2. run.bat/./run.sh            → Abre app
3. Ingresa URL + Admin Key     → Se conecta
4. Usa 6 pestañas              → Administra bot
5. build_exe.bat/./build_exe.sh → (Opcional) Generar .exe
```

---

## 🚀 Cómo Compartir la App

### Opción A: Ejecutable Único (Recomendado)
```
Después de: build_exe.bat/./build_exe.sh
Archivo: dist/cursala-admin.exe (o cursala-admin sin extensión)
Tamaño: ~200MB
Usuario: Solo ejecuta el archivo, no necesita Python
```

### Opción B: Carpeta Completa
```
Env: admin_app/ entera
Usuario ejecuta: install.bat (Windows) o ./install.sh (macOS/Linux)
Luego: run.bat o ./run.sh
```

### Opción C: Instalador Windows (Avanzado)
Requiere herramientas adicionales (no incluido)

---

## 🔐 Seguridad

⚠️ **No compartas**: `.admin_config.json` (contiene Admin Key)
✅ **Sí compartes**: `dist/cursala-admin.exe` o carpeta sin `.admin_config.json`

El usuario ingresará su propia Admin Key al abrir la app por primera vez.

---

## 📞 Soporte Rápido

```
Paso         Si falla...
─────────────────────────────────────────
install.bat  → Verifica Python esté en PATH
run.bat      → Ejecuta install.bat primero
Conexión     → Verifica bot esté corriendo
Actualizar   → Edita .admin_config.json
Tema oscuro  → En pestaña "Configuración"
```

---

**¿Necesitas ayuda?** Ver `README.md` o `GETTING_STARTED.md`

**¿Quieres contribuir?** Ver `ARCHITECTURE.md` para estructura del proyecto

**Estado del proyecto:** Ver `CHECKLIST.md`
