import time
from app.infrastructure.supabase.repositories import SupabaseRepository
from app.application.inbound_service import InboundService

print("Criando repository...")
t0 = time.time()
r = SupabaseRepository()
t1 = time.time()
print(f"Repository criado em {t1-t0:.2f}s")

print("Criando service...")
t2 = time.time()
svc = InboundService(repository=r)
t3 = time.time()
print(f"Service criado em {t3-t2:.2f}s")

print("Listando pendentes...")
t4 = time.time()
rows = r.list_unprocessed_raw_inbound(limit=10)
t5 = time.time()
print(f"Listagem: {len(rows)} registros em {t5-t4:.2f}s")
