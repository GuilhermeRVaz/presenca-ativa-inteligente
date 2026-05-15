import time, httpx

url = 'https://cpniwvghxlkposaeyboa.supabase.co/rest/v1/raw_inbound?select=id&limit=1'
headers = {
    'apikey': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNwbml3dmdoeGxrcG9zYWV5Ym9hIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NTI5MDc3MiwiZXhwIjoyMDkwODY2NzcyfQ.aGCEqHjue7sORZQ_Wa0OVS5fzSIKkS08OxV3ewb7HP8',
    'Authorization': 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNwbml3dmdoeGxrcG9zYWV5Ym9hIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NTI5MDc3MiwiZXhwIjoyMDkwODY2NzcyfQ.aGCEqHjue7sORZQ_Wa0OVS5fzSIKkS08OxV3ewb7HP8',
    'Prefer': 'return=minimal'
}
for i in range(5):
    try:
        start = time.time()
        r = httpx.get(url, headers=headers, timeout=10)
        elapsed = time.time() - start
        print(f"Req {i+1}: status {r.status_code} in {elapsed:.2f}s")
    except Exception as e:
        elapsed = time.time() - start
        print(f"Req {i+1}: ERROR {type(e).__name__}: {str(e)[:100]} after {elapsed:.2f}s")
    time.sleep(1)
