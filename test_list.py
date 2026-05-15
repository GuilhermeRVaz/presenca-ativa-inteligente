from app.infrastructure.supabase.repositories import SupabaseRepository
r = SupabaseRepository()
rows = r.list_unprocessed_raw_inbound(limit=80)
print(f'Pendentes: {len(rows)}')
for row in rows:
    print(f"  {row['message_id']}")
