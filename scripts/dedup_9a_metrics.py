"""
scripts/dedup_9a_metrics.py

Deduplicação e auditoria fina das métricas do 9º Ano A (35 alunos únicos).
Verifica se todas as mensagens do 9º Ano A foram efetivamente disparadas/finalizadas.
"""

import sys
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

repo = SupabaseRepository(timeout=30.0, attempts=3)
client = repo.client

print("=" * 80)
print("🔍 AUDITORIA E DEDUPLICAÇÃO FOCADA NO 9º ANO A")
print("=" * 80)

# 1. Buscar todos os 35 alunos cadastrados na turma '9 ANO 9A INTEGRAL 9H ANUAL'
res_st = client.schema("busca_ativa_v2").table("students").select("id, name, ra, class_name").eq("school_id", SCHOOL_ID).eq("class_name", "9 ANO 9A INTEGRAL 9H ANUAL").execute()
students = res_st.data or []

print(f"\n📌 Total de Alunos Cadastrados no 9º A: {len(students)}")

st_ids = [s["id"] for s in students]

# 2. Buscar todas as mensagens de campanha vinculadas aos alunos do 9º A
res_m = client.schema("busca_ativa_v2").table("messages").select("id, campaign_id, student_id, guardian_id, wa_jid, status, created_at, updated_at").in_("student_id", st_ids).execute()
msgs = res_m.data or []

print(f"📌 Total de Histórico de Mensagens Registradas para os Alunos do 9º A: {len(msgs)}")

# 3. Deduplicar por Aluno Único (Selecionando o status mais recente/avançado de cada aluno)
# Hierarquia de status: replied > sent > delivered > failed > pending
STATUS_PRIORITY = {
    "replied": 5,
    "read": 4,
    "delivered": 3,
    "sent": 2,
    "failed": 1,
    "pending": 0
}

student_latest_msg = {}
student_msg_history = defaultdict(list)

for m in msgs:
    st_id = m.get("student_id")
    student_msg_history[st_id].append(m)

    current_best = student_latest_msg.get(st_id)
    if not current_best:
        student_latest_msg[st_id] = m
    else:
        p_new = STATUS_PRIORITY.get((m.get("status") or "pending").lower(), 0)
        p_cur = STATUS_PRIORITY.get((current_best.get("status") or "pending").lower(), 0)
        if p_new > p_cur:
            student_latest_msg[st_id] = m
        elif p_new == p_cur:
            # Pegar o mais recente por data
            if (m.get("updated_at") or "") > (current_best.get("updated_at") or ""):
                student_latest_msg[st_id] = m

# Contagem por Aluno Único
status_dedup_counts = defaultdict(int)
for st in students:
    st_id = st["id"]
    best_msg = student_latest_msg.get(st_id)
    st_status = (best_msg.get("status") if best_msg else "sem_mensagem").lower()
    status_dedup_counts[st_status] += 1

print("\n" + "=" * 80)
print("📊 MÉTRICAS DEDUPLICADAS DO 9º ANO A (35 ALUNOS ÚNICOS)")
print("=" * 80)
print(f"• Total de Alunos Únicos da Turma:           {len(students)}")
print(f"• Alunos com Envio de Mensagem com Êxito:     {status_dedup_counts['sent'] + status_dedup_counts['replied'] + status_dedup_counts['delivered']} ({(status_dedup_counts['sent'] + status_dedup_counts['replied'] + status_dedup_counts['delivered'])/len(students)*100:.1f}%)")
print(f"  └─ Mensagens Respondidas pelos Pais:        {status_dedup_counts['replied']}")
print(f"  └─ Mensagens Enviadas com Sucesso (Sent):   {status_dedup_counts['sent']}")
print(f"• Alunos com Falha no Envio:                  {status_dedup_counts['failed']}")
print(f"• Alunos com Envio Ainda PENDENTE:             {status_dedup_counts['pending']}")
print(f"• Alunos Sem Nenhuma Mensagem Enfileirada:    {status_dedup_counts['sem_mensagem']}")

# 4. Listar alunos PENDENTES e COM FALHA
print("\n" + "=" * 80)
print("📋 STATUS INDIVIDUAL DOS 35 ALUNOS DO 9º ANO A")
print("=" * 80)

for idx, st in enumerate(students, 1):
    st_id = st["id"]
    st_name = st["name"]
    best_msg = student_latest_msg.get(st_id)
    status_str = (best_msg.get("status") if best_msg else "NÃO ENFILEIRADO").upper()
    phone = best_msg.get("wa_jid") if best_msg else ""
    print(f" {idx:02d}. {st_name:<40} ➔ Status: {status_str:<12} (Tel: {phone})")

print("\n" + "=" * 80)
