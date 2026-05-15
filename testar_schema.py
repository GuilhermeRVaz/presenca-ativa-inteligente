from supabase import create_client
import json

url = 'https://cpniwvghxlkposaeyboa.supabase.co'
key = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNwbml3VmdoeGxrcG9zYWV5Ym9hIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NTI5MDc3MiwiZXhwIjoyMDkwODY2NzcyfQ.aGCEqHjue7sORZQ_Wa0OVS5fzSIKkS08OxV3ewb7HP8'

client = create_client(url, key)

# Testar se o schema busca_ativa_v2 realmente existe via RPC
schemas = ['public', 'busca_ativa_v2', 'evolution']

for s in schemas:
    try:
        # Usar função para listar tabelas no schema
        resp = client.schema(s).rpc('pg_catalog.pg_tables', {}).execute()
        print(f'{s}: {resp.data}')
    except Exception as e:
        # Se falhar, testar se é erro de permissão ou schema inexistente
        print(f'{s} ERRO: {str(e)[:100]}')

# Testar consulta direta com select count em cada tabela conhecida
tabelas_interesse = [
    'raw_inbound', 'phone_identity_map', 'messages', 'campaigns',
    'students', 'guardians', 'student_guardians', 'responses'
]

print('\n--- Teste direto em cada schema ---')
for s in ['public', 'busca_ativa_v2']:
    for t in tabelas_interesse:
        try:
            resp = client.schema(s).table(t).select('count').execute()
            print(f'  [{s}] {t}: {len(resp.data)} registros')
        except Exception as e:
            print(f'  [{s}] {t}: NOK - {str(e)[:60]}')
