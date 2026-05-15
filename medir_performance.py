import sys
sys.path.insert(0, '.')

from app.infrastructure.supabase.repositories import SupabaseRepository
from supabase import create_client
from app.core.config import settings

print("=== CONFIGURAÇÃO ATUAL ===")
print(f"Supabase URL: {settings.supabase_url}")
print(f"Supabase Key: {settings.supabase_key[:30]}...")
print(f"Evolution timeout: {settings.evolution_timeout_seconds}s")
print(f"Project root: {settings.project_root}")

# Verificar como o cliente Supabase é criado
repo = SupabaseRepository()
client = repo.client

# Inspecionar opções do cliente
print("\n=== CLIENTE SUPABASE ===")
print(f"Tipo: {type(client)}")
print(f"Has _postgrest: {hasattr(client, '_postgrest')}")
if hasattr(client, '_postgrest'):
    pg = client._postgrest
    print(f"Postgrest session: {pg.session if hasattr(pg, 'session') else 'N/A'}")
    # Verificar timeout
    if hasattr(pg, 'session') and hasattr(pg.session, 'timeout'):
        print(f"Timeout config: {pg.session.timeout}")

# Testar velocidade de consultas
import time

print("\n=== TESTE DE PERFORMANCE ===")

# Teste 1: list_unprocessed_raw_inbound
start = time.time()
try:
    rows = repo.list_unprocessed_raw_inbound(limit=10)
    elapsed = time.time() - start
    print(f"list_unprocessed_raw_inbound: {len(rows)} registros em {elapsed:.3f}s")
except Exception as e:
    print(f"list_unprocessed_raw_inbound ERRO: {e}")

# Teste 2: find_identity_by_jid para um sender não mapeado
start = time.time()
try:
    identity = repo.find_identity_by_jid(
        school_id="aac99735-32cb-4615-b2cb-0be315f18374",
        sender_jid="63990801666230@lid",
    )
    elapsed = time.time() - start
    print(f"find_identity_by_jid: {identity} em {elapsed:.3f}s")
except Exception as e:
    print(f"find_identity_by_jid ERRO: {e}")

# Teste 3: get_last_outbound_message_for_guardian (pode não existir)
start = time.time()
try:
    msg = repo.get_last_outbound_message_for_guardian(
        school_id="aac99735-32cb-4615-b2cb-0be315f18374",
        guardian_id="nenhum",
    )
    elapsed = time.time() - start
    print(f"get_last_outbound_message_for_guardian: None em {elapsed:.3f}s")
except Exception as e:
    elapsed = time.time() - start
    print(f"get_last... ERRO esperado: {e} em {elapsed:.3f}s")

# Teste 4: find_recent_messages_for_identity
start = time.time()
try:
    msgs = repo.find_recent_messages_for_identity(
        school_id="aac99735-32cb-4615-b2cb-0be315f18374",
        sender_jid="63990801666230@lid",
        hours=72,
    )
    elapsed = time.time() - start
    print(f"find_recent_messages_for_identity: {len(msgs)} registros em {elapsed:.3f}s")
except Exception as e:
    print(f"find_recent_messages_for_identity ERRO: {e}")

print("\n=== FIM ===")
