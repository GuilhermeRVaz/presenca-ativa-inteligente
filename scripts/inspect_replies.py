"""
scripts/inspect_replies.py

Examina detalhadamente as mensagens com status 'replied' e interações na ai_interactions.
"""

import sys
from pathlib import Path

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
print("🔍 INSPEÇÃO DE MENSAGENS RESPONDIDAS ('replied') E AI_INTERACTIONS")
print("=" * 80)

# 1. Mensagens com status 'replied'
res_m = client.schema("busca_ativa_v2").table("messages").select("id, status, wa_jid, campaign_id, updated_at, students(name, class_name), guardians(name, phone_e164)").eq("status", "replied").execute()
replied_msgs = res_m.data or []

print(f"\n📌 Total Mensagens com status 'replied' no Supabase: {len(replied_msgs)}")

for m in replied_msgs[:15]:
    st = m.get("students") or {}
    g = m.get("guardians") or {}
    print(f"   • Aluno: {st.get('name')} ({st.get('class_name')}) | Tel: {g.get('phone_e164') or m.get('wa_jid')} | Atualizado: {m.get('updated_at')}")

# 2. Todas as tabelas no busca_ativa_v2 para ver onde ficam salvas as respostas de presença
print("\n📌 Verificando ai_interactions recentes:")
res_ai = client.schema("busca_ativa_v2").table("ai_interactions").select("*").order("created_at", desc=True).limit(30).execute()
ai_rows = res_ai.data or []

print(f"   Total de interações na ai_interactions (últimas 30): {len(ai_rows)}")
for r in ai_rows[:15]:
    jid = r.get("sender_jid")
    inbound = r.get("inbound_message") or r.get("user_message") or ""
    intent = r.get("intent") or r.get("detected_intent") or ""
    ai_resp = r.get("ai_response") or ""
    print(f"   • JID: {jid} | Intent: '{intent}' | Inbound: \"{inbound}\" | AI: \"{ai_resp[:50]}...\"")

# 3. Verificar se existe tabela 'attendance_responses' ou 'student_interactions' ou 'campaign_responses'
for tbl in ["attendance_responses", "student_interactions", "campaign_responses", "inbound_messages"]:
    try:
        res_t = client.schema("busca_ativa_v2").table(tbl).select("*").limit(5).execute()
        print(f"\n📌 Tabela '{tbl}': {len(res_t.data or [])} registros")
        for row in (res_t.data or [])[:3]:
            print(f"   {row}")
    except Exception as e:
        print(f"\n⚠️ Tabela '{tbl}' não existe ou falhou: {e}")

print("\n" + "=" * 80)
