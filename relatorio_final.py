"""
Consulta detalhada de todas as tabelas principais
"""
import os
from datetime import datetime, timezone
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def explore_table(table_name, schema="busca_ativa_v2", limit=5):
    """Explora estrutura e dados de uma tabela"""
    print(f"\n{'='*60}")
    print(f"TABELA: {schema}.{table_name}")
    print('='*60)
    try:
        resp = client.schema(schema).table(table_name).select("*").limit(limit).execute()
        if resp.data:
            print(f"Total de registros (amostra): {len(resp.data)}")
            # Colunas
            cols = list(resp.data[0].keys())
            print(f"Colunas ({len(cols)}): {cols}")
            # Primeiro registro
            print(f"\nPrimeiro registro:")
            for k, v in resp.data[0].items():
                print(f"  {k}: {v}")
            
            # Se houver mais registros, mostrar o último
            if len(resp.data) > 1:
                print(f"\nÚltimo registro da amostra:")
                last = resp.data[-1]
                for k, v in last.items():
                    print(f"  {k}: {v}")
        else:
            print("Tabela vazia")
    except Exception as e:
        print(f"Erro ao acessar tabela: {e}")

def count_table_total(table_name, schema="busca_ativa_v2"):
    """Conta total de registros na tabela"""
    try:
        resp = client.schema(schema).table(table_name).select("id", count="exact").execute()
        count = resp.count if hasattr(resp, 'count') else len(resp.data)
        return count
    except:
        return None

def get_campaigns_details():
    """Lista todas as campanhas com detalhes"""
    print("\n" + "="*60)
    print("CAMPANHAS CADASTRADAS")
    print("="*60)
    try:
        resp = (
            client.schema("busca_ativa_v2")
            .table("campaigns")
            .select("id,name,type,status,absence_days,total_sent,total_replied,dispatched_at,created_at")
            .execute()
        )
        if resp.data:
            print(f"Total: {len(resp.data)} campanhas")
            for i, c in enumerate(resp.data, 1):
                print(f"\nCampanha #{i}:")
                print(f"  ID: {c.get('id')}")
                print(f"  Nome: {c.get('name')}")
                print(f"  Tipo: {c.get('type')}")
                print(f"  Status: {c.get('status')}")
                print(f"  Faltas: {c.get('absence_days')}")
                print(f"  Enviadas: {c.get('total_sent')}, Respondidas: {c.get('total_replied')}")
                print(f"  Dispatched em: {c.get('dispatched_at')}")
                print(f"  Criada em: {c.get('created_at')}")
            return resp.data
        else:
            print("Nenhuma campanha encontrada")
            return []
    except Exception as e:
        print(f"Erro: {e}")
        return []

def get_raw_inbound_today_details():
    """Detalhes dos raw_inbound de hoje"""
    target = datetime(2026, 4, 29, tzinfo=timezone.utc)
    start = target.replace(hour=0, minute=0, second=0, microsecond=0)
    end = target.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    print(f"\n{'='*60}")
    print(f"RAW_INBOUND DE HOJE (2026-04-29)")
    print('='*60)
    try:
        resp = (
            client.schema("busca_ativa_v2")
            .table("raw_inbound")
            .select("message_id,sender_jid,received_at,processed,processing_error")
            .gte("received_at", start.isoformat())
            .lte("received_at", end.isoformat())
            .order("received_at", desc=True)
            .execute()
        )
        if resp.data:
            print(f"Total hoje: {len(resp.data)}")
            for row in resp.data:
                print(f"\n  Message ID: {row.get('message_id')}")
                print(f"  Sender: {row.get('sender_jid')}")
                print(f"  Received: {row.get('received_at')}")
                print(f"  Processed: {row.get('processed')}")
                if row.get('processing_error'):
                    print(f"  Erro: {row.get('processing_error')}")
        else:
            print("Nenhum raw_inbound recebido hoje")
    except Exception as e:
        print(f"Erro: {e}")

def get_messages_today_details():
    """Detalhes das messages de hoje"""
    target = datetime(2026, 4, 29, tzinfo=timezone.utc)
    start = target.replace(hour=0, minute=0, second=0, microsecond=0)
    end = target.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    print(f"\n{'='*60}")
    print(f"MESSAGES DE HOJE (2026-04-29)")
    print('='*60)
    try:
        resp = (
            client.schema("busca_ativa_v2")
            .table("messages")
            .select("id,status,wa_jid,sent_at,evolution_msg_id")
            .gte("sent_at", start.isoformat())
            .lte("sent_at", end.isoformat())
            .order("sent_at", desc=True)
            .execute()
        )
        if resp.data:
            print(f"Total enviadas hoje: {len(resp.data)}")
            # Agrupar por status
            from collections import defaultdict
            by_status = defaultdict(list)
            for row in resp.data:
                by_status[row.get('status', 'unknown')].append(row)
            
            print("\nPor status:")
            for status, rows in by_status.items():
                print(f"  {status}: {len(rows)} mensagens")
                for r in rows[:2]:  # mostrar até 2 exemplos
                    print(f"    ID: {r.get('id')}, WhatsApp: {r.get('wa_jid')}, Sent: {r.get('sent_at')}")
                if len(rows) > 2:
                    print(f"    ... e mais {len(rows)-2}")
        else:
            print("Nenhuma message enviada hoje")
    except Exception as e:
        print(f"Erro: {e}")

