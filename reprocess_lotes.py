import sys, time
from app.infrastructure.supabase.repositories import SupabaseRepository
from app.application.inbound_service import InboundService

r = SupabaseRepository()
svc = InboundService(repository=r)
batch_size = 20
rows = r.list_unprocessed_raw_inbound(limit=100)
total = len(rows)
print(f'Total pendentes: {total}', flush=True)
if total == 0:
    print('Nenhum pendente!', flush=True)
    sys.exit(0)

for i in range(0, total, batch_size):
    batch = rows[i:i+batch_size]
    print(f'\n--- Lote {i//batch_size + 1} ({len(batch)} regs) ---', flush=True)
    for j, rec in enumerate(batch, 1):
        result = svc.process_recorded(payload=rec.get('payload') or {}, school_id=rec.get('school_id') or None)
        print(f'  [{i+j}/{total}] {rec["message_id"]}: {result.status}', flush=True)
    print(f'Lote concluído.', flush=True)
    time.sleep(1)

print('\n=== FIM ===', flush=True)
