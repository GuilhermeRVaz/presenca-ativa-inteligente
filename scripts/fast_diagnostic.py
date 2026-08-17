"""
scripts/fast_diagnostic.py

Diagnóstico rápido e direto sem joins pesados para extração de métricas de Reunião de Pais.
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

repo = SupabaseRepository(timeout=10.0, attempts=1)
client = repo.client

print("=" * 80)
print("📊 RELATÓRIO EXECUTIVO - CAMPANHAS REUNIÃO DE PAIS (5 DE AGOSTO)")
print("=" * 80)

# 1. Campanhas
res_c = client.schema("busca_ativa_v2").table("campaigns").select("id, name, created_at, target_filter").eq("school_id", SCHOOL_ID).execute()
camps = res_c.data or []

reuniao_camps = [c for c in camps if any(kw in (c.get("name") or "").lower() or kw in str(c.get("target_filter") or "").lower() for kw in ["reunião", "reuniao", "agosto", "convocação"])]

print(f"\n📌 Total Campanhas de Reunião Encontradas: {len(reuniao_camps)}")

# 2. Mensagens
c_ids = [c["id"] for c in reuniao_camps]
res_m = client.schema("busca_ativa_v2").table("messages").select("id, campaign_id, status, student_id, guardian_id, wa_jid").in_("campaign_id", c_ids).execute()
msgs = res_m.data or []

print(f"📌 Total Mensagens Processadas: {len(msgs)}")

status_counts = defaultdict(int)
for m in msgs:
    status_counts[m.get("status") or "pending"] += 1

print(f"📌 Distribuição de Status das Mensagens: {dict(status_counts)}")

# 3. Mapear estudantes para saber as turmas
res_st = client.schema("busca_ativa_v2").table("students").select("id, name, class_name").eq("school_id", SCHOOL_ID).execute()
students_dict = {s["id"]: s for s in (res_st.data or [])}

# Mapear mensagens por Turma
turma_metrics = defaultdict(lambda: {"total": 0, "enviadas_sucesso": 0, "replied": 0, "failed": 0, "pending": 0})

for m in msgs:
    st_id = m.get("student_id")
    st_info = students_dict.get(st_id, {})
    turma = st_info.get("class_name") or "Outras / Não Identificada"
    status = m.get("status") or "pending"

    turma_metrics[turma]["total"] += 1

    if status in ["sent", "delivered", "read"]:
        turma_metrics[turma]["enviadas_sucesso"] += 1
    elif status == "replied":
        turma_metrics[turma]["enviadas_sucesso"] += 1
        turma_metrics[turma]["replied"] += 1
    elif status in ["failed", "erro"]:
        turma_metrics[turma]["failed"] += 1
    else:
        turma_metrics[turma]["pending"] += 1

print("\n" + "=" * 80)
print("🏫 MÉTRICAS POR TURMA (SALAS)")
print("=" * 80)

total_alunos = 0
total_sucesso = 0
total_replied = 0

for turma in sorted(turma_metrics.keys()):
    met = turma_metrics[turma]
    tot = met["total"]
    suc = met["enviadas_sucesso"]
    rep = met["replied"]
    fai = met["failed"]
    pen = met["pending"]

    total_alunos += tot
    total_sucesso += suc
    total_replied += rep

    pct_suc = (suc / tot * 100) if tot > 0 else 0
    print(f"🔹 Turma: {turma}")
    print(f"   • Total de Alunos Enfileirados: {tot}")
    print(f"   • Mensagens Enviadas c/ Êxito: {suc} ({pct_suc:.1f}%)")
    print(f"   • Pais que Responderam:       {rep}")
    print(f"   • Falhas no Envio:             {fai}")
    print(f"   • Pendentes:                   {pen}")
    print("-" * 50)

# 4. Interações de confirmação em ai_interactions
res_ai = client.schema("busca_ativa_v2").table("ai_interactions").select("sender_jid, user_message, ai_response, detected_intent, created_at").order("created_at", desc=True).execute()
ai_rows = res_ai.data or []

confirmacoes = []
justificativas = []

for row in ai_rows:
    intent = (row.get("detected_intent") or "").upper()
    msg_text = row.get("user_message") or ""
    jid = row.get("sender_jid") or ""

    if "CONFIRMA" in intent or msg_text.strip() == "1" or "confirm" in msg_text.lower() or "estarei" in msg_text.lower() or "vou sim" in msg_text.lower():
        confirmacoes.append((jid, msg_text, row.get("created_at")))
    elif "AUSENCIA" in intent or "JUSTIF" in intent or msg_text.strip() == "2" or "nao vou" in msg_text.lower() or "não vou" in msg_text.lower():
        justificativas.append((jid, msg_text, row.get("created_at")))

print("\n" + "=" * 80)
print("📊 RESUMO GERAL DAS MÉTRICAS")
print("=" * 80)
print(f"• Total de Campanhas de Reunião:          {len(reuniao_camps)}")
print(f"• Total de Mensagens Processadas:         {total_alunos}")
print(f"• Total Enviadas com Êxito (Sent/Replied): {total_sucesso} ({(total_sucesso/total_alunos*100 if total_alunos > 0 else 0):.1f}%)")
print(f"• Total de Pais que Responderam:          {total_replied}")
print(f"• Confirmações de Presença Identificadas: {len(confirmacoes)}")
print(f"• Justificativas de Ausência Identificadas: {len(justificativas)}")
print("=" * 80 + "\n")
