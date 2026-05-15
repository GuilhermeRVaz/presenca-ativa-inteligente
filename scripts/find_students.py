import os
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client, ClientOptions

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
client = create_client(url, key, options=ClientOptions(schema="busca_ativa_v2"))

names = ['%JUNIO LUCAS%', '%HUGO C%SAR%', '%FELIPE ALMEIDA%']
for n in names:
    res = client.table('students').select('id, name').ilike('name', n).execute()
    for d in res.data:
        print(f"{d['name']}: {d['id']}")
