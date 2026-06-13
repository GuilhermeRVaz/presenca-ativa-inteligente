import streamlit as st
import subprocess
import sys
import re
import os
import json

# Remover códigos ANSI de cor do terminal para exibir no Streamlit de forma limpa
ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

st.set_page_config(page_title="⚙️ PAI - Presença Ativa Inteligente", layout="wide")

# Custom styling for UI wow effect
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&display=swap');

/* Main font application */
.main .block-container, [data-testid="stHeader"] {
    font-family: 'Outfit', sans-serif;
}

/* Premium metric cards styling */
div[data-testid="stMetric"] {
    background: linear-gradient(135deg, rgba(28, 30, 41, 0.95) 0%, rgba(43, 47, 66, 0.95) 100%);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 16px;
    padding: 22px 26px !important;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
    transition: transform 0.3s ease, box-shadow 0.3s ease, border-color 0.3s ease;
}

div[data-testid="stMetric"]:hover {
    transform: translateY(-4px);
    box-shadow: 0 15px 35px rgba(0, 0, 0, 0.3);
    border-color: rgba(99, 102, 241, 0.4);
}

div[data-testid="stMetric"] label {
    font-size: 13px !important;
    font-weight: 600 !important;
    color: rgba(255, 255, 255, 0.6) !important;
    letter-spacing: 0.8px;
    text-transform: uppercase;
}

div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
    font-size: 34px !important;
    font-weight: 800 !important;
    color: #ffffff !important;
    margin-top: 6px;
    background: linear-gradient(90deg, #ffffff 0%, #cbd5e1 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

/* Button style overrides for modern rounded looks */
.stButton > button {
    border-radius: 10px !important;
    font-weight: 600 !important;
    padding: 10px 20px !important;
    transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
}

.stButton > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 20px rgba(99, 102, 241, 0.2) !important;
}

