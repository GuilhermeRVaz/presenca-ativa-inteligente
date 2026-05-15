from app.infrastructure.supabase.repositories import SupabaseRepository
r = SupabaseRepository()

# Campanhas
camp_id = "bd325fa5-c111-4c12-a517-745055ed302b"

msgs = r.client.schema("busca_ativa_v2").table("messages").select("id, status, evolution_msg_id, sent_at").eq("campaign_id", camp_id).execute()

total = len(msgs.data)
from collections import Counter
status_counts = Counter(m["status"] for m in msgs.data)

print(f"Campanha: {camp_id}")
print(f"Total mensagens: {total}")
print("Status distribution:")
for status, count in status_counts.items():
    print(f"  {status}: {count}")

# Listar detalhes
print("\nDetalhes:")
for m in msgs.data:
    print(f"  ID={m['id'][:8]}... status={m['status']} evo={m.get('evolution_msg_id') or 'None'}")
