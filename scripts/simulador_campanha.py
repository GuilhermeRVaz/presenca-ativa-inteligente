"""
simulador_campanha.py — Simulador E2E do Presença Ativa Inteligente (PAI)
Executa cenários integrados com n8n, FastAPI e Supabase.
"""
import os
import sys
import time
import json
import uuid
import threading
import requests
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv

# Garante UTF-8 no console do Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

load_dotenv()

# Configurações do Ambiente
SCHOOL_ID = os.getenv("DEFAULT_SCHOOL_ID", "aac99735-32cb-4615-b2cb-0be315f18374")
N8N_WEBHOOK = os.getenv("N8N_CHAT_WEBHOOK_URL", "http://127.0.0.1:5678/webhook/chat-interaction")
FASTAPI_BASE = "http://127.0.0.1:8000"

# IDs Fictícios para o Teste
MOCK_STUDENT_ID = "00000000-0000-0000-0000-000000000001"
MOCK_GUARDIAN_ID = "00000000-0000-0000-0000-000000000002"
MOCK_CAMPAIGN_ID = "00000000-0000-0000-0000-000000000003"
MOCK_MESSAGE_ID = "00000000-0000-0000-0000-000000000004"
MOCK_PHONE = "5511999999999"
MOCK_JID = f"{MOCK_PHONE}@s.whatsapp.net"

# Cores do terminal
def cor(txt, code): return f"\033[{code}m{txt}\033[0m"
def ok(txt):    return cor(f"[OK] {txt}", "92")
def err(txt):   return cor(f"[ERRO] {txt}", "91")
def warn(txt):  return cor(f"[AVISO] {txt}", "93")
def cyan(txt):  return cor(txt, "96")

# Lista global para capturar as mensagens disparadas pelo n8n via Evolution API Mock
captured_messages = []
captured_lock = threading.Lock()

class MockEvolutionHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            payload = json.loads(post_data.decode('utf-8'))
        except Exception:
            payload = {}

        with captured_lock:
            captured_messages.append({
                "path": self.path,
                "body": payload,
                "timestamp": time.time()
            })

        self.send_response(201)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"status": "SUCCESS", "message": "Mock Send Success"}).encode('utf-8'))

    def log_message(self, format, *args):
        pass  # Silencia logs técnicos no console

