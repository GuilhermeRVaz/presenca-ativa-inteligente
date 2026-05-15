from app.infrastructure.supabase.repositories import SupabaseRepository
r = SupabaseRepository()
# Teste simples
result = r.client.schema('busca_ativa_v2').table('raw_inbound').select('count', count='exact').execute()
print('Count:', result.count)
