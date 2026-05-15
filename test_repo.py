import sys
sys.path.insert(0, '.')

from app.infrastructure.supabase.repositories import SupabaseRepository

repo = SupabaseRepository()
print("Cliente criado")
try:
    # Teste simples
    rows = repo.list_unprocessed_raw_inbound(limit=1)
    print(f"Total pendentes: {len(rows)}")
    if rows:
        print("Primeiro registro:", rows[0])
except Exception as e:
    print(f"ERRO: {type(e).__name__}: {e}")
