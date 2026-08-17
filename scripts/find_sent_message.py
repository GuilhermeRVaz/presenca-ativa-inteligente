"""
scripts/find_sent_message.py
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

repo = SupabaseRepository(timeout=15.0, attempts=2)
client = repo.client

print("=" * 80)
print("🔍 BUSCANDO MENSAGEM ENVIADA PARA 997456023")
print("=" * 80)

res_m = client.schema("busca_ativa_v2").table("messages").select("*, students(*)").ilike("wa_jid", "%997456023%").execute()
msgs = res_m.data or []
print(f"\nTotal mensagens com 997456023: {len(msgs)}")
for m in msgs:
    print(f"\nMessage ID: {m.get('id')}")
    print(f"Status: {m.get('status')} | Created: {m.get('created_at')}")
    print(f"JID: {m.get('wa_jid')}")
    print(f"Body: {m.get('body')}")
    st = m.get("students") or {}
    print(f"Student vinculado na mensagem: ID={st.get('id')} | Name='{st.get('name')}' | RA={st.get('ra')} | Class='{st.get('class_name')}'")

print("\n" + "=" * 80)
