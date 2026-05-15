"""
Exploração completa do Supabase usando cliente oficial.
"""
import os
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def list_tables(schema="busca_ativa_v2"):
    """Lista todas as tabelas do schema usando INFORMATION_SCHEMA"""
    print(f"\n=== Tabelas no schema '{schema}' ===")
    try:
        # Usar RPC para consultar information_schema
        resp = client.rpc(
            "information_schema.tables",
            {"schema_name": schema}
        ).execute()
        if resp.data:
            tables = [row["table_name"] for row in resp.data]
            print(f"Tabelas: {tables}")
            return tables
        else:
            print("Nenhuma tabela encontrada ou RPC indisponível")
            return []
    except Exception as e:
        print(f"Erro: {e}")
        return []

def get_table_info(table_name, schema="busca_ativa_v2"):
    """Obtém informações de uma tabela"""
    print(f"\n=== Info de {schema}.{table_name} ===")
    try:
        # Descrever colunas
        resp = client.schema(schema).table(table_name).select("*").limit(1).execute()
        if resp.data:
            print(f"Colunas disponíveis: {list(resp.data[0].keys())}")
            print(f"Sample: {resp.data[0]}")
        else:
            print("Tabela vazia ou não existe")
        
        # Contar total
        resp2 = client.schema(schema).table(table_name).select("count").execute()
        count = resp2.data[0].get("count", 0) if resp2.data else 0
        print(f"Total de registros: {count}")
        return count
    except Exception as e:
        print(f"Erro: {e}")
        return None

def get_count_today(table_name, date_column="received_at", schema="busca_ativa_v2"):
    """Conta registros de hoje"""
    target_date = datetime(2026, 4, 29, tzinfo=timezone.utc)
    start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    try:
        resp = (
            client.schema(schema)
            .table(table_name)
            .select("count")
            .gte(date_column, start.isoformat())
            .lte(date_column, end.isoformat())
            .execute()
        )
        count = resp.data[0].get("count", 0) if resp.data else 0
        return count
    except Exception as e:
        print(f"Erro ao contar {table_name}: {e}")
        return None

def get_messages_by_status_today(schema="busca_ativa_v2"):
    """Conta messages por status hoje"""
    target_date = datetime(2026, 4, 29, tzinfo=timezone.utc)
    start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    print(f"\n=== Messages por status em 2026-04-29 ===")
    try:
        resp = (
            client.schema(schema)
            .table("messages")
            .select("status,count")
            .gte("sent_at", start.isoformat())
            .lte("sent_at", end.isoformat())
            .execute()
        )
        if resp.data:
            # Agrupar por status
            status_counts = {}
            for row in resp.data:
                status = row.get("status", "unknown")
                count = row.get("count", 0)
                status_counts[status] = count
            print(f"Contagem por status: {status_counts}")
            return status_counts
        else:
            print("Nenhum registro encontrado")
            return {}
    except Exception as e:
        print(f"Erro: {e}")
        return {}

def get_campaigns_active(schema="busca_ativa_v2"):
    """Obtém campanhas ativas"""
    print(f"\n=== Campanhas Ativas ===")
    try:
        resp = (
            client.schema(schema)
            .table("campaigns")
            .select("id,name,status,is_active,start_date,end_date")
            .execute()
        )
        if resp.data:
            active = [c for c in resp.data if c.get("is_active")]
            print(f"Total de campanhas: {len(resp.data)}")
            print(f"Campanhas ativas: {len(active)}")
            for c in active:
                print(f"  ID: {c.get('id')}, Nome: {c.get('name')}, Status: {c.get('status')}")
            return active
        else:
            print("Nenhuma campanha encontrada")
            return []
    except Exception as e:
        print(f"Erro: {e}")
        return []

def main():
    print("Exploração do Supabase")
    print(f"URL: {SUPABASE_URL}")
    print(f"Data alvo: 2026-04-29")
    
    # 1. Listar tabelas do schema busca_ativa_v2
    tables = list_tables("busca_ativa_v2")
    
    # 2. Contar raw_inbound total e hoje
    print("\n=== raw_inbound ===")
    total_inbound = get_table_info("raw_inbound", "busca_ativa_v2")
    count_inbound_today = get_count_today("raw_inbound", "received_at", "busca_ativa_v2")
    print(f"raw_inbound hoje (2026-04-29): {count_inbound_today}")
    
    # 3. Contar responses hoje
    print("\n=== responses ===")
    total_responses = get_table_info("responses", "busca_ativa_v2")
    count_responses_today = get_count_today("responses", "received_at", "busca_ativa_v2")
    print(f"responses hoje (2026-04-29): {count_responses_today}")
    
    # 4. Messages por status hoje
    msgs_status = get_messages_by_status_today("busca_ativa_v2")
    
    # 5. Campanhas ativas
    campaigns = get_campaigns_active("busca_ativa_v2")
    
    # 6. Informações adicionais das tabelas principais
    print("\n=== Informações detalhadas ===")
    for table in ["messages", "campaigns", "students", "guardians"]:
        if table in tables or table in ["messages", "campaigns"]:
            print(f"\n--- {table} ---")
            try:
                resp = client.schema("busca_ativa_v2").table(table).select("*").limit(3).execute()
                if resp.data:
                    cols = list(resp.data[0].keys())
                    print(f"Colunas: {cols}")
                    print(f"Primeiro registro: {resp.data[0]}")
            except Exception as e:
                print(f"Erro: {e}")

if __name__ == "__main__":
    main()
