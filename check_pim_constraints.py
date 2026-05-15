from app.infrastructure.supabase.repositories import SupabaseRepository
r = SupabaseRepository()

# Listar constraints da tabela phone_identity_map
sql = """
SELECT conname, pg_get_constraintdef(c.oid)
FROM pg_constraint c
JOIN pg_namespace n ON n.oid = c.connamespace
WHERE conrelid = 'busca_ativa_v2.phone_identity_map'::regclass;
"""
try:
    res = r.client.schema('busca_ativa_v2').rpc('execute_sql', {'query': sql}).execute()
    print('Constraints:', res.data)
except Exception as e:
    print('Erro:', e)

# Alternativa: usar information_schema
sql2 = """
SELECT constraint_name, column_name
FROM information_schema.constraint_column_usage ccu
JOIN information_schema.table_constraints tc
  ON ccu.constraint_name = tc.constraint_name
WHERE tc.table_schema = 'busca_ativa_v2' AND tc.table_name = 'phone_identity_map';
"""
try:
    res2 = r.client.schema('busca_ativa_v2').rpc('execute_sql', {'query': sql2}).execute()
    print('Constraints colunas:', res2.data)
except Exception as e2:
    print('Erro2:', e2)
