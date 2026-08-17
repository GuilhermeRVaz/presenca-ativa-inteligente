"""
scripts/query_vw_campaign_responses.py

Consulta a view 'vw_campaign_responses' e 'ai_interactions' no Supabase para extrair
as confirmações de presença e dados consolidados da Reunião de Pais (5 de Agosto).
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

repo = SupabaseRepository(timeout=15.0, attempts=2)
client = repo.client

print("=" * 80)
print("📊 CONSULTA VIEW 'vw_campaign_responses' E MENSAGENS RECENTES (30 E 31 DE JULHO)")
print("=" * 80)

# 1. Tentar consultar vw_campaign_responses
try:
    res_vw = client.schema("busca_ativa_v2").table("vw_campaign_responses").select("*").execute()
    rows_vw = res_vw.data or []
    print(f"\n📌 Total de registros na view 'vw_campaign_responses': {len(rows_vw)}")
    for r in rows_vw[:10]:
        print(f"   • {r}")
except Exception as e:
    print(f"\n⚠️ Falha ao consultar vw_campaign_responses: {e}")

# 2. Consultar ai_interactions com created_at recente (a partir de 2026-07-30)
try:
    res_ai = client.schema("busca_ativa_v2").table("ai_interactions").select("*").gte("created_at", "2026-07-30T00:00:00").execute()
    rows_ai = res_ai.data or []
    print(f"\n📌 Total de interações na 'ai_interactions' desde 30/07: {len(rows_ai)}")
    for r in rows_ai:
        print(f"   • JID: {r.get('sender_jid')} | Intent: {r.get('detected_intent') or r.get('intent')} | Msg: \"{r.get('user_message') or r.get('inbound_message')}\"")
except Exception as e:
    print(f"\n⚠️ Falha ao consultar ai_interactions: {e}")

# 3. Consultar mensagens por campanha criadas em 30/07 e 31/07
res_c = client.schema("busca_ativa_v2").table("campaigns").select("id, name, created_at, target_filter").gte("created_at", "2026-07-30T00:00:00").execute()
camps = res_c.data or []

print(f"\n📌 Total de Campanhas criadas a partir de 30/07: {len(camps)}")
for c in camps:
    c_id = c["id"]
    res_m = client.schema("busca_ativa_v2").table("messages").select("status, student_id, guardian_id, wa_jid").eq("campaign_id", c_id).execute()
    msgs = res_m.data or []
    status_map = defaultdict(int)
    for m in msgs:
        status_map[m.get("status") or "pending"] += 1
    print(f"   • Campanha: '{c.get('name')}' (ID: {c_id}) | Criada: {c.get('created_at')}")
    print(f"     Target Filter: {c.get('target_filter')}")
    print(f"     Total Mensagens: {len(msgs)} | Status: {dict(status_map)}")

print("\n" + "=" * 80)
