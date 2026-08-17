"""
scripts/get_base_message.py
Busca a mensagem base exata usada nas campanhas de Reunião de Pais no Supabase.
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

res_c = client.schema("busca_ativa_v2").table("campaigns").select("id, name, base_message, created_at").eq("school_id", SCHOOL_ID).order("created_at", desc=True).execute()

print("=" * 80)
print("📌 MENSAGENS BASE ENCONTRADAS NAS CAMPANHAS RECENTES:")
print("=" * 80)

for c in (res_c.data or []):
    name = c.get("name") or ""
    base = c.get("base_message") or ""
    created = c.get("created_at") or ""
    if any(kw in name.lower() for kw in ["reunião", "reuniao", "agosto", "convocação"]):
        print(f"\n🔹 Campanha: '{name}' ({created})")
        print(f"   Mensagem Base:\n{base}")
        print("-" * 50)
