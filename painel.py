import streamlit as st
import subprocess
import sys
import re
import os
import json
import httpx
import pandas as pd
from datetime import datetime, timezone

from app.core.config import settings
from app.services.extraordinary_campaign_service import ExtraordinaryCampaignService
from app.services.campaign_ai_service import CampaignAIService

# Regex para limpar códigos ANSI do terminal para exibição no Streamlit
ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

st.set_page_config(
    page_title="⚙️ PAI — Presença Ativa Inteligente",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilização CSS de alto impacto (Modern Dark / Glassmorphism)
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&display=swap');

.main .block-container, [data-testid="stHeader"] {
    font-family: 'Outfit', sans-serif;
}

/* Titulo Principal */
.main-title {
    background: linear-gradient(90deg, #6366f1 0%, #a855f7 50%, #ec4899 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    font-weight: 800;
    font-size: 2.6rem;
    margin-bottom: 0px;
}

.sub-title {
    color: rgba(255, 255, 255, 0.6);
    font-size: 1rem;
    margin-bottom: 25px;
}

/* Metric Cards */
div[data-testid="stMetric"] {
    background: linear-gradient(135deg, rgba(28, 30, 41, 0.95) 0%, rgba(43, 47, 66, 0.95) 100%);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 16px;
    padding: 18px 22px !important;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
    transition: transform 0.3s ease, border-color 0.3s ease;
}

div[data-testid="stMetric"]:hover {
    transform: translateY(-3px);
    border-color: rgba(99, 102, 241, 0.5);
}

div[data-testid="stMetric"] label {
    font-size: 12px !important;
    font-weight: 700 !important;
    color: rgba(255, 255, 255, 0.6) !important;
    letter-spacing: 0.8px;
    text-transform: uppercase;
}

div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
    font-size: 30px !important;
    font-weight: 800 !important;
    color: #ffffff !important;
}

/* Botões Customizados */
.stButton > button {
    border-radius: 10px !important;
    font-weight: 600 !important;
    padding: 8px 18px !important;
    transition: all 0.2s ease !important;
}

.stButton > button:hover {
    transform: translateY(-2px) !important;
}

/* Risk Cards */
.risk-card-healthy {
    background: rgba(16, 185, 129, 0.1);
    border: 1px solid rgba(16, 185, 129, 0.4);
    border-radius: 12px;
    padding: 16px;
    color: #10b981;
}

.risk-card-moderate {
    background: rgba(245, 158, 11, 0.1);
    border: 1px solid rgba(245, 158, 11, 0.4);
    border-radius: 12px;
    padding: 16px;
    color: #f59e0b;
}

.risk-card-high {
    background: rgba(239, 68, 68, 0.1);
    border: 1px solid rgba(239, 68, 68, 0.4);
    border-radius: 12px;
    padding: 16px;
    color: #ef4444;
}

/* Banner de Campanha Ativa */
.active-banner {
    background: linear-gradient(135deg, rgba(99, 102, 241, 0.15) 0%, rgba(168, 85, 247, 0.15) 100%);
    border: 1px solid rgba(99, 102, 241, 0.4);
    border-radius: 14px;
    padding: 18px 24px;
    margin-bottom: 25px;
}
</style>
""", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# FUNÇÕES DE EXECUÇÃO E SUPORTE
# -----------------------------------------------------------------------------
def run_script_live(command: list[str], description: str):
    """
    Executa um script Python em subprocesso e exibe a saída linha a linha no Streamlit.
    """
    st.markdown(f"### 🖥️ Terminal ao Vivo: {description}")
    log_container = st.empty()
    logs = [">>> Iniciando execução...\n"]
    log_container.code("".join(logs), language="text")

    try:
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
            env=env
        )

        for line in iter(process.stdout.readline, ''):
            clean_line = ansi_escape.sub('', line)
            logs.append(clean_line)
            display_text = "".join(logs[-60:])
            log_container.code(display_text, language="text")

        process.stdout.close()
        process.wait()
        log_container.code("".join(logs), language="text")

        if process.returncode == 0:
            st.success(f"✅ {description} concluída com sucesso!")
        else:
            st.error(f"❌ {description} encerrou com código de erro {process.returncode}.")
    except Exception as e:
        st.error(f"Erro ao executar o script: {e}")


def trigger_kill_switch():
    """
    Aciona o Kill Switch Global: Cancela todas as campanhas em andamento.
    """
    try:
        service = ExtraordinaryCampaignService()
        res = (
            service.client.table("campaigns")
            .update({"status": "cancelled"})
            .in_("status", ["draft", "pending", "dispatching", "active", "paused"])
            .execute()
        )
        st.toast(f"🚨 KILL SWITCH EXECUTADO! {len(res.data or [])} campanhas foram canceladas.", icon="🚨")
        st.rerun()
    except Exception as e:
        st.error(f"Erro ao acionar Kill Switch: {e}")


# -----------------------------------------------------------------------------
# CABEÇALHO DA APLICAÇÃO & KILL SWITCH GLOBAL
# -----------------------------------------------------------------------------
col_head1, col_head2 = st.columns([3, 1])

with col_head1:
    st.markdown('<h1 class="main-title">⚙️ PAI — Presença Ativa Inteligente</h1>', unsafe_allow_html=True)
    st.markdown('<p class="sub-title">Plataforma SaaS de Engajamento Escolar e Busca Ativa com IA Conversacional</p>', unsafe_allow_html=True)

with col_head2:
    st.write("")
    if st.button("🚨 KILL SWITCH GLOBAL", type="primary", use_container_width=True, help="Cancela instantaneamente todas as campanhas ativas ou enfileiradas."):
        trigger_kill_switch()

# Servico principal
camp_service = ExtraordinaryCampaignService()
ai_service = CampaignAIService()

# -----------------------------------------------------------------------------
# BANNER DE CAMPANHA ATIVA / DUPLICIDADE
# -----------------------------------------------------------------------------
try:
    active_camps = (
        camp_service.client.table("campaigns")
        .select("*")
        .in_("status", ["dispatching", "active", "pending"])
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if active_camps.data:
        ac = active_camps.data[0]
        # Pega mensagens pendentes/enviadas
        res_m = (
            camp_service.client.table("messages")
            .select("status")
            .eq("campaign_id", ac["id"])
            .execute()
        )
        msgs_data = res_m.data or []
        n_pending = sum(1 for m in msgs_data if m.get("status") == "pending")
        n_sent = sum(1 for m in msgs_data if m.get("status") == "sent")
        n_total = len(msgs_data)

        st.markdown(f"""
        <div class="active-banner">
            <h4 style="margin:0; color:#6366f1;">📢 Campanha Ativa em Andamento: <b>{ac.get('name')}</b></h4>
            <p style="margin: 5px 0 0 0; font-size: 14px; color: rgba(255,255,255,0.8);">
                Status: <b>{ac.get('status').upper()}</b> | Enviadas: <b>{n_sent}</b> | Pendentes na Fila: <b>{n_pending}</b> (Total: {n_total})
            </p>
        </div>
        """, unsafe_allow_html=True)

        col_b1, col_b2, col_b3 = st.columns(3)
        with col_b1:
            if st.button("🚀 Executar / Retomar Disparos", key="btn_resume_banner", use_container_width=True, type="primary"):
                cmd = [sys.executable, "-u", "scripts/campaign_orchestrator.py", "--campaign-id", ac["id"]]
                run_script_live(cmd, f"Orquestrador — {ac.get('name')}")
        with col_b2:
            if st.button("⏸️ Pausar Campanha", key="btn_pause_banner", use_container_width=True):
                camp_service.client.table("campaigns").update({"status": "paused"}).eq("id", ac["id"]).execute()
                st.toast("Campanha pausada com sucesso!")
                st.rerun()
        with col_b3:
            if st.button("🚫 Cancelar Campanha", key="btn_cancel_banner", use_container_width=True):
                camp_service.client.table("campaigns").update({"status": "cancelled"}).eq("id", ac["id"]).execute()
                st.toast("Campanha cancelada!")
                st.rerun()
except Exception as e:
    pass

st.divider()

# -----------------------------------------------------------------------------
# ESTRUTURA EM 5 ABAS PRINCIPAIS
# -----------------------------------------------------------------------------
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📢 Nova Campanha Extraordinária",
    "🩺 Diagnóstico Pré-Voo",
    "📁 Biblioteca de Templates",
    "📊 Histórico & Métricas",
    "🚨 Busca Ativa (Diária / SEDUC)"
])


# =============================================================================
# ABA 1: NOVA CAMPANHA EXTRAORDINÁRIA
# =============================================================================
with tab1:
    st.subheader("📢 Criar Nova Campanha Extraordinária")
    st.markdown("Configure parâmetros, gere variações por IA para proteção anti-ban e avalie o Risk Score antes do envio.")

    col_form1, col_form2 = st.columns([1.2, 1])

    with col_form1:
        camp_title = st.text_input(
            "Nome da Campanha",
            value=st.session_state.get("draft_title", ""),
            placeholder="Ex: Convocação para Reunião de Pais - 3º Bimestre"
        )

        c_cat, c_aud = st.columns(2)
        with c_cat:
            category = st.selectbox(
                "Categoria",
                ["CONVOCACAO", "INFORMATIVA", "EVENTO", "LEMBRETE", "EMERGENCIAL", "OUTRO"]
            )
        with c_aud:
            audience_type = st.radio(
                "Público Alvo",
                ["Toda a Escola", "Turmas Específicas"],
                horizontal=True
            )

        selected_classes = []
        if audience_type == "Turmas Específicas":
            available_classes = camp_service.list_available_classes()
            selected_classes = st.multiselect(
                "Selecione as Turmas",
                available_classes,
                default=available_classes[:2] if available_classes else []
            )

        base_message = st.text_area(
            "Mensagem Base Original (com Placeholders)",
            value=st.session_state.get("draft_body", (
                "Olá {{nome_responsavel}}, aqui é da {{escola}}. "
                "Convidamos você para a Reunião de Pais do aluno {{nome_aluno}} (Turma: {{turma}}) "
                "nesta próxima Quinta-feira às 19:00. Sua presença é fundamental!"
            )),
            height=140
        )

        campaign_faq = st.text_area(
            "💡 FAQ / Contexto para IA Conversacional (Apoio ao Atendimento)",
            placeholder="Ex: A reunião será presencial no pátio principal. Haverá entrega de boletins. Estacionamento no portão 2.",
            help="Este contexto orientará a IA a responder às dúvidas que os pais enviarem pelo WhatsApp após o disparo."
        )

        st.caption("Placeholders disponíveis: `{{nome_responsavel}}`, `{{nome_aluno}}`, `{{turma}}`, `{{escola}}`")

    with col_form2:
        st.markdown("### 🛡️ Configuração Anti-Spam & Risk Engine")

        daily_limit = st.slider("Limite Máximo Diário", 5, 250, 50, step=5, help="Quantidade máxima de mensagens enviadas por dia.")
        pilot_mode = st.toggle("🧪 Modo Piloto (Lote Fracionado)", value=True, help="Envia apenas para um lote reduzido primeiro para testar receptividade.")
        
        pilot_limit = 5
        if pilot_mode:
            pilot_limit = st.select_slider("Tamanho do Lote Piloto", options=[5, 10, 20, 35], value=5)

        col_d1, col_d2 = st.columns(2)
        with col_d1:
            min_delay = st.number_input("Delay Mínimo (s)", value=45, min_value=15)
        with col_d2:
            max_delay = st.number_input("Delay Máximo (s)", value=120, min_value=30)

        # Cálculo do Risk Score
        target_count_est = 100 if audience_type == "Toda a Escola" else len(selected_classes) * 30
        risk_info = camp_service.calculate_risk_score(
            num_variants=20,
            daily_limit=daily_limit,
            pilot_mode_active=pilot_mode,
            min_delay=int(min_delay),
            target_count=target_count_est
        )

        # Card de Risk Score
        score = risk_info["score"]
        card_class = "risk-card-healthy" if score <= 25 else ("risk-card-moderate" if score <= 50 else "risk-card-high")
        
        st.markdown(f"""
        <div class="{card_class}">
            <h4 style="margin:0;">Risk Score: <b>{score} / 100</b> — Nível: {risk_info['level']}</h4>
            <ul style="margin: 8px 0 0 0; padding-left: 20px; font-size: 13px;">
                {''.join([f'<li>{f}</li>' for f in risk_info['factors']])}
            </ul>
        </div>
        """, unsafe_allow_html=True)

    st.divider()

    # GERAÇÃO DE VARIAÇÕES POR IA
    col_ai1, col_ai2, col_ai3 = st.columns([1, 1, 1])

    with col_ai1:
        if st.button("🤖 1. Gerar 20 Variações de IA (Anti-Ban)", use_container_width=True):
            if not base_message:
                st.warning("Preencha a mensagem base!")
            else:
                with st.spinner("Gerando 20 variações parafraseadas via OpenAI..."):
                    variants = ai_service.generate_variants(base_message=base_message, num_variants=20)
                    st.session_state["ai_variants"] = variants
                    st.success(f"🎉 {len(variants)} variações geradas com sucesso!")

    variants_list = st.session_state.get("ai_variants", [])

    if variants_list:
        with st.expander(f"👁️ Visualizar as {len(variants_list)} Variações Geradas pela IA", expanded=False):
            for i, v in enumerate(variants_list, 1):
                st.markdown(f"**Variação {i:02d}:** {v}")

    with col_ai2:
        if st.button("💾 2. Salvar como Template Reutilizável", use_container_width=True):
            if not camp_title or not base_message:
                st.warning("Preencha o Título e a Mensagem Base.")
            else:
                target_filter = {"type": audience_type, "classes": selected_classes}
                camp_service.save_template(
                    title=camp_title,
                    category=category,
                    base_message=base_message,
                    target_filter=target_filter
                )
                st.toast("Template salvo na biblioteca com sucesso!")

    with col_ai3:
        if st.button("🚀 3. Criar e Enfileirar Campanha", type="primary", use_container_width=True):
            if not camp_title or not base_message:
                st.error("Preencha o Nome e a Mensagem Base!")
            else:
                with st.spinner("Criando campanha e enfileirando destinatários no Supabase..."):
                    target_filter = {"type": audience_type, "classes": selected_classes, "faq": campaign_faq}
                    created = camp_service.create_campaign(
                        name=camp_title,
                        category=category,
                        base_message=base_message,
                        target_filter=target_filter,
                        ai_variants=variants_list or [base_message]
                    )
                    if created:
                        enq_result = camp_service.enqueue_campaign_messages(
                            campaign_id=created["id"],
                            target_filter=target_filter,
                            ai_variants=variants_list or [base_message]
                        )
                        msg_count = enq_result.get("total_enqueued", 0) if isinstance(enq_result, dict) else enq_result
                        st.success(f"✅ Campanha '{camp_title}' criada com {msg_count} mensagens enfileiradas!")
                        st.session_state["active_campaign_id"] = created["id"]
                        st.rerun()


# =============================================================================
# ABA 2: DIAGNÓSTICO PRÉ-VOO
# =============================================================================
with tab2:
    st.subheader("🩺 Diagnóstico Pré-Voo de Infraestrutura")
    st.markdown("Verifique a integridade e saúde dos 4 pilares do sistema antes de iniciar grandes disparos.")

    if st.button("🔄 Executar Diagnóstico Completo Agora"):
        col_diag1, col_diag2 = st.columns(2)

        # 1. FastAPI Health Check
        with col_diag1:
            st.markdown("#### 1. Backend FastAPI Local")
            try:
                r = httpx.get("http://127.0.0.1:8000/health", timeout=5.0)
                if r.status_code == 200:
                    st.success(f"🟢 **FastAPI OK** ({r.json()})")
                else:
                    st.error(f"🔴 **FastAPI Erro HTTP {r.status_code}**")
            except Exception as e:
                st.error(f"🔴 **FastAPI Fora do Ar:** {e}")

        # 2. OpenAI API Key
        with col_diag1:
            st.markdown("#### 2. OpenAI API Key")
            if settings.openai_api_key:
                st.success("🟢 **Chave OpenAI Configurada**")
            else:
                st.warning("🟡 **OPENAI_API_KEY não configurada no .env (Fallback ativo)**")

        # 3. Supabase Database
        with col_diag2:
            st.markdown("#### 3. Supabase Database (`busca_ativa_v2`)")
            try:
                res_db = camp_service.client.table("campaigns").select("id").limit(1).execute()
                st.success("🟢 **Supabase Conectado & Tabelas OK**")
            except Exception as e:
                st.error(f"🔴 **Erro Supabase:** {e}")

        # 4. Evolution API Gateway
        with col_diag2:
            st.markdown("#### 4. Evolution API Gateway (WhatsApp)")
            try:
                url_evo = f"{settings.evolution_api_url.rstrip('/')}/instance/connectionState/{settings.evolution_api_instance}"
                r_evo = httpx.get(url_evo, headers={"apikey": settings.evolution_api_key}, timeout=5.0)
                if r_evo.status_code == 200 and r_evo.json().get("instance", {}).get("state") == "open":
                    st.success(f"🟢 **Evolution API Conectada & WhatsApp ONLINE** ({settings.evolution_api_instance})")
                else:
                    st.warning(f"🟡 **Evolution Respondeu:** {r_evo.text[:150]}")
            except Exception as e:
                st.error(f"🔴 **Evolution API Fora do Ar:** {e}")


# =============================================================================
# ABA 3: BIBLIOTECA DE TEMPLATES
# =============================================================================
with tab3:
    st.subheader("📁 Biblioteca de Templates Reutilizáveis")
    st.markdown("Selecione modelos pré-configurados pela escola para carregar instantaneamente na Aba 1.")

    templates = camp_service.list_templates()
    if not templates:
        st.info("Nenhum template salvo na biblioteca ainda. Salve novos modelos na Aba 1.")
    else:
        for tpl in templates:
            with st.expander(f"📌 {tpl.get('title')} ({tpl.get('category')})", expanded=False):
                st.markdown(f"**Mensagem Base:**\n```\n{tpl.get('base_message')}\n```")
                if st.button("⚡ Usar este Template na Aba 1", key=f"use_tpl_{tpl.get('id')}"):
                    st.session_state["draft_title"] = tpl.get("title")
                    st.session_state["draft_body"] = tpl.get("base_message")
                    st.toast("Template carregado para a Aba 1!")


# =============================================================================
# ABA 4: HISTÓRICO & MÉTRICAS
# =============================================================================
with tab4:
    st.subheader("📊 Histórico e Dashboard de Campanhas")
    st.markdown("Acompanhe métricas em tempo real, gerencie campanhas ativas e acompanhe o terminal ao vivo.")

    try:
        all_camps = (
            camp_service.client.table("campaigns")
            .select("*")
            .order("created_at", desc=True)
            .limit(30)
            .execute()
        )
        camp_options = {c["name"] + f" ({c['id'][:8]})": c for c in (all_camps.data or [])}

        if camp_options:
            selected_name = st.selectbox("Selecione a Campanha para Analisar", list(camp_options.keys()))
            c_data = camp_options[selected_name]

            # Cards de Métricas
            res_m = (
                camp_service.client.table("messages")
                .select("status")
                .eq("campaign_id", c_data["id"])
                .execute()
            )
            msgs = res_m.data or []
            total = len(msgs)
            pending = sum(1 for m in msgs if m.get("status") == "pending")
            sent = sum(1 for m in msgs if m.get("status") == "sent")
            failed = sum(1 for m in msgs if m.get("status") == "failed")
            replied = sum(1 for m in msgs if m.get("status") == "replied")

            col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
            col_m1.metric("Total Fila", total)
            col_m2.metric("Pendentes", pending)
            col_m3.metric("Enviadas", sent)
            col_m4.metric("Falhas", failed)
            col_m5.metric("Respondidas", replied, delta=f"{(replied/sent*100):.1f}%" if sent > 0 else "0%")

            ignore_sched_tab4 = st.checkbox("🌙 Ignorar Trava Noturna / Finais de Semana", value=False, key=f"ignore_sched_{c_data['id']}")
            col_ctl1, col_ctl2 = st.columns(2)
            with col_ctl1:
                if st.button("▶️ Executar / Retomar Disparos Desta Campanha", use_container_width=True, type="primary"):
                    cmd = [sys.executable, "-u", "scripts/campaign_orchestrator.py", "--campaign-id", c_data["id"]]
                    if ignore_sched_tab4:
                        cmd.append("--ignore-schedule")
                    run_script_live(cmd, f"Disparos — {c_data['name']}")
            with col_ctl2:
                if st.button("⏸️ Pausar Esta Campanha", use_container_width=True):
                    camp_service.client.table("campaigns").update({"status": "paused"}).eq("id", c_data["id"]).execute()
                    st.toast("Campanha pausada!")
                    st.rerun()

    except Exception as e:
        st.error(f"Erro ao carregar histórico: {e}")


# =============================================================================
# ABA 5: BUSCA ATIVA DIÁRIA (SEDUC & OBMEP)
# =============================================================================
with tab5:
    st.subheader("🚨 Busca Ativa Diária (SEDUC & OBMEP)")
    st.markdown("Preservação integral dos fluxos originais de extração diária, carga de faltosos, follow-up e relatórios.")

    # FASE 0: PREPARAÇÃO SEDUC
    st.markdown("### Fase 0: Extração SEDUC")
    colA, colB = st.columns(2)
    with colA:
        if st.button("A: Abrir Navegador Robô (SEDUC)", use_container_width=True):
            cache_dir = r"C:\chrome-debug"
            os.system(f'cmd.exe /c rmdir /s /q "{cache_dir}"')
            chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
            cmd_chrome = f'"{chrome_path}" --remote-debugging-port=9222 --user-data-dir="{cache_dir}"'
            subprocess.Popen(cmd_chrome, shell=True, creationflags=subprocess.DETACHED_PROCESS)
            st.info("Navegador aberto! Faça login na SED e depois execute a extração ao lado.")
    with colB:
        if st.button("B: Iniciar Extração Automatizada", use_container_width=True):
            run_script_live([sys.executable, "-u", "scripts/acesso_seduc.py"], "Fase 0: Extração SEDUC")

    st.divider()

    # PARÂMETROS DA BUSCA ATIVA
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        dia_seduc = st.text_input("Dia da Campanha (SEDUC Excel)", value="4")
        dry_run_seduc = st.toggle("🧪 Modo Simulação (Dry Run)", value=True, key="dry_run_seduc")
        ignore_schedule_seduc = st.toggle("🌙 Ignorar Trava Noturna / Finais de Semana (Forçar Envio)", value=False, key="ignore_schedule_seduc")
    with col_p2:
        min_delay_seduc = st.number_input("Intervalo Mínimo (s)", value=45, key="min_delay_seduc")
        max_delay_seduc = st.number_input("Intervalo Máximo (s)", value=120, key="max_delay_seduc")

    st.divider()

    # OBMEP 2026
    st.markdown("### 🏆 Campanha Especial OBMEP 2026")
    col_o1, col_o2 = st.columns(2)
    with col_o1:
        if st.button("📋 1. Gerar Fila OBMEP", use_container_width=True):
            cmd = [sys.executable, "-u", "scripts/create_obmep_campaign.py"]
            if dry_run_seduc:
                cmd.append("--dry-run")
            run_script_live(cmd, "Carga OBMEP")
    with col_o2:
        if st.button("🚀 2. Disparar OBMEP", use_container_width=True, type="primary"):
            cmd = [
                sys.executable, "-u", "scripts/campaign_orchestrator.py",
                "--min-delay", str(int(min_delay_seduc)),
                "--max-delay", str(int(max_delay_seduc))
            ]
            if dry_run_seduc:
                cmd.append("--dry-run")
            if ignore_schedule_seduc:
                cmd.append("--ignore-schedule")
            run_script_live(cmd, "Disparos OBMEP")

    st.divider()

    # FASE 1 & 1.5
    st.markdown("### Fases 1 & 1.5: Carregamento & Follow-up")
    col_f1, col_f15 = st.columns(2)
    with col_f1:
        if st.button("1️⃣ Carregar Faltosos do Dia", use_container_width=True):
            cmd = [sys.executable, "-u", "scripts/campaign_loader.py", "--day", str(dia_seduc)]
            if dry_run_seduc:
                cmd.append("--dry-run")
            run_script_live(cmd, "Fase 1: Carga de Faltosos")
    with col_f15:
        if st.button("🔁 Gerar Carga de Follow-up (2º Contato)", use_container_width=True):
            cmd = [sys.executable, "-u", "scripts/campaign_followup_loader.py", "--day", str(dia_seduc)]
            if dry_run_seduc:
                cmd.append("--dry-run")
            run_script_live(cmd, "Fase 1.5: Carga de Follow-up")

    st.divider()

    # FASE 2 & 3
    st.markdown("### Fases 2 & 3: Orquestração e Relatórios")
    col_f2, col_f3 = st.columns(2)
    with col_f2:
        if st.button("🚀 Iniciar Orquestrador de Disparos", use_container_width=True, type="primary", key="btn_fase2_seduc"):
            cmd = [
                sys.executable, "-u", "scripts/campaign_orchestrator.py",
                "--min-delay", str(int(min_delay_seduc)),
                "--max-delay", str(int(max_delay_seduc))
            ]
            if dry_run_seduc:
                cmd.append("--dry-run")
            if ignore_schedule_seduc:
                cmd.append("--ignore-schedule")
            run_script_live(cmd, "Fase 2: Orquestrador de Disparos")
    with col_f3:
        if st.button("📊 Gerar Relatórios Consolidados", use_container_width=True, key="btn_fase3_seduc"):
            cmd = [sys.executable, "-u", "scripts/campaign_reporter.py"]
            if dia_seduc:
                cmd.extend(["--day", str(dia_seduc)])
            run_script_live(cmd, "Fase 3: Relatórios Consolidados")