/* Header dynamic gradient colors */
.main-title {
    background: linear-gradient(90deg, #6366f1 0%, #a855f7 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    font-weight: 800;
    font-size: 3rem;
    margin-bottom: 20px;
}
</style>
""", unsafe_allow_html=True)

def run_script_live(command, description):
    """
    Executa um comando e joga o stdout linha a linha em um bloco na tela do Streamlit.
    """
    with st.spinner(f"Executando {description}..."):
        # Contêiner vazio que será atualizado em tempo real
        log_container = st.empty()
        logs = []
        
        try:
            # Força o Windows a entender emojis (UTF-8) no console
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"

            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                env=env  # <--- A linha mágica que resolve o erro
            )
            
            for line in iter(process.stdout.readline, ''):
                clean_line = ansi_escape.sub('', line)
                logs.append(clean_line)
                # Pega as últimas 50 linhas para não travar a UI caso o log seja imenso
                display_text = "".join(logs[-50:])
                log_container.code(display_text, language="text")
                
            process.stdout.close()
            process.wait()
            
            # Quando finaliza, mostra tudo de uma vez de forma expansível ou completa
            log_container.code("".join(logs), language="text")
            
            if process.returncode == 0:
                st.success(f"✅ {description} concluída com sucesso!")
            else:
                st.error(f"❌ {description} terminou com código de erro {process.returncode}.")
        except Exception as e:
            st.error(f"Ocorreu um erro ao rodar o script: {e}")

def handle_followup_preview(dia):
    if not dia:
        st.warning("⚠️ Preencha o Dia da Campanha para simular o follow-up!")
        return

    with st.spinner("🔍 Analisando campanha principal e contatos secundários..."):
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        
        cmd = [sys.executable, "-u", "scripts/campaign_followup_loader.py", "--day", str(dia), "--preview"]
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                env=env
            )
            
            # Captura a saída do processo
            stdout, _ = process.communicate()
            process.wait()
            
            # Remove códigos ANSI da saída técnica
            clean_stdout = ansi_escape.sub('', stdout)
            
            # Encontra e parseia o JSON de preview
            json_match = re.search(r"__PREVIEW_JSON_START__\n(.*?)\n__PREVIEW_JSON_END__", clean_stdout, re.DOTALL)
            preview_json = None
            if json_match:
                try:
                    preview_json = json.loads(json_match.group(1).strip())
                except Exception as e:
                    st.error(f"Erro ao analisar o JSON de preview: {e}")
                # Remove o JSON da saída de log para exibição limpa
                clean_stdout = clean_stdout.replace(json_match.group(0), "")
            
            if process.returncode != 0:
                st.error(f"❌ Erro na execução da simulação (Código: {process.returncode})")
                st.code(clean_stdout, language="text")
                return

            if preview_json:
                st.success("🎉 Simulação de Follow-up concluída com sucesso!")
                
                # Cards de métricas premium
                m1, m2, m3 = st.columns(3)
                with m1:
                    st.metric(
                        label="👥 Alunos Não-Respondentes",
                        value=preview_json.get("total_eligible", 0),
                        help="Alunos da campanha principal que receberam a mensagem inicial, mas não responderam."
                    )
                with m2:
                    st.metric(
                        label="✅ Com 2º Contato (Prontos)",
                        value=preview_json.get("with_secondary", 0),
                        help="Alunos que possuem um contato secundário cadastrado e receberão a mensagem."
                    )
                with m3:
                    st.metric(
                        label="⚠️ Sem 2º Contato (Pulados)",
                        value=preview_json.get("without_secondary", 0),
                        help="Alunos sem contato secundário. Não receberão o follow-up."
                    )
                
                # Tabs para exibir as tabelas
                tab_envio, tab_alertas, tab_log = st.tabs([
                    "📋 Fila de Envio Prevista", 
                    f"⚠️ Alunos Sem 2º Contato ({preview_json.get('without_secondary', 0)})", 
                    "🖥️ Log Técnico Completo"
                ])
                
                with tab_envio:
                    eligible_list = preview_json.get("eligible_students", [])
                    if eligible_list:
                        import pandas as pd
                        df_eligible = pd.DataFrame(eligible_list)
                        df_eligible.columns = ["Aluno", "ID Aluno", "Responsável Primário", "Responsável Secundário", "Telefone Secundário"]
                        st.dataframe(df_eligible, use_container_width=True)
                    else:
                        st.info("Nenhum aluno elegível com segundo contato cadastrado no momento.")
                        
                with tab_alertas:
                    no_sec_list = preview_json.get("no_secondary_students", [])
                    if no_sec_list:
                        import pandas as pd
                        df_no_sec = pd.DataFrame(no_sec_list)
                        df_no_sec.columns = ["Aluno", "ID Aluno", "Responsável Primário"]
                        st.dataframe(df_no_sec, use_container_width=True)
                        st.warning("Esses alunos acima não receberão o follow-up automático porque não têm um contato secundário configurado na tabela 'student_guardians'.")
                    else:
                        st.success("Excelente! Todos os alunos não-respondentes têm segundo contato cadastrado!")
                        
                with tab_log:
                    st.code(clean_stdout, language="text")
            else:
                st.warning("⚠️ Não foi possível carregar a visualização estruturada. Exibindo logs brutos:")
                st.code(clean_stdout, language="text")
                
        except Exception as e:
            st.error(f"Erro ao executar a simulação: {e}")

# Render dynamic title with CSS styling
st.markdown('<h1 class="main-title">⚙️ PAI - Presença Ativa Inteligente</h1>', unsafe_allow_html=True)

# ==========================================
# FASE 0: Extração SEDUC
# ==========================================
st.header("Fase 0: Preparação de Dados (SEDUC)")
st.markdown("Extraia os dados de falta da Secretaria Escolar Digital de forma automatizada.")

colA, colB = st.columns(2)

with colA:
    if st.button("A: Abrir Navegador Robô", use_container_width=True):
        # Excluir a pasta de cache
        cache_dir = r"C:\chrome-debug"
        os.system(f'cmd.exe /c rmdir /s /q "{cache_dir}"')
        
        # Abrir o Chrome de forma não-bloqueante
        chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        cmd_chrome = f'"{chrome_path}" --remote-debugging-port=9222 --user-data-dir="{cache_dir}"'
        
        # Cria um processo independente (DETACHED_PROCESS = 0x00000008)
        subprocess.Popen(cmd_chrome, shell=True, creationflags=subprocess.DETACHED_PROCESS)
        
        st.info("Navegador aberto! Faça o login na SED, vá para a tela inicial e depois clique no botão ao lado.")

with colB:
    if st.button("B: Iniciar Extração (Robô)", use_container_width=True):
        run_script_live([sys.executable, "-u", "scripts/acesso_seduc.py"], "Fase 0: Extração SEDUC")

st.divider()

# ==========================================
# CONFIGURAÇÃO DE DIAS E PARÂMETROS
# ==========================================
st.header("Parâmetros da Campanha")
st.markdown("Defina o dia da planilha SEDUC e os modos de controle do sistema.")

col_p1, col_p2 = st.columns(2)
with col_p1:
    dia = st.text_input("Dia da Campanha (Filtro para Fase 1 / 1.5)", value="4", help="O dia exato a ser buscado no Excel da SEDUC.")
    dry_run = st.toggle("🧪 Modo Simulação (Dry Run)", value=True, help="Executa as fases sem gravar disparos reais na API do WhatsApp.")
with col_p2:
    min_delay = st.number_input("⏱️ Intervalo Mínimo (segundos)", value=45, min_value=1, help="Tempo mínimo de espera entre mensagens (anti-ban).")
    max_delay = st.number_input("⏱️ Intervalo Máximo (segundos)", value=120, min_value=1, help="Tempo máximo de espera entre mensagens (anti-ban).")

skip_backfill = st.toggle("⚡ Pular Backfill de LIDs (mais rápido)", value=False, help="Se ligado, não varre os chats @lid do WhatsApp antes de gerar os relatórios. Menos respostas serão detectadas.")

st.divider()

# ==========================================
# CAMPANHA ESPECIAL: OBMEP 2026
# ==========================================
st.header("🏆 Campanha Especial: OBMEP 2026 (09/06)")
st.markdown("Campanha informativa para notificar os responsáveis dos alunos de 8ºs e 7ºs anos sobre a realização da prova da OBMEP.")

col_obmep1, col_obmep2 = st.columns(2)
with col_obmep1:
    if st.button("📋 1. Gerar Fila da Campanha OBMEP", use_container_width=True, help="Seleciona alunos dos 8ºs e 7ºs anos no banco, escolhe mensagens randomizadas e enfileira as mensagens como 'pending'."):
        cmd = [sys.executable, "-u", "scripts/create_obmep_campaign.py"]
        if dry_run:
            cmd.append("--dry-run")
        run_script_live(cmd, "Carga da Campanha OBMEP")

with col_obmep2:
    if st.button("🚀 2. Disparar Mensagens da OBMEP", use_container_width=True, type="primary", help="Inicia o orquestrador especificamente para a campanha da OBMEP com pacing customizado."):
        cmd = [
            sys.executable, "-u", "scripts/campaign_orchestrator.py",
            "--min-delay", str(int(min_delay)),
            "--max-delay", str(int(max_delay))
        ]
        if dry_run:
            cmd.append("--dry-run")
        run_script_live(cmd, "Disparos da Campanha OBMEP")

st.divider()

# ==========================================
# FASE 1: Carregamento Inicial
# ==========================================
st.header("1️⃣ Fase 1: Carregamento Inicial (Primeiro Contato)")
st.markdown("Carrega os alunos faltosos do Excel correspondente e enfileira para o primeiro responsável (Primário).")

if st.button("1️⃣ Carregar Faltosos (Primeiro Contato)", use_container_width=True):
    if not dia:
        st.warning("⚠️ Preencha o Dia da Campanha!")
    else:
        cmd = [sys.executable, "-u", "scripts/campaign_loader.py", "--day", str(dia)]
        if dry_run:
            cmd.append("--dry-run")
        run_script_live(cmd, "Fase 1: Carregamento de Faltosos")

st.divider()

# ==========================================
# FASE 1.5: Preparar Follow-up (Segundo Contato)
# ==========================================
st.header("🔁 Fase 1.5: Preparar Follow-up (Segundo Contato)")
st.markdown("Varre a campanha principal em busca de não-respondentes, resolve o contato secundário e cria a campanha de follow-up.")

col_f15_1, col_f15_2 = st.columns(2)

with col_f15_1:
    if st.button("🔍 Visualizar Elegíveis (Preview Follow-up)", use_container_width=True, help="Simula a busca por não-respondentes e exibe a fila prevista."):
        handle_followup_preview(dia)

with col_f15_2:
    if st.button("🔁 Confirmar Geração do Follow-up (Carga)", use_container_width=True, type="primary", help="Cria ou reutiliza a campanha de follow-up e enfileira as mensagens no banco."):
        if not dia:
            st.warning("⚠️ Preencha o Dia da Campanha!")
        else:
            cmd = [sys.executable, "-u", "scripts/campaign_followup_loader.py", "--day", str(dia)]
            if dry_run:
                cmd.append("--dry-run")
            run_script_live(cmd, "Fase 1.5: Carga do Follow-up")

st.divider()

# ==========================================
# FASE 2 & FASE 3: Disparos e Relatórios
# ==========================================
st.header("2️⃣ & 3️⃣ Execução e Fechamento")
st.markdown("Inicie a orquestração de disparos ativos na fila de envio ou gere relatórios consolidados do dia.")

col_exec1, col_exec2 = st.columns(2)

with col_exec1:
    if st.button("🚀 Iniciar Orquestrador de Disparos (Fase 2)", use_container_width=True, help="Dispara as mensagens pendentes (tanto primárias quanto follow-ups) com pacing anti-ban."):
        cmd = [
            sys.executable, "-u", "scripts/campaign_orchestrator.py",
            "--min-delay", str(int(min_delay)),
            "--max-delay", str(int(max_delay))
        ]
        if dry_run:
            cmd.append("--dry-run")
        run_script_live(cmd, "Fase 2: Orquestração de Disparos")

with col_exec2:
    if st.button("📊 Gerar Relatórios Consolidados (Fase 3)", use_container_width=True, help="Varre respostas recebidas e consolida as estatísticas finais da campanha."):
        cmd = [sys.executable, "-u", "scripts/campaign_reporter.py"]
        if dia:
            cmd.extend(["--day", str(dia)])
        if skip_backfill:
            cmd.append("--skip-backfill")
        run_script_live(cmd, "Fase 3: Relatórios Consolidados")
