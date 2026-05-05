@echo off
REM Script de instalación para Admin App - Bot WhatsApp Cursala
REM Este script configura el entorno virtual e instala dependencias

echo ====================================
echo Admin App Setup - Cursala Bot
echo ====================================
echo.

REM Verificar que Python está instalado
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python no está instalado o no está en PATH
    echo Descarga Python desde https://www.python.org/
    echo Asegúrate de marcar "Add Python to PATH" durante la instalación
    pause
    exit /b 1
)

echo ✓ Python encontrado

REM Crear entorno virtual si no existe
if not exist "venv" (
    echo.
    echo Creando entorno virtual...
    python -m venv venv
    echo ✓ Entorno virtual creado
) else (
    echo ✓ Entorno virtual ya existe
)

REM Activar entorno virtual
echo.
echo Activando entorno virtual...
call venv\Scripts\activate.bat

REM Actualizar pip
echo.
echo Actualizando pip...
python -m pip install --upgrade pip -q

REM Instalar dependencias
echo.
echo Instalando dependencias...
pip install -r requirements.txt -q

if errorlevel 1 (
    echo ERROR: Error instando las dependencias
    pause
    exit /b 1
)

echo ✓ Dependencias instaladas

REM Crear carpeta de backups
if not exist "backups" (
    mkdir backups
    echo ✓ Carpeta de backups creada
)

echo.
echo ====================================
echo ¡Instalación completada!
echo ====================================
echo.
echo Para ejecutar la aplicación:
echo   python main.py
echo.
echo O simplemente ejecutar: run.bat
echo.
pause
