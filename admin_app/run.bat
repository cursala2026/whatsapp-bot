@echo off
REM Script para ejecutar Admin App - Bot WhatsApp Cursala

REM Activar entorno virtual
if not exist "venv" (
    echo Error: Entorno virtual no encontrado
    echo Por favor ejecuta primero: install.bat
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

REM Ejecutar la aplicación
python main.py

pause
