from app.infrastructure.supabase.repositories import SupabaseRepository
r = SupabaseRepository()

# Consultar constraints da tabela students
sql = """
SELECT tc.constraint_name, kcu.column_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name
WHERE tc.table_schema = 'busca_ativa_v2' AND tc.table_name = 'students' AND tc.constraint_type = 'UNIQUE';
"""
try:
    res = r.client.schema('busca_ativa_v2').rpc('execute_sql', {'query': sql}).execute()
    print('Students constraints:', res.data)
except Exception as e:
    print('Erro RPC:', e)
    # tentar diretamente via rest
    print('Tentando query direta...')
    try:
        import httpx
        url = f"{r.client.supabase_url}/rest/v1/rpc/execute_sql"
        headers = {
            'apikey': r.client.supabase_key,
            'Authorization': f'Bearer {r.client.supabase_key}',
            'Content-Type': 'application/json'
        }
        r_http = httpx.post(url, json={'query': sql}, headers=headers, timeout=10)
        print('Status:', r_http.status_code, r_http.text[:300])
    except Exception as e2:
        print('HTTP error:', e2)
