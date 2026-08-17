"""
scripts/check_messages_columns.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.infrastructure.supabase.repositories import SupabaseRepository

repo = SupabaseRepository()
res = repo.client.schema("busca_ativa_v2").table("messages").select("*").limit(1).execute()
if res.data:
    print("KEYS IN MESSAGES TABLE:")
    print(list(res.data[0].keys()))
else:
    print("NO DATA IN MESSAGES TABLE")
