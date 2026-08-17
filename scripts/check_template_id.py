"""
scripts/check_template_id.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.infrastructure.supabase.repositories import SupabaseRepository

repo = SupabaseRepository()
res_m = repo.client.schema("busca_ativa_v2").table("messages").select("template_id").not_.is_("template_id", "null").limit(5).execute()
if res_m.data:
    print("EXISTING TEMPLATE IDS IN MESSAGES:", [r["template_id"] for r in res_m.data])
else:
    res_t = repo.client.schema("busca_ativa_v2").table("campaign_templates").select("id").limit(1).execute()
    print("TEMPLATE FROM CAMPAIGN_TEMPLATES:", res_t.data)
