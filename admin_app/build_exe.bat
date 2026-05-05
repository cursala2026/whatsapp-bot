@echo off
REM Script para generar ejecutable (.exe) del Admin App

echo ====================================
echo Generador de Ejecutable - Cursala Bot Admin App
echo ====================================
echo.

REM Verificar que venv existe
if not exist "venv" (
    echo ERROR: Entorno virtual no encontrado
    echo Ejecuta primero: install.bat
    pause
    exit /b 1
)

REM Activar entorno virtual
call venv\Scripts\activate.bat

REM Verificar que PyInstaller está instalado
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo.
    echo Instalando PyInstaller...
    pip install pyinstaller -q
    if errorlevel 1 (
        echo ERROR: No se pudo instalar PyInstaller
        pause
        exit /b 1
    )
)

echo ✓ PyInstaller está disponible

REM Generar ejecutable
echo.
echo Generando ejecutable...
echo (Esto puede tardar 1-2 minutos)
echo.

pyinstaller ^
    --onefile ^
    --windowed ^
    --name "ADMIN CURSALA BOT" ^
    --add-data "tabs;tabs" ^
    --add-data "assets;assets" ^
    --collect-all PyQt6 ^
    main.py

if errorlevel 1 (
    echo ERROR: Error generando ejecutable
    pause
    exit /b 1
)

echo.
echo ====================================
echo ¡Ejecutable generado!
echo ====================================
echo.
echo Ubicación: dist\ADMIN CURSALA BOT.exe
echo.
echo Puedes:
echo   1. Ejecutarlo directamente desde dist\
echo   2. Crear un acceso directo
echo   3. Distribuirlo a otros usuarios
echo.
echo Nota: El ejecutable tiene ~200MB (incluye Python y PyQt6)
echo.
pause
