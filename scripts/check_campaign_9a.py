"""
scripts/check_campaign_9a.py
Verifica os registros de campanhas recentes no Supabase e o enfileiramento de mensagens.
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

repo = SupabaseRepository(timeout=15.0, attempts=2)
client = repo.client

print("=" * 70)
print("🔍 CONSULTA DAS ÚLTIMAS CAMPANHAS NO SUPABASE")
print("=" * 70)

res_c = client.schema("busca_ativa_v2").table("campaigns").select("*").eq("school_id", SCHOOL_ID).order("created_at", desc=True).limit(5).execute()
camps = res_c.data or []

for c in camps:
    c_id = c.get("id")
    c_name = c.get("name")
    c_tf = c.get("target_filter") or {}
    c_created = c.get("created_at")
    
    # Contar mensagens enfileiradas nesta campanha
    res_m = client.schema("busca_ativa_v2").table("messages").select("id, status, wa_jid").eq("campaign_id", c_id).execute()
    msgs = res_m.data or []
    
    print(f"\n📌 Campanha: '{c_name}' (ID: {c_id})")
    print(f"   • Criada em:      {c_created}")
    print(f"   • Target Filter:  {c_tf}")
    print(f"   • Total Mensagens Enfileiradas: {len(msgs)}")

print("\n" + "=" * 70)
