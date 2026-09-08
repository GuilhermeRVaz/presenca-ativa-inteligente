# GUIA DEFINITIVO DE REPLICAÇÃO — PRESENÇA ATIVA INTELIGENTE (PAI)
## Manual Passo a Passo de Implantação em Novas Escolas

---

## 1. VISÃO GERAL E ARQUITETURA DO SISTEMA

O **Presença Ativa Inteligente (PAI)** é uma plataforma integrada de combate à evasão escolar, comunicação automatizada e busca ativa de estudantes por meio de inteligência artificial e WhatsApp.

```
       ┌────────────────────────┐
       │   WhatsApp da Escola   │
       │ (Celular da Secretaria)│
       └───────────┬────────────┘
                   │
                   ▼
       ┌────────────────────────┐
       │     Evolution API      │ ◄── [Instância WhatsApp / QR Code]
       └───────────┬────────────┘
                   │ Webhook (Mensagens Recebidas)
                   ▼
       ┌────────────────────────┐
       │      Orquestrador      │ ◄── [Fluxos de Triagem, FAQ, RAG e Disparos]
       │         (n8n)          │
       └─────┬────────────┬─────┘
             │            │
  API / Docs │            │ Chamada IA
             ▼            ▼
┌──────────────────┐  ┌──────────────────┐
│   Backend PAI    │  │ OpenAI / Gemini  │ ◄── [Classificação de Intenção,
│    (FastAPI)     │  │   (Modelos LLM)  │      RAG FAQ, Respostas Humanizadas]
└────────┬─────────┘  └──────────────────┘
         │
         ▼
┌──────────────────────────────────────┐
│       Banco de Dados PostgreSQL      │ ◄── [Tabelas: Alunos, Turmas, Responsáveis,
│              (Supabase)              │      Faltas, Conversas, Histórico de Mensagens]
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│     Painel Web de Gestão Escolar     │ ◄── [Usado pela Direção / Secretaria:
│             (Streamlit)              │      Disparos de Faltas, Relatórios, Justificativas]
└──────────────────────────────────────┘
```

### Componentes do Ecossistema:
1. **Painel de Gestão (Streamlit - Porta 8501)**: Interface visual intuitiva onde a secretaria escolar cadastra turmas, visualiza ausências, dispara campanhas de busca ativa e exporta relatórios oficiais (Word/PDF).
2. **Backend API (FastAPI - Porta 8000)**: Núcleo de regras de negócio, validação de números de telefone, sincronização de dados e roteamento seguro.
3. **Orquestrador de Fluxos (n8n - Porta 5678)**: Gerencia a recepção e envio de mensagens no WhatsApp, validação de webhooks e automação de triagem.
4. **Gateway WhatsApp (Evolution API ou Z-API)**: Conecta o número de WhatsApp oficial da escola à internet via API REST.
5. **Cérebro de Inteligência Artificial (OpenAI / Gemini)**: Analisa as mensagens dos responsáveis, classifica justificativas de faltas e responde dúvidas institucionais com base no FAQ da escola.
6. **Banco de Dados (Supabase / PostgreSQL)**: Armazenamento em nuvem seguro e escalável de todos os cadastros e históricos de conversas.

---

## 2. O QUE COPIAR NO PEN DRIVE (KIT DE IMPLANTAÇÃO)

Para levar o sistema até a nova escola em um Pen Drive ou pasta compactada (ZIP), siga o checklist abaixo.

