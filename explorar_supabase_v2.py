"""
Script para explorar o schema do Supabase usando o cliente oficial
e também consultas SQL diretas via RPC.
"""
import os
from datetime import datetime, timezone
from supabase import create_client, Client

# Carregar do .env
from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

print(f"URL: {SUPABASE_URL}")
print(f"Key (prefix): {SUPABASE_KEY[:30]}...")

# 1. Testar conexão com cliente Supabase
print("\n=== Teste com cliente Supabase ===")
try:
    client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("Cliente criado com sucesso")
    
    # Testar schema
    print("\nTestando acesso ao schema 'busca_ativa_v2'...")
    resp = client.schema("busca_ativa_v2").table("raw_inbound").select("count").execute()
    print(f"Status: {resp.status_code if hasattr(resp, 'status_code') else 'OK'}")
    print(f"Data: {resp.data}")
except Exception as e:
    print(f"Erro: {e}")

# 2. Se falhar, tentar listar schemas disponíveis via SQL
print("\n=== Listando schemas via RPC ===")
try:
    import requests
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    
    # Executar SQL para listar schemas
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/rpc/exec",
        headers=headers,
        json={"command": "SELECT schema_name FROM information_schema.schemata ORDER BY schema_name"},
        timeout=10
    )
    print(f"RPC exec status: {resp.status_code}")
    print(f"Resposta: {resp.text[:500]}")
except Exception as e:
    print(f"Erro RPC: {e}")

# 3. Tentar listar tabelas no schema busca_ativa_v2 via RPC direct
print("\n=== Listando tabelas no schema busca_ativa_v2 ===")
try:
    sql = """
    SELECT table_name 
    FROM information_schema.tables 
    WHERE table_schema = 'busca_ativa_v2' 
    ORDER BY table_name
    """
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/rpc/exec",
        headers=headers,
        json={"command": sql},
        timeout=10
    )
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        tables = resp.json()
        print(f"Tabelas: {[t['table_name'] for t in tables]}")
    else:
        print(f"Erro: {resp.text}")
except Exception as e:
    print(f"Erro: {e}")

# 4. Se não existir schema busca_ativa_v2, listar tabelas no public
print("\n=== Listando tabelas no schema public ===")
try:
    sql = """
    SELECT table_name 
    FROM information_schema.tables 
    WHERE table_schema = 'public' 
    ORDER BY table_name
    """
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/rpc/exec",
        headers=headers,
        json={"command": sql},
        timeout=10
    )
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        tables = resp.json()
        print(f"Tabelas no public: {[t['table_name'] for t in tables]}")
    else:
        print(f"Erro: {resp.text}")
except Exception as e:
    print(f"Erro: {e}")

# 5. Consultas de contagem
print("\n=== Contagens ===")
target_date = "2026-04-29"
start = f"{target_date}T00:00:00.000Z"
end = f"{target_date}T23:59:59.999Z"

for schema in ["busca_ativa_v2", "public"]:
    print(f"\nSchema: {schema}")
    for table in ["raw_inbound", "messages", "campaigns", "responses"]:
        try:
            # Tentar com header X-Schema
            custom_headers = headers.copy()
            custom_headers["X-Schema"] = schema
            custom_headers["Accept-Profile"] = schema
            
            url = f"{SUPABASE_URL}/rest/v1/{table}?select=count&received_at.gte={start}&received_at.lte={end}"
            resp = requests.get(url, headers=custom_headers, timeout=10)
            print(f"  {table}: status={resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                count = data[0].get("count") if data else 0
                print(f"    count={count}")
            elif resp.status_code == 401:
                # Tentar sem X-Schema (public)
                url2 = f"{SUPABASE_URL}/rest/v1/{table}?select=count&received_at.gte={start}&received_at.lte={end}"
                resp2 = requests.get(url2, headers=headers, timeout=10)
                print(f"    (public fallback) status={resp2.status_code}")
                if resp2.status_code == 200:
                    data2 = resp2.json()
                    count = data2[0].get("count") if data2 else 0
                    print(f"    count={count}")
        except Exception as e:
            print(f"  {table}: erro - {e}")
