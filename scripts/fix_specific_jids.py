import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
load_dotenv()

from supabase import create_client, ClientOptions

def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    client = create_client(url, key, options=ClientOptions(schema="busca_ativa_v2"))
    
    campaign_id = "d7fbdc0b-81ac-4400-a4ff-29401b375e16"
    
    # 1. Update Junio Lucas
    student_id_1 = "ca288485-8abb-4100-bafa-7dedcab39b8c"
    res1 = client.table('responses').update({
        'student_id': student_id_1,
        'campaign_id': campaign_id,
        'identity_confidence': 'HIGH'
    }).eq('sender_jid', '33694052012164@lid').execute()
    print(f"Updated Junio Lucas: {len(res1.data)} rows")
    
    # 2. Update Hugo Cesar
    student_id_2 = "353f9d3f-02b5-4d4a-94d0-6abaf65112aa"
    res2 = client.table('responses').update({
        'student_id': student_id_2,
        'campaign_id': campaign_id,
        'identity_confidence': 'HIGH'
    }).eq('sender_jid', '833441783897@lid').execute()
    print(f"Updated Hugo Cesar: {len(res2.data)} rows")
    
    # 3. Update Felipe Almeida
    student_id_3 = "5eca77a2-7c3f-4e96-8304-5cf32b5cc46c"
    res3 = client.table('responses').update({
        'student_id': student_id_3,
        'campaign_id': campaign_id,
        'identity_confidence': 'HIGH'
    }).eq('sender_jid', '171004156461128@lid').execute()
    print(f"Updated Felipe Almeida: {len(res3.data)} rows")

if __name__ == '__main__':
    main()
