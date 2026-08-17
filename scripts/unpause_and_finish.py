"""
scripts/unpause_and_finish.py
Despausa a campanha no Supabase e finaliza os 12 envios restantes.
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
CAMPAIGN_ID = "5318046f-80d8-40e5-999e-ac0d83b8917f"

repo = SupabaseRepository(timeout=15.0, attempts=2)

# Atualizar status para active
repo.client.schema("busca_ativa_v2").table("campaigns").update({"status": "active"}).eq("id", CAMPAIGN_ID).execute()
print(f"✅ Campanha {CAMPAIGN_ID} reativada (status: 'active')!")
