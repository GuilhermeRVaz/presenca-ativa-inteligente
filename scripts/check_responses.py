import os
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client, ClientOptions

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

if not url or not key:
    print("No env vars")
    exit(1)

supabase = create_client(url, key, options=ClientOptions(schema="busca_ativa_v2"))

res_resp = supabase.table("responses").select(
    "id, body, identity_confidence, campaign_id, student_id, received_at, sender_jid"
).order("received_at", desc=True).limit(50).execute()

import json
with open("responses_dump.json", "w", encoding="utf-8") as f:
    json.dump(res_resp.data, f, ensure_ascii=False, indent=2)

print("Saved to responses_dump.json")
