"""
scripts/generate_complete_meeting_report.py

Gera o relatório consolidado completo e a tabela de busca ativa dos alunos sem confirmação ou com justificativa (Opção 2) para a Reunião de Pais do dia 5 de Agosto.
"""

import sys
import json
import re
import unicodedata
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.platform.startswith("win"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

from app.infrastructure.supabase.repositories import SupabaseRepository

SCHOOL_ID = "aac99735-32cb-4615-b2cb-0be315f18374"


def normalize_txt(text: str) -> str:
    if not text:
        return ""
    nfkd = unicodedata.normalize('NFKD', str(text))
    return "".join([c for c in nfkd if not unicodedata.combining(c)]).lower().strip()


def run_report():
    print("=" * 80)
    print("📊 PROCESSANDO DIAGNÓSTICO COMPLETO DE TODAS AS TURMAS")
    print("=" * 80)

    repo = SupabaseRepository(timeout=30.0, attempts=3)
    client = repo.client

    # 1. Buscar todas as campanhas de Reunião de Pais
    res_c = client.schema("busca_ativa_v2").table("campaigns").select("id, name, created_at, target_filter").eq("school_id", SCHOOL_ID).execute()
    camps = res_c.data or []

    reuniao_camps = [c for c in camps if any(kw in (c.get("name") or "").lower() or kw in str(c.get("target_filter") or "").lower() for kw in ["reunião", "reuniao", "agosto", "convocação"])]
    reuniao_ids = [c["id"] for c in reuniao_camps]

    print(f"📌 Total de Campanhas de Reunião Processadas: {len(reuniao_camps)}")

    # 2. Buscar todos os alunos da escola
    res_st = client.schema("busca_ativa_v2").table("students").select("id, name, ra, class_name").eq("school_id", SCHOOL_ID).execute()
    all_students = res_st.data or []
    student_map = {s["id"]: s for s in all_students}

    # 3. Buscar todos os responsáveis e telefones por aluno (student_guardians -> guardians)
    res_sg = client.schema("busca_ativa_v2").table("student_guardians").select("student_id, is_primary, guardians(id, name, phone_e164, wa_jid)").execute()
    student_phones = defaultdict(list)
    
    for sg in (res_sg.data or []):
        st_id = sg.get("student_id")
        g = sg.get("guardians") or {}
        p = g.get("phone_e164") or g.get("wa_jid") or ""
        g_name = g.get("name") or "Responsável"
        if p and p not in [item["phone"] for item in student_phones[st_id]]:
            student_phones[st_id].append({
                "name": g_name,
                "phone": p,
                "is_primary": sg.get("is_primary", False)
            })

    # 4. Buscar histórico de mensagens enviadas nessas campanhas
    res_m = client.schema("busca_ativa_v2").table("messages").select("id, campaign_id, student_id, guardian_id, wa_jid, status, updated_at").in_("campaign_id", reuniao_ids).execute()
    messages = res_m.data or []

    # 5. Buscar todas as respostas de pais na view vw_campaign_responses e ai_interactions
    res_vw = client.schema("busca_ativa_v2").table("vw_campaign_responses").select("*").execute()
    vw_responses = res_vw.data or []

    res_ai = client.schema("busca_ativa_v2").table("ai_interactions").select("*").execute()
    ai_rows = res_ai.data or []

    # Mapear intenção por telefone / JID
    phone_intent_map = {}
    phone_body_map = {}

    for row in ai_rows:
        jid = row.get("sender_jid") or ""
        p = "".join(ch for ch in jid if ch.isdigit())
        intent = (row.get("detected_intent") or "").upper()
        msg_text = row.get("user_message") or ""

        if "CONFIRMA" in intent or msg_text.strip() == "1" or "confirm" in msg_text.lower() or "estarei" in msg_text.lower() or "vou sim" in msg_text.lower():
            phone_intent_map[p] = "CONFIRMADO"
            phone_body_map[p] = msg_text
        elif "AUSENCIA" in intent or "JUSTIF" in intent or msg_text.strip() == "2" or "nao vou" in msg_text.lower() or "não vou" in msg_text.lower() or "trabalh" in msg_text.lower():
            phone_intent_map[p] = "JUSTIFICADO_AUSENTE"
            phone_body_map[p] = msg_text

    for r in vw_responses:
        p = "".join(ch for ch in (r.get("phone_e164") or r.get("sender_jid") or "") if ch.isdigit())
        body = r.get("body") or ""
        norm_b = normalize_txt(body)

        if norm_b == "1" or "confirm" in norm_b or "vou sim" in norm_b or "estarei" in norm_b or "irei" in norm_b or "pode contar" in norm_b:
            phone_intent_map[p] = "CONFIRMADO"
            phone_body_map[p] = body
        elif norm_b == "2" or "nao vou" in norm_b or "não vou" in norm_b or "trabalh" in norm_b or "ausente" in norm_b or "viagem" in norm_b or "medico" in norm_b:
            phone_intent_map[p] = "JUSTIFICADO_AUSENTE"
            phone_body_map[p] = body

    # 6. Mapear status por Aluno Único por Turma
    # Agrupar mensagens por Aluno
    student_messages = defaultdict(list)
    for m in messages:
        st_id = m.get("student_id")
        student_messages[st_id].append(m)

    STATUS_HIERARCHY = {"replied": 5, "read": 4, "delivered": 3, "sent": 2, "failed": 1, "pending": 0}

    turmas_alunos = defaultdict(list)

    # Identificar todos os alunos participantes das campanhas
    participating_st_ids = set(m["student_id"] for m in messages if m.get("student_id"))

    for st_id in participating_st_ids:
        st = student_map.get(st_id)
        if not st:
            continue
        c_name = st.get("class_name") or "Sem Turma"
        st_name = st.get("name") or "Desconhecido"
        ra = st.get("ra") or ""

        # Descobrir melhor status de envio do aluno
        st_msgs = student_messages[st_id]
        best_msg = max(st_msgs, key=lambda x: (STATUS_HIERARCHY.get((x.get("status") or "pending").lower(), 0), x.get("updated_at") or ""))
        send_status = (best_msg.get("status") or "pending").lower()

        # Descobrir telefones do aluno
        plist = student_phones.get(st_id, [])
        tel1 = plist[0]["phone"] if len(plist) > 0 else (best_msg.get("wa_jid") or "").split("@")[0]
        tel2 = plist[1]["phone"] if len(plist) > 1 else ""

        # Verificar se confirmou ou justificou ausência por algum dos telefones
        digits1 = "".join(ch for ch in tel1 if ch.isdigit())
        digits2 = "".join(ch for ch in tel2 if ch.isdigit())

        intent1 = phone_intent_map.get(digits1) or phone_intent_map.get(digits1.replace("55", ""))
        intent2 = phone_intent_map.get(digits2) or phone_intent_map.get(digits2.replace("55", ""))

        final_intent = intent1 or intent2
        body_text = phone_body_map.get(digits1) or phone_body_map.get(digits2) or ""

        if not final_intent:
            if send_status == "replied":
                final_intent = "DUVIDA_OUTROS"
            elif send_status in ["sent", "delivered", "read"]:
                final_intent = "SEM_RESPOSTA"
            elif send_status in ["failed", "erro"]:
                final_intent = "FALHA_ENVIO"
            else:
                final_intent = "PENDENTE"

        turmas_alunos[c_name].append({
            "student_id": st_id,
            "student_name": st_name,
            "ra": ra,
            "class_name": c_name,
            "send_status": send_status,
            "intent": final_intent,
            "body": body_text,
            "tel1": tel1,
            "tel2": tel2,
            "guardian_name": plist[0]["name"] if len(plist) > 0 else "Responsável"
        })

    # 7. EXIBIR MÉTRICAS CONSOLIDADAS E GERAR TABELAS
    print("\n" + "=" * 80)
    print("🏫 METRICAS DETALHADAS E DEDUPLICADAS POR TURMA")
    print("=" * 80)

    total_alunos_escola = 0
    total_enviados_sucesso = 0
    total_confirmados = 0
    total_justificados = 0
    total_sem_confirmacao = 0

    unconfirmed_list = []

    for c_name in sorted(turmas_alunos.keys()):
        alunos = turmas_alunos[c_name]
        tot = len(alunos)
        suc = sum(1 for a in alunos if a["send_status"] in ["sent", "delivered", "read", "replied"])
        conf = sum(1 for a in alunos if a["intent"] == "CONFIRMADO")
        just = sum(1 for a in alunos if a["intent"] == "JUSTIFICADO_AUSENTE")
        sem_conf = tot - conf

        total_alunos_escola += tot
        total_enviados_sucesso += suc
        total_confirmados += conf
        total_justificados += just
        total_sem_confirmacao += sem_conf

        print(f"\n📍 TURMA: {c_name}")
        print(f"   • Total de Alunos Únicos:          {tot}")
        print(f"   • Mensagens Entregues c/ Êxito:    {suc} ({(suc/tot*100):.1f}%)")
        print(f"   • ✅ Confirmações de Presença (1):  {conf} ({(conf/tot*100):.1f}%)")
        print(f"   • ⚠️ Justificativas de Ausência (2): {just} ({(just/tot*100):.1f}%)")
        print(f"   • 🔍 Sem Confirmação (Busca Ativa): {sem_conf}")

        for a in alunos:
            if a["intent"] != "CONFIRMADO":
                unconfirmed_list.append(a)

    print("\n" + "=" * 80)
    print(f"📊 TOTAL DA TABELA DE BUSCA ATIVA (NÃO CONFIRMADOS / OPÇÃO 2): {len(unconfirmed_list)} ALUNOS")
    print("=" * 80)

    # Exibir amostra dos alunos sem confirmação
    for item in unconfirmed_list[:10]:
        print(f" • [{item['class_name']}] {item['student_name']:<35} | Tel 1: {item['tel1']:<14} | Tel 2: {item['tel2']:<14} | Intent: {item['intent']}")

    # Gravar dados em arquivo JSON para renderização impecável no markdown
    with open(ROOT / "scripts" / "unconfirmed_report.json", "w", encoding="utf-8") as f:
        json.dump(unconfirmed_list, f, ensure_ascii=False, indent=2)

    print("\n✅ Relatório gerado e salvo com sucesso!")


if __name__ == "__main__":
    run_report()
