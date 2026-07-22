import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.infrastructure.supabase.repositories import SupabaseRepository

repo = SupabaseRepository()
client = repo.client

res = client.table("contacts").select("*").eq("ra", "113735296").execute()
rows = res.data or []

if rows:
    row = rows[0]
    print("Ja existe, atualizando...")
    updated = client.table("contacts").update({
        "nome_aluno": "ISAQUE VINICIUS NASCIMENTO",
        "turma": "8A",
        "telefone_1": "14996437671",
    }).eq("id", row["id"]).execute()
    print("Depois:", updated.data)
else:
    print("Nao encontrado, criando novo registro...")
    new_row = {
        "ra": "113735296",
        "nome_aluno": "ISAQUE VINICIUS NASCIMENTO",
        "turma": "8A",
        "telefone_1": "14996437671",
    }
    created = client.table("contacts").insert(new_row).execute()
    print("Criado:", created.data)
