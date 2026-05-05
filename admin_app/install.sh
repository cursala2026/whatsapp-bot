#!/bin/bash

# Script de instalación para Admin App - Bot WhatsApp Cursala
# Este script configura el entorno virtual e instala dependencias

echo "===================================="
echo "Admin App Setup - Cursala Bot"
echo "===================================="
echo ""

# Verificar que Python está instalado
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 no está instalado"
    echo "En macOS: brew install python3"
    echo "En Linux: sudo apt-get install python3 python3-venv python3-pip"
    exit 1
fi

echo "✓ Python encontrado: $(python3 --version)"

# Crear entorno virtual si no existe
if [ ! -d "venv" ]; then
    echo ""
    echo "Creando entorno virtual..."
    python3 -m venv venv
    echo "✓ Entorno virtual creado"
else
    echo "✓ Entorno virtual ya existe"
fi

# Activar entorno virtual
echo ""
echo "Activando entorno virtual..."
source venv/bin/activate

# Actualizar pip
echo ""
echo "Actualizando pip..."
pip install --upgrade pip -q

# Instalar dependencias
echo ""
echo "Instalando dependencias..."
pip install -r requirements.txt -q

if [ $? -ne 0 ]; then
    echo "ERROR: Error instalando dependencias"
    exit 1
fi

echo "✓ Dependencias instaladas"

# Crear carpeta de backups
if [ ! -d "backups" ]; then
    mkdir -p backups
    echo "✓ Carpeta de backups creada"
fi

# Hacer ejecutable el script run.sh
chmod +x run.sh

echo ""
echo "===================================="
echo "¡Instalación completada!"
echo "===================================="
echo ""
echo "Para ejecutar la aplicación:"
echo "  python main.py"
echo ""
echo "O simplemente ejecutar: ./run.sh"
echo ""
