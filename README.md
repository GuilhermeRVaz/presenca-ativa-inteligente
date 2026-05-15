# Presenca Ativa Inteligente / Busca Ativa Escolar V2

Reconstrucao paralela e isolada do sistema de comunicacao escolar via WhatsApp.

Nesta etapa, o projeto contem apenas a fundacao de banco:

- migrations SQL versionadas;
- schema isolado `busca_ativa_v2`;
- tabelas, constraints, indices e comentarios;
- runner com `dry-run`, `print-sql` e aplicacao apenas em PostgreSQL local.

Nenhuma migration e aplicada automaticamente no Supabase de producao.

## Guia de Instalação (Nova Máquina)

Siga estes passos para configurar o ambiente em uma máquina nova.

### 1. Requisitos
- [Docker](https://www.docker.com/products/docker-desktop/) e Docker Compose instalados.
- [Git](https://git-scm.com/) instalado.

### 2. Configuração do Supabase
1. Crie um novo projeto no [Supabase](https://supabase.com/).
2. Vá em **SQL Editor** e crie uma nova query.
3. Copie e cole o conteúdo dos arquivos na pasta `migrations/` (na ordem numérica) para criar o schema e as tabelas.
4. Em **Settings > API**, anote a `Project URL` e a `anon public API key`.

### 3. Clonar e Configurar
```powershell
git clone <url-do-repositorio>
cd presenca-ativa-inteligente
copy .env.example .env
```
Edite o arquivo `.env` com as chaves do Supabase e da Evolution API.

### 4. Iniciar com Docker
```powershell
docker-compose up -d --build
```

Após o build, os serviços estarão disponíveis em:
- **API (FastAPI):** http://localhost:8000/docs
- **Painel (Streamlit):** http://localhost:8501
- **n8n:** http://localhost:5678

### 5. Configurar n8n
1. Acesse o n8n local.
2. Importe o arquivo `workflow_triagem_final.json`.
3. Configure as credenciais de Webhook e HTTP Request apontando para a URL da sua API (ex: `http://api:8000`).

## Comandos Úteis (Desenvolvimento Local)
...
