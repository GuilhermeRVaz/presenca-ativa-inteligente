from app.infrastructure.supabase.repositories import SupabaseRepository
from app.application.inbound_service import InboundService

r = SupabaseRepository()
svc = InboundService(repository=r)
rows = r.list_unprocessed_raw_inbound(limit=80)
print(f'Total a processar: {len(rows)}')
for rec in rows:
    result = svc.process_recorded(payload=rec.get('payload') or {}, school_id=rec.get('school_id') or None)
    print(f"{rec['message_id']}: {result.status}")
