import requests
import json
from datetime import datetime, date

SUPABASE_URL = "https://cpniwvghxlkposaeyboa.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNwbml3dmdoeGxrcG9zYWV5Ym9hIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NTI5MDc3MiwiZXhwIjoyMDkwODY2NzcyfQ.aGCEqHjue7sORZQ_Wa0OVS5fzSIKkS08OxV3ewb7HP8"

headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

# Header com schema
headers_schema = headers.copy()
headers_schema["X-Schema"] = "busca_ativa_v2"

SCHEMA = "busca_ativa_v2"
today = "2026-04-29"

def query_table(table, select="*", filters=None, params=None):
    """Consulta tabela no schema busca_ativa_v2"""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    all_params = {"select": select}
    if filters:
        for k, v in filters.items():
            all_params[k] = v
    if params:
        all_params.update(params)
    resp = requests.get(url, headers=headers_schema, params=all_params)
    return resp

print("=" * 60)
print("CONSULTANDO SCHEMA busca_ativa_v2 NO SUPABASE")
print("=" * 60)

# 1. raw_inbound de hoje
resp = query_table(
    f"{SCHEMA}.raw_inbound",
    select="count",
    filters={"created_at": f"gte.{today}T00:00:00", "created_at": f"lte.{today}T23:59:59"}
)
print(f"\n1. raw_inbound hoje: status={resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    count = len(data) if isinstance(data, list) else 0
    print(f"   Total: {count} registros")
else:
    print(f"   ERRO: {resp.text[:200]}")

# 2. raw_inbound não processados
resp = query_table(
    f"{SCHEMA}.raw_inbound",
    select="id,school_id,message_id,sender_jid,payload,received_at,processing_error,processed",
    filters={"processed": "eq.0"}
)
print(f"\n2. raw_inbound NÃO PROCESSADOS: status={resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    print(f"   Total pendentes: {len(data)}")
    if data:
        for rec in data[:3]:
            print(f"   - ID: {rec.get('id')}, MsgID: {rec.get('message_id')}, Error: {rec.get('processing_error')}")
            payload = rec.get('payload', {})
            if isinstance(payload, dict) or isinstance(payload, str):
                print(f"     Payload: {str(payload)[:100]}")
else:
    print(f"   ERRO: {resp.text[:200]}")

# 3. responses de hoje
resp = query_table(
    f"{SCHEMA}.responses",
    select="*",
    filters={"created_at": f"gte.{today}T00:00:00", "created_at": f"lte.{today}T23:59:59"}
)
print(f"\n3. responses hoje: status={resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    print(f"   Total: {len(data)} registros")
    if data:
        for rec in data[:3]:
            print(f"   - ID: {rec.get('id')}, Body: {str(rec.get('body',''))[:50]}")
else:
    print(f"   ERRO: {resp.text[:200]}")

# 4. messages de hoje
resp = query_table(
    f"{SCHEMA}.messages",
    select="id,status,sent_at,evolution_msg_id",
    filters={"created_at": f"gte.{today}T00:00:00", "created_at": f"lte.{today}T23:59:59"}
)
print(f"\n4. messages enviadas hoje: status={resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    print(f"   Total: {len(data)} mensagens")
    if data:
        status_count = {}
        for rec in data:
            s = rec.get('status', 'unknown')
            status_count[s] = status_count.get(s, 0) + 1
        for s, c in status_count.items():
            print(f"   - Status '{s}': {c}")
else:
    print(f"   ERRO: {resp.text[:200]}")

# 5. campaigns
resp = query_table(f"{SCHEMA}.campaigns", select="*")
print(f"\n5. campaigns ativas: status={resp.status_code}")
if resp.status_code == 200:
    campaigns = resp.json()
    print(f"   Total: {len(campaigns)} campaigns")
    for camp in campaigns:
        print(f"   - ID: {camp.get('id')}, absence_days: {camp.get('absence_days')}, status: {camp.get('status')}, school_id: {camp.get('school_id')}")
else:
    print(f"   ERRO: {resp.text[:200]}")

# 6. Estrutura das tabelas (ver colunas disponíveis)
print("\n6. ESTRUTURA DAS TABELAS:")
for table in ['raw_inbound', 'messages', 'campaigns', 'responses']:
    resp = query_table(f"{SCHEMA}.{table}", select="*", filters={"id": "is.not.null"})
    if resp.status_code == 200 and resp.json():
        sample = resp.json()[0]
        print(f"\n   {table}: {list(sample.keys())}")

print("\n" + "=" * 60)
