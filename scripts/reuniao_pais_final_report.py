"""
scripts/reuniao_pais_final_report.py

Relatório final consolidado para o /goal da Reunião de Pais de 5 de Agosto.
Analisa mensagens, respostas na view vw_campaign_responses e métricas por turma.
"""

import sys
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
    print("📊 DIAGNÓSTICO EXECUTIVO COMPLETO — REUNIÃO DE PAIS (5 DE AGOSTO)")
    print("=" * 80)

    repo = SupabaseRepository(timeout=30.0, attempts=3)
    client = repo.client

    # 1. Campanhas de Reunião de Pais
    res_c = client.schema("busca_ativa_v2").table("campaigns").select("id, name, created_at, target_filter").eq("school_id", SCHOOL_ID).execute()
    camps = res_c.data or []

    reuniao_camps = []
    for c in camps:
        name = (c.get("name") or "").lower()
        tf = str(c.get("target_filter") or "").lower()
        if any(kw in name or kw in tf for kw in ["reunião", "reuniao", "agosto", "convocação"]):
            reuniao_camps.append(c)

    reuniao_ids = [c["id"] for c in reuniao_camps]
    print(f"\n📌 Total de Campanhas de Reunião Identificadas: {len(reuniao_camps)}")

    # 2. Mensagens Enviadas / Enfileiradas
    res_m = client.schema("busca_ativa_v2").table("messages").select("id, campaign_id, status, student_id, guardian_id, wa_jid, updated_at").in_("campaign_id", reuniao_ids).execute()
    msgs = res_m.data or []

    print(f"📌 Total de Mensagens Processadas nas Campanhas de Reunião: {len(msgs)}")

    # Mapear Estudantes
    st_ids = list(set(m["student_id"] for m in msgs if m.get("student_id")))
    res_st = client.schema("busca_ativa_v2").table("students").select("id, name, ra, class_name").eq("school_id", SCHOOL_ID).execute()
    students_dict = {s["id"]: s for s in (res_st.data or [])}

    # Turma -> Métricas
    turma_data = defaultdict(lambda: {
        "total": 0,
        "sent": 0,
        "replied": 0,
        "failed": 0,
        "pending": 0,
        "confirmations": [],
        "justifications": [],
        "others": []
    })

    for m in msgs:
        st_id = m.get("student_id")
        st_info = students_dict.get(st_id, {})
        class_name = st_info.get("class_name") or "Turma Não Identificada"
        status = m.get("status") or "pending"

        turma_data[class_name]["total"] += 1

        if status == "sent":
            turma_data[class_name]["sent"] += 1
        elif status == "replied":
            turma_data[class_name]["replied"] += 1
        elif status in ["failed", "erro"]:
            turma_data[class_name]["failed"] += 1
        else:
            turma_data[class_name]["pending"] += 1

    # 3. Respostas dos Pais na View 'vw_campaign_responses'
    res_vw = client.schema("busca_ativa_v2").table("vw_campaign_responses").select("*").in_("campaign_id", reuniao_ids).execute()
    vw_responses = res_vw.data or []

    print(f"📌 Total de Respostas de Pais Capturadas na View: {len(vw_responses)}")

    for resp in vw_responses:
        body = resp.get("body") or ""
        norm_body = normalize_txt(body)
        st_name = resp.get("student_name") or "Aluno"
        class_name = resp.get("class_name") or "Turma Não Identificada"
        phone = resp.get("phone_e164") or resp.get("sender_jid") or ""
        rec_at = resp.get("received_at") or ""

        # Classificação de intenção
        is_confirm = False
        is_absence = False

        if norm_body == "1" or "confirm" in norm_body or "vou sim" in norm_body or "estarei" in norm_body or "irei" in norm_body or "pode contar" in norm_body or "estaremo" in norm_body or "presenca" in norm_body:
            is_confirm = True
        elif norm_body == "2" or "nao vou" in norm_body or "não vou" in norm_body or "trabalh" in norm_body or "ausente" in norm_body or "impossivel" in norm_body or "viagem" in norm_body or "medico" in norm_body:
            is_absence = True

        entry = {
            "student_name": st_name,
            "phone": phone,
            "body": body,
            "received_at": rec_at
        }

        if is_confirm:
            turma_data[class_name]["confirmations"].append(entry)
        elif is_absence:
            turma_data[class_name]["justifications"].append(entry)
        else:
            turma_data[class_name]["others"].append(entry)

    # 4. IMPRESSÃO DO RELATÓRIO POR TURMA
    print("\n" + "=" * 80)
    print("🏫 MÉTRICAS DETALHADAS POR SALA / TURMA")
    print("=" * 80)

    total_alunos_geral = 0
    total_sucesso_geral = 0
    total_confirmacoes_geral = 0
    total_justificativas_geral = 0
    total_duvidas_geral = 0

    for c_name in sorted(turma_data.keys()):
        d = turma_data[c_name]
        tot = d["total"]
        sent = d["sent"]
        replied = d["replied"]
        failed = d["failed"]
        pending = d["pending"]

        sucesso = sent + replied
        pct_sucesso = (sucesso / tot * 100) if tot > 0 else 0

        conf_list = d["confirmations"]
        just_list = d["justifications"]
        oth_list = d["others"]

        total_alunos_geral += tot
        total_sucesso_geral += sucesso
        total_confirmacoes_geral += len(conf_list)
        total_justificativas_geral += len(just_list)
        total_duvidas_geral += len(oth_list)

        print(f"\n📍 TURMA: {c_name}")
        print(f"   • Total Alunos Enfileirados:       {tot}")
        print(f"   • Mensagens Enviadas c/ Sucesso:   {sucesso} ({pct_sucesso:.1f}%) [Sent: {sent} | Replied: {replied}]")
        print(f"   • Falhas no Envio:                 {failed}")
        print(f"   • Pendentes:                       {pending}")
        print(f"   • Confirmações de Presença (1):    {len(conf_list)}")
        print(f"   • Justificativas de Ausência (2):  {len(just_list)}")
        print(f"   • Outras Interações / Dúvidas:     {len(oth_list)}")

        if conf_list:
            print("   ✅ Respostas de Confirmação:")
            for item in conf_list[:5]:
                print(f"      - {item['student_name']} ({item['phone']}): \"{item['body']}\"")
        if just_list:
            print("   ⚠️ Respostas de Justificativa:")
            for item in just_list[:5]:
                print(f"      - {item['student_name']} ({item['phone']}): \"{item['body']}\"")
        print("-" * 70)

    print("\n" + "=" * 80)
    print("📈 RESUMO EXECUTIVO CONSOLIDADO")
    print("=" * 80)
    print(f"• Total de Campanhas de Reunião Processadas: {len(reuniao_camps)}")
    print(f"• Total Geral de Alunos Contemplados:        {total_alunos_geral}")
    print(f"• Total de Mensagens Entregues c/ Êxito:    {total_sucesso_geral} ({(total_sucesso_geral/total_alunos_geral*100 if total_alunos_geral > 0 else 0):.1f}%)")
    print(f"• Total de Pais que Interagiram:            {total_confirmacoes_geral + total_justificativas_geral + total_duvidas_geral}")
    print(f"  └─ Confirmações de Presença (Opção 1):     {total_confirmacoes_geral}")
    print(f"  └─ Justificativas de Ausência (Opção 2):   {total_justificativas_geral}")
    print(f"  └─ Dúvidas / Outros Assuntos:              {total_duvidas_geral}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    run_report()
