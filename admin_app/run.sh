#!/bin/bash

# Script para ejecutar Admin App - Bot WhatsApp Cursala

if [ ! -d "venv" ]; then
    echo "Error: Entorno virtual no encontrado"
    echo "Por favor ejecuta primero: ./install.sh"
    exit 1
fi

source venv/bin/activate
python main.py