### ✅ O que COPIAR para o Pen Drive:
| Pasta / Arquivo | Descrição |
| :--- | :--- |
| `app/` | Código fonte do Backend FastAPI (regras de negócio e serviços) |
| `pages/` | Páginas complementares do Painel Streamlit (ex: CRUD Supabase) |
| `migrations/` | Todos os scripts SQL de criação do banco de dados (pasta `versions/`) |
| `scripts/` | Utilitários de ingestão de dados, sincronização e relatórios |
| `docker-compose.yml` | Orquestrador de inicialização de todos os containers |
| `Dockerfile` | Receita de construção das imagens Docker da API e Painel |
| `requirements.txt` | Lista de bibliotecas Python necessárias |
| `painel.py` | Código principal do Painel de Gestão Streamlit |
| `workflow_triagem_final.json` | Fluxo de automação exportado do n8n para importação direta |
| `.env.example` | Modelo de arquivo de configuração com as variáveis em branco |
| `TUTORIAL_REPLICACAO_NOVA_ESCOLA.md` | Este guia de implantação |
| `Manual_Replicacao_Presenca_Ativa_Inteligente.docx` | Manual formatado para impressão ou leitura em Word |

### ❌ O que NÃO COPIAR (Omitir para segurança e limpeza):
- **NUNCA copie o arquivo `.env`** com as chaves e dados da escola antiga!
- Pastas temporárias de ambiente: `.venv/`, `venv/`, `__pycache__/`, `.pytest_cache/`.
- Histórico Git grande: `.git/` (opcional, pode ser recriado com `git init`).
- Arquivos de dados de alunos específicos da escola anterior (ex: PDFs de calendários antigos, planilhas da escola anterior).

---

## 3. ONDE E COMO CONSEGUIR TODAS AS CHAVES E SERVIÇOS (`.env`)

Na pasta raiz da nova instalação, crie uma cópia de `.env.example` e renomeie para `.env`. Preencha cada bloco conforme as orientações a seguir:

```ini
# ==============================================================================
# CONFIGURAÇÕES DA NOVA ESCOLA
# ==============================================================================
APP_NAME=busca-ativa-v2
DEBUG=true
LOG_LEVEL=INFO
SCHOOL_NAME="Escola Estadual Modelo"
DEFAULT_SCHOOL_ID=

# ==============================================================================
# 1. SUPABASE (BANCO DE DADOS EM NUVEM)
# ==============================================================================
SUPABASE_URL=https://sua-url-aqui.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.sua-chave-anon-ou-service-role

# ==============================================================================
# 2. EVOLUTION API (CONEXÃO COM O WHATSAPP DA ESCOLA)
# ==============================================================================
EVOLUTION_API_URL=https://api-whatsapp.sua-escola.com.br
EVOLUTION_API_KEY=sua-chave-global-ou-de-autenticacao
EVOLUTION_API_INSTANCE=presenca_ativa_escola
EVOLUTION_TIMEOUT_SECONDS=30

# ==============================================================================
# 3. N8N (ORQUESTRADOR DE MENSAGENS)
# ==============================================================================
N8N_WEBHOOK_URL=http://n8n:5678/webhook/triagem

# ==============================================================================
# 4. INTELIGÊNCIA ARTIFICIAL (OPENAI / GEMINI)
# ==============================================================================
OPENAI_API_KEY=sk-proj-sua-chave-openai-aqui
```

---

### Passo a Passo para Obter cada Chave:

