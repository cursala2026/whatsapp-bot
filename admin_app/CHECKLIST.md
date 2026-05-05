# Checklist de Desarrollo - Admin App

## ✅ Completado

### Core App
- [x] **main.py** - Ventana principal con 6 pestañas
- [x] **settings.py** - Sistema de configuración con persistencia
- [x] **api_client.py** - Cliente HTTP completo para el bot
- [x] **tabs/__init__.py** - Módulo inicializador

### Interfaz Gráfica (Pestañas)
- [x] **MenuEditorTab** - Editor de menús, saludo, opciones, respuestas
- [x] **ContactsManagerTab** - Tabla de contactos con búsqueda
- [x] **VendorsManagerTab** - CRUD de vendedores
- [x] **TestMessagesTab** - Envío de mensajes de prueba
- [x] **BackupsManagerTab** - Gestor de backups
- [x] **SettingsPanelTab** - Configuración de la app

### Documentación
- [x] **README.md** - Documentación completa
- [x] **QUICKSTART.md** - Guía rápida
- [x] **ARCHITECTURE.md** - Documentación técnica

### Scripts de Instalación
- [x] **install.bat** - Instalación en Windows
- [x] **install.sh** - Instalación en macOS/Linux
- [x] **run.bat** - Ejecutar en Windows
- [x] **run.sh** - Ejecutar en macOS/Linux
- [x] **build_exe.bat** - Generar EXE para Windows
- [x] **build_exe.sh** - Generar ejecutable para macOS/Linux

### Configuración
- [x] **requirements.txt** - Dependencias runtime
- [x] **requirements-dev.txt** - Dependencias desarrollo
- [x] **.admin_config.json.example** - Ejemplo de configuración

---

## 🚧 Pendiente / En Desarrollo

### Funcionalidades Avanzadas
- [ ] **Sincronización automática de cambios** entre app y bot
- [ ] **Editor visual de JSON** para menú_config (más amigable)
- [ ] **Importación desde Excel mejorada** con validación en tiempo real
- [ ] **Vista previa de menús** antes de guardar
- [ ] **Historial de cambios** (git-like) en backups
- [ ] **Exportación de reportes** (PDF con estadísticas)

### Interfaz Mejorada
- [ ] **Tema dark mode** completo
- [ ] **Iconos personalizados** para cada pestaña
- [ ] **Notificaciones de escritorio** cuando hay cambios en el bot
- [ ] **Búsqueda avanzada** en contactos (múltiples filtros)
- [ ] **Arrastrar y soltar** para importar Excel

### Testing
- [ ] **Tests unitarios** para api_client.py
- [ ] **Tests de integración** con bot backend
- [ ] **Tests de UI** con PyAutoGUI
- [ ] **Cobertura de código** >80%

### Deployment
- [ ] **Certificado digital** para el ejecutable
- [ ] **Instalador MSI** para Windows (no solo EXE)
- [ ] **Versiones macOS arm64/x86_64** (universal)
- [ ] **Actualizador automático** de versiones
- [ ] **Distribución vía GitHub Releases**

### Documentación Adicional
- [ ] **Video tutorial** de instalación
- [ ] **Troubleshooting guide** expandido
- [ ] **API reference** del bot (en admin_app)
- [ ] **Keyboard shortcuts** (Ctrl+S para guardar, etc.)
- [ ] **Glosario de términos**

### Optimizaciones
- [ ] **Caché de contactos** para carga más rápida
- [ ] **Paginación** en tabla de contactos (>1000 registros)
- [ ] **Multi-threading mejorado** para operaciones largas
- [ ] **Compresión de backups** (ZIP automático)

---

## 📋 Próximos Pasos Recomendados

### Corto Plazo (Esta semana)
1. Instalar dependencias: `pip install -r requirements.txt`
2. Ejecutar la app: `python main.py`
3. Configurar conexión al bot
4. Probar cada pestaña manualmente

### Medio Plazo (Este mes)
1. Completar lógica de importación/exportación Excel
2. Agregar validación de datos en formularios
3. Mejorar manejo de errores y mensajes
4. Crear tests básicos

### Largo Plazo (Próximos 2-3 meses)
1. Compilar a ejecutable final (.exe)
2. Crear instalador anuevo Windows (MSI)
3. Preparar para distribución
4. Documentar en wiki del proyecto

---

## 🐛 Bugs Conocidos

Actualmente no hay bugs reportados.

---

## 📝 Notas de Desarrollo

- Las pestañas heredan de `QWidget` para máxima flexibilidad
- El cliente HTTP (`api_client.py`) es agnóstico a las funcionalidades específicas
- La configuración se persiste en `~/.admin_config.json`
- Los backups se guardan en `admin_app/backups/`
- El theme se puede cambiar desde la pestaña de Configuración

---

**Última actualización:** 2026-03-26
**Versión App:** 0.1.0 (Alpha)
**Estado:** Funcional pero sin pulir
