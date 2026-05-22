import streamlit as st
import subprocess
import sys
import re
import os

# Remover códigos ANSI de cor do terminal para exibir no Streamlit de forma limpa
ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

st.set_page_config(page_title="⚙️ PAI - Presença Ativa Inteligente", layout="wide")

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

st.title("⚙️ PAI - Presença Ativa Inteligente")

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
# FASES 1 a 3: Busca Ativa Diária
# ==========================================
st.header("Fases 1 a 3: Busca Ativa Diária")
st.markdown("""
Opere a campanha de disparos diretamente por este painel após a extração da SEDUC.
""")

dia = st.text_input("Dia da Campanha (Filtro para Fase 1)", value="4", help="O dia exato a ser buscado no Excel da SEDUC.")
dry_run = st.toggle("🧪 Modo Simulação (Dry Run)", value=True, help="Executa as fases sem gravar disparos reais na API do WhatsApp.")
skip_backfill = st.toggle("⚡ Pular Backfill de LIDs (mais rapido)", value=False, help="Se ligado, nao varre os chats @lid do WhatsApp antes de gerar os relatorios. Menos respostas serao detectadas.")

st.divider()

col1, col2, col3 = st.columns(3)

with col1:
    if st.button("1️⃣ Carregar Faltosos (Fase 1)", use_container_width=True):
        if not dia:
            st.warning("Preencha o Dia da Campanha!")
        else:
            cmd = [sys.executable, "-u", "scripts/campaign_loader.py", "--day", str(dia)]
            if dry_run:
                cmd.append("--dry-run")
            run_script_live(cmd, "Fase 1: Carregamento")

with col2:
    if st.button("2️⃣ Iniciar Disparos (Fase 2)", use_container_width=True):
        cmd = [sys.executable, "-u", "scripts/campaign_orchestrator.py"]
        if dry_run:
            cmd.append("--dry-run")
        run_script_live(cmd, "Fase 2: Disparos")

with col3:
    if st.button("3️⃣ Gerar Relatórios Consolidados (Fase 3)", use_container_width=True):
        cmd = [sys.executable, "-u", "scripts/campaign_reporter.py"]
        if skip_backfill:
            cmd.append("--skip-backfill")
        run_script_live(cmd, "Fase 3: Relatórios Consolidados")
