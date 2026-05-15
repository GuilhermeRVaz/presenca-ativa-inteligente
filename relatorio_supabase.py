"""
Exploração final - consultas corretas e completas
"""
import os
from datetime import datetime, timezone
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_all_tables():
    """Lista todas as tabelas do schema busca_ativa_v2"""
    print("=== Listando todas as tabelas do schema 'busca_ativa_v2' ===")
    # Como não temos RPC para information_schema, consultamos diretamente a tabela pg_tables
    try:
        # Usar o endpoint REST para pg_tables
        resp = client.from_("pg_tables").select("*").eq("schemaname", "busca_ativa_v2").execute()
        if resp.data:
            tables = [row["tablename"] for row in resp.data]
            print(f"Tabelas encontradas: {tables}")
            return tables
        else:
            print("Nenhuma tabela encontrada via pg_tables")
    except Exception as e:
        print(f"Erro ao listar pg_tables: {e}")
    
    # Fallback: lista manual conhecida do código
    known_tables = [
        "raw_inbound", "messages", "campaigns", "responses",
        "guardians", "students", "student_guardians", "phone_identity_map"
    ]
    print(f"Tabelas conhecidas do código: {known_tables}")
    return known_tables

def count_raw_inbound_today():
    """Conta raw_inbound recebidos hoje"""
    target = datetime(2026, 4, 29, tzinfo=timezone.utc)
    start = target.replace(hour=0, minute=0, second=0, microsecond=0)
    end = target.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    resp = (
        client.schema("busca_ativa_v2")
        .table("raw_inbound")
        .select("id", count="exact")
        .gte("received_at", start.isoformat())
        .lte("received_at", end.isoformat())
        .execute()
    )
    count = resp.count if hasattr(resp, 'count') else (len(resp.data) if resp.data else 0)
    print(f"raw_inbound hoje (2026-04-29): {count}")
    return count

def count_responses_today():
    """Conta responses recebidas hoje"""
    target = datetime(2026, 4, 29, tzinfo=timezone.utc)
    start = target.replace(hour=0, minute=0, second=0, microsecond=0)
    end = target.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    resp = (
        client.schema("busca_ativa_v2")
        .table("responses")
        .select("id", count="exact")
        .gte("received_at", start.isoformat())
        .lte("received_at", end.isoformat())
        .execute()
    )
    count = resp.count if hasattr(resp, 'count') else (len(resp.data) if resp.data else 0)
    print(f"responses hoje (2026-04-29): {count}")
    return count

def get_active_campaigns():
    """Lista campanhas ativas (status != 'draft' e dispatched_at not null)"""
    print("\n=== Campanhas Ativas ===")
    try:
        resp = (
            client.schema("busca_ativa_v2")
            .table("campaigns")
            .select("id,name,status,type,absence_days,total_sent,total_replied,dispatched_at")
            .execute()
        )
        if resp.data:
            # Considerar ativa se status != 'draft' e dispatched_at not null
            active = [c for c in resp.data if c.get("status") != "draft" and c.get("dispatched_at")]
            print(f"Total de campanhas: {len(resp.data)}")
            print(f"Campanhas ativas (dispatched): {len(active)}")
            if active:
                for c in active:
                    print(f"  ID: {c.get('id')}")
                    print(f"  Nome: {c.get('name')}")
                    print(f"  Tipo: {c.get('type')}")
                    print(f"  Status: {c.get('status')}")
                    print(f"  Faltas: {c.get('absence_days')}")
                    print(f"  Enviadas: {c.get('total_sent')}, Respondidas: {c.get('total_replied')}")
                    print()
            else:
                print("  Nenhuma campanha ativa encontrada (dispatched_at NULL ou status=draft)")
            return active
        else:
            print("Nenhuma campanha encontrada")
            return []
    except Exception as e:
        print(f"Erro: {e}")
        return []

def count_messages_by_status_today():
    """Conta mensagens enviadas hoje por status"""
    target = datetime(2026, 4, 29, tzinfo=timezone.utc)
    start = target.replace(hour=0, minute=0, second=0, microsecond=0)
    end = target.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    print(f"\n=== Messages enviadas hoje (2026-04-29) por status ===")
    try:
        resp = (
            client.schema("busca_ativa_v2")
            .table("messages")
            .select("status")
            .gte("sent_at", start.isoformat())
            .lte("sent_at", end.isoformat())
            .execute()
        )
        if resp.data:
            from collections import Counter
            status_counts = Counter(row.get("status", "unknown") for row in resp.data)
            for status, count in status_counts.items():
                print(f"  {status}: {count}")
            return dict(status_counts)
        else:
            print("  Nenhuma message enviada hoje")
            return {}
    except Exception as e:
        print(f"  Erro: {e}")
        return {}

def get_schema_info():
    """Obtém informações do schema"""
    print("=== Informações do Schema ===")
    print(f"Supabase URL: {SUPABASE_URL}")
    
    # Verificar se o schema busca_ativa_v2 existe
    try:
        # Listar todas as tabelas que o cliente consegue acessar
        resp = client.table("raw_inbound").select("*").limit(1).execute()
        print("Schema atual: busca_ativa_v2 (acesso funcionando)")
    except Exception as e:
        print(f"Erro ao acessar schema: {e}")

def main():
    print("RELATÓRIO DE EXPLORAÇÃO DO SUPABASE")
    print("=" * 60)
    
    get_schema_info()
    
    # Listar tabelas
    tables = get_all_tables()
    
    # Contagens de hoje
    print("\n=== CONTAGENS DE HOJE (2026-04-29) ===")
    count_inbound = count_raw_inbound_today()
    count_responses = count_responses_today()
    
    # Campaigns ativas
    active_campaigns = get_active_campaigns()
    
    # Messages por status
    msgs_status = count_messages_by_status_today()
    
    # Sumário
    print("\n" + "=" * 60)
    print("RESUMO EXECUTIVO")
    print("=" * 60)
    print(f"Schema principal: busca_ativa_v2")
    print(f"Tabelas disponíveis: {', '.join(tables[:8])}")
    print()
    print(f"raw_inbound recebidos hoje: {count_inbound}")
    print(f"responses recebidas hoje: {count_responses}")
    print(f"Campanhas ativas: {len(active_campaigns)}")
    if active_campaigns:
        for c in active_campaigns:
            print(f"  - {c.get('name')} ({c.get('status')})")
    print(f"Messages enviadas hoje por status:")
    for status, count in msgs_status.items():
        print(f"  - {status}: {count}")

if __name__ == "__main__":
    main()
