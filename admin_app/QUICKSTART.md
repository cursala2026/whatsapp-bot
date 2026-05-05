# ⚡ Guía Rápida - Admin App

## Instalación (2 minutos)

### Windows
```bash
install.bat
```

### macOS/Linux
```bash
chmod +x install.sh
./install.sh
```

## Ejecutar la App

### Windows
```bash
run.bat
```

### macOS/Linux
```bash
./run.sh
```

## Primera Configuración

1. **Se abrirá un diálogo de conexión**
   - URL: `http://localhost:8000` (ajusta si es diferente)
   - Admin Key: La que configuraste en el bot
   - Haz clic en "Probar Conexión"

2. **¡Listo!** Ahora tienes acceso a 6 pestañas:
   - 📋 **Saludo**: Personaliza el mensaje de bienvenida
   - 🗂️ **Contactos**: Importa/exporta contactos
   - 👥 **Vendedores**: Administra el equipo de ventas
   - 💬 **Mensajes de Prueba**: Prueba el bot
   - 💾 **Backups**: Protege tu configuración
   - ⚙️ **Configuración**: Ajusta parámetros

## Accede desde la Consola (dev)

```bash
# Activar entorno virtual
venv\Scripts\activate  # Windows
source venv/bin/activate  # macOS/Linux

# Ejecutar
python main.py
```

## Problemas?

- **"No se pudo conectar"**: Verifica que el bot esté corriendo
- **"ModuleNotFoundError"**: Ejecuta `install.bat` o `./install.sh`
- **"Python not found"**: Instala Python desde https://www.python.org

## Documentación Completa

Ver `README.md` para información detallada.
