from app.infrastructure.supabase.repositories import SupabaseRepository
r = SupabaseRepository()
rows = r.list_unprocessed_raw_inbound(limit=1)
if rows:
    rec = rows[0]
    print("Message ID:", rec['message_id'])
    print("Payload keys:", list(rec.get('payload', {}).keys()) if rec.get('payload') else 'None')
    # Não processar ainda, apenas inspecionar
else:
    print("Nenhum pendente")
