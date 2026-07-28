"""
test_inbound_ai_flow.py - Teste de integração do Webhook de Entrada e IA
"""
import sys
import io
import httpx
import json

if sys.platform.startswith("win"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

payload = {
    "event": "messages.upsert",
    "instance": "escola-decia",
    "data": {
        "key": {
            "remoteJid": "5514981324832@s.whatsapp.net",
            "fromMe": False,
            "id": "TEST_INBOUND_123"
        },
        "pushName": "Responsavel Teste",
        "message": {
            "conversation": "Bom dia, o João não pôde ir na aula hoje porque está com febre e gripado."
        },
        "messageTimestamp": 1785243500
    }
}

print("🧪 Enviando mensagem inbound de teste para /webhooks/evolution com timeout de 60s...")
r = httpx.post("http://localhost:8000/webhooks/evolution", json=payload, timeout=60.0)
print(f"Status Code FastAPI: {r.status_code}")
print(f"Resposta FastAPI: {r.json()}")
