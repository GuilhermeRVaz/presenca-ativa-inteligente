from supabase import create_client
import json

url = 'https://cpniwvghxlkposaeyboa.supabase.co'
key = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNwbml3VmdoeGxrcG9zYWV5Ym9hIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NTI5MDc3MiwiZXhwIjoyMDkwODY2NzcyfQ.aGCEqHjue7sORZQ_Wa0OVS5fzSIKkS08OxV3ewb7HP8'

client = create_client(url, key)

schema = 'busca_ativa_v2'

print("=" * 60)
print("ANÁLISE DETALHADA DO SUPABASE")
print("=" * 60)

# 1. raw_inbound PENDENTES (processed = false)
print("\n1. RAW_INBOND NÃO PROCESSADOS:")
try:
    rows = client.schema(schema).table('raw_inbound').select('*').eq('processed', False).execute()
    data = rows.data or []
    print(f"   Total pendentes: {len(data)}")
    for rec in data:
        print(f"\n   ID: {rec.get('id')}")
        print(f"   Message ID: {rec.get('message_id')}")
        print(f"   School ID: {rec.get('school_id')}")
        print(f"   Received at: {rec.get('received_at')}")
        print(f"   Error: {rec.get('processing_error')}")
        payload = rec.get('payload', {})
        if payload:
            print(f"   Payload keys: {list(payload.keys()) if isinstance(payload, dict) else type(payload)}")
            # Mostrar trecho do payload
            payload_str = str(payload)[:200]
            print(f"   Payload preview: {payload_str}")
except Exception as e:
    print(f"   ERRO: {e}")

# 2. raw_inbound de HOJE (processed e não processados)
from datetime import datetime, timezone
today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
today_end = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()

print(f"\n2. RAW_INBOUND DE HOJE (range: {today_start} a {today_end}):")
try:
    rows = client.schema(schema).table('raw_inbound').select('*').gte('created_at', today_start).lte('created_at', today_end).execute()
    data = rows.data or []
    print(f"   Total: {len(data)}")
    for rec in data:
        print(f"\n   ID: {rec.get('id')}, MsgID: {rec.get('message_id')}")
        print(f"   Processed? {rec.get('processed')}")
        print(f"   Error: {rec.get('processing_error')}")
except Exception as e:
    print(f"   ERRO: {e}")

# 3. RESPONSES de hoje
print(f"\n3. RESPONSES DE HOJE:")
try:
    rows = client.schema(schema).table('responses').select('*').gte('created_at', today_start).lte('created_at', today_end).execute()
    data = rows.data or []
    print(f"   Total: {len(data)}")
    for rec in data:
        print(f"   ID: {rec.get('id')}, Guardian: {rec.get('guardian_id')}, Student: {rec.get('student_id')}, Confidence: {rec.get('identity_confidence')}")
except Exception as e:
    print(f"   ERRO: {e}")

# 4. MESSAGES de hoje
print(f"\n4. MESSAGES ENVIADAS HOJE:")
try:
    rows = client.schema(schema).table('messages').select('*').gte('created_at', today_start).lte('created_at', today_end).execute()
    data = rows.data or []
    print(f"   Total: {len(data)}")
    status_count = {}
    for rec in data:
        s = rec.get('status', 'unknown')
        status_count[s] = status_count.get(s, 0) + 1
        print(f"   ID: {rec.get('id')}, Status: {s}, WA_JID: {rec.get('wa_jid')}, Campaign: {rec.get('campaign_id')}, Student: {rec.get('student_id')}")
    for s, c in status_count.items():
        print(f"   -> Status '{s}': {c}")
except Exception as e:
    print(f"   ERRO: {e}")

# 5. CAMPAIGNS
print(f"\n5. CAMPAIGNS NO SISTEMA:")
try:
    rows = client.schema(schema).table('campaigns').select('*').execute()
    campaigns = rows.data or []
    print(f"   Total: {len(campaigns)}")
    for c in campaigns:
        print(f"   ID: {c.get('id')}")
        print(f"   Nome: {c.get('name')}")
        print(f"   absence_days: {c.get('absence_days')}")
        print(f"   school_id: {c.get('school_id')}")
        print(f"   status: {c.get('status')}")
        print(f"   dispatched_at: {c.get('dispatched_at')}")
        print("")
except Exception as e:
    print(f"   ERRO: {e}")

# 6. GUARDIANS e STUDENTS (para referência)
print(f"\n6. ESTUDANTES CADASTRADOS:")
try:
    rows = client.schema(schema).table('students').select('id,name,ra,class_name').execute()
    students = rows.data or []
    print(f"   Total: {len(students)}")
    for s in students[:5]:
        print(f"   - {s.get('name')} | RA: {s.get('ra')} | Turma: {s.get('class_name')}")
except Exception as e:
    print(f"   ERRO: {e}")

print("\n" + "=" * 60)
