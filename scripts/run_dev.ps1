# Script PowerShell para configurar ambiente virtual e rodar a aplicação

Set-Location "C:\Users\user\presenca-ativa-inteligente"

# Verifica se o ambiente virtual já existe
if (-Not (Test-Path "venv\")) {
    Write-Host "Criando ambiente virtual..." -ForegroundColor Yellow
    python -m venv venv
}

# Ativa o ambiente virtual
Write-Host "Ativando ambiente virtual..." -ForegroundColor Yellow
.\venv\Scripts\Activate

# Instala as dependências
Write-Host "Instalando dependências..." -ForegroundColor Yellow
pip install -r requirements.txt

# Roda a aplicação
Write-Host "Iniciando servidor FastAPI..." -ForegroundColor Green
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload