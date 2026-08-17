"""
scripts/reuniao_pais_diagnostic.py

Relatório e diagnóstico completo das campanhas para a Reunião de Pais do dia 5 de Agosto.
Métricas extraídas do Supabase:
1. Lista de campanhas da Reunião de Pais (criadas em 30 e 31 de Julho / Sexta-feira)
2. Turmas contempladas (classes)
3. Total de mensagens enfileiradas e enviadas com êxito (status: sent/delivered/read)
4. Respostas dos pais (Confirmações de Presença, Justificativas de Ausência, Dúvidas)
"""

import sys
import json
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


def generate_report():
    print("=" * 80)
    print("📊 DIAGNÓSTICO DAS CAMPANHAS DA REUNIÃO DE PAIS (5 DE AGOSTO)")
    print("=" * 80)

    repo = SupabaseRepository(timeout=30.0, attempts=3)
    client = repo.client

    # 1. Buscar todas as campanhas relacionadas à Reunião de Pais / Agosto
    res_c = client.schema("busca_ativa_v2").table("campaigns").select("*").eq("school_id", SCHOOL_ID).execute()
    all_campaigns = res_c.data or []

    reuniao_camps = []
    for c in all_campaigns:
        name = (c.get("name") or "").lower()
        cat = (c.get("category") or "").lower()
        ctype = (c.get("campaign_type") or "").lower()
        tf = str(c.get("target_filter") or "").lower()
        if any(kw in name or kw in cat or kw in ctype or kw in tf for kw in ["reunião", "reuniao", "agosto", "convocação", "convocacao"]):
            reuniao_camps.append(c)

    print(f"\n📌 Total de Campanhas de Reunião Identificadas: {len(reuniao_camps)}")

    camp_ids = [c["id"] for c in reuniao_camps]

    # 2. Buscar todas as mensagens vinculadas a essas campanhas
    res_m = client.schema("busca_ativa_v2").table("messages").select("*, students(id, name, class_name), guardians(id, name, phone_e164)").in_("campaign_id", camp_ids).execute()
    messages = res_m.data or []

    print(f"📌 Total de Mensagens Registradas nessas Campanhas: {len(messages)}")

    # Agrupamento por Campanha e Turma
    camp_summary = defaultdict(lambda: {
        "name": "",
        "created_at": "",
        "classes": set(),
        "total": 0,
        "sent": 0,
        "delivered": 0,
        "read": 0,
        "failed": 0,
        "pending": 0,
        "other_status": defaultdict(int),
        "students": set()
    })

    class_summary = defaultdict(lambda: {
        "total": 0,
        "sent_success": 0,
        "failed": 0,
        "pending": 0,
        "confirmed": 0,
        "justified": 0,
        "students": []
    })

    sent_jids = set()

    for m in messages:
        c_id = m.get("campaign_id")
        status = (m.get("status") or "pending").lower()
        st = m.get("students") or {}
        st_name = st.get("name") or "Desconhecido"
        class_name = st.get("class_name") or "Sem Turma"
        g = m.get("guardians") or {}
        phone = g.get("phone_e164") or m.get("wa_jid") or ""

        if phone:
            jid = phone if "@" in phone else f"{phone}@s.whatsapp.net"
            sent_jids.add(jid)

        c_info = next((c for c in reuniao_camps if c["id"] == c_id), {})
        camp_summary[c_id]["name"] = c_info.get("name", "Campanha Desconhecida")
        camp_summary[c_id]["created_at"] = c_info.get("created_at", "")
        tf_classes = (c_info.get("target_filter") or {}).get("classes", [])
        for cl in tf_classes:
            camp_summary[c_id]["classes"].add(cl)
        camp_summary[c_id]["classes"].add(class_name)

        camp_summary[c_id]["total"] += 1
        class_summary[class_name]["total"] += 1

        if status in ["sent", "enviado"]:
            camp_summary[c_id]["sent"] += 1
            class_summary[class_name]["sent_success"] += 1
        elif status in ["delivered", "entregue"]:
            camp_summary[c_id]["delivered"] += 1
            class_summary[class_name]["sent_success"] += 1
        elif status in ["read", "lido"]:
            camp_summary[c_id]["read"] += 1
            class_summary[class_name]["sent_success"] += 1
        elif status in ["failed", "erro", "error"]:
            camp_summary[c_id]["failed"] += 1
            class_summary[class_name]["failed"] += 1
        else:
            camp_summary[c_id]["pending"] += 1
            class_summary[class_name]["pending"] += 1
            camp_summary[c_id]["other_status"][status] += 1

        class_summary[class_name]["students"].append({
            "name": st_name,
            "phone": phone,
            "status": status,
            "message_id": m.get("id")
        })

    # 3. Buscar Interações e Respostas dos Pais (ai_interactions e inbound messages)
    res_ai = client.schema("busca_ativa_v2").table("ai_interactions").select("*").execute()
    ai_interactions = res_ai.data or []

    print(f"📌 Total de Interações Registradas na Tabela ai_interactions: {len(ai_interactions)}")

    # Classificação de Respostas por JID / Telefone
    responses_by_jid = defaultdict(list)
    confirmations_count = 0
    absences_count = 0

    for inter in ai_interactions:
        jid = inter.get("sender_jid") or inter.get("wa_jid") or ""
        intent = (inter.get("intent") or inter.get("detected_intent") or "").upper()
        inbound = inter.get("inbound_message") or inter.get("user_message") or ""
        ai_out = inter.get("ai_response") or ""
        created_at = inter.get("created_at") or ""

        if "CONFIRMA" in intent or inbound.strip() == "1" or "confirm" in inbound.lower() or "vou" in inbound.lower() or "irei" in inbound.lower() or "estarei" in inbound.lower():
            intent = "CONFIRMA_PRESENCA"

        if "AUSENCIA" in intent or "JUSTIF" in intent or inbound.strip() == "2" or "nao vou" in inbound.lower() or "não vou" in inbound.lower() or "trabalh" in inbound.lower():
            intent = "INFORMA_AUSENCIA"

        responses_by_jid[jid].append({
            "intent": intent,
            "inbound": inbound,
            "ai_response": ai_out,
            "created_at": created_at
        })

    # Cruzar respostas com os alunos enfileirados por Turma
    confirmed_students = []
    justified_students = []

    for c_name, c_data in class_summary.items():
        for st_item in c_data["students"]:
            p = st_item["phone"]
            jid = p if "@" in p else f"{p}@s.whatsapp.net"
            jids_to_check = [jid, p, p.replace("55", "")]

            user_resps = []
            for j in jids_to_check:
                if j in responses_by_jid:
                    user_resps.extend(responses_by_jid[j])

            has_confirm = any(r["intent"] == "CONFIRMA_PRESENCA" for r in user_resps)
            has_absence = any(r["intent"] == "INFORMA_AUSENCIA" for r in user_resps)

            if has_confirm:
                c_data["confirmed"] += 1
                confirmations_count += 1
                confirmed_students.append((c_name, st_item["name"], p, user_resps[0]["inbound"]))
            elif has_absence:
                c_data["justified"] += 1
                absences_count += 1
                justified_students.append((c_name, st_item["name"], p, user_resps[0]["inbound"]))

    # 4. EXIBIÇÃO DO RELATÓRIO
    print("\n" + "=" * 80)
    print("📋 DETALHAMENTO POR CAMPANHA")
    print("=" * 80)
    for c_id, c_data in camp_summary.items():
        print(f"\n🔹 Campanha: '{c_data['name']}'")
        print(f"   • Criada em: {c_data['created_at']}")
        print(f"   • Turmas contempladas: {', '.join(sorted(list(c_data['classes'])))}")
        print(f"   • Total Enfileirado:  {c_data['total']}")
        print(f"   • Enviadas (sent):    {c_data['sent']}")
        print(f"   • Entregues:          {c_data['delivered']}")
        print(f"   • Lidas:              {c_data['read']}")
        print(f"   • Falhas:             {c_data['failed']}")
        print(f"   • Outros/Pendente:    {c_data['pending']} ({dict(c_data['other_status'])})")

    print("\n" + "=" * 80)
    print("🏫 DETALHAMENTO POR TURMA (SALAS)")
    print("=" * 80)
    total_enviadas_sucesso = 0
    total_alunos_campanha = 0

    for c_name in sorted(class_summary.keys()):
        c_data = class_summary[c_name]
        tot = c_data["total"]
        succ = c_data["sent_success"] + c_data["sent"] if "sent" in c_data else c_data["sent_success"]
        conf = c_data["confirmed"]
        just = c_data["justified"]
        total_alunos_campanha += tot
        total_enviadas_sucesso += succ

        tx_sucesso = (succ / tot * 100) if tot > 0 else 0
        print(f"🔹 Turma: {c_name}")
        print(f"   • Total Alunos:             {tot}")
        print(f"   • Enviadas com Êxito:       {succ} ({tx_sucesso:.1f}%)")
        print(f"   • Pais que Confirmaram:      {conf}")
        print(f"   • Pais que Justificaram:     {just}")
        print("-" * 50)

    print("\n" + "=" * 80)
    print("✅ LISTA DE PAIS QUE CONFIRMARAM PRESENÇA")
    print("=" * 80)
    if confirmed_students:
        for idx, (c_name, st_name, phone, text) in enumerate(confirmed_students, 1):
            print(f" {idx:02d}. [{c_name}] Aluno(a): {st_name} | Tel: {phone}")
            print(f"     Resposta do Pai: \"{text}\"")
    else:
        print(" ⚠️ Nenhuma confirmação registrada até o momento.")

    print("\n" + "=" * 80)
    print("📊 RESUMO GERAL DAS MÉTRICAS")
    print("=" * 80)
    print(f"• Total de Campanhas de Reunião:          {len(reuniao_camps)}")
    print(f"• Total de Mensagens Processadas:         {total_alunos_campanha}")
    print(f"• Total Enviadas com Êxito:               {total_enviadas_sucesso}")
    print(f"• Taxa Global de Entrega:                 {(total_enviadas_sucesso / total_alunos_campanha * 100 if total_alunos_campanha > 0 else 0):.1f}%")
    print(f"• Total de Confirmações de Presença:      {confirmations_count}")
    print(f"• Total de Justificativas de Ausência:    {absences_count}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    generate_report()
