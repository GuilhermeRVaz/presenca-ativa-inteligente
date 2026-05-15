#!/bin/bash
# Script para configurar ambiente virtual e rodar a aplicação

cd /c/Users/user/presenca-ativa-inteligente

# Verifica se o ambiente virtual já existe
if [ ! -d "venv/" ]; then
    echo "Criando ambiente virtual..."
    python -m venv venv
fi

# Ativa o ambiente virtual
source venv/bin/activate

# Instala as dependências
echo "Instalando dependências..."
pip install -r requirements.txt

# Roda a aplicação
echo "Iniciando servidor FastAPI..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload