from app.infrastructure.supabase.repositories import SupabaseRepository
from app.application.inbound_service import InboundService

r = SupabaseRepository()
svc = InboundService(repository=r)
batch_size = 20
rows = r.list_unprocessed_raw_inbound(limit=batch_size)
total = len(rows)
print(f'Batch de {total}')
for i, rec in enumerate(rows, 1):
    result = svc.process_recorded(payload=rec.get('payload') or {}, school_id=rec.get('school_id') or None)
    print(f"[{i}/{total}] {rec['message_id']}: {result.status}")
print('Batch concluído.')
