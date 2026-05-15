import sys
sys.path.insert(0, '.')

from app.infrastructure.supabase.repositories import SupabaseRepository
from app.application.inbound_service import InboundService
from app.infrastructure.evolution.payload_parser import EvolutionPayloadParser
from datetime import datetime, timezone
import traceback

# Pegar um raw_inbound pendente que falhou
repo = SupabaseRepository()
rows = repo.list_unprocessed_raw_inbound(limit=1)
if not rows:
    print("Nenhum raw_inbound pendente")
    sys.exit(0)

row = rows[0]
print(f"Analisando raw_inbound ID: {row['id']}")
print(f"Message ID: {row['message_id']}")
print(f"Sender JID: {row['sender_jid']}")
print(f"Payload (primeiros 300 chars): {str(row['payload'])[:300]}")
print(f"Erro atual: {row['processing_error']}")

# Re-executar processamento com debug
payload = row.get("payload") or {}
message_id = str(row.get("message_id") or "")
school_id = str(row.get("school_id") or "") or None

print("\n" + "=" * 60)
print("REPROCESSANDO COM DEBUG")
print("=" * 60)

parser = EvolutionPayloadParser()
inbound = parser.parse(payload)
print(f"\nParsed inbound:")
print(f"  message_id: {inbound.message_id}")
print(f"  sender_jid: {inbound.sender_jid}")
print(f"  from_me: {inbound.from_me}")
print(f"  has_message: {inbound.has_message}")
print(f"  school_id: {inbound.school_id}")
print(f"  text: {str(inbound.text)[:100]}")
print(f"  stanza_id: {inbound.stanza_id}")

if inbound.from_me:
    print("\nSTATUS: ignorado (from_me=True)")
    sys.exit(0)
if not inbound.has_message:
    print("\nSTATUS: ignorado (has_message=False)")
    sys.exit(0)

resolved_school_id = school_id or inbound.school_id or None
print(f"\nSchool ID resolvido: {resolved_school_id}")

# Agora, passo a passo do processamento
from app.application.identity_resolver import IdentityResolver

service = InboundService(repository=repo)
identity_resolver = IdentityResolver(repository=repo)

print("\n--- Etapa 1: Resolver identidade ---")
try:
    identity = identity_resolver.resolve_identity(
        sender_jid=inbound.sender_jid,
        stanza_id=inbound.stanza_id,
        school_id=resolved_school_id or "aac99735-32cb-4615-b2cb-0be315f18374",
    )
    print(f"Identidade resolvida:")
    print(f"  confidence: {identity.confidence}")
    print(f"  guardian: {identity.guardian}")
    print(f"  message: {identity.message}")
    print(f"  source: {identity.source}")
except Exception as e:
    print(f"ERRO na resolução de identidade: {e}")
    traceback.print_exc()
    sys.exit(1)

print("\n--- Etapa 2: Salvar response ---")
try:
    response_id = service._save_response(
        school_id=resolved_school_id or "aac99735-32cb-4615-b2cb-0be315f18374",
        inbound=inbound,
        identity=identity,
    )
    print(f"Response salva com ID: {response_id}")
except Exception as e:
    print(f"ERRO ao salvar response: {e}")
    traceback.print_exc()
    sys.exit(1)

print("\n--- Etapa 3: Marcar raw_inbound como processado ---")
try:
    repo.mark_raw_inbound_processed(
        message_id=inbound.message_id,
        processed=True,
        error=None,
    )
    print("raw_inbound marcado como processado")
except Exception as e:
    print(f"ERRO ao marcar processado: {e}")
    traceback.print_exc()
