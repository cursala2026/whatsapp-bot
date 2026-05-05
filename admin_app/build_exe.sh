#!/bin/bash

# Script para generar ejecutable del Admin App (macOS/Linux)

echo "===================================="
echo "Generador de Ejecutable - Cursala Bot Admin App"
echo "===================================="
echo ""

# Verificar que venv existe
if [ ! -d "venv" ]; then
    echo "ERROR: Entorno virtual no encontrado"
    echo "Ejecuta primero: ./install.sh"
    exit 1
fi

source venv/bin/activate

# Verificar que PyInstaller está instalado
pip show pyinstaller > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo ""
    echo "Instalando PyInstaller..."
    pip install pyinstaller -q
    if [ $? -ne 0 ]; then
        echo "ERROR: No se pudo instalar PyInstaller"
        exit 1
    fi
fi

echo "✓ PyInstaller está disponible"

# Generar ejecutable
echo ""
echo "Generando ejecutable..."
echo "(Esto puede tardar 1-2 minutos)"
echo ""

# Detectar SO
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    pyinstaller \
        --onefile \
        --windowed \
        --name "cursala-admin" \
        --add-data "tabs:tabs" \
        --collect-all PyQt6 \
        main.py
else
    # Linux
    pyinstaller \
        --onefile \
        --windowed \
        --name "cursala-admin" \
        --add-data "tabs:tabs" \
        --collect-all PyQt6 \
        main.py
fi

if [ $? -ne 0 ]; then
    echo "ERROR: Error generando ejecutable"
    exit 1
fi

echo ""
echo "===================================="
echo "¡Ejecutable generado!"
echo "===================================="
echo ""
echo "Ubicación: dist/cursala-admin"
echo ""
echo "Puedes:"
echo "  1. Ejecutarlo directamente desde dist/"
echo "  2. Crear un acceso directo"
echo "  3. Distribuirlo a otros usuarios"
echo ""
echo "Nota: El ejecutable tiene ~200MB (incluye Python y PyQt6)"
echo ""
