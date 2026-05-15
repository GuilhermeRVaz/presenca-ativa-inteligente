import os
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client, ClientOptions

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
client = create_client(url, key, options=ClientOptions(schema="busca_ativa_v2"))

protos = ['%P-18C04F%', '%P-91395F%', '%A98FBF%']
for p in protos:
    res = client.table('messages').select('id, campaign_id, student_id, guardian_id, message_text').ilike('message_text', p).execute()
    print(f'Protocol {p}:')
    for d in res.data:
        print(f"  c: {d.get('campaign_id')} s: {d.get('student_id')} g: {d.get('guardian_id')}")
