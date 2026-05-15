import sys
sys.path.insert(0, '.')

from app.infrastructure.supabase.repositories import SupabaseRepository
import json

repo = SupabaseRepository()

# Buscar TODOS os pendentes
rows = repo.list_unprocessed_raw_inbound(limit=100)
print(f"Total de raw_inbound NÃO PROCESSADOS: {len(rows)}")
print("=" * 60)

for i, rec in enumerate(rows, 1):
    print(f"\n[{i}] ID: {rec.get('id')}")
    print(f"    Message ID: {rec.get('message_id')}")
    print(f"    School ID: {rec.get('school_id')}")
    print(f"    Sender JID: {rec.get('sender_jid')}")
    print(f"    Received at: {rec.get('received_at')}")
    print(f"    Error: {rec.get('processing_error')}")
    
    # Analisar payload
    payload = rec.get('payload', {})
    if isinstance(payload, dict):
        data = payload.get('data', {})
        msg = data.get('message', {})
        msg_type = list(msg.keys())[0] if msg else 'none'
        print(f"    Message type: {msg_type}")
        # Mostrar body se texto
        if 'conversation' in msg:
            print(f"    Text: {msg.get('conversation')[:80]}")
        elif 'extendedTextMessage' in msg:
            ext = msg.get('extendedTextMessage', {})
            print(f"    Text: {str(ext.get('text',''))[:80]}")
    elif isinstance(payload, str):
        print(f"    Payload str: {payload[:100]}")

# Agora, verificar messages e responses existentes
print("\n\n" + "=" * 60)
print("CONSULTANDO OUTRAS TABELAS")
print("=" * 60)

schema = 'busca_ativa_v2'

# Campaigns
campaigns = repo.client.schema(schema).table('campaigns').select('*').execute().data or []
print(f"\nCampaigns: {len(campaigns)}")
for c in campaigns:
    print(f"  {c.get('name')} | absence_days: {c.get('absence_days')} | status: {c.get('status')}")

# Messages recentes
print("\nMessages recentes (últimas 10):")
msgs = repo.client.schema(schema).table('messages').select('id,status,sent_at,wa_jid').order('created_at', desc=True).limit(10).execute().data or []
for m in msgs:
    print(f"  ID: {m.get('id')} | Status: {m.get('status')} | WA: {m.get('wa_jid')}")

# Responses recentes
print("\nResponses recentes (últimas 10):")
resps = repo.client.schema(schema).table('responses').select('id,body,identity_confidence,guardian_id,student_id').order('created_at', desc=True).limit(10).execute().data or []
for r in resps:
    print(f"  ID: {r.get('id')} | Body: {str(r.get('body',''))[:50]} | Conf: {r.get('identity_confidence')} | G: {r.get('guardian_id')} | S: {r.get('student_id')}")

# Estudantes
print("\nEstudantes cadastrados (primeiros 5):")
students = repo.client.schema(schema).table('students').select('id,name,ra,class_name').limit(5).execute().data or []
for s in students:
    print(f"  {s.get('name')} | RA: {s.get('ra')} | Turma: {s.get('class_name')}")

print("\n" + "=" * 60)
