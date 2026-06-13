import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.infrastructure.supabase.repositories import SupabaseRepository

repo = SupabaseRepository()
client = repo.client

res = client.table("contacts").select("*").eq("ra", "114788129").execute()
rows = res.data or []
if not rows:
    raise SystemExit("Aluno nao encontrado na tabela contacts")

row = rows[0]
print("Antes:", row)

updated = client.table("contacts").update({
    "responsavel_1": "mae",
    "telefone_1": "14981564617",
    "responsavel_2": "pai",
    "telefone_2": "14998477641",
}).eq("id", row["id"]).execute()
print("Depois:", updated.data)
