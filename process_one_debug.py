import time
import traceback
from app.infrastructure.supabase.repositories import SupabaseRepository
from app.application.inbound_service import InboundService

r = SupabaseRepository()
svc = InboundService(repository=r)
rows = r.list_unprocessed_raw_inbound(limit=1)
if not rows:
    print("Sem pendentes")
else:
    rec = rows[0]
    print(f"Processando {rec['message_id']}...")
    t0 = time.time()
    try:
        result = svc.process_recorded(payload=rec.get('payload') or {}, school_id=rec.get('school_id') or None)
        t1 = time.time()
        print(f"Resultado: {result.status} em {t1-t0:.2f}s")
    except Exception as e:
        t1 = time.time()
        print(f"Exceção após {t1-t0:.2f}s:")
        traceback.print_exc()