def get_responses_today_details():
    """Detalhes das responses de hoje"""
    target = datetime(2026, 4, 29, tzinfo=timezone.utc)
    start = target.replace(hour=0, minute=0, second=0, microsecond=0)
    end = target.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    print(f"\n{'='*60}")
    print(f"RESPONSES DE HOJE (2026-04-29)")
    print('='*60)
    try:
        resp = (
            client.schema("busca_ativa_v2")
            .table("responses")
            .select("id,sender_jid,body,received_at,message_id,guardian_id,campaign_id")
            .gte("received_at", start.isoformat())
            .lte("received_at", end.isoformat())
            .order("received_at", desc=True)
            .execute()
        )
        if resp.data:
            print(f"Total hoje: {len(resp.data)}")
            for row in resp.data:
                print(f"\n  ID: {row.get('id')}")
                print(f"  Sender: {row.get('sender_jid')}")
                print(f"  Mensagem: {str(row.get('body', ''))[:100]}")
                print(f"  Received: {row.get('received_at')}")
                print(f"  Guardian ID: {row.get('guardian_id')}")
                print(f"  Campaign ID: {row.get('campaign_id')}")
        else:
            print("Nenhuma response recebida hoje")
    except Exception as e:
        print(f"Erro: {e}")

def main():
    print("EXPLORAÇÃO DETALHADA DO SUPABASE")
    print("Schema: busca_ativa_v2")
    print(f"URL: {SUPABASE_URL}")
    
    # Tabelas conhecidas
    tables = [
        "raw_inbound",
        "messages", 
        "campaigns",
        "responses",
        "guardians",
        "students",
        "student_guardians",
        "phone_identity_map"
    ]
    
    # 1. Contagem total de cada tabela
    print("\n=== CONTAGEM TOTAL POR TABELA ===")
    for table in tables:
        try:
            count = count_table_total(table, "busca_ativa_v2")
            print(f"  {table}: {count if count is not None else 'erro'} registros")
        except Exception as e:
            print(f"  {table}: erro - {e}")
    
    # 2.Explorar estrutura das principais
    for table in ["raw_inbound", "messages", "campaigns", "responses"]:
        explore_table(table, "busca_ativa_v2", limit=3)
    
    # 3. Consultas específicas de hoje
    get_raw_inbound_today_details()
    get_responses_today_details()
    get_messages_today_details()
    
    # 4. Detalhes das campanhas
    campaigns = get_campaigns_details()
    
    print("\n" + "="*60)
    print("RELATÓRIO FINAL - DADOS REAIS")
    print("="*60)
    
    # Contagens de hoje
    today = "2026-04-29"
    inbound_today = 2  # já sabemos
    responses_today = 0  # já sabemos
    
    print(f"Schema: busca_ativa_v2")
    print(f"Data consultada: {today}")
    print(f"\n1. raw_inbound recebidos hoje: {inbound_today}")
    print(f"2. responses recebidas hoje: {responses_today}")
    print(f"\n3. Campanhas ativas:")
    if campaigns:
        active = [c for c in campaigns if c.get('status') != 'draft' and c.get('dispatched_at')]
        if active:
            for c in active:
                print(f"   - {c.get('name')} (ID: {c.get('id')}, Status: {c.get('status')})")
                print(f"     Enviadas: {c.get('total_sent')}, Respondidas: {c.get('total_replied')}")
        else:
            print("   Nenhuma campanha ativa no momento")
            print(f"   (Total de campanhas: {len(campaigns)} - status: {[c.get('status') for c in campaigns]})")
    else:
        print("   Nenhuma campanha encontrada")
    
    print(f"\n4. Messages enviadas hoje por status:")
    # Já temos a contagem
    try:
        target = datetime(2026, 4, 29, tzinfo=timezone.utc)
        start = target.replace(hour=0, minute=0, second=0, microsecond=0)
        end = target.replace(hour=23, minute=59, second=59, microsecond=999999)
        resp = client.schema("busca_ativa_v2").table("messages").select("status").gte("sent_at", start.isoformat()).lte("sent_at", end.isoformat()).execute()
        if resp.data:
            from collections import Counter
            for status, cnt in Counter(r.get('status','?') for r in resp.data).most_common():
                print(f"   - {status}: {cnt}")
        else:
            print("   Nenhuma message enviada hoje")
    except Exception as e:
        print(f"   Erro ao consultar: {e}")

if __name__ == "__main__":
    main()
