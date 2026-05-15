import socket
import time

host = "cpniwvghxlkposaeyboa.supabase.co"
port = 443

print(f"Testando conectividade TCP para {host}:{port}...")
start = time.time()
try:
    sock = socket.create_connection((host, port), timeout=10)
    elapsed = time.time() - start
    print(f"CONEXÃO TCP OK em {elapsed:.3f}s")
    sock.close()
except Exception as e:
    elapsed = time.time() - start
    print(f"FALHA na conexão TCP após {elapsed:.3f}s: {e}")

# Testar HTTP simples
import urllib.request
print(f"\nTestando HTTP GET na raiz...")
start = time.time()
try:
    req = urllib.request.Request(f"https://{host}/", method="GET")
    # timeout em segundos
    with urllib.request.urlopen(req, timeout=10) as resp:
        elapsed = time.time() - start
        print(f"HTTP OK status {resp.status} em {elapsed:.3f}s")
except Exception as e:
    elapsed = time.time() - start
    print(f"HTTP FALHA após {elapsed:.3f}s: {e}")

# Testar PostgREST /rest/v1/ com header simples (sem auth)
print(f"\nTestando PostgREST /rest/v1/ (sem auth)...")
start = time.time()
try:
    req = urllib.request.Request(
        f"https://{host}/rest/v1/",
        headers={"Accept": "application/json"},
        method="GET"
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        elapsed = time.time() - start
        body = resp.read().decode()[:200]
        print(f"PostgREST OK status {resp.status} em {elapsed:.3f}s")
        print(f"Body: {body}")
except Exception as e:
    elapsed = time.time() - start
    print(f"PostgREST FALHA após {elapsed:.3f}s: {e}")