def start_mock_server():
    server = HTTPServer(('0.0.0.0', 8080), MockEvolutionHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    return server

# Inicialização do Supabase
try:
    from supabase import create_client, ClientOptions
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise ValueError("SUPABASE_URL ou SUPABASE_KEY não configurados no .env")
    supabase = create_client(url, key, options=ClientOptions(schema="busca_ativa_v2"))
except Exception as e:
    print(err(f"Falha ao conectar com o Supabase: {e}"))
    sys.exit(1)

def database_cleanup():
    print(cyan("Limpando dados de teste antigos do Supabase..."))
    try:
        # 1. Limpar respostas e mensagens pelo ID de teste e dados fixados
        supabase.table("ai_interactions").delete().eq("student_id", MOCK_STUDENT_ID).execute()
        supabase.table("responses").delete().eq("school_id", SCHOOL_ID).eq("sender_jid", MOCK_JID).execute()
        supabase.table("responses").delete().eq("school_id", SCHOOL_ID).eq("campaign_id", MOCK_CAMPAIGN_ID).execute()
        supabase.table("responses").delete().eq("school_id", SCHOOL_ID).eq("sender_jid", "5511888888888@s.whatsapp.net").execute()
        supabase.table("conversation_sessions").delete().eq("school_id", SCHOOL_ID).eq("sender_jid", MOCK_JID).execute()
        supabase.table("raw_inbound").delete().eq("school_id", SCHOOL_ID).eq("sender_jid", MOCK_JID).execute()
        supabase.table("messages").delete().eq("id", MOCK_MESSAGE_ID).execute()
        supabase.table("messages").delete().eq("campaign_id", MOCK_CAMPAIGN_ID).execute()
        supabase.table("student_guardians").delete().eq("student_id", MOCK_STUDENT_ID).execute()

        # 2. Buscar responsáveis cadastrados com os telefones de teste
        test_phones = [MOCK_PHONE, "5511888888888"]
        for phone in test_phones:
            guardians_res = supabase.table("guardians").select("id, wa_jid").eq("school_id", SCHOOL_ID).eq("phone_e164", phone).execute()
            if guardians_res.data:
                for g in guardians_res.data:
                    # Deleta mensagens associadas
                    supabase.table("messages").delete().eq("guardian_id", g["id"]).execute()
                    # Deleta student_guardians associados
                    supabase.table("student_guardians").delete().eq("guardian_id", g["id"]).execute()
                    # Deleta responses associadas
                    if g.get("wa_jid"):
                        supabase.table("responses").delete().eq("school_id", SCHOOL_ID).eq("sender_jid", g["wa_jid"]).execute()
                        supabase.table("conversation_sessions").delete().eq("school_id", SCHOOL_ID).eq("sender_jid", g["wa_jid"]).execute()
                    # Deleta o responsável
                    supabase.table("guardians").delete().eq("id", g["id"]).execute()

        # 3. Excluir aluno e responsável por ID padrão
        supabase.table("students").delete().eq("id", MOCK_STUDENT_ID).execute()
        supabase.table("guardians").delete().eq("id", MOCK_GUARDIAN_ID).execute()
        
        # 4. Excluir campanha
        supabase.table("campaigns").delete().eq("id", MOCK_CAMPAIGN_ID).execute()
        print(ok("Limpeza concluída com sucesso!"))
    except Exception as e:
        print(warn(f"Aviso durante limpeza: {e}"))

def database_setup():
    print(cyan("Inserindo massa de dados temporária de teste no Supabase..."))
    try:
        # 1. Garante que a escola exista
        school_res = supabase.table("schools").select("id").eq("id", SCHOOL_ID).execute()
        if not school_res.data:
            supabase.table("schools").insert({
                "id": SCHOOL_ID,
                "name": "Escola Décia Teste",
                "slug": "escola-decia-teste",
                "active": True
            }).execute()

        # 2. Insere campanha de teste
        supabase.table("campaigns").insert({
            "id": MOCK_CAMPAIGN_ID,
            "school_id": SCHOOL_ID,
            "name": "Campanha Simulada E2E",
            "type": "absence",
            "campaign_type": "primary",
            "absence_days": "13/06/2026",
            "status": "active"
        }).execute()

        # 3. Insere aluno de teste
        supabase.table("students").insert({
            "id": MOCK_STUDENT_ID,
            "school_id": SCHOOL_ID,
            "ra": "999999-TESTE",
            "name": "Bernardo da Silva",
            "class_name": "8 ANO A",
            "active": True
        }).execute()

        # 4. Insere responsável de teste
        supabase.table("guardians").insert({
            "id": MOCK_GUARDIAN_ID,
            "school_id": SCHOOL_ID,
            "name": "Maria Teste PAI",
            "phone_e164": MOCK_PHONE,
            "wa_jid": MOCK_JID,
            "active": True
        }).execute()

        # 5. Vincula aluno e responsável
        supabase.table("student_guardians").insert({
            "student_id": MOCK_STUDENT_ID,
            "guardian_id": MOCK_GUARDIAN_ID,
            "relationship": "mãe",
            "is_primary": True
        }).execute()

        # 6. Cria mensagem outbound pendente
        supabase.table("messages").insert({
            "id": MOCK_MESSAGE_ID,
            "school_id": SCHOOL_ID,
            "campaign_id": MOCK_CAMPAIGN_ID,
            "student_id": MOCK_STUDENT_ID,
            "guardian_id": MOCK_GUARDIAN_ID,
            "tracking_ref": "CMP-TESTE-STU-9999",
            "wa_jid": MOCK_JID,
            "template_id": "teste-outbound",
            "body_preview": "Olá Maria, notamos que o Bernardo da Silva faltou hoje...",
            "status": "sent",
            "sent_at": datetime.now(timezone.utc).isoformat()
        }).execute()

        print(ok("Massa de dados carregada com sucesso no Supabase!"))
    except Exception as e:
        print(err(f"Erro fatal no setup do banco de dados: {e}"))
        database_cleanup()
        sys.exit(1)

def trigger_n8n(sender_jid, text, response_id=None, student_id=None):
    if not response_id:
        response_id = f"test-raw-{uuid.uuid4()}"
    
    payload = {
        "sender_jid": sender_jid,
        "school_id": SCHOOL_ID,
        "message_text": text,
        "response_id": response_id,
        "student_id": student_id
    }
    
    try:
        res = requests.post(N8N_WEBHOOK, json=payload, timeout=45)
        return res.status_code, res.text
    except Exception as e:
        return 500, str(e)

def wait_for_evolution_message(timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        with captured_lock:
            if captured_messages:
                return captured_messages.pop(0)
        time.sleep(0.2)
    return None

def clear_interaction_state(jid):
    print(cyan(f"     Limpando estado de interação anterior para {jid}..."))
    try:
        supabase.table("conversation_sessions").delete().eq("school_id", SCHOOL_ID).eq("sender_jid", jid).execute()
        supabase.table("responses").delete().eq("school_id", SCHOOL_ID).eq("sender_jid", jid).execute()
        supabase.table("ai_interactions").delete().eq("student_id", MOCK_STUDENT_ID).execute()
        supabase.table("raw_inbound").delete().eq("school_id", SCHOOL_ID).eq("sender_jid", jid).execute()
    except Exception as e:
        print(warn(f"     Aviso ao limpar estado: {e}"))

# ─────────────────────────────────────────────────────────────
# CENÁRIOS DE TESTE
# ─────────────────────────────────────────────────────────────

def cenario_1_justificativa_valida():
    print(cyan("\n[Cenário 1] Testando Justificativa de Falta Válida (Doença)"))
    clear_interaction_state(MOCK_JID)
    text = "Bom dia, o Bernardo da Silva não vai hoje porque está com muita febre e gripe."
    
    status, _ = trigger_n8n(MOCK_JID, text, student_id=MOCK_STUDENT_ID)
    if status != 200:
        print(err(f"Falha ao acionar n8n (HTTP {status})"))
        return False

    outbound = wait_for_evolution_message(12)
    if not outbound:
        print(err("Nenhuma resposta capturada no mock do WhatsApp."))
        return False

    msg_text = outbound["body"].get("text", "")
    print(f"     IA respondeu: \"{msg_text}\"")
    
    # Validações
    try:
        assert "melhoras" in msg_text.lower() or "recuperação" in msg_text.lower() or "saúde" in msg_text.lower() or "melhore" in msg_text.lower(), "Mensagem não contém desejos de melhoras."
        assert "bernardo" in msg_text.lower(), "Mensagem não usou o nome do aluno."
        
        # Validação do BD
        resp_data = supabase.table("responses").select("reason, needs_review, detected_intent").eq("sender_jid", MOCK_JID).execute().data
        assert resp_data, "Nenhum registro de resposta gravado no banco de dados."
        latest_resp = resp_data[-1]
        assert latest_resp["reason"] == "ILLNESS", f"Classificação incorreta de motivo: {latest_resp['reason']}"
        assert latest_resp["detected_intent"] == "JUSTIFICATIVA_FALTA", "Intenção errada."
        assert latest_resp["needs_review"] is False, "Sinalizou revisão humana desnecessariamente."
        
        print(ok("Cenário 1 passou perfeitamente!"))
        return True
    except AssertionError as ae:
        print(err(f"Erro de validação no Cenário 1: {ae}"))
        return False

def cenario_2_aluno_nao_identificado():
    print(cyan("\n[Cenário 2] Testando Justificativa Sem Aluno Identificado"))
    clear_interaction_state(MOCK_JID)
    
    # Remove o nome do aluno do relacionamento para simular contexto vazio
    supabase.table("student_guardians").delete().eq("student_id", MOCK_STUDENT_ID).execute()
    
    text = "Olá, meu filho faltou hoje porque foi ao médico."
    status, _ = trigger_n8n(MOCK_JID, text)
    if status != 200:
        print(err(f"Falha ao acionar n8n (HTTP {status})"))
        return False

    outbound = wait_for_evolution_message(12)
    if not outbound:
        print(err("Nenhuma resposta capturada no mock do WhatsApp."))
        return False

    msg_text = outbound["body"].get("text", "")
    print(f"     IA respondeu: \"{msg_text}\"")

    try:
        # Reinsere o relacionamento de volta para os próximos cenários
        supabase.table("student_guardians").insert({
            "student_id": MOCK_STUDENT_ID,
            "guardian_id": MOCK_GUARDIAN_ID,
            "relationship": "mãe",
            "is_primary": True
        }).execute()
        
        assert "nome" in msg_text.lower() or "completo" in msg_text.lower() or "turma" in msg_text.lower(), "IA não solicitou os dados do aluno como esperado."
        print(ok("Cenário 2 passou perfeitamente!"))
        return True
    except AssertionError as ae:
        print(err(f"Erro de validação no Cenário 2: {ae}"))
        return False

def cenario_3_rag_sac():
    print(cyan("\n[Cenário 3] Testando Dúvida Escolar / FAQ (RAG)"))
    clear_interaction_state(MOCK_JID)
    text = "Qual o horário de funcionamento da secretaria da escola?"
    
    status, _ = trigger_n8n(MOCK_JID, text, student_id=MOCK_STUDENT_ID)
    if status != 200:
        print(err(f"Falha ao acionar n8n (HTTP {status})"))
        return False

    outbound = wait_for_evolution_message(12)
    if not outbound:
        print(err("Nenhuma resposta capturada no mock do WhatsApp."))
        return False

    msg_text = outbound["body"].get("text", "")
    print(f"     IA respondeu: \"{msg_text}\"")

    try:
        # Verifica se respondeu usando termos relacionados a horários
        assert "secretaria" in msg_text.lower(), "RAG não respondeu adequadamente."
        
        resp_data = supabase.table("ai_interactions").select("classified_reason, risk_level").eq("student_id", MOCK_STUDENT_ID).execute().data
        assert resp_data, "Nenhum registro de interação de IA gravado no banco de dados."
        latest_resp = resp_data[-1]
        assert latest_resp["classified_reason"] == "DUVIDA_SECRETARIA", f"Intenção detectada incorreta: {latest_resp['classified_reason']}"
        assert latest_resp["risk_level"] == "LOW", f"Risco incorreto: {latest_resp['risk_level']}"
        
        print(ok("Cenário 3 passou perfeitamente!"))
        return True
    except AssertionError as ae:
        print(err(f"Erro de validação no Cenário 3: {ae}"))
        return False

def cenario_4_high_risk_handoff():
    print(cyan("\n[Cenário 4] Testando Mensagem de Alto Risco / Bullying (Handoff)"))
    clear_interaction_state(MOCK_JID)
    text = "Por favor me ajuda meu filho está sofrendo ameaças e bullying muito sério na sala de aula e chora direto."
    
    status, _ = trigger_n8n(MOCK_JID, text)
    if status != 200:
        print(err(f"Falha ao acionar n8n (HTTP {status})"))
        return False

    outbound = wait_for_evolution_message(12)
    if not outbound:
        print(err("Nenhuma resposta capturada no mock do WhatsApp."))
        return False

    msg_text = outbound["body"].get("text", "")
    print(f"     IA respondeu: \"{msg_text}\"")

    try:
        resp_data = supabase.table("responses").select("detected_intent, needs_review, risk_level").eq("sender_jid", MOCK_JID).execute().data
        latest_resp = resp_data[-1]
        
        assert latest_resp["needs_review"] is True, "Handoff humano não foi acionado!"
        assert latest_resp["risk_level"] == "HIGH", f"Nível de risco incorreto no BD: {latest_resp['risk_level']}"
        
        print(ok("Cenário 4 passou perfeitamente! (Handoff acionado e risco HIGH gravado)"))
        return True
    except AssertionError as ae:
        print(err(f"Erro de validação no Cenário 4: {ae}"))
        return False

def cenario_5_desconhecido():
    print(cyan("\n[Cenário 5] Testando Contato Desconhecido (Fora da Campanha)"))
    UNKNOWN_JID = "5511888888888@s.whatsapp.net"
    text = "Oi bom dia como vcs estão hoje"
    
    status, _ = trigger_n8n(UNKNOWN_JID, text)
    if status != 200:
        print(err(f"Falha ao acionar n8n (HTTP {status})"))
        return False

    outbound = wait_for_evolution_message(12)
    if not outbound:
        print(err("Nenhuma resposta capturada no mock do WhatsApp."))
        return False

    msg_text = outbound["body"].get("text", "")
    print(f"     IA respondeu: \"{msg_text}\"")

    try:
        resp_data = supabase.table("responses").select("needs_review, detected_intent").eq("sender_jid", UNKNOWN_JID).execute().data
        latest_resp = resp_data[-1]
        
        assert latest_resp["needs_review"] is True, "Não sinalizou revisão humana para contato desconhecido."
        assert latest_resp["detected_intent"] == "DESCONHECIDO", "Intenção classificada errada."
        
        print(ok("Cenário 5 passou perfeitamente!"))
        return True
    except AssertionError as ae:
        print(err(f"Erro de validação no Cenário 5: {ae}"))
        return False

def cenario_6_debounce_fastapi():
    print(cyan("\n[Cenário 6] Testando o Debounce da FastAPI (Rajada de Mensagens)"))
    clear_interaction_state(MOCK_JID)
    
    # Limpa as mensagens antigas capturadas
    with captured_lock:
        captured_messages.clear()
        
    # Prepara payload no padrão da Evolution API
    def post_webhook(text, msg_id):
        payload = {
            "event": "messages.upsert",
            "instance": "escola-decia-teste",
            "data": {
                "key": {
                    "remoteJid": MOCK_JID,
                    "fromMe": False,
                    "id": msg_id
                },
                "message": {
                    "conversation": text
                },
                "messageType": "conversation",
                "messageTimestamp": int(time.time()),
                "pushName": "Maria Teste"
            }
        }
        try:
            requests.post(f"{FASTAPI_BASE}/webhooks/evolution", json=payload, timeout=5)
        except Exception as e:
            print(err(f"Erro no post para o webhook FastAPI: {e}"))

    # Dispara 3 mensagens em rajada (intervalo de 0.2 segundos)
    print("     Enviando 3 mensagens rápidas...")
    post_webhook("Olá", "msg-1")
    time.sleep(0.2)
    post_webhook("o Aluno de Teste PAI faltou hoje", "msg-2")
    time.sleep(0.2)
    post_webhook("porque precisou ir ao hospital", "msg-3")
    
    print("     Aguardando processamento e disparo do debounce (aprox. 35s a 60s)...")
    
    # Aguarda o disparo
    outbound = wait_for_evolution_message(90)
    
    # Verifica quantas mensagens o n8n disparou via mock do WhatsApp
    with captured_lock:
        total_captured = len(captured_messages) + (1 if outbound else 0)
        # Limpa para segurança
        captured_messages.clear()

    try:
        assert outbound, "Nenhuma mensagem de resposta foi recebida."
        assert total_captured == 1, f"Debounce falhou! O n8n enviou {total_captured} mensagens de resposta em vez de apenas 1 consolidada."
        
        msg_text = outbound["body"].get("text", "")
        print(f"     Resposta final consolidada da IA: \"{msg_text}\"")
        assert "melhoras" in msg_text.lower() or "hospital" in msg_text.lower() or "recuperação" in msg_text.lower(), "A IA não respondeu sobre a justificativa consolidada."
        
        print(ok("Cenário 6 passou perfeitamente! Debounce aglutinou e o n8n respondeu apenas uma vez."))
        return True
    except AssertionError as ae:
        print(err(f"Erro de validação no Cenário 6: {ae}"))
        return False

# ─────────────────────────────────────────────────────────────
# EXECUÇÃO PRINCIPAL
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\nIniciando Simulador E2E: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    
    # 1. Inicia Mock da Evolution API
    server = start_mock_server()
    print(ok("Servidor Mock da Evolution API rodando na porta 8080!"))
    
    # 2. Configura massa de dados
    database_cleanup()
    database_setup()
    
    sucessos = 0
    testes = [
        cenario_1_justificativa_valida,
        cenario_2_aluno_nao_identificado,
        cenario_3_rag_sac,
        cenario_4_high_risk_handoff,
        cenario_5_desconhecido,
        cenario_6_debounce_fastapi
    ]
    
    for test in testes:
        try:
            if test():
                sucessos += 1
        except Exception as e:
            print(err(f"Cenário falhou com exceção não tratada: {e}"))
        time.sleep(1.0)
        
    print(f"\n{'='*60}")
    print(cyan(f"RESULTADO DAS SIMULAÇÕES E2E: {sucessos}/{len(testes)} passados"))
    print(f"{'='*60}")
    
    # 3. Limpeza final
    database_cleanup()
    server.shutdown()
    
    if sucessos == len(testes):
        print(ok("🎉 SUCESSO TOTAL! O workflow do n8n e o backend FastAPI estão 100% integrados e funcionando."))
        sys.exit(0)
    else:
        print(err("❌ ALGUNS CENÁRIOS FALHARAM. Revise o log de testes acima."))
        sys.exit(1)
