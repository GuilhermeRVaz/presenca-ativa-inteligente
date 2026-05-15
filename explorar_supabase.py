import requests
import json
from datetime import datetime, timezone

# Configurações
SUPABASE_URL = "https://cpniwvghxlkposaeyboa.supabase.co"
API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNwbml3VmdoeGxrcG9zYWV5Ym9hIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NTI5MDc3MiwiZXhwIjoyMDkwODY2NzcyfQ.aGCEqHjue7sORZQ_Wa0OVS5fzSIKkS08OxV3ewb7HP8"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "apikey": API_KEY,
    "Content-Type": "application/json",
    "Accept": "application/json"
}

def test_headers():
    """Testa diferentes combinações de headers para acessar o schema busca_ativa_v2"""
    print("=== Testando Headers ===")
    
    endpoints = [
        "/rest/v1/raw_inbound?select=count",
        "/rest/v1/raw_inbound?select=*&limit=1",
    ]
    
    header_variants = [
        {"X-Schema": "busca_ativa_v2"},
        {"Accept-Profile": "busca_ativa_v2"},
        {
            "X-Schema": "busca_ativa_v2",
            "Accept-Profile": "busca_ativa_v2"
        },
    ]
    
    for endpoint in endpoints:
        print(f"\nEndpoint: {endpoint}")
        for i, headers_variant in enumerate(header_variants):
            headers = HEADERS.copy()
            headers.update(headers_variant)
            try:
                resp = requests.get(f"{SUPABASE_URL}{endpoint}", headers=headers, timeout=10)
                print(f"  Variant {i+1} {headers_variant}: {resp.status_code}")
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list) and len(data) > 0:
                        print(f"    Data sample: {json.dumps(data[0], ensure_ascii=False)[:200]}")
                    elif isinstance(data, dict):
                        print(f"    Data: {json.dumps(data, ensure_ascii=False)[:200]}")
            except Exception as e:
                print(f"  Variant {i+1}: Error - {e}")

def list_tables_via_rpc():
    """Lista tabelas usando RPC pg_catalog.pg_tables"""
    print("\n=== Listando Tabelas via RPC ===")
    
    headers = HEADERS.copy()
    headers["X-Schema"] = "busca_ativa_v2"
    
    # Tentar listar tabelas no schema busca_ativa_v2
    try:
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/rpc/pg_catalog.pg_tables",
            headers=headers,
            json={},
            timeout=10
        )
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            tables = resp.json()
            print(f"Tabelas encontradas no schema busca_ativa_v2: {len(tables)}")
            for table in tables:
                print(f"  - {table}")
        else:
            print(f"Resposta: {resp.text[:500]}")
    except Exception as e:
        print(f"Erro ao listar tabelas: {e}")

def query_table(table_name, select="*", filters=None, limit=None):
    """Consulta uma tabela específica"""
    url = f"{SUPABASE_URL}/rest/v1/{table_name}?select={select}"
    if filters:
        for key, value in filters.items():
            url += f"&{key}={value}"
    if limit:
        url += f"&limit={limit}"
    
    headers = HEADERS.copy()
    headers["X-Schema"] = "busca_ativa_v2"
    headers["Accept-Profile"] = "busca_ativa_v2"
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        return resp.status_code, resp.json()
    except Exception as e:
        return None, str(e)

def get_count(table_name, date_column=None, target_date=None):
    """Obtém count de registros, opcionalmente filtrados por data"""
    if date_column and target_date:
        # Data no formato ISO (YYYY-MM-DD)
        start = f"{target_date}T00:00:00.000Z"
        end = f"{target_date}T23:59:59.999Z"
        status, data = query_table(
            table_name,
            select="count",
            filters={f"{date_column}.gte": start, f"{date_column}.lte": end}
        )
    else:
        status, data = query_table(table_name, select="count")
    
    if status == 200 and isinstance(data, list) and len(data) > 0:
        return data[0].get("count", 0)
    return None

def get_messages_by_status(target_date):
    """Obtém contagem de messages por status"""
    start = f"{target_date}T00:00:00.000Z"
    end = f"{target_date}T23:59:59.999Z"
    
    headers = HEADERS.copy()
    headers["X-Schema"] = "busca_ativa_v2"
    headers["Accept-Profile"] = "busca_ativa_v2"
    
    url = f"{SUPABASE_URL}/rest/v1/messages?select=count&status=eq.any(pending,sent,delivered,read,replied,failed)&sent_at.gte={start}&sent_at.lte={end}"
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                return data[0].get("count", 0)
        return None
    except Exception as e:
        return str(e)

def main():
    print("Exploração do Supabase - Schema busca_ativa_v2")
    print(f"URL: {SUPABASE_URL}")
    print(f"Data: {datetime.now().strftime('%Y-%m-%d')}")
    
    # 1. Testar headers
    test_headers()
    
    # 2. Listar tabelas via RPC
    list_tables_via_rpc()
    
    # 3. Verificar tabelas no schema public
    print("\n=== Verificando schema public ===")
    public_tables = ["raw_inbound", "messages", "campaigns", "responses"]
    for table in public_tables:
        status, data = query_table(table, select="*", limit=1)
        print(f"  public.{table}: status {status}")
    
    # 4. Contar raw_inbound today
    print("\n=== Contagem de Registros Hoje (2026-04-29) ===")
    
    # Tentar no schema busca_ativa_v2
    count_inbound = get_count("raw_inbound", "received_at", "2026-04-29")
    print(f"raw_inbound hoje: {count_inbound if count_inbound is not None else 'N/A'}")
    
    # Se não funcionar, tentar no schema public
    if count_inbound is None:
        status, data = query_table("raw_inbound", select="count", 
                                   filters={"received_at.gte": "2026-04-29T00:00:00.000Z", 
                                           "received_at.lte": "2026-04-29T23:59:59.999Z"})
        if status == 200:
            count_inbound = data[0].get("count", 0) if data else 0
            print(f"raw_inbound hoje (public): {count_inbound}")
        else:
            print(f"raw_inbound hoje: erro - {status}")
    
    # 5. Contar responses hoje
    count_responses = get_count("responses", "received_at", "2026-04-29")
    print(f"responses hoje: {count_responses if count_responses is not None else 'N/A'}")
    
    # 6. Verificar campaigns ativas
    print("\n=== Campaigns Ativas ===")
    status, campaigns = query_table("campaigns", select="id,name,status,is_active", limit=10)
    if status == 200:
        active_campaigns = [c for c in campaigns if c.get("is_active")]
        print(f"Campanhas ativas: {len(active_campaigns)}")
        for camp in active_campaigns:
            print(f"  ID: {camp.get('id')}, Nome: {camp.get('name')}, Status: {camp.get('status')}")
    else:
        print(f"Erro ao buscar campaigns: {status}")
    
    # 7. Messages por status hoje
    print("\n=== Messages Hoje por Status ===")
    try:
        headers = HEADERS.copy()
        headers["X-Schema"] = "busca_ativa_v2"
        
        url = f"{SUPABASE_URL}/rest/v1/messages?select=status,count"
        start = "2026-04-29T00:00:00.000Z"
        end = "2026-04-29T23:59:59.999Z"
        resp = requests.get(
            f"{url}&sent_at.gte={start}&sent_at.lte={end}&group=status",
            headers=headers,
            timeout=10
        )
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"Contagem por status: {json.dumps(data, ensure_ascii=False, indent=2)}")
    except Exception as e:
        print(f"Erro: {e}")

if __name__ == "__main__":
    main()
