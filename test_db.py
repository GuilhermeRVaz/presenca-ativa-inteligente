from supabase import create_client, Client
import requests

url = 'https://cpniwvghxlkposaeyboa.supabase.co'
key = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNwbml3dmdoeGxrcG9zYWV5Ym9hIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NTI5MDc3MiwiZXhwIjoyMDkwODY2NzcyfQ.aGCEqHjue7sORZQ_Wa0OVS5fzSIKkS08OxV3ewb7HP8'

try:
    supabase = create_client(url, key)
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    
    # Tentar chamar função para listar tabelas
    resp = supabase.rpc('get_table_names', {}).execute()
    print(f"RPC Status: {resp.status_code}")
    print(resp.data)
        
except Exception as e:
    print(f'Erro: {e}')