#!/usr/bin/env python3
"""
Script para testar o webhook do n8n com dados reais.
"""
import sys
import httpx
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.core.config import settings

def test_n8n_webhook():
    print("Testando webhook do n8n...")

    # Dados de exemplo de uma mensagem raw_inbound
    payload = {
        "school_id": settings.default_school_id or "school-1",
        "lid_jid": "128737517523049@lid",  # exemplo de um dos senders
        "sender_jid": "128737517523049@lid",
        "raw_message_id": "AC2A1C091079FD7CA2FEEB607DCE53EC",
        "message_text": "O aluno esta doente com febre",
        "received_at": "2026-05-04T15:00:00Z"
    }

    print(f"Enviando payload: {payload}")
    print(f"Para URL: {settings.n8n_webhook_url}")

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(settings.n8n_webhook_url, json=payload)
            print(f"Status: {response.status_code}")
            print(f"Response: {response.text}")

            if response.status_code == 200:
                data = response.json()
                print(f"Resposta JSON: {data}")
                return True
            else:
                print(f"Erro no webhook: {response.status_code}")
                return False

    except Exception as e:
        print(f"Erro ao testar webhook: {e}")
        return False

if __name__ == "__main__":
    test_n8n_webhook()