### 🔹 1. Supabase (Banco de Dados PostgreSQL)
1. Acesse **[supabase.com](https://supabase.com)** e crie uma conta gratuita (ou faça login).
2. Clique em **"New Project"** (Novo Projeto).
3. Defina um **Nome** (ex: `PAI - Escola Modelo`), escolha uma **Senha Forte para o Banco** e selecione a Região `Sao Paulo (sa-east-1)`.
4. Após o projeto ser provisionado (cerca de 1 minuto):
   - Vá no menu lateral esquerdo em **Project Settings (Ícone de Engrenagem) > API**.
   - Copie o **Project URL** ➔ cole em `SUPABASE_URL` no `.env`.
   - Copie a chave **`anon` `public`** (ou `service_role` para acesso total) ➔ cole em `SUPABASE_KEY` no `.env`.
5. **Criando as Tabelas no Banco**:
   - No menu lateral esquerdo do Supabase, clique em **SQL Editor** > **New query**.
   - Abra a pasta `migrations/versions/` do projeto no computador.
   - Copie e execute o conteúdo de cada arquivo SQL **na ordem numérica**:
     1. `0001_create_busca_ativa_v2_schema.sql` (Cria o schema, tabelas de alunos, faltas, responsáveis, etc.)
     2. `0002_create_migration_and_helper_functions.sql` (Cria funções auxiliares)
     3. `0003_enable_rls_policies_scaffold.sql` (Políticas de segurança)
     4. `0004_add_production_correlation_indexes.sql` (Índices de performance)
     5. `0005_fix_conversation_sessions_permissions.sql` (Permissões de sessões de conversa)
     6. `0006_create_ai_interactions_table.sql` (Tabela de interações de IA)
     7. `0007_add_campaign_type.sql` (Tipos de campanhas)
   - Clique em **Run** para cada uma. Ao final, o banco estará 100% pronto!

---

### 🔹 2. Evolution API (WhatsApp)
1. Pode ser contratado um serviço de hospedagem de Evolution API (ou instalado em VPS própria).
2. No painel da Evolution API:
   - Crie uma nova instância (ex: `escola_modelo`).
   - Obtenha a **API URL** (ex: `https://api.meuservidor.com`) ➔ cole em `EVOLUTION_API_URL`.
   - Obtenha a **API Key Global** ➔ cole em `EVOLUTION_API_KEY`.
   - O nome da instância criada vai em `EVOLUTION_API_INSTANCE`.
3. Abra a tela da instância no painel da Evolution API e clique em **Gerar QR Code**.
4. Pegue o celular do WhatsApp oficial da escola, abra o WhatsApp > **Aparelhos Conectados** > **Conectar Aparelho** e aponte para o QR Code.
5. Configure o Webhook na Evolution API apontando para a URL do n8n (ex: `http://seu-servidor:5678/webhook/triagem` ou via ngrok/túnel seguro em testes).

---

### 🔹 3. OpenAI / Google Gemini (Inteligência Artificial)
1. Acesse **[platform.openai.com](https://platform.openai.com)**.
2. Faça login e vá em **API Keys**.
3. Clique em **Create new secret key**, dê um nome (ex: `PAI_Escola_Modelo`) e copie a chave gerada (iniciada em `sk-proj-...`).
4. Cole em `OPENAI_API_KEY` no `.env`.
5. *(Opcional)*: Para usar Google Gemini, acesse **[aistudio.google.com](https://aistudio.google.com)**, crie uma chave em **Get API key** e adicione `GEMINI_API_KEY=...` no `.env`.

---

### 🔹 4. n8n (Orquestrador)
1. Ao iniciar o sistema (via Docker), o n8n estará acessível em `http://localhost:5678`.
2. No primeiro acesso, crie seu usuário e senha de administrador.
3. Clique em **Workflows > Import from File** e selecione o arquivo `workflow_triagem_final.json` da raiz do projeto.
4. Ajuste as credenciais dos nós de envio (HTTP Request / Evolution API) e salve o fluxo ativando a chave **Active**.

---

## 4. CONSTRUÇÃO, VIBECODING E CUSTOMIZAÇÃO VIA IDE ANTIGRAVITY

A **IDE Antigravity** é o ambiente de desenvolvimento orientado a IA que permite implantar, testar, alterar e operar o sistema em modo **"Vibecoding"** (programação guiada por intenção em linguagem natural).

### Como abrir e preparar a IDE Antigravity na Nova Escola:
1. Abra a **IDE Antigravity** no computador.
2. Clique em **Open Folder** (Abrir Pasta) e selecione a pasta `presenca-ativa-inteligente`.
3. O assistente de IA da Antigravity lerá automaticamente a estrutura do projeto e as regras do sistema (`AGENTS.md`).

---

### Como Ativar MCPs e Skills para Turbinar o "Vibecoding"

Para que a IA da Antigravity possa executar tarefas diretamente no banco de dados, no n8n e no backend sem você precisar digitar código manual, configure os **MCP Servers** e **Skills**:

#### A. O que são MCPs (Model Context Protocol)?
MCPs são protocolos de extensão que dão à IA a capacidade de executar ações diretas em ferramentas externas (ex: consultar o banco Supabase em tempo real, manipular nós do n8n, executar queries e inspecionar logs).

#### B. Como configurar os MCPs na Antigravity:
No arquivo de configuração de MCP (`mcp_config.json` ou nas configurações da IDE Antigravity), adicione os servidores:

```json
{
  "mcpServers": {
    "supabase-mcp-server": {
      "command": "npx",
      "args": [
        "-y",
        "@supabase/mcp-server"
      ],
      "env": {
        "SUPABASE_URL": "https://seu-projeto.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "sua-chave-service-role"
      }
    },
    "n8n-mcp": {
      "command": "npx",
      "args": [
        "-y",
        "n8n-mcp"
      ],
      "env": {
        "N8N_API_URL": "http://localhost:5678/api/v1",
        "N8N_API_KEY": "sua-chave-api-n8n"
      }
    }
  }
}
```

#### C. Como ativar as Skills Especialistas:
Na pasta `.agent/skills/` do projeto, garanta que as seguintes skills estejam ativas:
- `n8n-mcp-tools-expert` e `n8n-workflow-patterns`: Permite à IA criar e validar fluxos complexos no n8n automaticamente.
- `supabase-automation` e `postgres-best-practices`: Permite à IA inspecionar schemas, criar índices e validar migrações SQL.
- `fastapi-pro` e `clean-code`: Garante extensão de endpoints com alta performance e sem quebrar compatibilidade.

---

### 💬 Prompts Mestres ("Plug and Play") para Colar na IDE Antigravity

Você pode copiar e colar qualquer um dos prompts abaixo diretamente no chat da IDE Antigravity para que ela faça o trabalho pesado para você:

#### Prompt 1: Configuração Inicial e Teste de Ambiente
> *"Olá Antigravity! Estou implantando o sistema PAI para a [Nome da Escola]. Acabei de preencher o arquivo .env. Por favor, verifique a conexão com o Supabase, teste as variáveis de ambiente e execute os testes unitários (`pytest`) para garantir que tudo está pronto para execução."*

#### Prompt 2: Validação e Aplicação das Migrações de Banco
> *"Antigravity, verifique o status das tabelas no Supabase. Compare com os arquivos da pasta `migrations/versions/` e garanta que todas as tabelas (alunos, responsáveis, faltas, conversas e campanhas) estão criadas e com as permissões corretas."*

#### Prompt 3: Ingestão de Lista de Alunos e Turmas da Nova Escola
> *"Antigravity, tenho uma planilha com a lista de alunos da escola [anexar arquivo CSV ou colar os dados com Nome, Matrícula, Turma, Nome do Responsável e Telefone WhatsApp]. Escreva e execute um script seguro em `scripts/import_novos_alunos.py` para cadastrar todos os alunos no Supabase associados à nossa escola."*

#### Prompt 4: Customização do FAQ Institucional da Escola para a IA
> *"Antigravity, aqui estão as regras da nossa escola: horário de entrada às 07h00, portão fecha às 07h15, uniforme obrigatório, reuniões de pais bimestrais. Atualize o prompt do assistente de triagem RAG para que a IA responda exatamente de acordo com essas regras institucionais."*

#### Prompt 5: Execução e Diagnóstico Completo
> *"Antigravity, inicie todos os serviços via Docker Compose. Em seguida, verifique a saúde da API em `http://127.0.0.1:8000/health` e garanta que o Painel Streamlit em `http://localhost:8501` está rodando sem erros."*

---

## 5. COMO INICIAR O SISTEMA (DOCKER OU LOCAL)

### Método 1: Inicialização via Docker Compose (Recomendado)
Este é o método mais simples e robusto. Com um único comando, o banco local de cache, o n8n, a API FastAPI e o Painel Streamlit sobem juntos em containers isolados.

1. Abra o terminal (PowerShell ou Bash) na pasta do projeto.
2. Execute o comando:
```powershell
docker-compose up -d --build
```
3. Verifique o status dos containers:
```powershell
docker-compose ps
```
4. Acesse os serviços no navegador:
   - **Painel de Gestão Escolar:** `http://localhost:8501`
   - **Documentação da API (FastAPI):** `http://localhost:8000/docs`
   - **Orquestrador n8n:** `http://localhost:5678`

---

### Método 2: Inicialização Local sem Docker (Python Nativo)
Caso o computador da escola não possua Docker instalado, execute com Python:

1. Certifique-se de ter o **Python 3.11 ou superior** instalado.
2. Abra o terminal na pasta do projeto e crie o ambiente virtual:
```powershell
python -m venv .venv
```
3. Ative o ambiente virtual:
   - Windows PowerShell: `.\.venv\Scripts\Activate.ps1`
   - Linux/Mac: `source .venv/bin/activate`
4. Instale as dependências:
```powershell
pip install -r requirements.txt
```
5. Inicie a API Backend (Terminal 1):
```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
6. Inicie o Painel de Gestão Streamlit (Terminal 2):
```powershell
streamlit run painel.py
```

---

## 6. ROTINA DE OPERAÇÃO DIÁRIA DA ESCOLA

1. **Início do Turno (07h30 / 13h30)**:
   - O professor ou secretaria lança as faltas do dia no sistema acadêmico oficial (SED, SGE, Diário de Classe).
   - O responsável pela busca ativa abre o **Painel PAI** (`http://localhost:8501`).
2. **Disparo da Campanha de Ausência**:
   - No painel, selecione a data e as turmas com ausências registradas.
   - Clique em **"Disparar Notificações via WhatsApp"**.
   - O sistema envia automaticamente uma mensagem acolhedora e personalizada para o WhatsApp de cada responsável.
3. **Atendimento Automatizado e Triagem com IA**:
   - Quando o responsável responde justificando o motivo (ex: *"Arthur acordou com febre e fomos ao posto"*), o n8n e a IA classificam o motivo (Saúde / Transporte / Motivo Pessoal), registram a justificativa no banco e notificam a escola.
   - Dúvidas institucionais (ex: *"Qual o horário da reunião?"*) são respondidas na hora pela IA com base nas diretrizes da escola.
4. **Relatórios Oficiais e Gestão**:
   - A qualquer momento, a gestão clica em **"Exportar Relatório Word/PDF"** para gerar a documentação comprobatória de Busca Ativa exigida pela Diretoria de Ensino ou Conselho Tutelar.

---

## 7. CHECKLIST DE VALIDAÇÃO E TROUBLESHOOTING

| Situação | Causa Provável | Solução |
| :--- | :--- | :--- |
| **Painel Streamlit exibe erro de conexão** | `.env` com `SUPABASE_URL` ou `SUPABASE_KEY` incorretos | Verifique o arquivo `.env` e confirme se o projeto no Supabase está ativo. |
| **Mensagens do WhatsApp não chegam** | Instância desconectada ou QR Code expirado | Acesse a Evolution API, verifique o status da instância e reconecte via QR Code. |
| **A IA não responde aos pais** | `OPENAI_API_KEY` sem créditos ou fluxo do n8n inativo | Verifique se há saldo na conta OpenAI e garanta que o workflow no n8n está com o botão **Active** ligado. |
| **Porta 8501 ou 8000 já em uso** | Outro processo local está rodando nessa porta | Feche terminais antigos ou altere a porta no `docker-compose.yml` ou comando de inicialização. |
| **Alunos importados não aparecem** | `school_id` inconsistente | Certifique-se de que a escola selecionada no painel corresponde ao `school_id` cadastrado no banco. |

---
*Presença Ativa Inteligente — Transformando a comunicação escolar e garantindo a permanência do estudante na sala de aula.*
