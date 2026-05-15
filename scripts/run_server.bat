@echo off
REM Script para configurar ambiente virtual e rodar a aplicacao

cd /d C:\Users\user\presenca-ativa-inteligente

REM Verifica se o ambiente virtual ja existe
if not exist "venv\" (
    echo Criando ambiente virtual...
    python -m venv venv
    if errorlevel 1 (
        echo ERRO: falha ao criar ambiente virtual.
        pause
        exit /b 1
    )
)

REM Ativa o ambiente virtual
call venv\Scripts\activate
if errorlevel 1 (
    echo ERRO: falha ao ativar ambiente virtual.
    pause
    exit /b 1
)

REM Instala as dependencias
echo Instalando dependencias...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERRO: falha ao instalar dependencias. Servidor nao sera iniciado.
    pause
    exit /b 1
)

REM Roda a aplicacao
echo Iniciando servidor FastAPI...
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

pause
